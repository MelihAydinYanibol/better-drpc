import email.utils
import os
import re
import time

import dotenv
import requests

from cache import get_image

dotenv.load_dotenv()
DEBUG = False
AUDIOBOOKSHELF_SERVER_URL = os.getenv("AUDIOBOOKSHELF_SERVER_URL")
API_KEY = os.getenv("AUDIOBOOKSHELF_API_KEY")
USER = os.getenv("AUDIOBOOKSHELF_USER")

REQUEST_TIMEOUT = 30

# Audiobookshelf clients push a session sync 20 seconds after playback starts
# and every 10 seconds after that, and the server only bumps `updatedAt` when
# listening time is actually reported. A session whose `updatedAt` stopped
# moving is therefore paused/stopped, but the window has to clear the 20 second
# first-sync gap or playback would be dropped for its first 20 seconds and then
# flicker between syncs.
STALE_AFTER = 30.0
try:
	STALE_AFTER = max(25.0, float(os.getenv("AUDIOBOOKSHELF_STALE_AFTER", STALE_AFTER)))
except (TypeError, ValueError):
	pass

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

# Session sources in preference order. `/api/sessions/open` is the only endpoint
# that reports live playback sessions; the other two are listening *history* and
# are used as fallbacks for older servers and for non-admin API keys. Both
# admin-only endpoints answer 404 (not 403) when the key is not an admin.
_SESSION_SOURCES = (
	("open", "/api/sessions/open", True),
	("all", "/api/sessions", True),
	("me", "/api/me/listening-sessions", False),
)
_ACTIVE_SOURCE = None
_WARNED = set()


def lg(*args):
	if DEBUG:
		print("[DABS]", *args)


def set_debug(value):
	"""Let main.py turn on this module's verbose logging."""
	global DEBUG
	DEBUG = bool(value)


def _warn_once(key, message):
	if key in _WARNED:
		return
	_WARNED.add(key)
	print(f"[Audiobookshelf] {message}")


def _to_ms(seconds_value):
	try:
		return int(float(seconds_value) * 1000)
	except (TypeError, ValueError):
		return 0


_CLOCK_OFFSET_MS = None


def _server_now_ms(response):
	"""Estimate the Audiobookshelf server's current time in milliseconds.

	`updatedAt` is stamped with the server's clock, so comparing it against the
	local clock silently breaks whenever the two machines are not in sync. The
	Date response header gives us the server's own time for free.

	The header only has one-second resolution, so it is used to learn a clock
	*offset* once rather than re-read every poll; re-reading would jitter the
	reported position by up to a second and make Discord's timestamps flap.
	"""
	global _CLOCK_OFFSET_MS

	local_ms = int(time.time() * 1000)
	date_header = response.headers.get("Date")
	if date_header:
		try:
			header_ms = int(email.utils.parsedate_to_datetime(date_header).timestamp() * 1000)
		except (TypeError, ValueError):
			header_ms = None
		if header_ms is not None:
			offset = header_ms - local_ms
			# Only re-sync when the clocks genuinely drifted apart.
			if _CLOCK_OFFSET_MS is None or abs(offset - _CLOCK_OFFSET_MS) > 2000:
				_CLOCK_OFFSET_MS = offset

	return local_ms + (_CLOCK_OFFSET_MS or 0)


def _source_params(name):
	if name == "open":
		return None
	params = {"itemsPerPage": 10}
	if name == "all":
		# The default sort is updatedAt ASCENDING, so without this the first page
		# is the ten oldest sessions ever recorded and nothing is ever current.
		params.update({"sort": "updatedAt", "desc": 1})
		# The server validates this as a UUID and ignores anything else, so only
		# send it when the configured user really is an id.
		if USER and _UUID_RE.match(USER.strip()):
			params["user"] = USER.strip()
	return params


def _extract_sessions(payload):
	if not isinstance(payload, dict):
		return None
	sessions = payload.get("sessions")
	return sessions if isinstance(sessions, list) else None


def _fetch_sessions(base_url, headers):
	"""Return (sessions, server_now_ms) from the first usable session source."""
	global _ACTIVE_SOURCE

	sources = _SESSION_SOURCES
	if _ACTIVE_SOURCE:
		sources = tuple(s for s in _SESSION_SOURCES if s[0] == _ACTIVE_SOURCE) + tuple(
			s for s in _SESSION_SOURCES if s[0] != _ACTIVE_SOURCE
		)

	last_error = None
	empty_result = None
	for name, path, admin_only in sources:
		try:
			response = requests.get(
				f"{base_url}{path}",
				headers=headers,
				params=_source_params(name),
				timeout=REQUEST_TIMEOUT,
			)
		except requests.RequestException as error:
			last_error = f"{path}: {error}"
			lg(f"Request to {path} failed: {error}")
			continue

		if response.status_code in (401, 403):
			last_error = f"{path}: HTTP {response.status_code}"
			_warn_once(
				"auth",
				"API key was rejected (HTTP "
				f"{response.status_code}). Check AUDIOBOOKSHELF_API_KEY.",
			)
			continue
		if response.status_code == 404:
			# Admin-only endpoints answer 404 for non-admin keys, so this is not
			# necessarily a missing route.
			last_error = f"{path}: HTTP 404"
			lg(f"{path} returned 404 ({'needs an admin key' if admin_only else 'not available'}).")
			continue
		if response.status_code != 200:
			last_error = f"{path}: HTTP {response.status_code}"
			lg(f"{path} returned HTTP {response.status_code}.")
			continue

		try:
			payload = response.json()
		except ValueError:
			last_error = f"{path}: invalid JSON"
			lg(f"{path} returned a non-JSON body.")
			continue

		sessions = _extract_sessions(payload)
		if sessions is None:
			last_error = f"{path}: unexpected payload"
			lg(f"{path} returned an unexpected payload shape.")
			continue

		if not sessions:
			# A working but empty source is not proof that nothing is playing:
			# the mobile apps can play locally and only sync progress, which
			# never opens a server-side session. Keep looking, and fall back to
			# this answer if no other source has anything either.
			if empty_result is None:
				empty_result = ([], _server_now_ms(response))
			lg(f"{path} reported no sessions.")
			continue

		if _ACTIVE_SOURCE != name:
			_ACTIVE_SOURCE = name
			lg(f"Using session source {path}.")
		return sessions, _server_now_ms(response)

	if empty_result is not None:
		return empty_result

	if last_error:
		_warn_once("nosource", f"Could not read sessions ({last_error}).")
	return None, int(time.time() * 1000)


def _session_matches_user(session):
	"""Match against the user id or the username, whichever was configured."""
	if not USER:
		return True
	wanted = USER.strip().lower()
	user = session.get("user")
	if not isinstance(user, dict):
		user = {}
	candidates = (session.get("userId"), user.get("id"), user.get("username"))
	return any(value and str(value).strip().lower() == wanted for value in candidates)


def _first_year(value):
	if value is None:
		return None
	match = re.search(r"(\d{4})", str(value))
	return match.group(1) if match else None


def _resolve_year(metadata):
	# Book metadata exposes publishedYear/publishedDate; podcast metadata
	# exposes releaseDate. The old code only looked at releaseDate, so every
	# audiobook reported no year at all.
	return (
		_first_year(metadata.get("publishedYear"))
		or _first_year(metadata.get("publishedDate"))
		or _first_year(metadata.get("releaseDate"))
	)


def _resolve_author(session, metadata):
	display_author = (session.get("displayAuthor") or "").strip()
	if display_author:
		return display_author

	authors = metadata.get("authors")
	if isinstance(authors, list):
		names = [a.get("name") for a in authors if isinstance(a, dict) and a.get("name")]
		if names:
			return ", ".join(names)

	# authorName is on expanded book metadata, author on podcast metadata.
	for key in ("authorName", "author"):
		value = metadata.get(key)
		if value:
			return str(value).strip()
	return "Unknown Author"


def _resolve_collection(session, metadata, title):
	"""Pick the secondary line shown next to the cover.

	For books the series is the useful extra context; falling back to the book
	title just repeated the title Discord already shows.
	"""
	series = metadata.get("series")
	if isinstance(series, list) and series:
		first = series[0]
		if isinstance(first, dict) and first.get("name"):
			sequence = first.get("sequence")
			return f"{first['name']} #{sequence}" if sequence else str(first["name"])
	elif isinstance(series, str) and series.strip():
		return series.strip()

	series_name = metadata.get("seriesName")
	if series_name:
		return str(series_name).strip()

	# Podcasts: mediaMetadata.title is the show, which differs from the episode
	# title in displayTitle and is worth showing.
	collection_title = (metadata.get("title") or "").strip()
	if collection_title and collection_title.lower() != title.lower():
		return collection_title

	narrators = metadata.get("narrators")
	if isinstance(narrators, list) and narrators:
		return "Narrated by " + ", ".join(str(n) for n in narrators if n)

	return "Audiobookshelf"


def _build_cover_url(base_url, session):
	item_id = session.get("libraryItemId")
	if item_id:
		# Ask for JPEG explicitly: the server content-negotiates to WebP when the
		# request sends `Accept: */*` (requests' default), while the image cache
		# stores every cover as .jpg.
		return f"{base_url}/api/items/{item_id}/cover?format=jpeg&width=512"

	cover_path = session.get("coverPath")
	if cover_path:
		if cover_path.startswith(("http://", "https://")):
			return cover_path
		if not cover_path.startswith("/"):
			cover_path = f"/{cover_path}"
		return f"{base_url}{cover_path}"
	return None


def get_audiobookshelf_data():
	if not AUDIOBOOKSHELF_SERVER_URL or not API_KEY:
		if AUDIOBOOKSHELF_SERVER_URL or API_KEY:
			_warn_once(
				"config",
				"Both AUDIOBOOKSHELF_SERVER_URL and AUDIOBOOKSHELF_API_KEY must be set; skipping.",
			)
		return None

	base_url = AUDIOBOOKSHELF_SERVER_URL.rstrip("/")
	headers = {
		"accept": "application/json",
		"Authorization": f"Bearer {API_KEY}",
	}

	sessions, server_now_ms = _fetch_sessions(base_url, headers)
	if not sessions:
		lg("No sessions returned.")
		return None

	# Never rely on the order the endpoint happens to use; the newest session
	# that is still being synced is the one being played.
	for session in sorted(sessions, key=lambda s: s.get("updatedAt") or 0, reverse=True):
		if not _session_matches_user(session):
			lg(f"Skipping session for user {session.get('userId')}, looking for {USER}.")
			continue

		updated_at = session.get("updatedAt") or 0
		age_ms = server_now_ms - updated_at
		if age_ms > STALE_AFTER * 1000:
			lg(f"Session '{session.get('displayTitle')}' last synced {age_ms / 1000:.0f}s ago, treating as paused.")
			continue

		duration_ms = _to_ms(session.get("duration"))
		current_ms = _to_ms(session.get("currentTime"))
		if duration_ms <= 0 or current_ms >= duration_ms:
			continue

		# currentTime only advances once per sync, so Discord's elapsed time
		# would sit still for ten seconds and then jump. Carrying it forward by
		# the session's age keeps the bar moving and keeps the payload stable
		# between polls.
		position_ms = min(current_ms + max(0, age_ms), duration_ms)

		metadata = session.get("mediaMetadata")
		if not isinstance(metadata, dict):
			metadata = {}

		title = (session.get("displayTitle") or metadata.get("title") or "Unknown Title").strip()
		author = _resolve_author(session, metadata)
		collection_title = _resolve_collection(session, metadata, title)
		year = _resolve_year(metadata)

		image_url = _build_cover_url(base_url, session)
		cached_image_url = None
		if image_url:
			# Cache on the library item, not the session: a session id is new for
			# every playback and would re-upload the same cover each time.
			cache_id = str(session.get("libraryItemId") or title)
			cached_image_url = get_image(
				image_url,
				cache_id,
				"audiobookshelf",
				headers={"Authorization": f"Bearer {API_KEY}"},
			).get("url", None)

		return {
			"server": "audiobookshelf",
			"media_type": "track",
			"progress": [position_ms, duration_ms],
			"media_title": title,
			"artist": author,
			"album": collection_title,
			"year": year,
			"image": cached_image_url,
		}

	return None


if __name__ == "__main__":
	set_debug(True)
	while True:
		lg(get_audiobookshelf_data())
		time.sleep(4)
