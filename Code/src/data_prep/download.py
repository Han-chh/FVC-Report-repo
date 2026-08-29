"""Standalone, resumable acquisition of publication-native source assets.

This module deliberately contains no runtime import from ``model`` or
``report/code``.  Credentials are loaded into the process environment only and
are never serialized.  It downloads source-resolution red/NIR and native QA
for Sentinel-2, Landsat and MOD09Q1 through Earth Engine, plus native-grid
FCOVER/QFLAG/NOBS windows through the Copernicus Data Space S3 endpoint.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import shutil
import time
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import ee
import httpx
import numpy as np
import rasterio
import requests
from affine import Affine
from dotenv import dotenv_values
from pyproj import CRS, Transformer
from rasterio.crs import CRS as RasterioCRS
from rasterio.merge import merge
from rasterio.session import AWSSession
from rasterio.windows import Window, from_bounds
from shapely.geometry import shape
from shapely.ops import transform as transform_geometry
from .fcover import fcover_value_valid_mask


S2_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"
S2_CLOUD_COLLECTION = "COPERNICUS/S2_CLOUD_PROBABILITY"
LANDSAT_COLLECTIONS = ("LANDSAT/LC08/C02/T1_L2", "LANDSAT/LC09/C02/T1_L2")
MODIS_COLLECTION = "MODIS/061/MOD09Q1"
FCOVER_STAC_COLLECTION = "clms_fcover_global_300m_10daily_v2_cog"
FCOVER_STAC_ITEMS = f"https://stac.dataspace.copernicus.eu/v1/collections/{FCOVER_STAC_COLLECTION}/items"
FCOVER_ODATA = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
MODIS_SINUSOIDAL_ALIAS = "SR-ORG:6974"
MODIS_SINUSOIDAL_PROJ4 = "+proj=sinu +R=6371007.181 +nadgrids=@null +wktext +units=m +no_defs"
NOMINAL_MONTH_DAYS = ((7, 20), (7, 31), (8, 10))


@dataclass(frozen=True)
class GridTile:
    xmin: float
    ymin: float
    xmax: float
    ymax: float
    width: int
    height: int
    transform: tuple[float, float, float, float, float, float]


def load_credentials(env_file: Path) -> list[str]:
    """Load non-empty values without returning or logging their contents."""
    loaded: list[str] = []
    for key, value in dotenv_values(env_file).items():
        if value is not None and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


def require_credentials() -> None:
    if not os.getenv("EE_PROJECT_ID"):
        raise RuntimeError("EE_PROJECT_MISSING")
    if not (os.getenv("EODATA_S3_ACCESS_KEY") and os.getenv("EODATA_S3_SECRET_KEY")) and not os.getenv("CDSE_DOWNLOAD_TOKEN"):
        raise RuntimeError("CDSE_NATIVE_ACCESS_MISSING")


def initialize_earth_engine() -> None:
    require_credentials()
    ee.Initialize(project=os.environ["EE_PROJECT_ID"], opt_url="https://earthengine-highvolume.googleapis.com")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_crs(value: str) -> CRS:
    return CRS.from_user_input(MODIS_SINUSOIDAL_PROJ4 if value.upper() == MODIS_SINUSOIDAL_ALIAS else value)


def geometry_bounds_in_crs(feature: dict[str, Any], target_crs: str) -> tuple[float, float, float, float]:
    geometry = shape(feature["geometry"])
    transformer = Transformer.from_crs(4326, canonical_crs(target_crs), always_xy=True)
    return transform_geometry(transformer.transform, geometry).bounds


def grid_tiles(bounds: tuple[float, float, float, float], resolution: float, tile_size: int = 2048) -> list[GridTile]:
    xmin, ymin, xmax, ymax = bounds
    xmin = math.floor(xmin / resolution) * resolution
    ymin = math.floor(ymin / resolution) * resolution
    xmax = math.ceil(xmax / resolution) * resolution
    ymax = math.ceil(ymax / resolution) * resolution
    width = int(round((xmax - xmin) / resolution))
    height = int(round((ymax - ymin) / resolution))
    tiles: list[GridTile] = []
    for row in range(0, height, tile_size):
        tile_height = min(tile_size, height - row)
        tile_ymax = ymax - row * resolution
        tile_ymin = tile_ymax - tile_height * resolution
        for column in range(0, width, tile_size):
            tile_width = min(tile_size, width - column)
            tile_xmin = xmin + column * resolution
            tile_xmax = tile_xmin + tile_width * resolution
            tiles.append(GridTile(tile_xmin, tile_ymin, tile_xmax, tile_ymax, tile_width, tile_height,
                                  (resolution, 0.0, tile_xmin, 0.0, -resolution, tile_ymax)))
    return tiles


def _write_ee_response(content: bytes, destination: Path) -> None:
    if content[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith((".tif", ".tiff"))]
            if not names:
                raise RuntimeError("EE_DOWNLOAD_ZIP_HAS_NO_TIFF")
            destination.write_bytes(archive.read(names[0]))
    else:
        destination.write_bytes(content)


def _download_url(url: str, destination: Path, retries: int = 5, timeout: int = 300) -> None:
    last_error: Exception | None = None
    partial = destination.with_suffix(destination.suffix + ".part")
    for attempt in range(retries):
        try:
            with requests.get(url, stream=True, timeout=timeout) as response:
                response.raise_for_status()
                with partial.open("wb") as stream:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            stream.write(chunk)
            _write_ee_response(partial.read_bytes(), destination)
            partial.unlink(missing_ok=True)
            with rasterio.open(destination) as source:
                if source.width <= 0 or source.height <= 0:
                    raise RuntimeError("EMPTY_RASTER")
            return
        except Exception as exc:
            last_error = exc
            partial.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            if attempt + 1 < retries:
                time.sleep(min(30, 2**attempt))
    raise RuntimeError(f"EE_DOWNLOAD_FAILED:{last_error}")


def _normalize_modis_crs(path: Path, requested_crs: str) -> None:
    if requested_crs.upper() != MODIS_SINUSOIDAL_ALIAS:
        return
    with rasterio.open(path, "r+") as dataset:
        dataset.crs = RasterioCRS.from_wkt(canonical_crs(requested_crs).to_wkt())


def download_ee_image(image: ee.Image, bands: Sequence[str], feature: dict[str, Any], target_crs: str,
                      resolution: int, destination: Path, tile_size: int = 2048) -> None:
    """Download an exact-resolution AOI bounding grid, resumably by final file."""
    if destination.is_file():
        with rasterio.open(destination) as source:
            if source.count == len(bands) and source.crs and source.width > 0 and source.height > 0:
                return
        destination.unlink()
    destination.parent.mkdir(parents=True, exist_ok=True)
    bounds = geometry_bounds_in_crs(feature, target_crs)
    tiles = grid_tiles(bounds, resolution, tile_size)
    temp_root = destination.parent / f".{destination.stem}_tiles"
    temp_root.mkdir(parents=True, exist_ok=True)
    tile_paths: list[Path] = []
    try:
        selected = image.select(list(bands))
        for index, tile in enumerate(tiles):
            tile_path = temp_root / f"tile_{index:04d}.tif"
            if not tile_path.is_file():
                params = {"name": f"{destination.stem}_{index:04d}", "crs": target_crs,
                          "crs_transform": list(tile.transform), "dimensions": [tile.width, tile.height],
                          "format": "GEO_TIFF"}
                _download_url(selected.getDownloadURL(params), tile_path)
                _normalize_modis_crs(tile_path, target_crs)
            tile_paths.append(tile_path)
        sources = [rasterio.open(path) for path in tile_paths]
        temporary = destination.with_suffix(destination.suffix + ".part.tif")
        try:
            merge(sources, dst_path=temporary, nodata=0, mem_limit=128)
        finally:
            for source in sources:
                source.close()
        _normalize_modis_crs(temporary, target_crs)
        temporary.replace(destination)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def _nominal_dates_for_observation(year: int, start: date, end: date) -> str:
    labels = []
    for month, day in NOMINAL_MONTH_DAYS:
        nominal = date(year, month, day)
        if start <= nominal + timedelta(days=15) and end >= nominal - timedelta(days=15):
            labels.append(nominal.isoformat())
    return ";".join(labels)


def _raster_record(path: Path, *, aoi_id: str, sensor: str, platform: str, year: int,
                   nominal_dates: str, acquisition: str, product_id: str, collection: str,
                   version: str, processing_level: str, source_catalog: str, source_uri: str,
                   scale: float, offset: float, qa_band: str, geometry_version: str,
                   asset_role: str, status: str = "DOWNLOADED") -> dict[str, Any]:
    with rasterio.open(path) as source:
        return {
            "aoi_id": aoi_id, "sensor": sensor, "platform": platform, "year": year,
            "nominal_fcover_date": nominal_dates, "acquisition_datetime": acquisition,
            "product_id": product_id, "collection": collection, "version": version,
            "processing_level": processing_level, "source_catalog": source_catalog,
            "source_uri": source_uri, "local_path": str(path.resolve()), "file_size": path.stat().st_size,
            "checksum": sha256_file(path), "crs": source.crs.to_string() if source.crs else None,
            "transform": list(source.transform)[:6], "width": source.width, "height": source.height,
            "count": source.count, "dtype": list(source.dtypes), "nodata": source.nodata,
            "scale": scale, "offset": offset, "qa_band": qa_band,
            "download_timestamp": datetime.now(timezone.utc).isoformat(),
            "clipping_geometry_version": geometry_version, "asset_role": asset_role, "status": status,
        }


def _get_collection_items(collection: ee.ImageCollection, fields: Sequence[str]) -> list[dict[str, Any]]:
    count = int(collection.size().getInfo())
    values = collection.toList(count)
    output = []
    for index in range(count):
        image = ee.Image(values.get(index))
        info = image.toDictionary(list(fields)).getInfo()
        info["_image"] = image
        output.append(info)
    return output


def download_sentinel2(feature: dict[str, Any], year: int, root: Path, limit: int | None = None) -> list[dict[str, Any]]:
    geometry = ee.Geometry(feature["geometry"])
    collection = (ee.ImageCollection(S2_COLLECTION).filterBounds(geometry)
                  .filterDate(f"{year}-06-05", f"{year}-08-26")
                  .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", 80)).sort("system:time_start"))
    items = _get_collection_items(collection, ("system:id", "system:index", "system:time_start",
                                                 "CLOUDY_PIXEL_PERCENTAGE", "MGRS_TILE", "PRODUCT_ID"))
    if limit is not None:
        items = items[:limit]
    clouds = ee.ImageCollection(S2_CLOUD_COLLECTION)
    records: list[dict[str, Any]] = []
    aoi_id = feature["properties"]["aoi_id"]
    version = feature["properties"]["geometry_version"]
    for info in items:
        image = info.pop("_image")
        item_id = str(info["system:index"])
        acquisition = datetime.fromtimestamp(info["system:time_start"] / 1000, tz=timezone.utc)
        item_root = root / "clipped_native" / aoi_id / "sentinel2" / str(year) / item_id
        projection = image.select("B4").projection().getInfo(); crs = projection["crs"]
        reflectance = item_root / "reflectance_dn.tif"
        scl = item_root / "scl.tif"
        cloud = item_root / "cloud_probability.tif"
        download_ee_image(image, ("B4", "B8"), feature, crs, 10, reflectance)
        download_ee_image(image, ("SCL",), feature, crs, 20, scl)
        cloud_match = clouds.filter(ee.Filter.eq("system:index", item_id))
        if int(cloud_match.size().getInfo()) == 0:
            raise RuntimeError(f"S2_CLOUD_PROBABILITY_MISSING:{aoi_id}:{item_id}")
        download_ee_image(ee.Image(cloud_match.first()), ("probability",), feature, crs, 10, cloud)
        nominal = _nominal_dates_for_observation(year, acquisition.date(), acquisition.date())
        common = dict(aoi_id=aoi_id, sensor="sentinel2", platform="Sentinel-2",
                      year=year, nominal_dates=nominal, acquisition=acquisition.isoformat(),
                      product_id=str(info.get("PRODUCT_ID") or item_id), collection=S2_COLLECTION,
                      version="HARMONIZED", processing_level="L2A surface reflectance",
                      source_catalog="Google Earth Engine", source_uri=f"{S2_COLLECTION}/{item_id}",
                      geometry_version=version)
        records.extend([
            _raster_record(reflectance, scale=0.0001, offset=0.0, qa_band="", asset_role="red_nir_dn", **common),
            _raster_record(scl, scale=1.0, offset=0.0, qa_band="SCL", asset_role="native_qa_scl", **common),
            _raster_record(cloud, scale=1.0, offset=0.0, qa_band="probability", asset_role="cloud_probability", **common),
        ])
    return records


def download_landsat(feature: dict[str, Any], year: int, root: Path, limit: int | None = None) -> list[dict[str, Any]]:
    geometry = ee.Geometry(feature["geometry"])
    merged: ee.ImageCollection | None = None
    for collection_id in LANDSAT_COLLECTIONS:
        subset = (ee.ImageCollection(collection_id).filterBounds(geometry)
                  .filterDate(f"{year}-06-05", f"{year}-08-26")
                  .filter(ee.Filter.lte("CLOUD_COVER", 80)))
        merged = subset if merged is None else merged.merge(subset)
    assert merged is not None
    items = _get_collection_items(merged.sort("system:time_start"),
                                  ("system:id", "system:index", "system:time_start", "CLOUD_COVER", "SPACECRAFT_ID"))
    if limit is not None:
        items = items[:limit]
    records: list[dict[str, Any]] = []
    aoi_id = feature["properties"]["aoi_id"]; version = feature["properties"]["geometry_version"]
    for info in items:
        image = info.pop("_image")
        image_id = str(info["system:id"]); item_id = str(info["system:index"])
        acquisition = datetime.fromtimestamp(info["system:time_start"] / 1000, tz=timezone.utc)
        collection_id = image_id.rsplit("/", 1)[0]
        item_root = root / "clipped_native" / aoi_id / "landsat" / str(year) / item_id
        crs = image.select("SR_B4").projection().getInfo()["crs"]
        reflectance = item_root / "reflectance_dn.tif"; qa = item_root / "qa.tif"
        download_ee_image(image, ("SR_B4", "SR_B5"), feature, crs, 30, reflectance)
        download_ee_image(image, ("QA_PIXEL", "QA_RADSAT"), feature, crs, 30, qa)
        nominal = _nominal_dates_for_observation(year, acquisition.date(), acquisition.date())
        platform = str(info.get("SPACECRAFT_ID") or ("LANDSAT_8" if "LC08" in collection_id else "LANDSAT_9"))
        common = dict(aoi_id=aoi_id, sensor="landsat", platform=platform, year=year,
                      nominal_dates=nominal, acquisition=acquisition.isoformat(), product_id=item_id,
                      collection=collection_id, version="Collection 2", processing_level="Level-2 Tier 1",
                      source_catalog="Google Earth Engine", source_uri=image_id, geometry_version=version)
        records.extend([
            _raster_record(reflectance, scale=0.0000275, offset=-0.2, qa_band="", asset_role="red_nir_dn", **common),
            _raster_record(qa, scale=1.0, offset=0.0, qa_band="QA_PIXEL;QA_RADSAT", asset_role="native_qa", **common),
        ])
    return records


def download_modis(feature: dict[str, Any], year: int, root: Path, limit: int | None = None) -> list[dict[str, Any]]:
    geometry = ee.Geometry(feature["geometry"])
    collection = (ee.ImageCollection(MODIS_COLLECTION).filterBounds(geometry)
                  .filterDate(f"{year}-05-29", f"{year}-08-26").sort("system:time_start"))
    items = _get_collection_items(collection, ("system:id", "system:index", "system:time_start"))
    if limit is not None:
        items = items[:limit]
    records: list[dict[str, Any]] = []
    aoi_id = feature["properties"]["aoi_id"]; version = feature["properties"]["geometry_version"]
    for info in items:
        image = info.pop("_image")
        image_id = str(info["system:id"]); item_id = str(info["system:index"])
        acquisition = datetime.fromtimestamp(info["system:time_start"] / 1000, tz=timezone.utc)
        support_end = acquisition.date() + timedelta(days=7)
        item_root = root / "clipped_native" / aoi_id / "modis" / str(year) / item_id
        crs = image.select("sur_refl_b01").projection().getInfo()["crs"]
        reflectance = item_root / "reflectance_dn.tif"; qa = item_root / "qa.tif"
        download_ee_image(image, ("sur_refl_b01", "sur_refl_b02"), feature, crs, 250, reflectance)
        download_ee_image(image, ("State", "QA"), feature, crs, 250, qa)
        nominal = _nominal_dates_for_observation(year, acquisition.date(), support_end)
        common = dict(aoi_id=aoi_id, sensor="modis", platform="Terra MODIS", year=year,
                      nominal_dates=nominal, acquisition=acquisition.isoformat(), product_id=item_id,
                      collection=MODIS_COLLECTION, version="061", processing_level="8-day L3 surface reflectance",
                      source_catalog="Google Earth Engine", source_uri=image_id, geometry_version=version)
        records.extend([
            _raster_record(reflectance, scale=0.0001, offset=0.0, qa_band="", asset_role="red_nir_dn", **common),
            _raster_record(qa, scale=1.0, offset=0.0, qa_band="State;QA", asset_role="native_qa", **common),
        ])
    return records


def _fcover_item(client: httpx.Client, nominal_date: str) -> dict[str, Any]:
    token = nominal_date.replace("-", "")
    response = client.get(FCOVER_ODATA, params={"$filter": f"contains(Name,'FCOVER300-RT6_{token}0000') and contains(Name,'_V2.') and contains(Name,'_cog')",
                                                 "$top": 10, "$orderby": "PublicationDate desc"})
    response.raise_for_status(); products = response.json().get("value") or []
    if not products:
        raise RuntimeError(f"FCOVER_PRODUCT_NOT_FOUND:{nominal_date}")
    item_id = str(products[0]["Name"]).removesuffix(".zip")
    item_response = client.get(f"{FCOVER_STAC_ITEMS}/{item_id}"); item_response.raise_for_status()
    item = item_response.json(); item["_odata"] = products[0]
    return item


def _fcover_assets(item: dict[str, Any]) -> list[dict[str, Any]]:
    assets = item.get("assets") or {}
    # This is the verified V2.0.1 source schema.  In particular, the source
    # product has no ``dataMask`` asset: validity is derived below from native
    # raster validity/NoData semantics, never advertised as source metadata.
    keys = ("fcover300_fcover", "fcover300_rmse", "fcover300_nobs",
            "fcover300_lbefore", "fcover300_lafter", "fcover300_qflag")
    if all(key in assets for key in keys):
        return [assets[key] for key in keys]
    result = []
    for needle in ("-FCOVER-", "-RMSE-", "-NOBS-", "-LBEFORE-", "-LAFTER-", "-QFLAG-"):
        match = next((asset for asset in assets.values() if needle in str(asset.get("href", "")).upper()), None)
        if match is None:
            raise RuntimeError(f"FCOVER_ASSET_MISSING:{needle}")
        result.append(match)
    return result


def _fcover_grid(item: dict[str, Any], assets: Sequence[dict[str, Any]]) -> tuple[Affine, int, int, str]:
    transforms = [asset.get("proj:transform") for asset in assets]
    shapes = [asset.get("proj:shape") for asset in assets]
    if any(not value for value in transforms) or any(not value for value in shapes):
        raise RuntimeError("FCOVER_GRID_METADATA_MISSING")
    first_transform = [float(value) for value in transforms[0][:6]]
    first_shape = [int(value) for value in shapes[0][:2]]
    if any(not np.allclose(first_transform, [float(value) for value in candidate[:6]], atol=1e-12, rtol=0)
           for candidate in transforms[1:]) or any(first_shape != [int(value) for value in candidate[:2]] for candidate in shapes[1:]):
        raise RuntimeError("FCOVER_ASSET_GRID_MISMATCH")
    crs = str((item.get("properties") or {}).get("proj:code") or "")
    if crs != "EPSG:4326":
        raise RuntimeError(f"FCOVER_CRS_INVALID:{crs}")
    return Affine(*first_transform), first_shape[1], first_shape[0], crs


def _fcover_window(bounds: Sequence[float], transform: Affine, width: int, height: int) -> Window:
    requested = from_bounds(*bounds, transform=transform)
    c0 = max(0, int(np.floor(requested.col_off))); r0 = max(0, int(np.floor(requested.row_off)))
    c1 = min(width, int(np.ceil(requested.col_off + requested.width)))
    r1 = min(height, int(np.ceil(requested.row_off + requested.height)))
    if c0 >= c1 or r0 >= r1:
        raise RuntimeError("FCOVER_NATIVE_NO_OVERLAP")
    return Window(c0, r0, c1 - c0, r1 - r0)


def _read_fcover_asset(asset: dict[str, Any], window: Window) -> tuple[np.ndarray, float | None]:
    session: AWSSession | None = None
    if os.getenv("EODATA_S3_ACCESS_KEY") and os.getenv("EODATA_S3_SECRET_KEY"):
        href = str(asset.get("href") or "")
        session = AWSSession(aws_access_key_id=os.environ["EODATA_S3_ACCESS_KEY"],
                             aws_secret_access_key=os.environ["EODATA_S3_SECRET_KEY"],
                             endpoint_url=os.getenv("EODATA_S3_ENDPOINT", "eodata.dataspace.copernicus.eu"))
        options = {"AWS_VIRTUAL_HOSTING": "FALSE", "AWS_HTTPS": "YES", "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
                   "GDAL_HTTP_CONNECTTIMEOUT": "20", "GDAL_HTTP_TIMEOUT": "90", "GDAL_HTTP_MAX_RETRY": "1",
                   "GDAL_HTTP_RETRY_DELAY": "2", "VSI_CACHE": "FALSE", "CPL_VSIL_CURL_USE_HEAD": "FALSE"}
    else:
        alternate = (asset.get("alternate") or {}).get("https") or {}
        href = str(alternate.get("href") or "")
        options = {"GDAL_HTTP_HEADERS": f"Authorization: Bearer {os.environ['CDSE_DOWNLOAD_TOKEN']}",
                   "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff",
                   "GDAL_HTTP_CONNECTTIMEOUT": "20", "GDAL_HTTP_TIMEOUT": "90", "GDAL_HTTP_MAX_RETRY": "1",
                   "GDAL_HTTP_RETRY_DELAY": "2", "VSI_CACHE": "FALSE", "CPL_VSIL_CURL_USE_HEAD": "FALSE"}
    with rasterio.Env(session=session, **options):
        with rasterio.open(href) as source:
            return source.read(1, window=window), source.nodata


def read_fcover_window_with_retry(asset: dict[str, Any], window: Window, *, attempts: int = 3,
                                  backoff_seconds: float = 2.0) -> tuple[np.ndarray, float | None]:
    """Read only a requested official COG window with bounded retries.

    This is deliberately a range-read helper, not a cache/downloader: source
    truth remains the identified CDSE object and only the caller's small AOI
    array enters memory.  GDAL connection/read timeouts are configured above;
    this outer loop makes the retry budget visible and finite.
    """
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return _read_fcover_asset(asset, window)
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(backoff_seconds * (2 ** attempt))
    raise RuntimeError(f"FCOVER_REMOTE_WINDOW_READ_FAILED_AFTER_{attempts}_ATTEMPTS:{last_error}")


def download_fcover(feature: dict[str, Any], year: int, root: Path, limit: int | None = None) -> list[dict[str, Any]]:
    aoi_id = feature["properties"]["aoi_id"]; version = feature["properties"]["geometry_version"]
    bounds = [float(value) for value in shape(feature["geometry"]).bounds]
    dates = [date(year, month, day).isoformat() for month, day in NOMINAL_MONTH_DAYS]
    if limit is not None:
        dates = dates[:limit]
    records: list[dict[str, Any]] = []
    with httpx.Client(timeout=300) as client:
        for nominal in dates:
            item = _fcover_item(client, nominal); assets = _fcover_assets(item)
            transform, width, height, crs = _fcover_grid(item, assets)
            window = _fcover_window(bounds, transform, width, height)
            destination = root / "fcover_native" / aoi_id / str(year) / f"fcover_{nominal}.tif"
            if not destination.is_file():
                arrays_nodata = [_read_fcover_asset(asset, window) for asset in assets]
                valid = fcover_value_valid_mask(arrays_nodata[0][0], nodata=arrays_nodata[0][1])
                # RT6 V2.0.1 source COGs are UInt8/255-NoData.  Preserve that
                # source representation; the validity layer is UInt8 0/1.
                stack = np.stack([*(array.astype("uint8") for array, _ in arrays_nodata),
                                  valid.astype("uint8")])
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_suffix(".part.tif")
                with rasterio.open(temporary, "w", driver="GTiff", width=int(window.width), height=int(window.height),
                                   count=7, dtype="uint8", crs=crs, transform=rasterio.windows.transform(window, transform),
                                   nodata=255, compress="deflate") as output:
                    output.write(stack)
                    for index, name in enumerate(("FCOVER", "RMSE", "NOBS", "LBEFORE", "LAFTER", "QFLAG", "valid_domain_mask"), 1):
                        output.set_band_description(index, name)
                temporary.replace(destination)
            properties = item.get("properties") or {}
            source_uris = ";".join(str(asset.get("href")) for asset in assets)
            records.append(_raster_record(destination, aoi_id=aoi_id, sensor="fcover", platform="Sentinel-3 OLCI",
                                          year=year, nominal_dates=nominal, acquisition=f"{nominal}T00:00:00+00:00",
                                          product_id=str(item.get("id")), collection=FCOVER_STAC_COLLECTION,
                                          version=str(properties.get("processing:version") or "V2.0.1"),
                                          processing_level="FCOVER 300 m V2 RT6 native COG window",
                                          source_catalog="Copernicus Data Space Ecosystem", source_uri=source_uris,
                                          scale=0.004, offset=0.0, qa_band="QFLAG;NOBS;derived_valid_domain_mask",
                                          geometry_version=version, asset_role="FCOVER_reference_native"))
    return records


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def load_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def merge_records(existing: list[dict[str, Any]], added: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    keyed = {(row["aoi_id"], row["sensor"], row["year"], row["product_id"], row["asset_role"]): row for row in existing}
    for row in added:
        keyed[(row["aoi_id"], row["sensor"], row["year"], row["product_id"], row["asset_role"])] = row
    return sorted(keyed.values(), key=lambda row: (row["aoi_id"], row["year"], row["sensor"], row["product_id"], row["asset_role"]))


def acquire_unit(feature: dict[str, Any], year: int, sensor: str, root: Path, limit: int | None = None) -> list[dict[str, Any]]:
    functions = {"sentinel2": download_sentinel2, "landsat": download_landsat,
                 "modis": download_modis, "fcover": download_fcover}
    return functions[sensor](feature, year, root, limit)
