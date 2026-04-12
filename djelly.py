import os
import time
import dotenv
import requests
from cache import get_image
import socket

dotenv.load_dotenv()

SERVER_URL = os.getenv("JELLYFIN_SERVER_URL")
API_KEY = os.getenv("JELLYFIN_API_KEY")
USER = os.getenv("JELLYFIN_USER")
ONLY_THIS_DEVICE = os.getenv("ONLY_GET_THIS_DEVICE", "false").lower() == "true"


def _ticks_to_ms(ticks):
	if not ticks:
		return 0
	return int(ticks // 10000)


def _format_index(value):
	if value is None:
		return "00"
	return f"{int(value):02d}"


def get_jellyfin_data():
	if not SERVER_URL or not API_KEY:
		return None

	headers = {
		"accept": "application/json",
		"X-Emby-Token": API_KEY,
	}

	try:
		response = requests.get(f"{SERVER_URL}/Sessions", headers=headers, timeout=30)
		response.raise_for_status()
		sessions = response.json()
	except (requests.RequestException, ValueError):
		return None

	if not sessions:
		return None

	for session in reversed(sessions):
		if USER and session.get("UserName") != USER:
			continue
		if ONLY_THIS_DEVICE:
			## Checking the hostname of the device running this code to check if it matches the session's device name. This is a simple way to filter sessions to only those from the current machine, but it relies on the device name being unique and consistent.
			hostname = socket.gethostname()
			if session.get("DeviceName") != hostname:
				continue
		# Ignore paused sessions so only actively playing media is returned.
		if session.get("PlayState", {}).get("IsPaused"):
			continue

		item = session.get("NowPlayingItem")
		if not item:
			continue

		item_type = (item.get("Type") or "").lower()
		position_ms = _ticks_to_ms(session.get("PlayState", {}).get("PositionTicks", 0))
		duration_ms = _ticks_to_ms(item.get("RunTimeTicks", 0))

		image_item_id = item.get("Id")
		image_tag = item.get("ImageTags", {}).get("Primary")
		if item_type == "episode":
			# For episodes, prefer the TV series poster instead of episode artwork.
			image_item_id = item.get("SeriesId") or image_item_id
			image_tag = item.get("SeriesPrimaryImageTag") or image_tag

		output = {
			"progress": [position_ms, duration_ms],
			"server": "jellyfin",
			"image": get_image(
				f"{SERVER_URL}/Items/{image_item_id}/Images/Primary?tag={image_tag}&quality=90",
				str(image_item_id),
				"jellyfin"
			).get("url", None),
		}
		if item_type == "movie":
			output["media_type"] = "movie"
			output["media_title"] = item.get("Name")
			output["year"] = item.get("ProductionYear")
			genres = item.get("Genres") or []
			output["genres"] = ", ".join(genres[:3])
			return output

		if item_type == "episode":
			output["media_type"] = "episode"
			output["media_title"] = item.get("SeriesName")
			output["episode_title"] = item.get("Name")
			output["season"] = _format_index(item.get("ParentIndexNumber"))
			output["episode"] = _format_index(item.get("IndexNumber"))
			output["year"] = item.get("ProductionYear") or item.get("PremiereDate", "")[:4]
			return output

		if item_type in {"audio", "song"}:
			output["media_type"] = "track"
			output["media_title"] = item.get("Name")
			output["artist"] = item.get("AlbumArtist") or ", ".join(item.get("Artists") or [])
			output["album"] = item.get("Album")
			output["year"] = item.get("ProductionYear")
			return output

	return None
