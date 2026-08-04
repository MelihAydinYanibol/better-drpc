import requests
import dotenv
import os
import base64
import threading
import time

dotenv.load_dotenv()

# Ordered list of upload hosts to try, first success wins. Configurable via the
# IMAGE_UPLOAD_HOSTS env var (comma-separated). litterbox is blocked in some
# regions (e.g. Turkey), so a fallback keeps Rich Presence images working.
# imgbb needs a free API key (IMGBB_API_KEY); it is skipped when unset.
DEFAULT_UPLOAD_HOSTS = "litterbox,imgbb"
UPLOAD_TIMEOUT = 30

if not os.path.exists(f"cache/jellyfin"): os.makedirs(f"cache/jellyfin", exist_ok=True)
if not os.path.exists(f"cache/plex"): os.makedirs(f"cache/plex", exist_ok=True)
if not os.path.exists(f"cache/audiobookshelf"): os.makedirs(f"cache/audiobookshelf", exist_ok=True)
if not os.path.exists(f"cache/jellyfin_cache.txt"): open(f"cache/jellyfin_cache.txt", "w").close()
if not os.path.exists(f"cache/plex_cache.txt"): open(f"cache/plex_cache.txt", "w").close()
if not os.path.exists(f"cache/audiobookshelf_cache.txt"): open(f"cache/audiobookshelf_cache.txt", "w").close()

def _upload_litterbox(file_path, expiry="1h"):
    """Upload to litterbox.catbox.moe. Returns the direct URL or None on failure."""
    url = "https://litterbox.catbox.moe/resources/internals/api.php"
    payload = {"reqtype": "fileupload", "time": expiry}
    with open(file_path, "rb") as file:
        files = {"fileToUpload": file}
        response = requests.post(url, data=payload, files=files, timeout=UPLOAD_TIMEOUT)

    file_url = response.text.strip()
    # Litterbox returns HTTP 200 even on failure, with an error message as the
    # body instead of a URL, so validate the response actually is a URL.
    if response.status_code == 200 and file_url.startswith("http"):
        return file_url
    return None


def _upload_imgbb(file_path, expiry="1h"):
    """Upload to imgbb.com. Requires a free API key in the IMGBB_API_KEY env
    var; returns None (host skipped) when it is not set. The API's data.url is
    already a direct image link, so no rewriting is needed."""
    key = os.getenv("IMGBB_API_KEY")
    if not key:
        return None
    with open(file_path, "rb") as file:
        payload = {"key": key, "image": base64.b64encode(file.read())}
    response = requests.post("https://api.imgbb.com/1/upload",
                             data=payload, timeout=UPLOAD_TIMEOUT)

    if response.status_code != 200:
        return None
    try:
        body = response.json()
    except ValueError:
        return None
    if not body.get("success"):
        return None
    file_url = (body.get("data") or {}).get("url", "")
    if file_url.startswith("http"):
        return file_url
    return None


_UPLOADERS = {
    "litterbox": _upload_litterbox,
    "imgbb": _upload_imgbb,
}


def upload_to_litterbox(file_path, cache_type, id, expiry="1h"):
    """Upload an image to the first available host and cache the resulting URL.

    Tries each host in IMAGE_UPLOAD_HOSTS in order (default: litterbox then
    tmpfiles) and returns the first that succeeds. Name kept for backwards
    compatibility with existing callers.
    """
    if not os.path.exists(file_path):
        return {"code": 404, "message": "File not found"}

    hosts = [h.strip().lower() for h in
             os.getenv("IMAGE_UPLOAD_HOSTS", DEFAULT_UPLOAD_HOSTS).split(",") if h.strip()]

    errors = []
    for host in hosts:
        uploader = _UPLOADERS.get(host)
        if uploader is None:
            errors.append(f"{host}: unknown host")
            continue
        try:
            file_url = uploader(file_path, expiry)
        except (requests.RequestException, OSError) as e:
            errors.append(f"{host}: {e}")
            continue
        if file_url:
            with open(f"cache/{cache_type}_cache.txt", "a") as cache_file:
                cache_file.write(f"{id}: {file_url}\n")
            return {"code": 200, "url": file_url,
                    "message": f"File uploaded successfully via {host}"}
        errors.append(f"{host}: rejected or unavailable")

    return {"code": 502, "message": "Failed to upload file (" + "; ".join(errors) + ")"}

def cache_image(image_url,id,type,headers=None):
    if not os.path.exists(f"cache/jellyfin"): os.makedirs(f"cache/jellyfin", exist_ok=True)
    if not os.path.exists(f"cache/plex"): os.makedirs(f"cache/plex", exist_ok=True)
    if not os.path.exists(f"cache/audiobookshelf"): os.makedirs(f"cache/audiobookshelf", exist_ok=True)
    if type in ["jellyfin", "plex", "audiobookshelf"]:
        response = requests.get(image_url, stream=True, headers=headers, timeout=UPLOAD_TIMEOUT)
        if response.status_code == 200:
            with open(f'cache/{type}/{id}.jpg', 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            return {"code":response.status_code, "message":"Image downloaded successfully", "path":f"cache/{type}/{id}.jpg"}
        else:
            return {"code":response.status_code}
    else:
        return {"code":400, "message":"Invalid type specified"}
    

# In-memory cache of already-resolved public image URLs so the main loop never
# has to touch the network for an item it has already handled. Resolving an
# image (download from the media server + upload to a public host) is slow and
# must never block the presence update, so it runs in a background thread while
# get_image() returns immediately.
_MEM_URL = {}          # (type, id) -> (url, resolved_at)
_INFLIGHT = set()      # (type, id) currently being resolved in a worker thread
_MEM_LOCK = threading.Lock()
# Refresh before litterbox's 1h expiry so Discord never shows a dead image link.
_URL_TTL = 50 * 60


def _resolve_worker(url, id, type, icon_mode, headers, key):
    """Background worker: do the slow download/upload, then cache the result."""
    try:
        result = _resolve_sync(url, id, type, icon_mode=icon_mode, headers=headers)
        if result.get("code") == 200 and result.get("url"):
            with _MEM_LOCK:
                _MEM_URL[key] = (result["url"], time.time())
    finally:
        with _MEM_LOCK:
            _INFLIGHT.discard(key)


def get_image(url, id, type, icon_mode=False, headers=None):
    """Return a public image URL without blocking the caller.

    If the URL is already resolved (and fresh), it is returned immediately.
    Otherwise resolution is kicked off in a background thread and the last known
    URL (or None) is returned right away, so a song/media change is reflected in
    Discord instantly instead of waiting on artwork upload.
    """
    key = (type, str(id))
    now = time.time()

    with _MEM_LOCK:
        entry = _MEM_URL.get(key)
        fresh = entry is not None and (now - entry[1]) < _URL_TTL
        if not fresh and key not in _INFLIGHT:
            _INFLIGHT.add(key)
            start_worker = True
        else:
            start_worker = False

    if fresh:
        return {"code": 200, "url": entry[0], "message": "Image URL from memory cache"}

    if start_worker:
        threading.Thread(
            target=_resolve_worker,
            args=(url, id, type, icon_mode, headers, key),
            daemon=True,
        ).start()

    # Serve a stale-but-usable URL while a refresh runs; otherwise None for now.
    return {
        "code": 200 if entry else 202,
        "url": entry[0] if entry else None,
        "message": "Resolving image in background",
    }


def _resolve_sync(url,id,type,icon_mode=False,headers=None):
    # Check if cached URL exists and is still valid
    if os.path.exists(f"cache/{type}_cache.txt"):
        with open(f"cache/{type}_cache.txt", "r") as cache_file:
            for line in cache_file:
                cached_id, cached_url = line.strip().split(": ", 1)
                if cached_id == id:
                    try:
                        response = requests.get(cached_url, timeout=5)
                        if response.status_code == 200:
                            return {"code": 200, "url": cached_url, "message": "Image URL retrieved from cache"}
                    except requests.RequestException:
                        pass
                    # URL is expired/invalid, fall through to re-cache
    
    # If we get here, either cache doesn't exist, ID wasn't found, or URL was expired
    if not os.path.exists(f"cache/{type}/{id}.jpg"):
        if icon_mode:
            data = {"code": 200, "message": "Icon mode enabled, skipping caching.", "path": url}
        else:
            data = cache_image(url, id, type, headers=headers)
    else: 
        data = {"code": 200, "message": "Image already cached", "path": f"cache/{type}/{id}.jpg"}
    
    if data["code"] == 200:
        upload_response = upload_to_litterbox(data["path"],type,id=id)
        if upload_response["code"] == 200:
            return {"code": 200, "url": upload_response["url"], "message": "Image uploaded and URL retrieved"}
        else:
            return {"code": upload_response["code"], "message": "Failed to upload image to litterbox"}
    else:
        return {"code": data["code"], "message": "Failed to cache image"}

