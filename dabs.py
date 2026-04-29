import requests
import dotenv
import os
from cache import get_image
import time

dotenv.load_dotenv()
DEBUG = False
AUDIOBOOKSHELF_SERVER_URL = os.getenv("AUDIOBOOKSHELF_SERVER_URL")
API_KEY = os.getenv("AUDIOBOOKSHELF_API_KEY")
USER = os.getenv("AUDIOBOOKSHELF_USER")

def _to_ms(seconds_value):
	try:
		return int(float(seconds_value) * 1000)
	except (TypeError, ValueError):
		return 0

def lg(*args):
	global DEBUG
	if DEBUG:
		print("[DABS]", *args)

def _resolve_year(metadata):
	release_date = metadata.get("releaseDate") if isinstance(metadata, dict) else None
	if not release_date:
		return None
	return str(release_date)[:4]


def _build_cover_url(base_url, item_id, cover_path):
	# Prefer the API cover endpoint, which is stable across media types.
	if item_id:
		return f"{base_url}/api/items/{item_id}/cover"
	if cover_path:
		if cover_path.startswith(("http://", "https://")):
			return cover_path
		if not cover_path.startswith("/"):
			cover_path = f"/{cover_path}"
		return f"{base_url}{cover_path}"
	return None


def get_audiobookshelf_data():
	if not AUDIOBOOKSHELF_SERVER_URL or not API_KEY:
		return None

	base_url = AUDIOBOOKSHELF_SERVER_URL.rstrip("/")
	headers = {
		"accept": "application/json",
		"Authorization": f"Bearer {API_KEY}",
	}
	params = {
		"itemsPerPage": 10,
	}
	if USER:
		params["user"] = USER

	try:
		response = requests.get(f"{base_url}/api/sessions", headers=headers, params=params, timeout=30)
		response.raise_for_status()
		payload = response.json()
	except (requests.RequestException, ValueError):
		return None

	sessions = payload.get("sessions") or []
	if not sessions:
		lg("No active sessions found.")
		return None

	for session in reversed(sessions):
		lg(session)
		if USER and session.get("userId") != USER:
			lg(f"Skipping session for user {session.get('userId')}, looking for {USER}.")
			continue
		is_stale = (int(time.time() * 1000) - session.get("updatedAt", 0)) > 30*1000
		if is_stale:
			lg(f"Session in state {session.get('state')} appears stale, skipping.")
			continue
		position_ms = _to_ms(session.get("currentTime", 0))
		duration_ms = _to_ms(session.get("duration", 0))
		if duration_ms <= 0:
			continue
		if position_ms >= duration_ms:
			continue

		metadata = session.get("mediaMetadata") or {}
		title = (session.get("displayTitle") or metadata.get("title") or "Unknown Title").strip()
		author = (session.get("displayAuthor") or metadata.get("author") or "Unknown Author").strip()
		collection_title = (metadata.get("title") or "Audiobookshelf").strip()
		year = _resolve_year(metadata)

		item_id = session.get("libraryItemId") or session.get("id") or title
		cover_path = session.get("coverPath")
		image_url = _build_cover_url(base_url, item_id, cover_path)

		cached_image_url = None
		if image_url:
			cached_image_url = get_image(
				image_url,
				str(item_id),
				"audiobookshelf",
				headers={"Authorization": f"Bearer {API_KEY}"},
			).get("url", None)

		output = {
			"server": "audiobookshelf",
			"media_type": "track",
			"progress": [position_ms, duration_ms],
			"media_title": title,
			"artist": author,
			"album": collection_title,
			"year": year,
			"image": cached_image_url,
		}
		return output

	return None

if __name__ == "__main__":
	DEBUG = True
	data = get_audiobookshelf_data()
	while True:
		lg(get_audiobookshelf_data())
		import time
		time.sleep(4)