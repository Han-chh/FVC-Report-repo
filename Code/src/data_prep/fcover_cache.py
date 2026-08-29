"""Immutable, validated acquisition of official Copernicus FCOVER COGs.

The cache is deliberately separate from scientific outputs.  It replaces
ad-hoc GDAL range reads with a recoverable local source artifact that can be
checksummed before Rasterio/GEE parity work begins.
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import rasterio
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
import boto3


class SourceDownloadError(RuntimeError):
    """A bounded official-source acquisition failure."""


@dataclass(frozen=True)
class CachedSource:
    item_id: str
    asset_key: str
    source_url: str
    access_method: str
    path: Path
    checksum: str
    file_size: int
    etag: str | None
    downloaded_at: str
    dtype: str
    nodata: float | int | None
    crs: str | None
    transform: tuple[float, float, float, float, float, float]
    width: int
    height: int


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _official_https_url(asset: dict[str, Any]) -> str:
    alternate = (asset.get("alternate") or {}).get("https") or {}
    value = alternate.get("href")
    if not value:
        raise SourceDownloadError("OFFICIAL_HTTPS_ACCESS_URL_MISSING")
    url = str(value)
    if "dataspace.copernicus.eu" not in url:
        raise SourceDownloadError("UNAPPROVED_SOURCE_ROUTE")
    return url


def _headers(offset: int) -> dict[str, str]:
    token = os.getenv("CDSE_DOWNLOAD_TOKEN")
    if not token:
        raise SourceDownloadError("CDSE_DOWNLOAD_TOKEN_MISSING")
    headers = {"Authorization": f"Bearer {token}"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    return headers


def _s3_identity(asset: dict[str, Any]) -> tuple[str, str] | None:
    href = str(asset.get("href") or "")
    if not href.startswith("s3://"):
        return None
    bucket, _, key = href[5:].partition("/")
    return (bucket, key) if bucket and key else None


def _s3_client(connect_timeout_s: float, read_timeout_s: float):
    access_key = os.getenv("EODATA_S3_ACCESS_KEY")
    secret_key = os.getenv("EODATA_S3_SECRET_KEY")
    if not access_key or not secret_key:
        raise SourceDownloadError("CDSE_NATIVE_ACCESS_MISSING")
    endpoint = os.getenv("EODATA_S3_ENDPOINT", "https://eodata.dataspace.copernicus.eu")
    if not endpoint.startswith("http"):
        endpoint = "https://" + endpoint
    return boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=access_key,
                        aws_secret_access_key=secret_key,
                        config=Config(connect_timeout=connect_timeout_s, read_timeout=read_timeout_s,
                                      retries={"max_attempts": 0, "mode": "standard"}))


def _cache_record(path: Path, *, item_id: str, asset_key: str, source_url: str,
                  access_method: str, etag: str | None, timestamp: str) -> CachedSource:
    with rasterio.open(path) as raster:
        return CachedSource(item_id=item_id, asset_key=asset_key, source_url=source_url,
                            access_method=access_method, path=path, checksum=sha256_file(path),
                            file_size=path.stat().st_size, etag=etag, downloaded_at=timestamp,
                            dtype=raster.dtypes[0], nodata=raster.nodata,
                            crs=raster.crs.to_string() if raster.crs else None,
                            transform=tuple(raster.transform)[:6], width=raster.width, height=raster.height)


def acquire_official_cog(item_id: str, asset_key: str, asset: dict[str, Any], cache_root: Path,
                         *, connect_timeout_s: float = 15, read_timeout_s: float = 60,
                         retries: int = 3, backoff_s: float = 2) -> CachedSource:
    """Download one official COG with bounded retries and immutable identity.

    A partial object is never returned.  A valid cached object is recognised by
    its checksum-bearing filename and a Rasterio open, then reused unchanged.
    """
    if retries < 1:
        raise ValueError("DOWNLOAD_RETRIES_MUST_BE_POSITIVE")
    source_url = _official_https_url(asset)
    s3_identity = _s3_identity(asset)
    safe_item = item_id.replace("/", "_")
    safe_asset = asset_key.replace("/", "_")
    directory = cache_root / safe_item
    directory.mkdir(parents=True, exist_ok=True)
    prefix = f"{safe_item}__{safe_asset}__"
    for cached in sorted(directory.glob(prefix + "*.tif")):
        try:
            checksum = sha256_file(cached)
            if cached.name == f"{prefix}{checksum}.tif":
                return _cache_record(cached, item_id=item_id, asset_key=asset_key, source_url=source_url,
                                     access_method="official_cdse_https_cache_reuse", etag=None,
                                     timestamp=datetime.now(timezone.utc).isoformat())
        except (OSError, rasterio.errors.RasterioError):
            continue
    partial = directory / f".{safe_item}__{safe_asset}.partial"
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            offset = partial.stat().st_size if partial.exists() else 0
            if s3_identity and os.getenv("EODATA_S3_ACCESS_KEY") and os.getenv("EODATA_S3_SECRET_KEY"):
                bucket, key = s3_identity
                params: dict[str, Any] = {"Bucket": bucket, "Key": key}
                if offset: params["Range"] = f"bytes={offset}-"
                response = _s3_client(connect_timeout_s, read_timeout_s).get_object(**params)
                with partial.open("ab" if offset else "wb") as stream:
                    for chunk in iter(lambda: response["Body"].read(1024 * 1024), b""):
                        stream.write(chunk)
                etag = str(response.get("ETag") or "").strip('"') or None
                access_method = "official_cdse_s3"
                expected = str(asset.get("file:size") or "")
            else:
                with requests.get(source_url, headers=_headers(offset), stream=True,
                                  timeout=(connect_timeout_s, read_timeout_s)) as response:
                # If the server cannot resume, discard only the incomplete
                # temporary file and restart the same bounded attempt.
                    if offset and response.status_code == 200:
                        partial.unlink(missing_ok=True); offset = 0
                    response.raise_for_status()
                    if offset and response.status_code != 206:
                        raise SourceDownloadError(f"RESUME_RESPONSE_INVALID:{response.status_code}")
                    mode = "ab" if offset else "wb"
                    with partial.open(mode) as stream:
                        for chunk in response.iter_content(1024 * 1024):
                            if chunk:
                                stream.write(chunk)
                    expected = response.headers.get("Content-Range", "").split("/")[-1] if offset else response.headers.get("Content-Length")
                    etag = response.headers.get("ETag")
                    access_method = "official_cdse_https"
            if expected and expected.isdigit() and partial.stat().st_size != int(expected):
                raise SourceDownloadError(f"FILE_SIZE_MISMATCH:{partial.stat().st_size}!={expected}")
            stac_size = asset.get("file:size")
            if stac_size is not None and partial.stat().st_size != int(stac_size):
                raise SourceDownloadError(f"STAC_FILE_SIZE_MISMATCH:{partial.stat().st_size}!={stac_size}")
            # A successful TIFF open is mandatory before the atomic rename.
            with rasterio.open(partial) as raster:
                if raster.width <= 0 or raster.height <= 0 or raster.count != 1:
                    raise SourceDownloadError("SOURCE_RASTER_INVALID")
            checksum = sha256_file(partial)
            final = directory / f"{prefix}{checksum}.tif"
            partial.replace(final)
            return _cache_record(final, item_id=item_id, asset_key=asset_key, source_url=source_url,
                                 access_method=access_method, etag=etag,
                                 timestamp=datetime.now(timezone.utc).isoformat())
        except (requests.RequestException, BotoCoreError, ClientError, OSError, rasterio.errors.RasterioError, SourceDownloadError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(backoff_s * (2 ** attempt))
    raise SourceDownloadError(f"DOWNLOAD_FAILED_AFTER_{retries}_ATTEMPTS:{last_error}")
