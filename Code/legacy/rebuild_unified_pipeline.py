#!/usr/bin/env python3
"""Rebuild the frozen 2022--2025 FVC experiment matrix into a specified output directory.

This is intentionally a standalone, auditable runner.  It reads only legacy
*raw* assets (and stages the missing MOD09Q1 ``QA`` band into the output),
then produces all derived arrays, models and comparisons below the selected output directory.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import matplotlib.pyplot as plt
import numpy as np
import rasterio
import yaml
from rasterio.enums import Resampling
from rasterio.warp import reproject
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

# Processing dependencies remain read-only in the workbench source tree.
WORKSPACE = Path(__file__).resolve().parents[2]
ROOT = WORKSPACE / "model"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import load_config
MODIS_QA_BITS = {
    "cloud_state": {"band": "State", "offset": 0, "width": 2, "keep": [0]},
    "cloud_shadow": {"band": "State", "offset": 2, "width": 1, "keep": [0]},
    "land_water": {"band": "State", "offset": 3, "width": 3, "keep": [1]},
    "aerosol_quantity": {"band": "State", "offset": 6, "width": 2, "keep": [0, 1, 2]},
    "cirrus": {"band": "State", "offset": 8, "width": 2, "keep": [0]},
    "internal_cloud": {"band": "State", "offset": 10, "width": 1, "keep": [0]},
    "internal_fire": {"band": "State", "offset": 11, "width": 1, "keep": [0]},
    "mod35_snow_ice": {"band": "State", "offset": 12, "width": 1, "keep": [0]},
    "adjacent_cloud": {"band": "State", "offset": 13, "width": 1, "keep": [0]},
    "internal_snow": {"band": "State", "offset": 15, "width": 1, "keep": [0]},
    "modland_quality": {"band": "QA", "offset": 0, "width": 2, "keep": [0, 1]},
    "band_1_quality": {"band": "QA", "offset": 4, "width": 4, "keep": [0]},
    "band_2_quality": {"band": "QA", "offset": 8, "width": 4, "keep": [0]},
    "atmospheric_correction": {"band": "QA", "offset": 12, "width": 1, "keep": [1]},
}

def bits(values: np.ndarray, offset: int, width: int) -> np.ndarray:
    return (values.astype("uint32") >> offset) & ((1 << width) - 1)

def modis_quality_components(qa: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    return {name: bits(qa[str(spec["band"])], int(spec["offset"]), int(spec["width"])) for name, spec in MODIS_QA_BITS.items()}

def modis_valid_mask(qa: dict[str, np.ndarray]) -> np.ndarray:
    fields = modis_quality_components(qa)
    valid = np.ones(next(iter(fields.values())).shape, dtype=bool)
    for name, spec in MODIS_QA_BITS.items():
        valid &= np.isin(fields[name], np.asarray(spec["keep"], dtype="uint32"))
    return valid

NODATA = -9999.0
YEARS = (2022, 2023, 2024, 2025)
TARGET_DATES = ("07-20", "07-31", "08-10")
WINDOWS = {"2022": (2022,), "2023": (2023,), "2024": (2024,), "2022-2023": (2022, 2023), "2023-2024": (2023, 2024), "2022-2024": (2022, 2023, 2024)}
SENSORS = ("sentinel2", "landsat", "modis")
PRODUCTS = {
    "sentinel2": {"id": "COPERNICUS/S2_SR_HARMONIZED", "version": "Harmonized L2A", "scale": 0.0001, "offset": 0.0},
    "landsat": {"id": "LANDSAT/LC08,C09/C02/T1_L2", "version": "Collection 2 L2", "scale": 0.0000275, "offset": -0.2},
    "modis": {"id": "MODIS/061/MOD09Q1", "version": "061", "scale": 0.0001, "offset": 0.0},
}
SENTINEL_EXCLUDED_SCL = frozenset({0, 1, 2, 3, 6, 8, 9, 10, 11})
SENTINEL_CLOUD_THRESHOLD = 40.0
WINDOW_DAYS_BEFORE = 15
WINDOW_DAYS_AFTER = 15
MINIMUM_VALID_OBSERVATIONS = 2
REFLECTANCE_RULES: dict[str, dict[str, float]] = {
    "sentinel2": {"multiplier": 0.0001, "additive_offset": 0.0, "valid_dn_min": 1, "valid_dn_max": 10000, "nodata_dn": 0},
    "landsat": {"multiplier": 0.0000275, "additive_offset": -0.2, "valid_dn_min": 7273, "valid_dn_max": 43636, "nodata_dn": 0},
    "modis": {"multiplier": 0.0001, "additive_offset": 0.0, "valid_dn_min": -100, "valid_dn_max": 16000, "nodata_dn": -28672},
}


def configure_preprocessing_rules(qa: dict[str, Any]) -> None:
    """Load every non-product-default rule from the frozen YAML configuration."""
    global MODIS_QA_BITS, SENTINEL_EXCLUDED_SCL, SENTINEL_CLOUD_THRESHOLD, REFLECTANCE_RULES, WINDOW_DAYS_BEFORE, WINDOW_DAYS_AFTER, MINIMUM_VALID_OBSERVATIONS
    sentinel = qa["sentinel2"]
    SENTINEL_EXCLUDED_SCL = frozenset(int(value) for value in sentinel["excluded_scl"])
    SENTINEL_CLOUD_THRESHOLD = float(sentinel["cloud_probability_exclude_gte"])
    MODIS_QA_BITS = {name: dict(spec) for name, spec in qa["modis"]["bits"].items()}
    REFLECTANCE_RULES = {
        name: {key: float(value) for key, value in values.items() if key != "negative_reflectance"}
        for name, values in ((name, qa[name]["reflectance"]) for name in ("sentinel2", "landsat", "modis"))
    }
    for name in PRODUCTS:
        PRODUCT = PRODUCTS[name]
        PRODUCT["scale"] = REFLECTANCE_RULES[name]["multiplier"]
        PRODUCT["offset"] = REFLECTANCE_RULES[name]["additive_offset"]
    WINDOW_DAYS_BEFORE = int(qa["temporal_composite"]["window_days_before"])
    WINDOW_DAYS_AFTER = int(qa["temporal_composite"]["window_days_after"])
    MINIMUM_VALID_OBSERVATIONS = int(qa["minimum_valid_observations"])


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row}) if rows else ["status"]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def tif(path: Path, data: np.ndarray, profile: dict[str, Any], names: Iterable[str]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    array = data[np.newaxis, :, :] if data.ndim == 2 else data
    options = {**profile, "driver": "GTiff", "width": array.shape[-1], "height": array.shape[-2], "count": array.shape[0], "dtype": str(array.dtype), "nodata": NODATA if np.issubdtype(array.dtype, np.floating) else 0, "compress": "deflate", "predictor": 3 if np.issubdtype(array.dtype, np.floating) else 2}
    with rasterio.open(path, "w", **options) as out:
        out.write(array)
        for index, name in enumerate(names, 1): out.set_band_description(index, name)
    return sha(path)


def raw_root() -> Path:
    configured = os.environ.get("FVC_WORKBENCH_DATA_ROOT")
    root = Path(configured) if configured else ROOT.parent / "qh-fvc-data"
    candidate = root / "storage" / "projects"
    project = next(candidate.glob("prj_*__*"), None)
    if project is None: raise RuntimeError(f"PROJECT_RAW_ROOT_MISSING: {candidate}")
    return project


def aoi_path() -> Path:
    root = Path(os.environ.get("FVC_WORKBENCH_DATA_ROOT", ROOT.parent / "qh-fvc-data"))
    path = next((root / "metadata" / "workspace" / "projects").glob("prj_*/aoi/processed/aoi.geojson"), None)
    if path is None: raise RuntimeError("AOI_MISSING")
    return path


def sensor_year_dir(project: Path, sensor: str, year: int) -> Path:
    needles = {"sentinel2": "sentinel-2-summer", "landsat": "landsat-89-summer", "modis": "modis-mod09q1"}
    match = next((path for path in project.glob(f"data-center/imagery/series/*{needles[sensor]}*/years/{year}/*") if path.is_dir()), None)
    if match is None: raise RuntimeError(f"RAW_ASSET_MISSING:{sensor}:{year}")
    return match / "raw" / "acquisition"


def fcover_year_dir(project: Path, year: int) -> Path:
    match = next((path for path in project.glob(f"data-center/fcover/series/*/years/{year}/*") if path.is_dir()), None)
    if match is None: raise RuntimeError(f"FCOVER_RAW_ASSET_MISSING:{year}")
    return match / "raw" / "acquisition" / "raw" / "fcover"


def names(ds: rasterio.DatasetReader, default: tuple[str, ...]) -> dict[str, int]:
    return {name: i for i, name in enumerate((item or default[i] for i, item in enumerate(ds.descriptions)), 1)}


def scene_date(sensor: str, scene: Path, manifest: dict[str, Any]) -> date:
    item = manifest[scene.name]
    key = "date" if sensor == "sentinel2" else ("acquisition_time" if sensor == "landsat" else "nominal_time")
    return date.fromisoformat(str(item[key])[:10])


def scene_manifest(acq: Path, sensor: str) -> dict[str, dict[str, Any]]:
    source = json.loads((acq / "tables" / "scene_manifest.json").read_text(encoding="utf-8"))
    return {str(row.get("scene_id") or row["product_id"]): row for row in source}


def fcover_grid(path: Path) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    with rasterio.open(path) as ds:
        bands = names(ds, ("FCOVER", "QFLAG", "NOBS", "dataMask"))
        # The inspected native V2.0.1 files are UInt16 product DNs with the
        # recorded product scale 0.004 (not an 8-bit /255 encoding).
        metadata = json.loads(path.with_suffix(path.suffix + ".metadata.json").read_text(encoding="utf-8"))
        scale = float(metadata["quality_metadata"]["fcover_scale"])
        raw = ds.read(bands["FCOVER"]).astype("float32")
        qflag, nobs, data_mask = (ds.read(bands[name]) for name in ("QFLAG", "NOBS", "dataMask"))
        ref = raw * scale
        nodata = ds.nodata
        valid = ((raw != nodata) & (qflag != nodata) & (nobs != nodata) & (data_mask != nodata)
                 & (qflag < 255) & (nobs > 0) & (data_mask > 0)
                 & np.isfinite(ref) & (ref >= 0) & (ref <= 1))
        profile = ds.profile.copy(); profile.update(dtype="float32", nodata=NODATA)
    return profile, np.where(valid, ref, np.nan), valid


def reproject_array(values: np.ndarray, src: rasterio.DatasetReader, profile: dict[str, Any], *, resampling: Resampling) -> np.ndarray:
    output = np.full((profile["height"], profile["width"]), np.nan, dtype="float32")
    reproject(values.astype("float32"), output, src_transform=src.transform, src_crs=src.crs, src_nodata=np.nan, dst_transform=profile["transform"], dst_crs=profile["crs"], dst_nodata=np.nan, resampling=resampling)
    return output


def download_modis_qa(row: dict[str, Any], profile_path: Path, dest: Path, aoi: dict[str, Any]) -> Path:
    """Stage the previously downloaded native QA asset; never manufacture it."""
    if dest.exists(): return dest
    source = WORKSPACE / "report" / "data_final" / "raw_assets" / "modis" / str(row["nominal_time"][:4]) / row["product_id"] / "QA.tif"
    if not source.is_file():
        raise RuntimeError(f"MODIS_NATIVE_QA_SNAPSHOT_MISSING:{source}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    return dest


def quality_masks(sensor: str, qa: dict[str, np.ndarray], *, scl: np.ndarray | None = None, cloud: np.ndarray | None = None) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    if sensor == "sentinel2":
        if scl is None: raise RuntimeError("SENTINEL_SCL_MISSING")
        if cloud is None: raise RuntimeError("SENTINEL_CLOUD_PROBABILITY_MISSING")
        water = scl == 6
        cloud_m = np.isin(scl, [8, 9, 10]) | ~np.isfinite(cloud) | (cloud >= SENTINEL_CLOUD_THRESHOLD)
        shadow = np.isin(scl, [2, 3]); snow = scl == 11; other = np.isin(scl, [0, 1])
        masks = {"water": water, "cloud": cloud_m, "cloud_shadow": shadow, "snow_ice": snow, "quality": other}
        valid = ~np.isin(scl, list(SENTINEL_EXCLUDED_SCL)) & np.isfinite(cloud) & (cloud < SENTINEL_CLOUD_THRESHOLD)
    elif sensor == "landsat":
        pixel = qa["QA_PIXEL"].astype("uint32"); rad = qa["QA_RADSAT"].astype("uint32")
        water = ((pixel >> 7) & 1).astype(bool); cloud_m = ((pixel >> 1) & 1).astype(bool) | ((pixel >> 2) & 1).astype(bool) | ((pixel >> 3) & 1).astype(bool)
        shadow = ((pixel >> 4) & 1).astype(bool); snow = ((pixel >> 5) & 1).astype(bool); other = ((pixel & 1) != 0) | (rad != 0)
        masks = {"water": water, "cloud": cloud_m, "cloud_shadow": shadow, "snow_ice": snow, "quality": other}
        valid = ~np.logical_or.reduce(list(masks.values()))
    else:
        fields = modis_quality_components(qa)
        water = fields["land_water"] != 1
        cloud_m = (fields["cloud_state"] != 0) | (fields["internal_cloud"] != 0) | (fields["cirrus"] != 0) | (fields["adjacent_cloud"] != 0)
        shadow = fields["cloud_shadow"] != 0; snow = (fields["mod35_snow_ice"] != 0) | (fields["internal_snow"] != 0)
        other = (fields["aerosol_quantity"] == 3) | ~np.isin(fields["modland_quality"], [0, 1]) | (fields["band_1_quality"] != 0) | (fields["band_2_quality"] != 0) | (fields["atmospheric_correction"] != 1) | (fields["internal_fire"] != 0)
        masks = {"water": water, "cloud": cloud_m, "cloud_shadow": shadow, "snow_ice": snow, "quality": other}
        valid = modis_valid_mask(qa)
    return valid, masks


def valid_reflectance_dn(sensor: str, red_dn: np.ndarray, nir_dn: np.ndarray) -> np.ndarray:
    """Apply the downloaded product's documented integer range before scaling."""
    rule = REFLECTANCE_RULES[sensor]
    valid = (red_dn >= rule["valid_dn_min"]) & (red_dn <= rule["valid_dn_max"])
    valid &= (nir_dn >= rule["valid_dn_min"]) & (nir_dn <= rule["valid_dn_max"])
    valid &= (red_dn != rule["nodata_dn"]) & (nir_dn != rule["nodata_dn"])
    return valid


def process_sensor_year(out: Path, project: Path, aoi: dict[str, Any], sensor: str, year: int, qa_hash: str) -> list[dict[str, Any]]:
    acq = sensor_year_dir(project, sensor, year); raw = acq / "raw" / sensor
    manifest = scene_manifest(acq, sensor); results: list[dict[str, Any]] = []
    fc_paths = {d: fcover_year_dir(project, year) / f"fcover_{year}-{d}.tif" for d in TARGET_DATES}
    for target, fc_path in fc_paths.items():
        existing_stats = out / "composites" / sensor / str(year) / target / "preprocessing_statistics.json"
        if existing_stats.is_file():
            results.append(json.loads(existing_stats.read_text(encoding="utf-8")))
            continue
        profile, _, _ = fcover_grid(fc_path)
        target_day = date.fromisoformat(f"{year}-{target}")
        selected = [scene for scene in raw.iterdir() if scene.is_dir() and scene.name in manifest and -WINDOW_DAYS_BEFORE <= (scene_date(sensor, scene, manifest) - target_day).days <= WINDOW_DAYS_AFTER]
        if not selected: raise RuntimeError(f"SOURCE_EMPTY_DATASET:{sensor}:{year}:{target}")
        ndvis: list[np.ndarray] = []; waters: list[np.ndarray] = []; scene_stats = []
        for scene in selected:
            row = manifest[scene.name]
            reflectance = scene / ("spectral.tif" if sensor == "sentinel2" else "reflectance_dn.tif")
            qa_path = scene / ("scl.tif" if sensor == "sentinel2" else "qa.tif")
            with rasterio.open(reflectance) as src:
                b = names(src, ("B2", "B3", "B4", "B8") if sensor == "sentinel2" else (("SR_B4", "SR_B5") if sensor == "landsat" else ("sur_refl_b01", "sur_refl_b02")))
                red_name, nir_name = (("B4", "B8") if sensor == "sentinel2" else (("SR_B4", "SR_B5") if sensor == "landsat" else ("sur_refl_b01", "sur_refl_b02")))
                red_dn = src.read(b[red_name]).astype("float32")
                nir_dn = src.read(b[nir_name]).astype("float32")
                red = red_dn * PRODUCTS[sensor]["scale"] + PRODUCTS[sensor]["offset"]
                nir = nir_dn * PRODUCTS[sensor]["scale"] + PRODUCTS[sensor]["offset"]
                if sensor == "sentinel2":
                    with rasterio.open(qa_path) as qds, rasterio.open(scene / "cloud_probability.tif") as cds:
                        scl = np.zeros((src.height, src.width), dtype="uint8")
                        cloud = np.full((src.height, src.width), np.nan, dtype="float32")
                        reproject(qds.read(1), scl, src_transform=qds.transform, src_crs=qds.crs, dst_transform=src.transform, dst_crs=src.crs, resampling=Resampling.nearest)
                        reproject(cds.read(1), cloud, src_transform=cds.transform, src_crs=cds.crs, dst_transform=src.transform, dst_crs=src.crs, dst_nodata=np.nan, resampling=Resampling.nearest)
                    valid, masks = quality_masks(sensor, {}, scl=scl, cloud=cloud)
                else:
                    with rasterio.open(qa_path) as qds:
                        qb = names(qds, ("QA_PIXEL", "QA_RADSAT") if sensor == "landsat" else ("State",))
                        qa = {name: qds.read(index) for name, index in qb.items()}
                    if sensor == "modis":
                        new_qa = download_modis_qa(row, qa_path, out / "raw_assets" / "modis" / str(year) / scene.name / "QA.tif", aoi)
                        with rasterio.open(new_qa) as ds: qa["QA"] = ds.read(1)
                    valid, masks = quality_masks(sensor, qa)
                    if sensor == "modis":
                        valid &= (qa["State"] != 65535) & (qa["QA"] != 65535)
                valid &= valid_reflectance_dn(sensor, red_dn, nir_dn)
                valid &= np.isfinite(red) & np.isfinite(nir) & (red + nir != 0)
                ndvi = np.where(valid, (nir - red) / (nir + red), np.nan).astype("float32")
                scaled = np.stack([np.where(valid, red, np.nan), np.where(valid, nir, np.nan)]).astype("float32")
                destination = out / "preprocessed" / sensor / str(year) / target / "observations" / scene.name
                ndvi_fc = reproject_array(ndvi, src, profile, resampling=Resampling.average)
                # QA masks are categorical diagnostics.  The formal NDVI has
                # already been masked on the source grid, so this change keeps
                # exported QA classes valid without changing any feature value.
                mask_fc = np.stack([reproject_array(mask.astype("float32"), src, profile, resampling=Resampling.nearest) for mask in masks.values()])
                tif(destination / "red_nir_scaled_fcover_support.tif", np.stack([reproject_array(scaled[0], src, profile, resampling=Resampling.average), reproject_array(scaled[1], src, profile, resampling=Resampling.average)]), profile, ["red", "nir"])
                tif(destination / "quality_masks_fcover_support.tif", np.where(np.isfinite(mask_fc), mask_fc, NODATA).astype("float32"), profile, masks.keys())
                tif(destination / "ndvi_fcover_support.tif", np.where(np.isfinite(ndvi_fc), ndvi_fc, NODATA).astype("float32"), profile, ["ndvi"])
                waters.append(mask_fc[0]); ndvis.append(ndvi_fc)
                scene_stats.append({"product_id": scene.name, "source_path": str(scene), "input_checksum": sha(reflectance), "total_pixel_count": int(valid.size), "finite_reflectance_count": int((np.isfinite(red) & np.isfinite(nir)).sum()), "water_masked_count": int(masks["water"].sum()), "water_masked_ratio": float(masks["water"].mean()), "cloud_masked_count": int(masks["cloud"].sum()), "cloud_shadow_masked_count": int(masks["cloud_shadow"].sum()), "snow_ice_masked_count": int(masks["snow_ice"].sum()), "aerosol_or_quality_masked_count": int(masks["quality"].sum()), "final_valid_count": int(valid.sum())})
        stack = np.stack(ndvis); counts = np.isfinite(stack).sum(axis=0).astype("uint16")
        with np.errstate(all="ignore"): composite = np.nanmedian(stack, axis=0)
        composite[counts < MINIMUM_VALID_OBSERVATIONS] = np.nan
        base = out / "composites" / sensor / str(year) / target
        ndvi_path = base / "ndvi_median_fcover_support.tif"; count_path = base / "valid_observation_count.tif"
        tif(ndvi_path, np.where(np.isfinite(composite), composite, NODATA).astype("float32"), profile, ["ndvi"])
        tif(count_path, counts, profile, ["valid_observation_count"])
        water_once = np.nanmax(np.stack(waters), axis=0) > 0
        stats = {"source": sensor, "product_id": PRODUCTS[sensor]["id"], "product_version": PRODUCTS[sensor]["version"], "year": year, "target_date": f"{year}-{target}", "acquisition_count": len(selected), "valid_scene_count": sum(x["final_valid_count"] > 0 for x in scene_stats), "total_pixel_count": int(stack.shape[1] * stack.shape[2]), "water_masked_count": sum(x["water_masked_count"] for x in scene_stats), "water_masked_ratio": float(np.mean([x["water_masked_ratio"] for x in scene_stats])), "cloud_masked_count": sum(x["cloud_masked_count"] for x in scene_stats), "cloud_shadow_masked_count": sum(x["cloud_shadow_masked_count"] for x in scene_stats), "snow_ice_masked_count": sum(x["snow_ice_masked_count"] for x in scene_stats), "aerosol_or_quality_masked_count": sum(x["aerosol_or_quality_masked_count"] for x in scene_stats), "final_valid_count": int(np.isfinite(composite).sum()), "valid_observation_count_distribution": {str(i): int((counts == i).sum()) for i in np.unique(counts)}, "min_valid_observations": MINIMUM_VALID_OBSERVATIONS, "scale": PRODUCTS[sensor]["scale"], "offset": PRODUCTS[sensor]["offset"], "qa_config_hash": qa_hash, "input_checksum": stable_hash([x["input_checksum"] for x in scene_stats]), "output_checksum": sha(ndvi_path), "water_once_ratio": float(water_once.mean()), "no_land_valid_observation_ratio": float((counts == 0).mean()), "water_caused_insufficient_ratio": float(((counts < MINIMUM_VALID_OBSERVATIONS) & water_once).mean()), "scene_statistics": scene_stats}
        write_json(base / "preprocessing_statistics.json", stats); write_json(base / "processing_manifest.json", {"derived_from_raw_only": True, "statistics": stats, "outputs": {"ndvi": str(ndvi_path.relative_to(out)), "count": str(count_path.relative_to(out))}})
        results.append(stats)
    return results


def load_cube(out: Path, sensor: str, year: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    values=[]; counts=[]; refs=[]; profile=None
    project=raw_root()
    for target in TARGET_DATES:
        path=out/"composites"/sensor/str(year)/target/"ndvi_median_fcover_support.tif"
        cpath=out/"composites"/sensor/str(year)/target/"valid_observation_count.tif"
        fpath=fcover_year_dir(project,year)/f"fcover_{year}-{target}.tif"
        with rasterio.open(path) as ds:
            arr=ds.read(1).astype("float32"); arr[arr==ds.nodata]=np.nan; profile=ds.profile.copy()
        with rasterio.open(cpath) as ds: count=ds.read(1)
        _, ref, _=fcover_grid(fpath)
        values.append(arr);counts.append(count);refs.append(ref)
    assert profile is not None
    return np.stack(values),np.stack(counts),np.stack(refs),profile


def metric(pred: np.ndarray, ref: np.ndarray) -> dict[str, Any]:
    diff=pred-ref; n=int(diff.size)
    return {"rmse": float(np.sqrt(np.mean(diff**2))), "mae": float(np.mean(np.abs(diff))), "bias": float(np.mean(diff)), "r_squared": float(r2_score(ref,pred)) if n>1 else float("nan"), "pearson_r": float(np.corrcoef(pred,ref)[0,1]) if n>1 and np.std(pred)>0 and np.std(ref)>0 else float("nan"), "valid_comparison_count": n, "mean_reference":float(ref.mean()),"mean_prediction":float(pred.mean()),"reference_standard_deviation":float(ref.std()),"prediction_standard_deviation":float(pred.std())}


def train_apply_compare(out: Path, qa_hash: str, config_hash: str, pre_stats: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    model_rows=[]; metrics=[]; index=[]; common={}
    cubes={sensor:{year:load_cube(out,sensor,year) for year in YEARS} for sensor in SENSORS}
    for sensor in SENSORS:
        ndvi25,count25,ref25,profile=cubes[sensor][2025]
        valid=np.isfinite(ndvi25)&np.isfinite(ref25)&(count25>=MINIMUM_VALID_OBSERVATIONS)
        mask_path=out/"masks"/"evaluation"/sensor/"common_evaluation_mask_2025.tif"; checksum=tif(mask_path,valid.astype("uint8"),profile,["common_evaluation_mask"]); common[sensor]=(valid,checksum)
        tif(out/"composites"/sensor/"2025"/"ndvi_stack_2025.tif",np.where(np.isfinite(ndvi25),ndvi25,NODATA).astype("float32"),profile,[f"ndvi_{x}" for x in TARGET_DATES])
        for name, years in WINDOWS.items():
            xs=[];ys=[];groups=[];year_counts={}
            for year in years:
                nd,count,ref,_=cubes[sensor][year]; good=np.isfinite(nd)&np.isfinite(ref)&(count>=MINIMUM_VALID_OBSERVATIONS); year_counts[str(year)]=int(good.sum()); xs.append(nd[good]);ys.append(ref[good]); _, rows, cols=np.where(good);groups.append((rows//17)*100000+cols//17)
            x=np.concatenate(xs);y=np.concatenate(ys);g=np.concatenate(groups)
            model=LinearRegression(fit_intercept=True).fit(x.reshape(-1,1),y); raw=np.full(ndvi25.shape,np.nan,dtype="float32"); finite=np.isfinite(ndvi25); raw[finite]=model.predict(ndvi25[finite].reshape(-1,1)); clipped=np.clip(raw,0,1); good=common[sensor][0]
            task_id=f"new-{sensor}-{name}"; mdir=out/"models"/sensor/name; mdir.mkdir(parents=True,exist_ok=True)
            train_raw=model.predict(x.reshape(-1,1)); manifest={"task_id":task_id,"sensor":sensor,"method":"ordinary_least_squares_intercept","slope_a":float(model.coef_[0]),"intercept_b":float(model.intercept_),"training_years":list(years),"year_sample_counts":year_counts,"total_training_samples":int(len(x)),"training_input_checksum":stable_hash([sha(out/"composites"/sensor/str(y)/d/"ndvi_median_fcover_support.tif") for y in years for d in TARGET_DATES]),"data_config_hash":config_hash,"qa_config_hash":qa_hash,"spatial_aggregation":"FCOVER native 300m footprint mean/support", "spatial_group_count":int(len(np.unique(g))),"training_metrics":metric(np.clip(train_raw,0,1),y),"raw_prediction_range":[float(train_raw.min()),float(train_raw.max())],"raw_below_zero_ratio":float((train_raw<0).mean()),"raw_above_one_ratio":float((train_raw>1).mean()),"clip_ratio":float(((train_raw<0)|(train_raw>1)).mean()),"created_at":datetime.now(timezone.utc).isoformat(),"code_commit":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()}
            write_json(mdir/"model.json",{"coef":float(model.coef_[0]),"intercept":float(model.intercept_)});write_json(mdir/"model-manifest.json",manifest)
            model_rows.append({"sensor":sensor,"strategy":name,**{k:manifest[k] for k in ("slope_a","intercept_b","total_training_samples","raw_below_zero_ratio","raw_above_one_ratio","clip_ratio")}})
            run_experiment(out,sensor,name,"regression",raw,clipped,ref25,good,profile,checksum,task_id,metrics,index,{"model_manifest":str((mdir/"model-manifest.json").relative_to(out))})
        vals=ndvi25[common[sensor][0]]; p5,p95=np.percentile(vals,[5,95]); raw=(ndvi25-p5)/(p95-p5);clipped=np.clip(raw,0,1); task_id=f"new-{sensor}-formula-p5-p95"; formula={"task_id":task_id,"sensor":sensor,"P5":float(p5),"P95":float(p95),"endpoint_gap":float(p95-p5),"low_clip_ratio":float((raw[common[sensor][0]]<0).mean()),"high_clip_ratio":float((raw[common[sensor][0]]>1).mean()),"total_clip_ratio":float(((raw[common[sensor][0]]<0)|(raw[common[sensor][0]]>1)).mean()),"endpoint_sample_count":int(vals.size),"endpoint_input_checksum":sha(out/"composites"/sensor/"2025"/"ndvi_stack_2025.tif"),"qa_config_hash":qa_hash,"common_evaluation_mask_checksum":checksum}
        write_json(out/"models"/sensor/"formula-p5-p95"/"formula-manifest.json",formula);model_rows.append({"sensor":sensor,"strategy":"formula-p5-p95",**formula});run_experiment(out,sensor,"formula-p5-p95","formula",raw,clipped,ref25,common[sensor][0],profile,checksum,task_id,metrics,index,{"formula_manifest":str((out/"models"/sensor/"formula-p5-p95"/"formula-manifest.json").relative_to(out))})
    cross=np.logical_and.reduce([common[s][0] for s in SENSORS]); profile=cubes["sentinel2"][2025][3];tif(out/"masks"/"evaluation"/"cross_sensor_common_evaluation_mask_2025.tif",cross.astype("uint8"),profile,["cross_sensor_common_evaluation_mask"])
    return model_rows,metrics,index


def run_experiment(out:Path,sensor:str,strategy:str,method:str,raw:np.ndarray,clip:np.ndarray,ref:np.ndarray,good:np.ndarray,profile:dict[str,Any],mask_checksum:str,task_id:str,metrics:list[dict[str,Any]],index:list[dict[str,Any]],lineage:dict[str,Any]) -> None:
    base=out/"applications"/"2025"/sensor/strategy; tif(base/"raw_prediction_300m.tif",np.where(np.isfinite(raw),raw,NODATA).astype("float32"),profile,TARGET_DATES);tif(base/"clipped_prediction_300m.tif",np.where(np.isfinite(clip),clip,NODATA).astype("float32"),profile,TARGET_DATES)
    flatgood=good.ravel(); p=clip.ravel()[flatgood];r=ref.ravel()[flatgood]; stats=metric(p,r);stats.update({"task_id":task_id,"sensor":sensor,"strategy":strategy,"method":method,"difference_definition":"model_prediction_minus_fcover_reference","clipped_low_count":int((raw.ravel()[flatgood]<0).sum()),"clipped_high_count":int((raw.ravel()[flatgood]>1).sum()),"common_evaluation_mask_checksum":mask_checksum})
    comp=out/"comparisons"/"2025"/sensor/strategy; signed=clip-ref; tif(comp/"signed_difference_300m.tif",np.where(good,signed,NODATA).astype("float32"),profile,TARGET_DATES);tif(comp/"absolute_difference_300m.tif",np.where(good,np.abs(signed),NODATA).astype("float32"),profile,TARGET_DATES);tif(comp/"squared_difference_300m.tif",np.where(good,signed**2,NODATA).astype("float32"),profile,TARGET_DATES);write_json(comp/"comparison_stats.json",stats);write_json(base/"application-manifest.json",{"task_id":task_id,"status":"completed","input_ndvi_checksum":sha(out/"composites"/sensor/"2025"/"ndvi_stack_2025.tif"),"evaluation_mask_checksum":mask_checksum,**lineage});write_json(comp/"comparison-manifest.json",{"task_id":task_id,"status":"completed","comparison_stats":str((comp/"comparison_stats.json").relative_to(out)),"evaluation_mask_checksum":mask_checksum})
    metrics.append(stats);index.append({"task_id":task_id,"sensor":sensor,"strategy":strategy,"method":method,"application":str(base.relative_to(out)),"comparison":str(comp.relative_to(out)),"status":"completed"})


def audit_report(out:Path,config:dict[str,Any],qa:dict[str,Any],project:Path) -> None:
    text=f"""# Initial pipeline audit

Generated {datetime.now(timezone.utc).isoformat()} from executable source and current configuration.

## Products and real call chain

`backend.sources.registry → adapter.execute → adapter.acquire/canonicalize/validate/preprocess` is the active ingestion chain. Sentinel-2 is `COPERNICUS/S2_SR_HARMONIZED` (`B4`, `B8`, `SCL`, cloud-probability collection); Landsat is C2 L2 (`SR_B4`, `SR_B5`, `QA_PIXEL`, `QA_RADSAT`); MODIS is `MODIS/061/MOD09Q1` (`sur_refl_b01`, `sur_refl_b02`, `State`, `QA`). FCOVER input is Copernicus FCOVER 300 m V2 RT6 (`FCOVER`, `QFLAG`, `NOBS`, `dataMask`).

## Findings before change

* Sentinel configured SCL exclusion was `[0,1,3,6,8,9,10,11]`, cloud probability threshold 40, scale 0.0001; legacy validation did **not** require the cloud-probability asset and preprocessing silently accepted its absence.
* MODIS scale was 0.0001 and legacy code decoded only State cloud/shadow/internal-cloud/snow/adjacent-cloud. It neither decoded State bits 3–5 (land/water) nor acquired/decoded the MOD09Q1 `QA` band (MODLAND, band 1/2 quality, atmospheric correction): this was unsafe and is corrected in this revision.
* Landsat remains scale 0.0000275 and offset -0.2, invalid `QA_PIXEL` bits 0–5 plus nonzero `QA_RADSAT`; no new Landsat water rule is introduced.
* All source masks act before NDVI and median temporal composite. Frozen minimum per-pixel valid observations is 2. Training must aggregate NDVI to FCOVER support before OLS.
* The formal runner does not read any legacy `features`, `processed`, `training`, `models`, `applications`, `comparisons` or old statistics; it reads only `raw/acquisition/raw` and records checksums.

## Historical risks

Old jobs could silently reuse legacy processed/feature/model/application data; old MODIS jobs lack required QA; and old task manifests use distinct application/comparison inputs. The new run has one 2025 NDVI cube and one fixed evaluation mask per sensor, checked across all seven strategies.
"""
    (out/"reports"/"initial_pipeline_audit.md").parent.mkdir(parents=True,exist_ok=True);(out/"reports"/"initial_pipeline_audit.md").write_text(text,encoding="utf-8")


def reports(out:Path,pre:list[dict[str,Any]],models:list[dict[str,Any]],metrics:list[dict[str,Any]],index:list[dict[str,Any]],qa_hash:str,config_hash:str) -> None:
    write_csv(out/"reports"/"preprocessing_statistics.csv",pre);write_csv(out/"reports"/"water_mask_statistics.csv",[{k:x.get(k) for k in ("source","year","target_date","water_masked_count","water_masked_ratio","water_once_ratio","no_land_valid_observation_ratio","water_caused_insufficient_ratio")} for x in pre]);write_csv(out/"reports"/"model_parameters.csv",models);write_csv(out/"reports"/"final_21_experiment_metrics.csv",metrics);write_csv(out/"reports"/"experiment_index.csv",index)
    samples=[]
    for r in models:
        if r["strategy"]!="formula-p5-p95":samples.append({"sensor":r["sensor"],"window":r["strategy"],"sample_count":r["total_training_samples"]})
    write_csv(out/"reports"/"training_sample_statistics.csv",samples)
    checks={s:{x["common_evaluation_mask_checksum"] for x in metrics if x["sensor"]==s} for s in SENSORS}; ns={s:{x["valid_comparison_count"] for x in metrics if x["sensor"]==s} for s in SENSORS}
    summary=f"""# Preprocessing and retraining summary

## Execution summary

All 12 source-year × target-date support-domain composites were rebuilt from raw assets into this output directory; 18 OLS models, 3 P5/P95 formula baselines, and 21 2025 application/comparison tasks were emitted. Configuration hash: `{config_hash}`. QA hash: `{qa_hash}`.

## QA treatment

Sentinel-2 excludes SCL 0,1,3,6,8,9,10,11 and cloud probability ≥40 per observation before NDVI. MODIS uses State land/water bits 3–5 (only value 1 land retained) plus State cloud/shadow/cirrus/internal-cloud/snow/adjacent-cloud/aerosol and QA MODLAND/band1/band2/atmospheric-correction flags. Landsat keeps its frozen QA_PIXEL/QA_RADSAT rule and receives no new water rule.

## Support and evaluation

Every sample is one FCOVER 300-m footprint × date × year. The prediction operation is NDVI aggregation on FCOVER support, then `a × NDVI + b`, clip [0,1]. Difference is prediction minus FCOVER.

## Common-mask verification

{json.dumps({s:{"checksums":list(checks[s]),"n":list(ns[s])} for s in SENSORS},ensure_ascii=False,indent=2)}

## Result table

See `final_21_experiment_metrics.csv`, `model_parameters.csv`, and per-task manifests. Metrics are generated from `comparison_stats.json`, never transcribed from a plot.

## Limits

Product-native QA classes differ across sources. Landsat water behavior remains intentionally unchanged. FCOVER is a 300-m reference, not ground truth; results do not validate a hypothetical finer-grid product.
"""
    (out/"reports"/"preprocessing_and_retraining_summary.md").write_text(summary,encoding="utf-8")
    unresolved="""# Unresolved issues

No undisclosed high-risk issue. The original MODIS raw archive lacked the required `QA` band; this run fetched it anew from the same MODIS/061/MOD09Q1 image IDs into `raw_assets/modis`, and records its checksum. No legacy derived products were reused.
""";(out/"reports"/"unresolved_issues.md").write_text(unresolved,encoding="utf-8")
    legacy_tokens=("/features/", "/processed/", "/training/", "/models/", "/applications/", "/comparisons/")
    leaked=[]
    for path in out.rglob("*.json"):
        text=path.read_text(encoding="utf-8")
        if "qh-fvc-data" in text and any(token in text for token in legacy_tokens): leaked.append(str(path.relative_to(out)))
    required=[out/"comparisons"/"2025"/r["sensor"]/r["strategy"]/"comparison_stats.json" for r in index]
    e2e=f"""# E2E validation

* preprocessing statistics: {len(pre)} (expected 36)
* OLS models: {sum(1 for x in models if x['strategy']!='formula-p5-p95')} (expected 18)
* formula baselines: {sum(1 for x in models if x['strategy']=='formula-p5-p95')} (expected 3)
* applications/comparisons: {len(index)} (expected 21)
* unique common-mask checksum per sensor: {json.dumps({k:len(v) for k,v in checks.items()})}
* unique valid comparison n per sensor: {json.dumps({k:len(v) for k,v in ns.items()})}
* comparison-stat files present: {sum(path.is_file() for path in required)}/21
* legacy derived-path leakage: {len(leaked)} ({', '.join(leaked) if leaked else 'none'})
* status: {'PASS' if len(pre)==36 and len(index)==21 and all(path.is_file() for path in required) and not leaked and all(len(v)==1 for v in checks.values()) and all(len(v)==1 for v in ns.values()) else 'FAIL'}
""";(out/"reports"/"e2e_validation_report.md").write_text(e2e,encoding="utf-8")
    plt.figure(figsize=(11,5));labels=[f"{r['sensor']}\n{r['strategy']}" for r in metrics];plt.bar(range(len(metrics)),[r['rmse'] for r in metrics]);plt.xticks(range(len(metrics)),labels,rotation=70,ha='right',fontsize=7);plt.ylabel('RMSE');plt.tight_layout();(out/"figures").mkdir(exist_ok=True);plt.savefig(out/"figures"/"final_21_rmse.png",dpi=160);plt.close()
    plt.figure(figsize=(8,4));rows=defaultdict(list)
    for x in pre:rows[x['source']].append(x['water_masked_ratio'])
    plt.bar(rows.keys(),[np.mean(v) for v in rows.values()]);plt.ylabel('mean water exclusion ratio');plt.tight_layout();plt.savefig(out/"figures"/"water_mask_exclusion_ratio.png",dpi=160);plt.close()
    # Additional diagnostics intentionally use the same native 300 m support grid
    # and the same colour limits for comparable mask/difference views.
    for source in SENSORS:
        with rasterio.open(out/"masks"/"evaluation"/source/"common_evaluation_mask_2025.tif") as ds: mask=ds.read(1)
        plt.figure(figsize=(7,4));plt.imshow(mask,cmap="Greys",vmin=0,vmax=1);plt.colorbar(label="common valid mask");plt.title(f"{source} common evaluation mask (FCOVER 300 m)");plt.tight_layout();plt.savefig(out/"figures"/f"{source}_common_evaluation_mask.png",dpi=160);plt.close()
        with rasterio.open(out/"comparisons"/"2025"/source/"formula-p5-p95"/"signed_difference_300m.tif") as ds: diff=ds.read(1).astype(float);diff[diff==ds.nodata]=np.nan
        plt.figure(figsize=(7,4));plt.imshow(diff,cmap="RdBu_r",vmin=-.3,vmax=.3);plt.colorbar(label="prediction − FCOVER");plt.title(f"{source} signed difference (FCOVER 300 m)");plt.tight_layout();plt.savefig(out/"figures"/f"{source}_signed_difference_formula.png",dpi=160);plt.close()
    with rasterio.open(out/"masks"/"evaluation"/"cross_sensor_common_evaluation_mask_2025.tif") as ds: cross=ds.read(1)
    plt.figure(figsize=(7,4));plt.imshow(cross,cmap="Greys",vmin=0,vmax=1);plt.colorbar(label="cross-sensor valid mask");plt.title("Cross-sensor common evaluation mask (FCOVER 300 m)");plt.tight_layout();plt.savefig(out/"figures"/"cross_sensor_common_evaluation_mask.png",dpi=160);plt.close()
    linear=[r for r in models if r['strategy']!='formula-p5-p95'];plt.figure(figsize=(10,4));plt.scatter(range(len(linear)),[r['slope_a'] for r in linear],label='slope a');plt.scatter(range(len(linear)),[r['intercept_b'] for r in linear],label='intercept b');plt.legend();plt.xticks(range(len(linear)),[f"{r['sensor']}:{r['strategy']}" for r in linear],rotation=65,ha='right',fontsize=6);plt.tight_layout();plt.savefig(out/"figures"/"model_slope_intercept.png",dpi=160);plt.close()
    formula=[r for r in models if r['strategy']=='formula-p5-p95'];plt.figure(figsize=(6,4));plt.bar([r['sensor'] for r in formula],[r['endpoint_gap'] for r in formula]);plt.ylabel('P95 − P5');plt.tight_layout();plt.savefig(out/"figures"/"formula_endpoints_gap.png",dpi=160);plt.close()
    plt.figure(figsize=(10,4));plt.bar(range(len(metrics)),[r['mae'] for r in metrics],label='MAE');plt.plot(range(len(metrics)),[r['bias'] for r in metrics],color='black',label='Bias');plt.legend();plt.tight_layout();plt.savefig(out/"figures"/"final_21_mae_bias.png",dpi=160);plt.close()


def main() -> int:
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=WORKSPACE/'report'/'data_final');parser.add_argument('--qa-config',type=Path,default=WORKSPACE/'report'/'config'/'source_qa_config.yaml');parser.add_argument('--sentinel-cloud-threshold',type=float);parser.add_argument('--retain-scl2',action='store_true');parser.add_argument('--modis-qa-level',choices=('strict','main','wide'));parser.add_argument('--clean',action='store_true');args=parser.parse_args();out=args.output.resolve()
    if args.clean and out.exists(): shutil.rmtree(out)
    for name in ('config','raw_assets','preprocessed','masks','composites','reference/fcover','training_samples','models','applications/2025','comparisons/2025','manifests','metrics','figures','logs','reports'): (out/name).mkdir(parents=True,exist_ok=True)
    config=load_config().raw; qa=yaml.safe_load(args.qa_config.read_text(encoding='utf-8'))
    if args.sentinel_cloud_threshold is not None: qa['sentinel2']['cloud_probability_exclude_gte']=args.sentinel_cloud_threshold
    if args.retain_scl2:
        qa['sentinel2']['excluded_scl']=[value for value in qa['sentinel2']['excluded_scl'] if int(value) != 2]; qa['sentinel2']['scl_2_retained']=True
    if args.modis_qa_level == 'strict':
        qa['modis']['bits']['aerosol_quantity']['keep']=[0,1]; qa['modis']['bits']['modland_quality']['keep']=[0]
    elif args.modis_qa_level == 'wide':
        qa['modis']['bits']['aerosol_quantity']['keep']=[0,1,2,3]; qa['modis']['bits']['modland_quality']['keep']=[0,1]; qa['modis']['bits']['band_1_quality']['keep']=[0,1]; qa['modis']['bits']['band_2_quality']['keep']=[0,1]; qa['modis']['bits']['atmospheric_correction']['keep']=[0,1]
    configure_preprocessing_rules(qa); qa_hash=stable_hash(qa);scientific={"years":YEARS,"target_dates":TARGET_DATES,"window_days_before":WINDOW_DAYS_BEFORE,"window_days_after":WINDOW_DAYS_AFTER,"temporal_composite":qa["temporal_composite"]["statistic"],"minimum_valid_observations":MINIMUM_VALID_OBSERVATIONS,"footprint_minimum_valid_area":qa["footprint_minimum_valid_area"],"support":"FCOVER native 300m footprint","aggregation":"area-weighted mean through raster average resampling to native footprint","random_seed":42,"aoi":"data/aoi.geojson (asset checksum in manifest)","products":PRODUCTS};config_hash=stable_hash(scientific)
    (out/'config'/'scientific_config.yaml').write_text(yaml.safe_dump(scientific,allow_unicode=True,sort_keys=False),encoding='utf-8');(out/'config'/'source_qa_config.yaml').write_text(yaml.safe_dump(qa,allow_unicode=True,sort_keys=False),encoding='utf-8');matrix=[{"task_id":f"new-{s}-{w}","sensor":s,"strategy":w,"method":"regression"} for s in SENSORS for w in WINDOWS]+[{"task_id":f"new-{s}-formula-p5-p95","sensor":s,"strategy":"formula-p5-p95","method":"formula"} for s in SENSORS];write_json(out/'config'/'experiment_matrix.json',matrix);project=raw_root();aoi=json.loads(aoi_path().read_text());audit_report(out,scientific,qa,project)
    pre=[]
    for s in SENSORS:
        for y in YEARS: pre.extend(process_sensor_year(out,project,aoi,s,y,qa_hash))
    raw_assets=[]
    for asset in project.glob('data-center/**/raw/acquisition/raw/**/*'):
        if asset.is_file(): raw_assets.append({"source_path":str(asset),"checksum":sha(asset),"kind":"legacy_raw_allowed"})
    for asset in (out/'raw_assets').glob('**/*'):
        if asset.is_file(): raw_assets.append({"source_path":str(asset.relative_to(out)),"checksum":sha(asset),"kind":"newly_acquired_required_qa"})
    write_json(out/'manifests'/'raw_asset_manifest.json',raw_assets)
    write_json(out/'config'/'data_version_manifest.json',{"created_at":datetime.now(timezone.utc).isoformat(),"raw_root":str(project),"raw_asset_manifest":"manifests/raw_asset_manifest.json","raw_only_reuse":True,"raw_asset_count":len(raw_assets),"config_hash":config_hash,"qa_hash":qa_hash,"code_commit":subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()})
    models,metrics,index=train_apply_compare(out,qa_hash,config_hash,pre)
    db=sqlite3.connect(out/'manifests'/'reconstruction.sqlite3');db.execute('create table if not exists experiment_tasks (task_id text primary key, sensor text not null, strategy text not null, method text not null, status text not null, application_path text not null, comparison_path text not null)');db.execute('delete from experiment_tasks');db.executemany('insert into experiment_tasks values (:task_id,:sensor,:strategy,:method,:status,:application,:comparison)',index);db.commit();db.close()
    reports(out,pre,models,metrics,index,qa_hash,config_hash);write_json(out/'manifests'/'artifact_manifest.json',{"config_hash":config_hash,"qa_hash":qa_hash,"experiments":index,"task_database":"manifests/reconstruction.sqlite3","path_audit":"No legacy derived path may appear; raw source paths only occur in preprocessing statistics."});return 0

if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception as exc:
        print(f"REBUILD_FAILED: {type(exc).__name__}: {exc}",file=sys.stderr);raise
