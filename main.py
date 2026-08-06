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
import sys
from dplex import get_plex_data
from djelly import get_jellyfin_data
import dabs
from dabs import get_audiobookshelf_data
from cache import get_image
DEBUG = False
args = sys.argv[1:]

if args and args[0] in ("--help", "-h"):
    print("Usage: python main.py [--clear-cache <jellyfin|plex|abs|all>] [--help|-h]")
    print("Options:")
    print("  --clear-cache <type>   Clear cached images and URLs for the specified type (jellyfin, plex, abs, or all).")
    print("  --help, -h            Show this help message and exit.")
    sys.exit(0)

if args and args[0] in ("-debug", "--debug"):
    DEBUG = True
    dabs.set_debug(True)
if args and args[0] == "--clear-cache":
    if len(args) < 2:
        print("Missing cache type. Use: --clear-cache <jellyfin|plex|abs|all>")
        sys.exit(1)

    CACHE_DIRS = {"jellyfin": "jellyfin", "plex": "plex", "abs": "audiobookshelf"}

    if args[1] == "all":
        targets = list(CACHE_DIRS.values())
    elif args[1] in CACHE_DIRS:
        targets = [CACHE_DIRS[args[1]]]
    else:
        print("Invalid cache type. Use one of: jellyfin, plex, abs, all")
        sys.exit(1)

    for target in targets:
        ## Clearing both the cached image files and the cached upload URLs. Leaving
        ## the URL list behind would keep serving the old (possibly expired) links.
        cache_dir = os.path.join("cache", target)
        if os.path.isdir(cache_dir):
            for filename in os.listdir(cache_dir):
                file_path = os.path.join(cache_dir, filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)
        url_cache = os.path.join("cache", f"{target}_cache.txt")
        if os.path.isfile(url_cache):
            open(url_cache, "w").close()
        print(f"Cleared {target} cache.")

    sys.exit(0)

dotenv.load_dotenv()
client_id = os.getenv("CLIENT_ID")
rpc = Presence(client_id)

os.system("cls" if os.name == "nt" else "clear")
if DEBUG: print("Debug mode enabled. Verbose logging is active.")

CHECK_INTERVAL = 7
ACTIVE_CHECK_INTERVAL = 3
LAST_CHECK = 0
LAST_CONNECT_ATTEMPT = 0
RECONNECT_INTERVAL = 10
ACTIVITY = {"jellyfin": None, "plex": None, "audiobookshelf": None}
_ACT = None
_RPC_CONNECTED = False
OLD_PAYLOAD = None

def lg(message):
    global DEBUG
    if DEBUG:
        print(message)

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
if os.path.exists("version.txt"):
    with open("version.txt", "r") as version_file:
        _version = version_file.read().strip(); version_file.close()
else: _version = "unknown"

def safe_rpc_call(fn, **kwargs):
    global _RPC_CONNECTED
    try:
        fn(**kwargs)
        return True
    except (ResponseTimeout, PipeClosed, ConnectionTimeout, InvalidPipe, OSError) as error:
        _RPC_CONNECTED = False
        print(f"Discord RPC call failed: {error}")
        return False

SERVER_ICONS = {
    "jellyfin": "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/jellyfin.png",
    "plex": "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/plex.png",
    "audiobookshelf": "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/audiobookshelf.png",
}
SERVER_NAMES = {"jellyfin": "Jellyfin", "plex": "Plex", "audiobookshelf": "Audiobookshelf"}
TRACK_APP_NAMES = {"jellyfin": "Jellyfin", "plex": "Plexamp", "audiobookshelf": "Audiobookshelf"}

def _fit_text(value, fallback=None):
    """Discord rejects activity text outside 2-128 characters.

    Returns None when nothing usable is left; pypresence drops None fields.
    """
    for candidate in (value, fallback):
        text = str(candidate).strip() if candidate is not None else ""
        if len(text) >= 2:
            return text[:128]
    return None

def _album_line(data):
    """Secondary artwork tooltip, without a bare '(None)' when the year is unknown."""
    album = (data.get("album") or "").strip()
    year = data.get("year")
    if album and year:
        return f"{album} ({year})"
    return album or (str(year) if year else data.get("media_title"))

def _payload_changed(new, old):
    """Whether Discord needs a fresh activity.

    Timestamps are compared with a one second tolerance: polling at slightly
    different points within a second shifts the rounded start/end by a second
    even though nothing actually changed, and re-sending restarts Discord's
    progress animation.
    """
    if not old:
        return True
    if any(new.get(key) != old.get(key) for key in set(new) | set(old)
           if key not in ("start", "end")):
        return True
    return any(abs((new.get(key) or 0) - (old.get(key) or 0)) > 1
               for key in ("start", "end"))

def drpc(data):
    global OLD_PAYLOAD
    if not ensure_rpc_connection():
        return False

    # Round to whole seconds: Discord's timestamps have second resolution, and
    # float jitter would otherwise make every poll look like a changed payload
    # and trigger a needless RPC update.
    now = time.time()
    start = round(now - (data["progress"][0] / 1000))
    end = round(now + (data["progress"][1] - data["progress"][0]) / 1000)
    provider = data.get("server")
    server = SERVER_NAMES.get(provider, "Jellyfin")

    payload = {
        "status_display_type": StatusDisplayType.DETAILS,
        "start": start,
        "end": end,
        "large_image": data.get("image"),
        "small_image": SERVER_ICONS.get(provider),
    }

    if data["media_type"] == "movie":
        payload.update(
            {
                "activity_type": ActivityType.WATCHING,
                "details": f"{data['media_title']} ({data['year']})",
                "state": f"{data['genres']}",
                "name": server,
                "large_text": data["media_title"],
                "small_text": f"better-drpc v{_version}",
            }
        )
    elif data["media_type"] == "episode":
        payload.update(
            {
                "activity_type": ActivityType.WATCHING,
                "details": f"{data['media_title']} ({data['year']})",
                "state": f"S{data['season']}E{data['episode']} - {data['episode_title']}",
                "name": server,
                "large_text": data["media_title"],
                "small_text": f"better-drpc v{_version}",
            }
        )
    elif data["media_type"] == "track":
        payload.update(
            {
                "activity_type": ActivityType.LISTENING,
                "details": _fit_text(data["media_title"]),
                "name": TRACK_APP_NAMES.get(provider, "Jellyfin"),
                "state": _fit_text(f"by {data['artist']}" if data.get("artist") else None),
                "large_text": _fit_text(_album_line(data), data["media_title"]),
                "small_text": f"better-drpc v{_version}",
            }
        )
    else:
        OLD_PAYLOAD = None
        return False
    
    if not _payload_changed(payload, OLD_PAYLOAD):
        return True

    if safe_rpc_call(rpc.update, **payload):
        # Remember what Discord is actually showing; without this the
        # comparison above never matched and every poll re-sent the same
        # activity.
        OLD_PAYLOAD = payload
        return True

    # Retry once after forcing a reconnect when the pipe times out/closes.
    if ensure_rpc_connection(force=True) and safe_rpc_call(rpc.update, **payload):
        OLD_PAYLOAD = payload
        return True
    OLD_PAYLOAD = None
    return False

def clear_presence():
    global OLD_PAYLOAD
    OLD_PAYLOAD = None
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
    adata = get_audiobookshelf_data()
    lg(adata)
    if jdata is not None and ACTIVITY["jellyfin"] is None:
        ACTIVITY["jellyfin"] = time.time()
    elif jdata is None:
        ACTIVITY["jellyfin"] = None

    if pdata is not None and ACTIVITY["plex"] is None:
        ACTIVITY["plex"] = time.time()
    elif pdata is None:
        ACTIVITY["plex"] = None

    if adata is not None and ACTIVITY["audiobookshelf"] is None:
        ACTIVITY["audiobookshelf"] = time.time()
    elif adata is None:
        ACTIVITY["audiobookshelf"] = None

    available = []
    if jdata is not None:
        available.append((ACTIVITY["jellyfin"] or 0, jdata))
    if pdata is not None:
        available.append((ACTIVITY["plex"] or 0, pdata))
    if adata is not None:
        available.append((ACTIVITY["audiobookshelf"] or 0, adata))

    if available:
        data = max(available, key=lambda item: item[0])[1]
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
        # Clear once on the way down (and once at startup), not on every poll.
        if _ACT is not False:
            clear_presence()
            _ACT = False
        lg("No active session found.")
        time.sleep(CHECK_INTERVAL)

