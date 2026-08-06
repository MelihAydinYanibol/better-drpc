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


def _float_env(name, default):
	try:
		return float(os.getenv(name, default))
	except (TypeError, ValueError):
		return float(default)


# Audiobookshelf players only push progress every 10-20 seconds (20s for the
# first sync of a session, 10s after that), and the server keeps a session
# "open" for 36 hours after playback stops. There is no explicit paused flag, so
# the freshness of updatedAt is the only usable playing/paused signal: it only
# moves while audio is actually playing. The window must therefore be safely
# larger than a sync interval or actively playing books get dropped.
SESSION_TIMEOUT = _float_env("AUDIOBOOKSHELF_SESSION_TIMEOUT", 45)
REQUEST_TIMEOUT = 10

# Remembered across polls so we only probe endpoint/auth variants once.
_ENDPOINT = None
_USE_TOKEN_PARAM = False
_WARNED = set()


def lg(*args):
	if DEBUG:
		print("[DABS]", *args)


def set_debug(enabled):
	global DEBUG
	DEBUG = bool(enabled)


def _warn_once(key, message):
	if key not in _WARNED:
		_WARNED.add(key)
		print(f"[Audiobookshelf] {message}")


def _to_ms(seconds_value):
	try:
		return int(float(seconds_value) * 1000)
	except (TypeError, ValueError):
		return 0


def _clean(value):
	if value is None:
		return None
	text = str(value).strip()
	return text or None


def _base_url():
	return (AUDIOBOOKSHELF_SERVER_URL or "").rstrip("/")


def _get(path, params=None):
	"""GET an Audiobookshelf API path, returning the parsed body or None.

	API keys are sent as a bearer token, which is what current Audiobookshelf
	expects. Older servers (and some reverse proxies that strip Authorization)
	only accept the key as a `token` query param, so a 401 makes us switch to
	that form and remember the choice.
	"""
	global _USE_TOKEN_PARAM

	url = f"{_base_url()}{path}"
	query = dict(params or {})
	headers = {"accept": "application/json"}
	if _USE_TOKEN_PARAM:
		query["token"] = API_KEY
	else:
		headers["Authorization"] = f"Bearer {API_KEY}"

	try:
		response = requests.get(url, headers=headers, params=query, timeout=REQUEST_TIMEOUT)
	except requests.RequestException as error:
		lg(f"Request to {path} failed: {error}")
		return None

	if response.status_code == 401 and not _USE_TOKEN_PARAM:
		lg("Bearer auth rejected, retrying with ?token= ...")
		_USE_TOKEN_PARAM = True
		return _get(path, params)

	if response.status_code != 200:
		lg(f"{path} returned HTTP {response.status_code}")
		return response.status_code

	try:
		return response.json()
	except ValueError:
		lg(f"{path} returned a non-JSON body")
		return None


def _fetch_sessions():
	"""Return (sessions, endpoint) for the currently known playback sessions.

	`/api/sessions/open` holds the sessions the server currently considers
	playing, but it is admin-only. Non-admin API keys fall back to
	`/api/me/listening-sessions`, which is that user's own session history
	sorted newest-first - the in-progress session is the first entry, kept up to
	date by the same progress syncs.

	Note: `/api/sessions` (used previously) is neither of these. It is the
	admin-only history of *every* session ever recorded and defaults to
	ascending order, so its first page is the ten oldest sessions on the server
	and never contains what is playing now.
	"""
	global _ENDPOINT

	if _ENDPOINT in (None, "open"):
		payload = _get("/api/sessions/open")
		if isinstance(payload, dict):
			_ENDPOINT = "open"
			return payload.get("sessions") or [], "open"
		if payload in (401, 403, 404):
			# Audiobookshelf answers 404 (not 403) for non-admin users here.
			_warn_once(
				"not_admin",
				"API key is not an admin key; falling back to /api/me/listening-sessions.",
			)
		elif _ENDPOINT == "open":
			return [], "open"

	payload = _get("/api/me/listening-sessions", {"itemsPerPage": 10, "page": 0})
	if isinstance(payload, dict):
		_ENDPOINT = "me"
		return payload.get("sessions") or [], "me"

	if payload == 401:
		_warn_once("unauthorized", "AUDIOBOOKSHELF_API_KEY was rejected by the server.")
	return [], _ENDPOINT


def _matches_user(session, endpoint):
	"""Match AUDIOBOOKSHELF_USER against a session.

	The value may be a username or a user id. The server's own `user` query
	param only accepts a UUID and silently ignores anything else, so filtering
	is done here instead. `/api/me/...` is already scoped to the key's owner.
	"""
	if not USER or endpoint == "me":
		return True

	wanted = USER.strip().lower()
	user = session.get("user") or {}
	for candidate in (user.get("username"), user.get("id"), session.get("userId")):
		if candidate and str(candidate).strip().lower() == wanted:
			return True
	return False


def _resolve_year(metadata):
	# Books carry publishedYear/publishedDate; podcasts carry releaseDate.
	for key in ("publishedYear", "publishedDate", "releaseDate"):
		value = _clean(metadata.get(key))
		if value:
			match = re.search(r"\d{4}", value)
			if match:
				return match.group(0)
	return None


def _resolve_author(session, metadata):
	names = [author.get("name") for author in metadata.get("authors") or [] if isinstance(author, dict)]
	return (
		_clean(session.get("displayAuthor"))
		or _clean(metadata.get("authorName"))
		or _clean(metadata.get("author"))
		or _clean(", ".join(name for name in names if name))
		or "Unknown Author"
	)


def _resolve_collection(session, metadata, title):
	"""The secondary line: podcast show, book series, or a sensible fallback."""
	if (session.get("mediaType") or "").lower() == "podcast":
		return _clean(metadata.get("title")) or "Podcast"

	series = _clean(metadata.get("seriesName"))
	if not series:
		entries = [s.get("name") for s in metadata.get("series") or [] if isinstance(s, dict)]
		series = _clean(", ".join(name for name in entries if name))
	if series:
		return series

	# For books mediaMetadata.title is the book itself, so using it here would
	# just repeat the title that is already on the first line.
	collection = _clean(metadata.get("title"))
	if collection and collection.lower() != title.lower():
		return collection
	return "Audiobook"


def _cover_url(item_id):
	# coverPath is a path on the server's filesystem, not something reachable
	# over HTTP, so the API cover endpoint is the only usable source.
	if not item_id:
		return None
	return f"{_base_url()}/api/items/{item_id}/cover?format=jpeg"


def get_audiobookshelf_data():
	if not AUDIOBOOKSHELF_SERVER_URL or not API_KEY:
		return None

	sessions, endpoint = _fetch_sessions()
	if not sessions:
		lg("No sessions returned.")
		return None

	now_ms = int(time.time() * 1000)
	timeout_ms = SESSION_TIMEOUT * 1000

	# Newest activity first, so the session being listened to right now wins
	# when several are open (e.g. another device left one behind).
	for session in sorted(sessions, key=lambda s: s.get("updatedAt") or 0, reverse=True):
		lg(session)

		if not _matches_user(session, endpoint):
			lg(f"Skipping session for user {(session.get('user') or {}).get('username') or session.get('userId')}.")
			continue

		updated_at = session.get("updatedAt") or 0
		# Clamp so a client/server clock skew cannot look like the future.
		age_ms = max(0, now_ms - updated_at)
		if age_ms > timeout_ms:
			lg(f"Session last synced {age_ms / 1000:.0f}s ago, treating as paused/stopped.")
			continue

		duration_ms = _to_ms(session.get("duration"))
		if duration_ms <= 0:
			lg("Session has no duration, skipping.")
			continue

		position_ms = _to_ms(session.get("currentTime"))
		if position_ms >= duration_ms:
			lg("Session is already at the end, skipping.")
			continue

		# currentTime is only as fresh as the last sync, so advance it by the
		# time since then to keep Discord's progress bar smooth between syncs.
		position_ms = min(position_ms + age_ms, duration_ms - 1)

		metadata = session.get("mediaMetadata") or {}
		title = _clean(session.get("displayTitle")) or _clean(metadata.get("title")) or "Unknown Title"

		item_id = session.get("libraryItemId")
		image_url = _cover_url(item_id)
		cached_image_url = None
		if image_url:
			headers = None if _USE_TOKEN_PARAM else {"Authorization": f"Bearer {API_KEY}"}
			if _USE_TOKEN_PARAM:
				image_url = f"{image_url}&token={API_KEY}"
			cached_image_url = get_image(
				image_url,
				str(item_id),
				"audiobookshelf",
				headers=headers,
			).get("url", None)

		return {
			"server": "audiobookshelf",
			"media_type": "track",
			"progress": [position_ms, duration_ms],
			"media_title": title,
			"artist": _resolve_author(session, metadata),
			"album": _resolve_collection(session, metadata, title),
			"year": _resolve_year(metadata),
			"image": cached_image_url,
		}

	return None


if __name__ == "__main__":
	set_debug(True)
	while True:
		print(get_audiobookshelf_data())
		time.sleep(4)
