"""GEE-only preparation backend for the FVC publication experiments.

Sentinel-2, Landsat and MOD09Q1 remain in the Earth Engine catalog. Native
FCOVER/QFLAG/NOBS windows are read from CDSE into memory and immediately
exported to Earth Engine assets; no persistent local raster is created.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import ee
import httpx
import numpy as np
import rasterio
from shapely.geometry import shape

from .download import (_fcover_assets, _fcover_grid, _fcover_item,
                       _fcover_window, _read_fcover_asset, load_credentials)
from .fcover import fcover_value_valid_mask


ASSET_ROOT = "projects/qinghai-internship-fvc-models/assets/fvc_report_data"
FCOVER_COLLECTION = f"{ASSET_ROOT}/fcover_native"
PAIR_COLLECTION = f"{ASSET_ROOT}/paired_observations"
TABLE_ROOT = f"{ASSET_ROOT}/tables"
S2 = "COPERNICUS/S2_SR_HARMONIZED"
S2_CLOUD = "COPERNICUS/S2_CLOUD_PROBABILITY"
L8 = "LANDSAT/LC08/C02/T1_L2"
L9 = "LANDSAT/LC09/C02/T1_L2"
MODIS = "MODIS/061/MOD09Q1"
NOMINAL_DATES = ((7, 20), (7, 31), (8, 10))
TERMINAL_STATES = {"COMPLETED", "FAILED", "CANCELLED"}
# Never overwrite the legacy schema.  This immutable revision is intentionally
# outside the legacy collection; active lineage is established by evidence,
# not by re-labelling an old image.
FCOVER_ASSET_REVISION = "r3_fcover_value_domain_v2"
FCOVER_ACTIVE_COLLECTION = f"{ASSET_ROOT}/fcover_native_{FCOVER_ASSET_REVISION}"
PAIR_ASSET_REVISION = "r3_fcover_value_domain_v2"
PAIR_ACTIVE_COLLECTION = f"{ASSET_ROOT}/paired_observations_{PAIR_ASSET_REVISION}"
FCOVER_SOURCE_BANDS = ("FCOVER", "RMSE", "NOBS", "LBEFORE", "LAFTER", "QFLAG")
FCOVER_SOURCE_ASSET_KEYS = ("fcover300_fcover", "fcover300_rmse", "fcover300_nobs",
                            "fcover300_lbefore", "fcover300_lafter", "fcover300_qflag")


def initialize(env_file: Path, retries: int = 6) -> None:
    load_credentials(env_file)
    project = os.getenv("EE_PROJECT_ID")
    if not project:
        raise RuntimeError("EE_PROJECT_MISSING")
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            ee.Initialize(project=project, opt_url="https://earthengine-highvolume.googleapis.com")
            return
        except Exception as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(min(30, 2**attempt))
    raise RuntimeError(f"GEE_INITIALIZATION_FAILED:{last_error}")


def asset_exists(asset_id: str) -> bool:
    try:
        ee.data.getAsset(asset_id)
        return True
    except ee.EEException:
        return False


def wait_task(task: ee.batch.Task, poll_seconds: int = 10) -> dict[str, Any]:
    while True:
        status = task.status()
        state = status.get("state")
        print(json.dumps({"task_id": task.id, "state": state,
                          "error": status.get("error_message")}, ensure_ascii=False), flush=True)
        if state in TERMINAL_STATES:
            if state != "COMPLETED":
                raise RuntimeError(f"GEE_TASK_{state}:{status.get('error_message')}")
            return status
        time.sleep(poll_seconds)


def _safe_id(value: str) -> str:
    return value.replace("-", "_").replace(":", "_")


def fcover_asset_id(aoi_id: str, nominal: str) -> str:
    return f"{FCOVER_ACTIVE_COLLECTION}/{_safe_id(aoi_id)}_{nominal.replace('-', '')}"


def pair_asset_id(aoi_id: str, year: int) -> str:
    return f"{PAIR_ACTIVE_COLLECTION}/{_safe_id(aoi_id)}_{year}"


def _array_checksum(arrays: Sequence[np.ndarray]) -> str:
    digest = hashlib.sha256()
    for array in arrays:
        digest.update(str(array.dtype).encode())
        digest.update(np.asarray(array.shape, dtype="int64").tobytes())
        digest.update(np.ascontiguousarray(array).tobytes())
    return digest.hexdigest()


def _fcover_points(arrays: Sequence[np.ndarray], transform: rasterio.Affine) -> ee.FeatureCollection:
    height, width = arrays[0].shape
    features = []
    for row in range(height):
        y = transform.f + (row + 0.5) * transform.e
        for column in range(width):
            x = transform.c + (column + 0.5) * transform.a
            features.append(ee.Feature(ee.Geometry.Point([x, y]), {
                **{name: int(arrays[index][row, column]) for index, name in enumerate(FCOVER_SOURCE_BANDS)},
                "valid_domain_mask": int(arrays[-1][row, column]),
            }))
    return ee.FeatureCollection(features)


def _ensure_image_collection(asset_id: str) -> None:
    """Create the immutable revision collection once; no legacy asset is touched."""
    try:
        ee.data.getAsset(asset_id)
    except ee.EEException:
        ee.data.createAsset({"type": "IMAGE_COLLECTION"}, asset_id)


def ingest_fcover(feature: dict[str, Any], nominal: str, overwrite: bool = False,
                   poll_seconds: int = 10) -> dict[str, Any]:
    """Read one CDSE native window into memory and persist it only in GEE."""
    aoi_id = str(feature["properties"]["aoi_id"])
    asset_id = fcover_asset_id(aoi_id, nominal)
    if asset_exists(asset_id) and not overwrite:
        info = ee.data.getAsset(asset_id)
        return {"kind": "fcover", "aoi_id": aoi_id, "nominal_date": nominal,
                "asset_id": asset_id, "status": "EXISTING", "size_bytes": info.get("sizeBytes")}
    if overwrite and asset_exists(asset_id):
        ee.data.deleteAsset(asset_id)
    _ensure_image_collection(FCOVER_ACTIVE_COLLECTION)
    bounds = [float(value) for value in shape(feature["geometry"]).bounds]
    with httpx.Client(timeout=300) as client:
        item = _fcover_item(client, nominal)
    assets = _fcover_assets(item)
    source_transform, width, height, crs = _fcover_grid(item, assets)
    window = _fcover_window(bounds, source_transform, width, height)
    arrays_nodata = [_read_fcover_asset(asset, window) for asset in assets]
    valid = fcover_value_valid_mask(arrays_nodata[0][0], nodata=arrays_nodata[0][1])
    # Verified RT6 V2.0.1 COG samples are UInt8 with NoData=255.  Do not widen
    # the source variables merely because an older intermediate used UInt16.
    arrays = [value[0].astype("uint8") for value in arrays_nodata] + [valid.astype("uint8")]
    transform = rasterio.windows.transform(window, source_transform)
    fc = _fcover_points(arrays, transform)
    valid_image = fc.reduceToImage(["valid_domain_mask"], ee.Reducer.first()).rename("valid_domain_mask").toUint8()
    source_images = [fc.reduceToImage([name], ee.Reducer.first()).rename(name).toUint8().updateMask(valid_image)
                     for name in FCOVER_SOURCE_BANDS]
    # The 0/1 validity field stays unmasked so an invalid support cell cannot
    # become indistinguishable from a missing exported pixel.  It is derived,
    # not a source QA band or quality score.
    image = ee.Image.cat([*source_images, valid_image])
    properties = item.get("properties") or {}
    checksum = _array_checksum(arrays)
    source_no_data = {name: nodata for name, (_, nodata) in zip(FCOVER_SOURCE_BANDS, arrays_nodata)}
    source_dtypes = {name: array.dtype.name for name, (array, _) in zip(FCOVER_SOURCE_BANDS, arrays_nodata)}
    source_hrefs = {name: str(asset.get("href") or "") for name, asset in zip(FCOVER_SOURCE_BANDS, assets)}
    source_asset_keys = {name: key for name, key in zip(FCOVER_SOURCE_BANDS, FCOVER_SOURCE_ASSET_KEYS)}
    ingestion_payload = {"asset_revision": FCOVER_ASSET_REVISION, "source_schema": list(FCOVER_SOURCE_BANDS),
                         "valid_domain": "fcover_source_raster_valid_and_not_nodata",
                         "pyramiding": "sample", "scale": {"FCOVER": 0.004}}
    ingestion_config_hash = hashlib.sha256(json.dumps(ingestion_payload, sort_keys=True).encode()).hexdigest()
    image = image.set({
        "aoi_id": aoi_id,
        "geometry_version": feature["properties"].get("geometry_version"),
        "nominal_date": nominal,
        "source_product_id": str(item.get("id")),
        "source_collection": "clms_fcover_global_300m_10daily_v2_cog",
        "source_version": str(properties.get("processing:version") or "V2.0.1"),
        "source_stac_item_id": str(item.get("id")),
        "source_asset_keys_json": json.dumps(source_asset_keys, sort_keys=True),
        "source_file_or_object": json.dumps(source_hrefs, sort_keys=True),
        "source_identity_mode": "official_STAC_item_asset_object_identity;remote_COG_window_only",
        "source_nodata_json": json.dumps(source_no_data, sort_keys=True),
        "source_dtype_json": json.dumps(source_dtypes, sort_keys=True),
        "official_source_schema": json.dumps(list(FCOVER_SOURCE_BANDS)),
        "asset_revision": FCOVER_ASSET_REVISION,
        "ingestion_config_hash": ingestion_config_hash,
        "source_window_sha256": checksum,
        "source_width": int(window.width),
        "source_height": int(window.height),
        "source_crs": crs,
        "fcover_scale": 0.004,
        "ingestion_method": "CDSE_official_remote_COG_range_window_to_GEE_native_grid_with_derived_valid_domain",
        "valid_domain_definition_version": "fcover-value-raster-valid-not-nodata-v2",
        "valid_domain_mask_semantics": "derived_from_FCOVER_source_nodata_and_raster_validity_only;QFLAG_NOBS_QA_separate;not_source_band;not_quality_score",
        "system:time_start": ee.Date(nominal).millis(),
    })
    left = transform.c
    top = transform.f
    right = left + int(window.width) * transform.a
    bottom = top + int(window.height) * transform.e
    epsilon = min(abs(transform.a), abs(transform.e)) * 1e-6
    region = ee.Geometry.Rectangle([left + epsilon, bottom + epsilon,
                                   right - epsilon, top - epsilon], None, False)
    task = ee.batch.Export.image.toAsset(
        image=image,
        description=f"fvc_report_fcover_{_safe_id(aoi_id)}_{nominal.replace('-', '')}",
        assetId=asset_id,
        region=region,
        crs="EPSG:4326",
        crsTransform=list(transform)[:6],
        maxPixels=1_000_000,
        pyramidingPolicy={".default": "sample"},
    )
    task.start()
    wait_task(task, poll_seconds)
    info = ee.data.getAsset(asset_id)
    grid = info["bands"][0]["grid"]
    dimensions = grid["dimensions"]
    if int(dimensions["width"]) != int(window.width) or int(dimensions["height"]) != int(window.height):
        raise RuntimeError(f"FCOVER_GEE_GRID_SIZE_MISMATCH:{asset_id}")
    return {"kind": "fcover", "aoi_id": aoi_id, "nominal_date": nominal,
            "asset_id": asset_id, "source_product_id": item.get("id"),
            "source_window_sha256": checksum, "width": int(window.width),
            "height": int(window.height), "valid_pixels": int(valid.sum()),
            "asset_revision": FCOVER_ASSET_REVISION, "ingestion_config_hash": ingestion_config_hash,
            "task_id": task.id, "status": "COMPLETED", "size_bytes": info.get("sizeBytes")}


def ingest_fcover_from_cache(feature: dict[str, Any], nominal: str, item: dict[str, Any],
                              cached_sources: Mapping[str, Path], source_checksums: Mapping[str, str],
                              overwrite: bool = False, poll_seconds: int = 10) -> dict[str, Any]:
    """Ingest a verified local source cache; it never opens a live source COG.

    ``cached_sources`` is keyed by the official STAC asset keys.  This keeps
    the canary and all later rebuilds reproducible from immutable bytes rather
    than the availability of a remote range endpoint.
    """
    aoi_id = str(feature["properties"]["aoi_id"]); asset_id = fcover_asset_id(aoi_id, nominal)
    if asset_exists(asset_id) and not overwrite:
        info = ee.data.getAsset(asset_id)
        return {"kind": "fcover", "aoi_id": aoi_id, "nominal_date": nominal, "asset_id": asset_id,
                "status": "EXISTING", "size_bytes": info.get("sizeBytes")}
    _ensure_image_collection(FCOVER_ACTIVE_COLLECTION)
    assets = [dict((item.get("assets") or {})[key]) for key in FCOVER_SOURCE_ASSET_KEYS]
    paths = [Path(cached_sources[key]) for key in FCOVER_SOURCE_ASSET_KEYS]
    if any(not path.is_file() for path in paths):
        raise RuntimeError("CACHED_FCOVER_SOURCE_MISSING")
    bounds = [float(value) for value in shape(feature["geometry"]).bounds]
    with rasterio.open(paths[0]) as first:
        source_transform, width, height, crs = first.transform, first.width, first.height, first.crs.to_string()
    if crs != "EPSG:4326":
        raise RuntimeError(f"FCOVER_CACHE_CRS_INVALID:{crs}")
    window = _fcover_window(bounds, source_transform, width, height)
    arrays_nodata = []
    for source in paths:
        with rasterio.open(source) as raster:
            if (raster.crs.to_string() if raster.crs else None) != crs or raster.transform != source_transform or raster.width != width or raster.height != height:
                raise RuntimeError(f"FCOVER_CACHE_GRID_MISMATCH:{source}")
            arrays_nodata.append((raster.read(1, window=window), raster.nodata))
    valid = fcover_value_valid_mask(arrays_nodata[0][0], nodata=arrays_nodata[0][1])
    arrays = [value[0].astype("uint8") for value in arrays_nodata] + [valid.astype("uint8")]
    transform = rasterio.windows.transform(window, source_transform); fc = _fcover_points(arrays, transform)
    valid_image = fc.reduceToImage(["valid_domain_mask"], ee.Reducer.first()).rename("valid_domain_mask").toUint8()
    source_images = [fc.reduceToImage([name], ee.Reducer.first()).rename(name).toUint8().updateMask(valid_image)
                     for name in FCOVER_SOURCE_BANDS]
    properties = item.get("properties") or {}; checksum = _array_checksum(arrays)
    source_hrefs = {name: str(asset.get("href") or "") for name, asset in zip(FCOVER_SOURCE_BANDS, assets)}
    source_nodata = {name: nodata for name, (_, nodata) in zip(FCOVER_SOURCE_BANDS, arrays_nodata)}
    source_dtypes = {name: values.dtype.name for name, (values, _) in zip(FCOVER_SOURCE_BANDS, arrays_nodata)}
    payload = {"asset_revision": FCOVER_ASSET_REVISION, "source_schema": list(FCOVER_SOURCE_BANDS),
               "valid_domain": "fcover_source_raster_valid_and_not_nodata", "pyramiding": "sample", "scale": {"FCOVER": 0.004}}
    ingestion_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    image = ee.Image.cat([*source_images, valid_image]).set({
        "aoi_id": aoi_id, "geometry_version": feature["properties"].get("geometry_version"), "nominal_date": nominal,
        "source_product_id": str(item.get("id")), "source_collection": "clms_fcover_global_300m_10daily_v2_cog",
        "source_version": str(properties.get("processing:version") or "V2.0.1"), "source_file_or_object": json.dumps(source_hrefs, sort_keys=True),
        "source_checksum_json": json.dumps(dict(source_checksums), sort_keys=True), "source_window_sha256": checksum,
        "source_nodata_json": json.dumps(source_nodata, sort_keys=True), "source_dtype_json": json.dumps(source_dtypes, sort_keys=True),
        "official_source_schema": json.dumps(list(FCOVER_SOURCE_BANDS)), "asset_revision": FCOVER_ASSET_REVISION,
        "ingestion_config_hash": ingestion_hash, "source_width": int(window.width), "source_height": int(window.height), "source_crs": crs,
        "fcover_scale": 0.004, "ingestion_method": "immutable_local_CDSE_cache_to_GEE_native_grid",
        "valid_domain_definition_version": "fcover-value-raster-valid-not-nodata-v2",
        "valid_domain_mask_semantics": "derived_from_FCOVER_source_nodata_and_raster_validity_only;QFLAG_NOBS_QA_separate;not_source_band;not_quality_score",
        "scientific_design_hash": "b21c8cc7f3d4d35e1db4dfa1c8245ff10ba657c0a0a001992b552808766cc49b", "system:time_start": ee.Date(nominal).millis()})
    left, top = transform.c, transform.f; right = left + int(window.width) * transform.a; bottom = top + int(window.height) * transform.e
    epsilon = min(abs(transform.a), abs(transform.e)) * 1e-6
    task = ee.batch.Export.image.toAsset(image=image, description=f"fvc_report_fcover_{_safe_id(aoi_id)}_{nominal.replace('-', '')}_{FCOVER_ASSET_REVISION}",
                                         assetId=asset_id, region=ee.Geometry.Rectangle([left + epsilon, bottom + epsilon, right - epsilon, top - epsilon], None, False),
                                         crs="EPSG:4326", crsTransform=list(transform)[:6], maxPixels=1_000_000, pyramidingPolicy={".default": "sample"})
    task.start(); wait_task(task, poll_seconds); info = ee.data.getAsset(asset_id); grid = info["bands"][0]["grid"]
    if int(grid["dimensions"]["width"]) != int(window.width) or int(grid["dimensions"]["height"]) != int(window.height):
        raise RuntimeError(f"FCOVER_GEE_GRID_SIZE_MISMATCH:{asset_id}")
    return {"kind": "fcover", "aoi_id": aoi_id, "nominal_date": nominal, "asset_id": asset_id, "asset_revision": FCOVER_ASSET_REVISION,
            "source_product_id": item.get("id"), "source_checksum_json": json.dumps(dict(source_checksums), sort_keys=True),
            "source_window_sha256": checksum, "width": int(window.width), "height": int(window.height), "valid_pixels": int(valid.sum()),
            "ingestion_config_hash": ingestion_hash, "task_id": task.id, "status": "COMPLETED", "size_bytes": info.get("sizeBytes")}


def _bits(image: ee.Image, offset: int, width: int = 1) -> ee.Image:
    return image.rightShift(offset).bitwiseAnd((1 << width) - 1)


def _average_to_fcover(ndvi: ee.Image, fcover: ee.Image) -> ee.Image:
    return (ndvi.reduceResolution(reducer=ee.Reducer.mean(), maxPixels=4096, bestEffort=False)
            .reproject(fcover.projection()).rename("NDVI"))


def _sentinel_collection(region: ee.Geometry, start: str, end_exclusive: str,
                         fcover: ee.Image,
                         exact_scene_ids: Sequence[str] | None = None) -> ee.ImageCollection:
    if exact_scene_ids is not None:
        prepared = []
        for asset_id in exact_scene_ids:
            image = ee.Image(asset_id)
            index = asset_id.rsplit("/", 1)[-1]
            cloud_image = ee.Image(f"{S2_CLOUD}/{index}")
            red_dn = image.select("B4"); nir_dn = image.select("B8"); scl = image.select("SCL")
            probability = cloud_image.select("probability")
            valid = (red_dn.gte(1).And(red_dn.lte(10000))
                     .And(nir_dn.gte(1)).And(nir_dn.lte(10000))
                     .And(scl.eq(4).Or(scl.eq(5)).Or(scl.eq(7)))
                     .And(probability.lt(30)))
            red = red_dn.multiply(0.0001); nir = nir_dn.multiply(0.0001)
            ndvi = nir.subtract(red).divide(nir.add(red)).rename("NDVI").updateMask(valid)
            prepared.append(_average_to_fcover(ndvi, fcover).copyProperties(
                image, ["system:time_start", "system:index"]))
        return ee.ImageCollection.fromImages(prepared)
    sr = (ee.ImageCollection(S2).filterBounds(region).filterDate(start, end_exclusive)
          .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", 80)))
    cloud = ee.ImageCollection(S2_CLOUD).filterBounds(region).filterDate(start, end_exclusive)
    joined = ee.ImageCollection(ee.Join.saveFirst("cloud_image").apply(
        sr, cloud, ee.Filter.equals(leftField="system:index", rightField="system:index")))
    joined = joined.filter(ee.Filter.notNull(["cloud_image"]))

    def prepare(value: ee.Image) -> ee.Image:
        image = ee.Image(value)
        red_dn = image.select("B4")
        nir_dn = image.select("B8")
        scl = image.select("SCL")
        probability = ee.Image(image.get("cloud_image")).select("probability")
        valid = (red_dn.gte(1).And(red_dn.lte(10000))
                 .And(nir_dn.gte(1)).And(nir_dn.lte(10000))
                 .And(scl.eq(4).Or(scl.eq(5)).Or(scl.eq(7)))
                 .And(probability.lt(30)))
        red = red_dn.multiply(0.0001)
        nir = nir_dn.multiply(0.0001)
        ndvi = nir.subtract(red).divide(nir.add(red)).rename("NDVI").updateMask(valid)
        return _average_to_fcover(ndvi, fcover).copyProperties(image, ["system:time_start", "system:index"])

    return joined.map(prepare)


def _landsat_collection(region: ee.Geometry, start: str, end_exclusive: str,
                        fcover: ee.Image,
                        exact_scene_ids: Sequence[str] | None = None) -> ee.ImageCollection:
    if exact_scene_ids is None:
        merged = (ee.ImageCollection(L8).filterBounds(region).filterDate(start, end_exclusive)
                  .merge(ee.ImageCollection(L9).filterBounds(region).filterDate(start, end_exclusive)))
        merged = merged.filter(ee.Filter.lte("CLOUD_COVER", 80))
    else:
        merged = ee.ImageCollection.fromImages([ee.Image(asset_id) for asset_id in exact_scene_ids])

    def prepare(value: ee.Image) -> ee.Image:
        image = ee.Image(value)
        red_dn = image.select("SR_B4")
        nir_dn = image.select("SR_B5")
        qa = image.select("QA_PIXEL")
        valid_qa = ee.Image(1)
        for bit in (0, 1, 2, 3, 4, 5, 7):
            valid_qa = valid_qa.And(_bits(qa, bit).eq(0))
        valid = (valid_qa.And(image.select("QA_RADSAT").eq(0))
                 .And(red_dn.gte(7273)).And(red_dn.lte(43636))
                 .And(nir_dn.gte(7273)).And(nir_dn.lte(43636)))
        red = red_dn.multiply(0.0000275).add(-0.2)
        nir = nir_dn.multiply(0.0000275).add(-0.2)
        ndvi = nir.subtract(red).divide(nir.add(red)).rename("NDVI").updateMask(valid)
        return _average_to_fcover(ndvi, fcover).copyProperties(image, ["system:time_start", "system:index", "SPACECRAFT_ID"])

    return merged.map(prepare)


def _modis_collection(region: ee.Geometry, window_start: date, window_end: date,
                      fcover: ee.Image,
                      exact_scene_ids: Sequence[str] | None = None) -> ee.ImageCollection:
    start = (window_start - timedelta(days=7)).isoformat()
    end_exclusive = (window_end + timedelta(days=1)).isoformat()
    collection = (ee.ImageCollection(MODIS).filterBounds(region).filterDate(start, end_exclusive)
                  if exact_scene_ids is None else
                  ee.ImageCollection.fromImages([ee.Image(asset_id) for asset_id in exact_scene_ids]))

    def prepare(value: ee.Image) -> ee.Image:
        image = ee.Image(value)
        red_dn = image.select("sur_refl_b01")
        nir_dn = image.select("sur_refl_b02")
        state = image.select("State")
        qc = image.select("QA")
        aerosol = _bits(state, 6, 2)
        modland = _bits(qc, 0, 2)
        valid = (_bits(state, 0, 2).eq(0)
                 .And(_bits(state, 2).eq(0))
                 .And(_bits(state, 3, 3).eq(1))
                 .And(aerosol.lte(2))
                 .And(_bits(state, 8, 2).eq(0))
                 .And(_bits(state, 10).eq(0))
                 .And(_bits(state, 11).eq(0))
                 .And(_bits(state, 12).eq(0))
                 .And(_bits(state, 13).eq(0))
                 .And(_bits(state, 15).eq(0))
                 .And(modland.lte(1))
                 .And(_bits(qc, 4, 4).eq(0))
                 .And(_bits(qc, 8, 4).eq(0))
                 .And(_bits(qc, 12).eq(1))
                 .And(red_dn.gte(-100)).And(red_dn.lte(16000))
                 .And(nir_dn.gte(-100)).And(nir_dn.lte(16000)))
        red = red_dn.multiply(0.0001)
        nir = nir_dn.multiply(0.0001)
        ndvi = nir.subtract(red).divide(nir.add(red)).rename("NDVI").updateMask(valid)
        return _average_to_fcover(ndvi, fcover).copyProperties(image, ["system:time_start", "system:index"])

    return collection.map(prepare)


def _quality_bands(raw: ee.Image, suffix: str) -> list[ee.Image]:
    d = raw.select("FCOVER")
    q = raw.select("QFLAG")
    n = raw.select("NOBS")
    valid_domain = raw.select("valid_domain_mask")
    valid_reference = (valid_domain.gt(0).And(q.lt(255)).And(n.gt(0)).And(d.gte(0)).And(d.lte(250)))
    return [
        d.multiply(0.004).toFloat().updateMask(valid_reference).rename(f"fcover_{suffix}"),
        raw.select("RMSE").rename(f"rmse_{suffix}"),
        q.rename(f"qflag_{suffix}"),
        n.rename(f"nobs_{suffix}"),
        valid_domain.rename(f"valid_domain_mask_{suffix}"),
        valid_reference.unmask(0).toUint8().rename(f"valid_reference_{suffix}"),
    ]


def _composite_bands(collection: ee.ImageCollection, sensor: str, suffix: str) -> list[ee.Image]:
    # Earth Engine drops the band schema when an ImageCollection is empty.
    # A fully masked placeholder preserves the NDVI schema while contributing
    # zero observations, so empty windows export as count=0 and masked NDVI.
    placeholder = (ee.Image.constant(0).rename("NDVI")
                   .updateMask(ee.Image.constant(0)))
    safe = collection.merge(ee.ImageCollection([placeholder]))
    count = safe.select("NDVI").count().rename(f"{sensor}_count_{suffix}")
    median = (safe.select("NDVI").median().updateMask(count.gte(2))
              .rename(f"{sensor}_ndvi_{suffix}").toFloat())
    return [median, count.toUint16()]


def build_pair_cube(feature: dict[str, Any], year: int, contract: dict[str, Any] | None = None,
                    overwrite: bool = False, poll_seconds: int = 10) -> dict[str, Any]:
    from execution.contract import actual_design_hash, load_contract, sha256
    from execution.identity import active_processing_hash, active_source_rows

    contract = contract or load_contract()
    aoi_id = str(feature["properties"]["aoi_id"])
    asset_id = pair_asset_id(aoi_id, year)
    _ensure_image_collection(PAIR_ACTIVE_COLLECTION)
    if asset_exists(asset_id) and not overwrite:
        info = ee.data.getAsset(asset_id)
        return {"kind": "pair_cube", "aoi_id": aoi_id, "year": year,
                "asset_id": asset_id, "status": "EXISTING", "size_bytes": info.get("sizeBytes")}
    if overwrite and asset_exists(asset_id):
        ee.data.deleteAsset(asset_id)
    region = ee.Geometry(feature["geometry"])
    bands: list[ee.Image] = []
    fcover_assets: list[str] = []
    source_hashes: dict[str, str] = {}
    all_scene_ids: list[str] = []
    first_info: dict[str, Any] | None = None
    for month, day in NOMINAL_DATES:
        nominal_date = date(year, month, day)
        nominal = nominal_date.isoformat()
        suffix = f"{month:02d}{day:02d}"
        fcover_id = fcover_asset_id(aoi_id, nominal)
        if not asset_exists(fcover_id):
            raise RuntimeError(f"FCOVER_ASSET_MISSING:{fcover_id}")
        if first_info is None:
            first_info = ee.data.getAsset(fcover_id)
        fcover_assets.append(fcover_id)
        raw = ee.Image(fcover_id)
        bands.extend(_quality_bands(raw, suffix))
        start_date = nominal_date - timedelta(days=15)
        end_date = nominal_date + timedelta(days=15)
        end_exclusive = (end_date + timedelta(days=1)).isoformat()
        exact: dict[str, list[dict[str, str]]] = {}
        for sensor in ("sentinel2", "landsat", "modis"):
            selected = [row for row in active_source_rows(contract, sensor)
                        if row["AOI_ID"] == aoi_id and int(row["year"]) == int(year)
                        and row["nominal_date"] == nominal
                        and str(row["included"]).lower() == "true"]
            if not selected:
                raise RuntimeError(f"FROZEN_SOURCE_SCENES_EMPTY:{aoi_id}:{year}:{nominal}:{sensor}")
            exact[sensor] = selected
            hashes = {row["source_manifest_hash"] for row in selected}
            if len(hashes) != 1:
                raise RuntimeError(f"SOURCE_MANIFEST_HASH_INCONSISTENT:{aoi_id}:{nominal}:{sensor}")
            source_hashes[f"{sensor}_{suffix}"] = next(iter(hashes))
            all_scene_ids.extend(row["system:id"] for row in selected)
        collections = {
            "s2": _sentinel_collection(region, start_date.isoformat(), end_exclusive, raw,
                                       [row["system:id"] for row in exact["sentinel2"]]),
            "landsat": _landsat_collection(region, start_date.isoformat(), end_exclusive, raw,
                                            [row["system:id"] for row in exact["landsat"]]),
            "modis": _modis_collection(region, start_date, end_date, raw,
                                        [row["system:id"] for row in exact["modis"]]),
        }
        for sensor, collection in collections.items():
            bands.extend(_composite_bands(collection, sensor, suffix))
    cube = ee.Image.cat(bands).set({
        "aoi_id": aoi_id,
        "year": year,
        "geometry_version": feature["properties"].get("geometry_version"),
        "fcover_assets": ";".join(fcover_assets),
        "processing_order": "native_scaling>native_QA>native_NDVI>average_to_FCOVER_grid>temporal_nanmedian",
        "temporal_window_days": 15,
        "minimum_finite_contributions": 2,
        "asset_revision": PAIR_ASSET_REVISION,
        "fcover_asset_revision": FCOVER_ASSET_REVISION,
        "scientific_design_hash": actual_design_hash(contract),
        "processing_hash": active_processing_hash(contract),
        "source_manifest_hashes_json": json.dumps(source_hashes, sort_keys=True),
        "source_scene_ids_sha256": sha256(sorted(all_scene_ids)),
        "source_selection_mode": "exact_active_source_scene_manifest_r2",
        "paired_cube_band_count": len(bands),
        "scientific_results_executed": 0,
        "system:time_start": ee.Date(f"{year}-07-20").millis(),
    })
    assert first_info is not None
    grid = first_info["bands"][0]["grid"]
    affine = grid["affineTransform"]
    transform = [affine["scaleX"], affine.get("shearX", 0), affine["translateX"],
                 affine.get("shearY", 0), affine["scaleY"], affine["translateY"]]
    dimensions = grid["dimensions"]
    width = int(dimensions["width"]); height = int(dimensions["height"])
    left = transform[2]; top = transform[5]
    right = left + width * transform[0]; bottom = top + height * transform[4]
    epsilon = min(abs(transform[0]), abs(transform[4])) * 1e-6
    export_region = ee.Geometry.Rectangle([left + epsilon, bottom + epsilon,
                                           right - epsilon, top - epsilon], None, False)
    task = ee.batch.Export.image.toAsset(
        image=cube,
        description=f"fvc_report_pair_cube_{_safe_id(aoi_id)}_{year}",
        assetId=asset_id,
        region=export_region,
        crs="EPSG:4326",
        crsTransform=transform,
        maxPixels=2_000_000,
        pyramidingPolicy={".default": "sample"},
    )
    task.start()
    wait_task(task, poll_seconds)
    info = ee.data.getAsset(asset_id)
    if len(info.get("bands", [])) != int(contract["gee_data_center"]["paired_cube_band_schema"]):
        raise RuntimeError(f"PAIR_BAND_COUNT_MISMATCH:{asset_id}:{len(info.get('bands', []))}")
    return {"kind": "pair_cube", "aoi_id": aoi_id, "year": year,
            "asset_id": asset_id, "band_count": len(info.get("bands", [])),
            "task_id": task.id, "status": "COMPLETED", "size_bytes": info.get("sizeBytes")}


def export_table(collection: ee.FeatureCollection, asset_id: str, description: str,
                 overwrite: bool = False, poll_seconds: int = 10) -> dict[str, Any]:
    if asset_exists(asset_id) and not overwrite:
        return {"kind": "table", "asset_id": asset_id, "status": "EXISTING"}
    if overwrite and asset_exists(asset_id):
        ee.data.deleteAsset(asset_id)
    task = ee.batch.Export.table.toAsset(collection=collection, description=description, assetId=asset_id)
    task.start(); wait_task(task, poll_seconds)
    return {"kind": "table", "asset_id": asset_id, "task_id": task.id, "status": "COMPLETED"}


def export_aoi_tables(registry: dict[str, Any], environmental_rows: Sequence[dict[str, Any]],
                      overwrite: bool = False, poll_seconds: int = 10) -> list[dict[str, Any]]:
    features = [ee.Feature(ee.Geometry(feature["geometry"]), feature["properties"])
                for feature in registry["features"]]
    aoi_table = export_table(ee.FeatureCollection(features), f"{TABLE_ROOT}/aoi_registry",
                             "fvc_report_aoi_registry", overwrite, poll_seconds)
    by_id = {feature["properties"]["aoi_id"]: feature for feature in registry["features"]}
    environment_features = []
    for row in environmental_rows:
        feature = by_id[str(row["aoi_id"])]
        clean = {key: (None if value != value else value) for key, value in row.items()}
        environment_features.append(ee.Feature(ee.Geometry(feature["geometry"]), clean))
    environment_table = export_table(ee.FeatureCollection(environment_features),
                                     f"{TABLE_ROOT}/environmental_features",
                                     "fvc_report_environmental_features", overwrite, poll_seconds)
    return [aoi_table, environment_table]


def export_manifest_table(records: Sequence[dict[str, Any]], overwrite: bool = True,
                          poll_seconds: int = 10) -> dict[str, Any]:
    # Asset-table export rejects null geometries. The fixed point is only an
    # inert carrier for manifest properties and has no analytical meaning.
    placeholder_geometry = ee.Geometry.Point([0, 0])
    features = [ee.Feature(placeholder_geometry, {key: ("" if value is None else value)
                                                   for key, value in record.items()})
                for record in records]
    return export_table(ee.FeatureCollection(features), f"{TABLE_ROOT}/preparation_manifest",
                        "fvc_report_preparation_manifest", overwrite, poll_seconds)
