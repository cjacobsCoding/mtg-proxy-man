import os
import requests

def download_image(url, path):
    """Download an image from URL to path. Returns True if downloaded, False if already exists."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    # Skip if already downloaded
    if os.path.exists(path):
        return False

    try:
        with requests.get(url, stream=True, timeout=10) as r:
            if r.status_code == 200:
                with open(path, "wb") as f:
                    for chunk in r.iter_content(1024):
                        f.write(chunk)
                return True
    except Exception as e:
        print(f"Error downloading {url}: {e}")
    
    return False