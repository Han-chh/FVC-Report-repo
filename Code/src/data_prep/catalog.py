from __future__ import annotations

import json
import os
import time
from urllib.parse import urlparse
import requests
from functools import lru_cache

PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"


def search(collection: str, bbox, *, datetime: str | None = None, limit: int = 1000, retries: int = 5):
    payload = {"collections": [collection], "bbox": list(bbox), "limit": limit}
    if datetime:
        payload["datetime"] = datetime
    for attempt in range(retries):
        try:
            response = requests.post(f"{PC_STAC}/search", json=payload, timeout=120)
        except requests.RequestException:
            if attempt + 1 == retries: raise
            time.sleep(2 ** attempt); continue
        if response.ok:
            return response.json().get("features", [])
        if attempt + 1 == retries:
            response.raise_for_status()
        time.sleep(2 ** attempt)


@lru_cache(maxsize=32)
def _container_token(account: str, container: str) -> str | None:
    environment_key = "PC_SAS_TOKEN_" + (account + "_" + container).upper().replace("-", "_")
    if os.environ.get(environment_key):
        return os.environ[environment_key]
    token_url = f"https://planetarycomputer.microsoft.com/api/sas/v1/token/{account}/{container}"
    for attempt in range(6):
        try:
            response = requests.get(token_url, timeout=60)
        except requests.RequestException:
            if attempt == 5: raise
            time.sleep(2 ** attempt); continue
        if response.ok: return response.json()["token"]
        if response.status_code == 404: return None
        if response.status_code != 429: response.raise_for_status()
        time.sleep(2 ** attempt)
    return None


def signed_href(href: str) -> str:
    parsed = urlparse(href)
    account = parsed.netloc.split(".")[0]
    container = parsed.path.strip("/").split("/")[0]
    token = _container_token(account, container)
    return href if token is None else href + ("&" if "?" in href else "?") + token
