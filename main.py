from pypresence import Presence
from pypresence.types import ActivityType, StatusDisplayType
from pypresence.exceptions import (
    ConnectionTimeout,
    DiscordNotFound,
    InvalidPipe,
    PipeClosed,
    ResponseTimeout,
)
import dotenv
import os
import time
from dplex import get_plex_data
from djelly import get_jellyfin_data
from cache import get_image
dotenv.load_dotenv()
client_id = os.getenv("CLIENT_ID")
rpc = Presence(client_id)

CHECK_INTERVAL = 7
ACTIVE_CHECK_INTERVAL = 3
LAST_CHECK = 0
LAST_CONNECT_ATTEMPT = 0
RECONNECT_INTERVAL = 10
ACTIVITY = {"jellyfin": None, "plex": None}
_ACT = None
_RPC_CONNECTED = False
OLD_PAYLOAD = None

def ensure_rpc_connection(force=False):
    global _RPC_CONNECTED, LAST_CONNECT_ATTEMPT

    now = time.time()
    if _RPC_CONNECTED and not force:
        return True
    if not force and (now - LAST_CONNECT_ATTEMPT) < RECONNECT_INTERVAL:
        return False

    LAST_CONNECT_ATTEMPT = now
    try:
        print("Connecting to Discord RPC...")
        rpc.connect()
        _RPC_CONNECTED = True
        print("Connected to Discord RPC.")
        return True
    except (DiscordNotFound, InvalidPipe, ConnectionTimeout, OSError) as error:
        _RPC_CONNECTED = False
        print(f"Discord RPC unavailable: {error}")
        return False


def safe_rpc_call(fn, **kwargs):
    global _RPC_CONNECTED
    try:
        fn(**kwargs)
        return True
    except (ResponseTimeout, PipeClosed, ConnectionTimeout, InvalidPipe, OSError) as error:
        _RPC_CONNECTED = False
        print(f"Discord RPC call failed: {error}")
        return False

def drpc(data):
    global OLD_PAYLOAD
    if not ensure_rpc_connection():
        return False

    start = (time.time()-(data["progress"][0]/1000))
    end = (data["progress"][1]-data["progress"][0])/1000 + time.time()
    server = "Plex" if data.get("server") == "plex" else "Jellyfin"

    payload = {
        "status_display_type": StatusDisplayType.DETAILS,
        "start": start,
        "end": end,
        "large_image": data.get("image"),
        "small_image": "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/jellyfin.png" if data.get("server") == "jellyfin" else ("https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/plex.png" if data.get("server") == "plex" else None),
        "small_text": "Jellyfin" if data.get("server") == "jellyfin" else ("Plex" if data.get("server") == "plex" else None),
    }

    if data["media_type"] == "movie":
        payload.update(
            {
                "activity_type": ActivityType.WATCHING,
                "details": f"{data['media_title']} ({data['year']})",
                "state": f"{data['genres']} - better-drpc",
                "name": server,
                "large_text": data["media_title"],
            }
        )
    elif data["media_type"] == "episode":
        payload.update(
            {
                "activity_type": ActivityType.WATCHING,
                "details": f"{data['media_title']} ({data['year']})",
                "state": f"S{data['season']}E{data['episode']} - {data['episode_title']} - better-drpc",
                "name": server,
                "large_text": data["media_title"],
            }
        )
    elif data["media_type"] == "track":
        payload.update(
            {
                "activity_type": ActivityType.LISTENING,
                "details": f"{data['media_title']}",
                "name": "Plexamp" if data.get("server") == "plex" else "Jellyfin",
                "state": f"by {data['artist']}",
                "large_text": f"{data['album']} ({data['year']})",
            }
        )
    else:
        OLD_PAYLOAD = None
        return False
    
    if OLD_PAYLOAD and payload == OLD_PAYLOAD:
        return True
    else:
        if safe_rpc_call(rpc.update, **payload):
            return True

        # Retry once after forcing a reconnect when the pipe times out/closes.
        if ensure_rpc_connection(force=True):
            return safe_rpc_call(rpc.update, **payload)
        return False


def clear_presence():
    if not ensure_rpc_connection():
        return False

    if safe_rpc_call(rpc.clear):
        return True
    if ensure_rpc_connection(force=True):
        return safe_rpc_call(rpc.clear)
    return False


print("Starting better-drpc...")
ensure_rpc_connection()

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
        if drpc(data):
            _ACT = True
        if (data.get("progress")[1]-data.get("progress")[0])/1000 < 7:
            time.sleep(1)
        else:
            time.sleep(ACTIVE_CHECK_INTERVAL)
    else:
        if _ACT:
            clear_presence()
            _ACT = False
        else:
            clear_presence()
        print("No active session found.")
        time.sleep(CHECK_INTERVAL)

