from plexapi.myplex import MyPlexAccount
import dotenv
import os
import time
from urllib.parse import urlencode
from cache import get_image

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



def get_plex_data():
    sessions = plex.sessions()
    print(sessions)
    if sessions:
        for session in sessions[::-1]:
            print(session)
            if session.usernames[0] == user:
                player_state = (getattr(session.players[0], "state", "") or "").lower()
                if player_state == "paused":
                    continue
                print(f"Title: {session.title}")
                print(f"Type: {session.type}")
                print(f"Player: {session.players[0].title}")
                print(f"Progress: {session.viewOffset}/{session.duration}")
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
                    output["year"] = session.grandparentYear
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