import requests
import dotenv
import os
if not os.path.exists(f"cache/jellyfin"): os.makedirs(f"cache/jellyfin", exist_ok=True)
if not os.path.exists(f"cache/plex"): os.makedirs(f"cache/plex", exist_ok=True)
if not os.path.exists(f"cache/jellyfin_cache.txt"): open(f"cache/jellyfin_cache.txt", "w").close()
if not os.path.exists(f"cache/plex_cache.txt"): open(f"cache/plex_cache.txt", "w").close()


def upload_to_litterbox(file_path, cache_type, expiry="1h"):
    url = "https://litterbox.catbox.moe/resources/internals/api.php"
    
    # Define the parameters for the request
    payload = {
        "reqtype": "fileupload",
        "time": expiry
    }
    
    # Open the file in binary mode and send the request
    try:
        with open(file_path, "rb") as file:
            files = {"fileToUpload": file}
            response = requests.post(url, data=payload, files=files)
            
            if response.status_code == 200:
                with open(f"cache/{cache_type}_cache.txt", "a") as cache_file:
                    file_url = response.text.strip()
                    cache_file.write(f"{id}: {file_url}\n")
                return {"code": response.status_code, "url": response.text, "message": "File uploaded successfully"}
            else:
                return {"code": response.status_code, "message": "Failed to upload file"}
                
    except FileNotFoundError:
        return {"code": 404, "message": "File not found"}

def cache_image(image_url,id,type):
    if not os.path.exists(f"cache/jellyfin"): os.makedirs(f"cache/jellyfin", exist_ok=True)
    if not os.path.exists(f"cache/plex"): os.makedirs(f"cache/plex", exist_ok=True)
    if type in ["jellyfin", "plex"]:
        response = requests.get(image_url, stream=True)
        if response.status_code == 200:
            with open(f'cache/{type}/{id}.jpg', 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            return {"code":response.status_code, "message":"Image downloaded successfully", "path":f"cache/{type}/{id}.jpg"}
        else:
            return {"code":response.status_code}
    else:
        return {"code":400, "message":"Invalid type specified"}
    

def get_image(url,id,type):
    if os.path.exists(f"cache/{type}_cache.txt"):
        with open(f"cache/{type}_cache.txt", "r") as cache_file:
            for line in cache_file:
                cached_id, cached_url = line.strip().split(": ", 1)
                if cached_id == id:
                    return {"code": 200, "url": cached_url, "message": "Image URL retrieved from cache"}
            else:
                data = cache_image(url, id, type)
                if data["code"] == 200:
                    upload_response = upload_to_litterbox(data["path"], type)
                    if upload_response["code"] == 200:
                        return {"code": 200, "url": upload_response["url"], "message": "Image uploaded and URL retrieved"}
                    else:
                        return {"code": upload_response["code"], "message": "Failed to upload image to litterbox"}
                else:
                    return {"code": data["code"], "message": "Failed to cache image"}
            cache_file.close()

