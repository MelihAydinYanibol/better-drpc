from plexapi.myplex import MyPlexAccount
import dotenv
import os
import time
import socket
from urllib.parse import urlencode
from cache import get_image
ONLY_THIS_DEVICE = os.getenv("ONLY_GET_THIS_DEVICE", "false").lower() == "true"

dotenv.load_dotenv()
token = os.getenv("PLEX_TOKEN")
server_name = os.getenv("PLEX_SERVER_NAME")
user = os.getenv("PLEX_USER")
account = MyPlexAccount(token=token)
plex = account.resource(server_name).connect()


def _format_index(value):
    if value is None:
        return "00"
    return f"{int(value):02d}"


def _build_image_url(session):
    is_episode = getattr(session, "type", None) == "episode"
    if is_episode:
        # Prefer series poster/background for episodes.
        thumb_path = (
            getattr(session, "grandparentThumb", None)
            or getattr(session, "grandparentArt", None)
            or getattr(session, "thumb", None)
            or getattr(session, "art", None)
        )
    else:
        thumb_path = getattr(session, "thumb", None) or getattr(session, "art", None)
    if not thumb_path:
        return None

    query = urlencode(
        {
            "X-Plex-Token": token,
            "X-Plex-Container-Size": "512,512",
            "X-Plex-Container-Format": "jpeg",
            "X-Plex-Image-Quality": "90",
        }
    )
    return f"{plex._baseurl}{thumb_path}?{query}"


def _get_episode_year(session):
    year = getattr(session, "grandparentYear", None)
    if year is not None:
        return year

    # Session payloads can be partial; refetching can expose missing fields.
    try:
        full_item = plex.fetchItem(session.ratingKey)
        year = getattr(full_item, "grandparentYear", None)
        if year is None:
            year = getattr(full_item, "year", None)
    except Exception:
        year = None

    if year is not None:
        return year

    available_at = getattr(session, "originallyAvailableAt", None)
    return getattr(available_at, "year", None)



def get_plex_data():
    sessions = plex.sessions()
    print(sessions)
    if sessions:
        for session in sessions[::-1]:
            if session.usernames[0] == user:
                player_state = (getattr(session.players[0], "state", "") or "").lower()
                if player_state == "paused":
                    continue
                if ONLY_THIS_DEVICE:
                    ## Checking the hostname of the device running this code to check if it matches the session's device name. This is a simple way to filter sessions to only those from the current machine, but it relies on the device name being unique and consistent.
                    hostname = socket.gethostname()
                    if session.players[0].title != hostname:
                        continue
                print(f"Title: {session.title}")
                print(f"Type: {session.type}")
                print(f"Player: {session.players[0].title}")
                print(f"Progress: {session.viewOffset}/{session.duration}")
                if session.type == "episode":
                    media_id = str(
                        getattr(session, "grandparentRatingKey", None)
                        or getattr(session, "ratingKey", "")
                    )
                else:
                    media_id = str(getattr(session, "ratingKey", ""))
                output = {
                    "server": "plex",
                    "media_type": session.type,
                    "progress": [session.viewOffset, session.duration],
                    "image": get_image(_build_image_url(session), media_id, "plex").get("url", None),
                }
                if session.type == "movie":
                    output["year"] = session.year
                    output["media_title"] = session.title
                    output["genres"] = ", ".join(genre.tag for genre in session.genres[:3])
                elif session.type == "episode":
                    output["media_title"] = session.grandparentTitle
                    output["episode_title"] = session.title
                    output["season"] = _format_index(getattr(session, "parentIndex", None))
                    output["episode"] = _format_index(getattr(session, "index", None))
                    output["year"] = _get_episode_year(session)
                elif session.type == "track":
                    output["media_title"] = session.title
                    output["artist"] = session.grandparentTitle
                    output["album"] = session.parentTitle
                    album_year = None
                    try:
                        # Session objects can miss album-year fields; resolve from the album object.
                        track_item = plex.fetchItem(session.ratingKey)
                        album_item = plex.fetchItem(track_item.parentKey)
                        album_year = getattr(album_item, "year", None)
                    except Exception:
                        album_year = None

                    if album_year is None:
                        album_year = getattr(session, "parentYear", None)
                    if album_year is None:
                        album_year = getattr(session, "year", None)

                    output["year"] = album_year
                return output
        else:
            return None
    else:
        return None
                

print(get_plex_data())