from pypresence import Presence
from pypresence.types import ActivityType, StatusDisplayType
import dotenv
import os
import time
from dplex import get_plex_data
from djelly import get_jellyfin_data

dotenv.load_dotenv()
client_id = os.getenv("CLIENT_ID")
rpc = Presence(client_id)

print("Connecting to Discord RPC...")
rpc.connect()
print("Connected to Discord RPC.")

CHECK_INTERVAL = 7
ACTIVE_CHECK_INTERVAL = 3
LAST_CHECK = 0
ACTIVITY = {"jellyfin": None, "plex": None}
_ACT = None

def drpc(data):
    start = (time.time()-(data["progress"][0]/1000))
    end = (data["progress"][1]-data["progress"][0])/1000 + time.time()
    if data.get("server") == "plex": server="Plex"
    elif data.get("server") == "jellyfin": server="Jellyfin"
    if data["media_type"] == "movie":
        rpc.update(
            activity_type=ActivityType.WATCHING,
            status_display_type=StatusDisplayType.DETAILS,
            details=f"{data['media_title']} ({data['year']})",
            state=f"{data['genres']} - better-drpc",
            name=server,
            start=start,
            end=end,
            large_image=data.get("image"),
            large_text=data['media_title']
        )
    elif data["media_type"] == "episode":
        rpc.update(
            activity_type=ActivityType.WATCHING,
            status_display_type=StatusDisplayType.DETAILS,
            details=f"{data['media_title']} ({data['year']})",
            state=f"S{data['season']}E{data['episode']} - {data['episode_title']} - better-drpc",
            name=server,
            start=start,
            end=end,
            large_image=data.get("image"),
            large_text=data['media_title']
        )
    elif data["media_type"] == "track":
        if data.get("server") == "plex": server="Plexamp"
        elif data.get("server") == "jellyfin": server="Jellyfin"
        rpc.update(
            activity_type=ActivityType.LISTENING,
            status_display_type=StatusDisplayType.DETAILS,
            details=f"{data['media_title']}",
            name=server,
            state=f"by {data['artist']}",
            large_text=f"{data['album']} ({data['year']})",
            start=start,
            end=end,
            large_image=data.get("image")
        )

while True:
    jdata = get_jellyfin_data()
    pdata = get_plex_data()

    if jdata is not None and ACTIVITY["jellyfin"] is None:
        ACTIVITY["jellyfin"] = time.time()
    elif jdata is None:
        ACTIVITY["jellyfin"] = None

    if pdata is not None and ACTIVITY["plex"] is None:
        ACTIVITY["plex"] = time.time()
    elif pdata is None:
        ACTIVITY["plex"] = None

    if jdata is not None and pdata is not None:
        if ACTIVITY["jellyfin"] >= ACTIVITY["plex"]:
            data = jdata
        else:
            data = pdata
    elif jdata is not None:
        data = jdata
    elif pdata is not None:
        data = pdata
    else:
        data = None

    if data is not None:
        drpc(data)
        _ACT = True
        if (data.get("progress")[1]-data.get("progress")[0])/1000 < 7:
            time.sleep(1)
        else:
            time.sleep(ACTIVE_CHECK_INTERVAL)
    else:
        if _ACT: rpc.clear(); _ACT = False
        print("No active session found.")
        time.sleep(CHECK_INTERVAL)

