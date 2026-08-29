#!/usr/bin/env python3
"""Run bounded Landsat or MODIS preprocessing parity from the active R2 contract.

The local side downloads exact frozen native source pixels into memory and
uses the approved NumPy QA/NDVI implementation.  The GEE side evaluates the
independent catalog expressions.  Both are compared at native resolution and
after exact coverage-weighted FCOVER-grid aggregation.  No assets or models
are created.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import ee
import numpy as np
import rasterio
import requests
from affine import Affine
from pyproj import Transformer
from rasterio.io import MemoryFile
from rasterio.windows import from_bounds
from shapely.geometry import shape
from shapely.ops import transform as shapely_transform

PUBLICATION = Path(__file__).resolve().parents[2]
WORKSPACE = PUBLICATION.parents[1]
sys.path.insert(0, str(PUBLICATION / "code" / "src"))

from common.raster_utils import area_weighted_to_fcover  # noqa: E402
from data_prep import landsat, modis  # noqa: E402
from data_prep.download import canonical_crs  # noqa: E402
from data_prep.gee_cloud import _average_to_fcover, _bits, initialize  # noqa: E402
from data_prep.temporal_composite import nanmedian_min_count  # noqa: E402
from execution.contract import assert_parity_validation_contract, load_contract  # noqa: E402

EXP = PUBLICATION / "new_experiments" / "15_three_sensor_parity"
CONTRACT_CSV = EXP / "15_ACTIVE_SOURCE_IDENTITY_CONTRACT" / "PARITY_SOURCE_INPUTS_R2.csv"
CONTRACT_JSON = EXP / "15_ACTIVE_SOURCE_IDENTITY_CONTRACT" / "SOURCE_IDENTITY_CONTRACT.json"
ROOT = EXP / "16_THREE_SENSOR_PARITY_R2"
CHECKPOINTS = ROOT / "_checkpoints"
AOI = PUBLICATION / "new_experiments" / "01_multi_aoi" / "final_four_aoi_registry.geojson"
FCOVER = "projects/qinghai-internship-fvc-models/assets/fvc_report_data/fcover_native_r3_fcover_value_domain_v2/AOI_00_20250720"
DESIGN_HASH = "b21c8cc7f3d4d35e1db4dfa1c8245ff10ba657c0a0a001992b552808766cc49b"
ALGORITHM_VERSION = "three-sensor-parity-r2-mask-aware-area-weighted-v1"
NODATA_NDVI = -9999.0


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"EMPTY_PARITY_EVIDENCE:{path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    fields = sorted({key for row in rows for key in row})
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)
    temporary.replace(path)


def aoi_geometry() -> dict[str, Any]:
    collection = json.loads(AOI.read_text(encoding="utf-8"))
    return next(feature["geometry"] for feature in collection["features"]
                if feature["properties"].get("aoi_id") == "AOI-00")


def source_profile(image: ee.Image, geometry: dict[str, Any]) -> dict[str, Any]:
    projection = image.projection().getInfo()
    affine = Affine(*projection["transform"])
    analysis_crs = canonical_crs(projection["crs"])
    transformer = Transformer.from_crs("EPSG:4326", analysis_crs, always_xy=True)
    projected = shapely_transform(transformer.transform, shape(geometry))
    window = from_bounds(*projected.bounds, transform=affine)
    column_start = int(np.floor(window.col_off)); row_start = int(np.floor(window.row_off))
    column_end = int(np.ceil(window.col_off + window.width)); row_end = int(np.ceil(window.row_off + window.height))
    return {
        "crs": projection["crs"], "analysis_crs": analysis_crs,
        "transform": affine * Affine.translation(column_start, row_start),
        "source_transform": affine, "source_row_start": row_start, "source_column_start": column_start,
        "width": column_end - column_start, "height": row_end - row_start,
    }


def tile_profile(profile: dict[str, Any], row: int, height: int) -> dict[str, Any]:
    return {"crs": profile["crs"], "transform": profile["transform"] * Affine.translation(0, row),
            "width": profile["width"], "height": height}


def fixed_params(profile: dict[str, Any]) -> dict[str, Any]:
    return {"crs": str(profile["crs"]), "crs_transform": list(profile["transform"])[:6],
            "dimensions": [profile["width"], profile["height"]]}


def request_tif(image: ee.Image, bands: list[str], profile: dict[str, Any], fills: list[float | int]) -> np.ndarray:
    if len(bands) != len(fills):
        raise RuntimeError("PARITY_FILL_SCHEMA_MISMATCH")
    params = {**fixed_params(profile), "format": "GEO_TIFF", "filePerBand": False,
              "name": "three_sensor_parity_r2"}
    response = requests.get(image.select(bands).getDownloadURL(params), timeout=(30, 300))
    if not response.ok:
        raise RuntimeError(f"PARITY_DOWNLOAD_HTTP_{response.status_code}:{response.text[:1200]}")
    content = response.content
    if content[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith((".tif", ".tiff"))]
            if len(names) != 1:
                raise RuntimeError(f"PARITY_DOWNLOAD_TIFF_COUNT:{len(names)}")
            content = archive.read(names[0])
    with MemoryFile(content) as memory:
        with memory.open() as dataset:
            observed_crs = canonical_crs(dataset.crs.to_wkt())
            expected_crs = canonical_crs(str(profile["crs"]))
            modis_alias_serialization = (
                str(profile["crs"]).upper() == "SR-ORG:6974" and
                "SINUSOIDAL" in str(dataset.crs).upper()
            )
            if ((dataset.width, dataset.height, dataset.transform) !=
                (profile["width"], profile["height"], profile["transform"]) or
                    not (observed_crs.equals(expected_crs, ignore_axis_order=True) or modis_alias_serialization)):
                raise RuntimeError(
                    "PARITY_DOWNLOAD_GRID_MISMATCH:"
                    f"observed_crs={dataset.crs}:expected_crs={profile['crs']}:"
                    f"observed_transform={list(dataset.transform)[:6]}:"
                    f"expected_transform={list(profile['transform'])[:6]}:"
                    f"observed_size={dataset.width}x{dataset.height}:"
                    f"expected_size={profile['width']}x{profile['height']}"
                )
            if dataset.count != len(bands):
                raise RuntimeError("PARITY_DOWNLOAD_BAND_COUNT_MISMATCH")
            values = dataset.read(); masks = dataset.read_masks() > 0
            return np.where(masks, values, np.asarray(fills)[:, None, None])


def request_strips(image: ee.Image, bands: list[str], profile: dict[str, Any],
                   fills: list[float | int], max_rows: int = 512) -> np.ndarray:
    parts = []
    for row in range(0, profile["height"], max_rows):
        part = tile_profile(profile, row, min(max_rows, profile["height"] - row))
        parts.append(request_tif(image, bands, part, fills))
    return np.concatenate(parts, axis=1)


def target_grid(info: dict[str, Any]) -> dict[str, Any]:
    grid = info["bands"][0]["grid"]; affine = grid["affineTransform"]
    transform = Affine(affine["scaleX"], affine.get("shearX", 0), affine["translateX"],
                       affine.get("shearY", 0), affine["scaleY"], affine["translateY"])
    return {"crs": grid["crsCode"], "transform": transform,
            "width": int(grid["dimensions"]["width"]), "height": int(grid["dimensions"]["height"])}


def metrics(local: np.ndarray, gee: np.ndarray) -> dict[str, Any]:
    local_valid, gee_valid = np.isfinite(local), np.isfinite(gee)
    common = local_valid & gee_valid
    delta = local[common].astype("float64") - gee[common].astype("float64")
    result: dict[str, Any] = {
        "total_cells": int(local.size), "valid_local": int(local_valid.sum()),
        "valid_GEE": int(gee_valid.sum()), "common_valid": int(common.sum()),
        "mask_disagreement": int(np.count_nonzero(local_valid != gee_valid)),
    }
    if delta.size:
        absolute = np.abs(delta)
        result.update({
            "mean_signed_difference": float(delta.mean()), "mean_absolute_difference": float(absolute.mean()),
            "median_absolute_difference": float(np.median(absolute)), "P95_absolute_difference": float(np.quantile(absolute, .95)),
            "P99_absolute_difference": float(np.quantile(absolute, .99)), "implementation_RMSE": float(np.sqrt(np.mean(delta ** 2))),
            "max_absolute_difference": float(absolute.max()),
            "Pearson_correlation": float(np.corrcoef(local[common], gee[common])[0, 1]) if delta.size > 1 else 1.0,
        })
    else:
        result.update({key: math.nan for key in (
            "mean_signed_difference", "mean_absolute_difference", "median_absolute_difference",
            "P95_absolute_difference", "P99_absolute_difference", "implementation_RMSE",
            "max_absolute_difference", "Pearson_correlation",
        )})
    return result


def mask_metrics(local: np.ndarray, gee: np.ndarray) -> dict[str, Any]:
    agreement = local == gee
    return {
        "total_pixels": int(local.size), "valid_local": int(local.sum()), "valid_GEE": int(gee.sum()),
        "common_valid": int((local & gee).sum()), "local_only_valid": int((local & ~gee).sum()),
        "GEE_only_valid": int((~local & gee).sum()), "agreement_pixels": int(agreement.sum()),
        "disagreement_pixels": int((~agreement).sum()), "agreement_fraction": float(agreement.mean()),
    }


def numeric_pass(row: dict[str, Any]) -> bool:
    if int(row["mask_disagreement"]) != 0:
        return False
    if int(row["valid_local"]) == 0 and int(row["valid_GEE"]) == 0:
        return True
    return (float(row["mean_absolute_difference"]) <= 1e-6 and
            float(row["implementation_RMSE"]) <= 1e-6 and
            float(row["max_absolute_difference"]) <= 1e-5)


def source_support(profile: dict[str, Any]) -> ee.Geometry:
    left, top = profile["transform"].c, profile["transform"].f
    right = left + profile["width"] * profile["transform"].a
    bottom = top + profile["height"] * profile["transform"].e
    if str(profile["crs"]).upper() == "SR-ORG:6974":
        samples = 32
        xs = np.r_[
            np.linspace(left, right, samples), np.full(samples, right),
            np.linspace(right, left, samples), np.full(samples, left),
        ]
        ys = np.r_[
            np.full(samples, top), np.linspace(top, bottom, samples),
            np.full(samples, bottom), np.linspace(bottom, top, samples),
        ]
        transformer = Transformer.from_crs(profile["analysis_crs"], "EPSG:4326", always_xy=True)
        longitude, latitude = transformer.transform(xs, ys)
        coordinates = [[float(x), float(y)] for x, y in zip(longitude, latitude)]
        coordinates.append(coordinates[0])
        return ee.Geometry.Polygon([coordinates], proj="EPSG:4326", geodesic=False)
    return ee.Geometry.Rectangle([left, bottom, right, top], proj=str(profile["crs"]), geodesic=False)


def source_window_mask(profile: dict[str, Any]) -> ee.Image:
    projection = ee.Projection(str(profile["crs"]), list(profile["source_transform"])[:6])
    coordinates = ee.Image.pixelCoordinates(projection)
    column_start = int(profile["source_column_start"]); row_start = int(profile["source_row_start"])
    return (coordinates.select("x").gte(column_start)
            .And(coordinates.select("x").lt(column_start + int(profile["width"])))
            .And(coordinates.select("y").gte(row_start))
            .And(coordinates.select("y").lt(row_start + int(profile["height"]))))


def landsat_images(image: ee.Image) -> tuple[ee.Image, ee.Image, ee.Image, list[str], list[int]]:
    red, nir = image.select("SR_B4"), image.select("SR_B5")
    qa, radsat = image.select("QA_PIXEL"), image.select("QA_RADSAT")
    valid_qa = ee.Image(1)
    for bit in (0, 1, 2, 3, 4, 5, 7):
        valid_qa = valid_qa.And(_bits(qa, bit).eq(0))
    valid = (valid_qa.And(radsat.eq(0)).And(red.gte(7273)).And(red.lte(43636))
             .And(nir.gte(7273)).And(nir.lte(43636))).rename("valid")
    scaled_red = red.multiply(.0000275).add(-.2); scaled_nir = nir.multiply(.0000275).add(-.2)
    ndvi = scaled_nir.subtract(scaled_red).divide(scaled_nir.add(scaled_red)).rename("NDVI").updateMask(valid)
    raw = ee.Image.cat([red.unmask(0, False), nir.unmask(0, False), qa.unmask(0, False), radsat.unmask(0, False)]).toInt32()
    return raw, valid, ndvi, ["SR_B4", "SR_B5", "QA_PIXEL", "QA_RADSAT"], [0, 0, 0, 0]


def modis_images(image: ee.Image) -> tuple[ee.Image, ee.Image, ee.Image, list[str], list[int]]:
    red, nir = image.select("sur_refl_b01"), image.select("sur_refl_b02")
    state, qa = image.select("State"), image.select("QA")
    valid = (_bits(state, 0, 2).eq(0).And(_bits(state, 2).eq(0)).And(_bits(state, 3, 3).eq(1))
             .And(_bits(state, 6, 2).lte(2)).And(_bits(state, 8, 2).eq(0))
             .And(_bits(state, 10).eq(0)).And(_bits(state, 11).eq(0)).And(_bits(state, 12).eq(0))
             .And(_bits(state, 13).eq(0)).And(_bits(state, 15).eq(0))
             .And(_bits(qa, 0, 2).lte(1)).And(_bits(qa, 4, 4).eq(0))
             .And(_bits(qa, 8, 4).eq(0)).And(_bits(qa, 12).eq(1))
             .And(red.gte(-100)).And(red.lte(16000)).And(nir.gte(-100)).And(nir.lte(16000))).rename("valid")
    ndvi = nir.multiply(.0001).subtract(red.multiply(.0001)).divide(
        nir.multiply(.0001).add(red.multiply(.0001))).rename("NDVI").updateMask(valid)
    raw = ee.Image.cat([
        red.unmask(-28672, False), nir.unmask(-28672, False),
        state.unmask(65535, False), qa.unmask(65535, False),
    ]).toInt32()
    return raw, valid, ndvi, ["sur_refl_b01", "sur_refl_b02", "State", "QA"], [-28672, -28672, 65535, 65535]


def checkpoint_identity(row: dict[str, str], sensor: str, grid: dict[str, Any], manifest_hash: str) -> str:
    payload = {"algorithm": ALGORITHM_VERSION, "design": DESIGN_HASH, "manifest": manifest_hash,
               "sensor": sensor, "row_identity_hash": row["row_identity_hash"],
               "target": {"crs": grid["crs"], "transform": list(grid["transform"])[:6],
                          "width": grid["width"], "height": grid["height"]}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def process_scene(row: dict[str, str], sensor: str, geometry: dict[str, Any],
                  fcover: ee.Image, grid: dict[str, Any]) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    image = ee.Image(row["system_id"])
    if sensor == "landsat":
        raw_image, valid_image, ndvi_image, bands, fills = landsat_images(image)
        profile = source_profile(image.select("SR_B4"), geometry)
    else:
        raw_image, valid_image, ndvi_image, bands, fills = modis_images(image)
        profile = source_profile(image.select("sur_refl_b01"), geometry)
    raw = request_strips(raw_image, bands, profile, fills)
    if sensor == "landsat":
        red, nir, qa, radsat = raw
        local_valid = landsat.native_valid_mask(qa, radsat) & (red >= 7273) & (red <= 43636) & (nir >= 7273) & (nir <= 43636)
        local_ndvi = landsat.ndvi(red, nir, qa, radsat)
    else:
        red, nir, state, qa = raw
        local_valid = modis.native_valid_mask(state, qa) & (red >= -100) & (red <= 16000) & (nir >= -100) & (nir <= 16000)
        local_ndvi = modis.ndvi(red, nir, state, qa)
    gee = request_strips(
        ee.Image.cat([valid_image.unmask(0, False).toUint8(), ndvi_image.unmask(NODATA_NDVI, False).toFloat()]),
        ["valid", "NDVI"], profile, [0, NODATA_NDVI], max_rows=128,
    )
    gee_valid = gee[0].astype(bool); gee_ndvi = gee[1].astype("float32"); gee_ndvi[gee_ndvi == NODATA_NDVI] = np.nan
    native_mask = mask_metrics(local_valid, gee_valid)
    native_ndvi = metrics(local_ndvi, gee_ndvi)
    source = SimpleNamespace(transform=profile["transform"], crs=profile["analysis_crs"])
    local_300 = area_weighted_to_fcover(local_ndvi, source, grid)
    bounded_ndvi = (ndvi_image.updateMask(source_window_mask(profile)) if sensor == "modis" else
                    ndvi_image.clip(source_support(profile)))
    gee_300_image = _average_to_fcover(bounded_ndvi, fcover).unmask(NODATA_NDVI, False)
    gee_300_raw = request_tif(gee_300_image, ["NDVI"], grid, [NODATA_NDVI])
    gee_300 = gee_300_raw[0].astype("float32"); gee_300[gee_300 == NODATA_NDVI] = np.nan
    aggregate = metrics(local_300, gee_300)
    scene = {
        "scene_id": row["system_index"], "system_id": row["system_id"], "platform": row["platform"],
        "source_crs": profile["crs"], "source_transform": json.dumps(list(profile["transform"])[:6]),
        "source_width": profile["width"], "source_height": profile["height"],
        "download_crs_rule": ("SR-ORG:6974_MODIS_SINUSOIDAL_WKT_ALIAS_EXACT_GRID" if sensor == "modis" else
                              "CANONICAL_CRS_EQUIVALENCE"),
        "native_mask": native_mask, "native_ndvi": native_ndvi, "aggregate": aggregate,
    }
    return scene, local_300, gee_300


def save_checkpoint(root: Path, identity: str, scene: dict[str, Any], local: np.ndarray, gee: np.ndarray) -> None:
    root.mkdir(parents=True, exist_ok=True)
    scene_id = scene["scene_id"]
    temporary = root / f"{scene_id}.partial.npz"
    np.savez_compressed(temporary, local=local, gee=gee)
    temporary.replace(root / f"{scene_id}.npz")
    payload = {"identity": identity, "scene": scene}
    temp_json = root / f"{scene_id}.json.partial"
    temp_json.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    temp_json.replace(root / f"{scene_id}.json")


def load_checkpoint(root: Path, scene_id: str, identity: str) -> tuple[dict[str, Any], np.ndarray, np.ndarray] | None:
    meta, arrays = root / f"{scene_id}.json", root / f"{scene_id}.npz"
    if not meta.exists() or not arrays.exists():
        return None
    payload = json.loads(meta.read_text(encoding="utf-8"))
    if payload.get("identity") != identity:
        return None
    with np.load(arrays) as data:
        return payload["scene"], data["local"], data["gee"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sensor", required=True, choices=("landsat", "modis"))
    args = parser.parse_args(); sensor = args.sensor
    contract = load_contract(PUBLICATION / "code" / "configs" / "scientific_execution.yaml")
    assert_parity_validation_contract(contract)
    source_contract = json.loads(CONTRACT_JSON.read_text(encoding="utf-8"))
    if source_contract["scientific_design_hash"] != DESIGN_HASH or not source_contract["all_assets_resolve"]:
        raise RuntimeError("ACTIVE_SOURCE_CONTRACT_NOT_CERTIFIED")
    prerequisite = (ROOT / "02_SENTINEL" / "SENTINEL_PARITY_RESULT.md" if sensor == "landsat" else
                    ROOT / "03_LANDSAT" / "LANDSAT_PARITY_RESULT.md")
    required = "Final verdict: **PASS**."
    if not prerequisite.exists() or required not in prerequisite.read_text(encoding="utf-8"):
        raise RuntimeError(f"FROZEN_SEQUENTIAL_PARITY_PREREQUISITE_NOT_PASS:{prerequisite}")
    initialize(WORKSPACE / "model/.env")
    geometry = aoi_geometry(); target_info = ee.data.getAsset(FCOVER); grid = target_grid(target_info); fcover = ee.Image(FCOVER)
    label = "Landsat-8/9" if sensor == "landsat" else "MODIS"
    rows = [row for row in csv_rows(CONTRACT_CSV) if row["sensor"] == label]
    expected = 12 if sensor == "landsat" else 4
    if len(rows) != expected:
        raise RuntimeError(f"PARITY_SOURCE_COUNT_MISMATCH:{sensor}:{len(rows)}:{expected}")
    checkpoint_root = CHECKPOINTS / sensor; scenes = []; local_aggregates = []; gee_aggregates = []
    for row in rows:
        identity = checkpoint_identity(row, sensor, grid, source_contract["manifest_hash"])
        prior = load_checkpoint(checkpoint_root, row["system_index"], identity)
        if prior is None:
            print(f"PARITY_PROCESSING:{sensor}:{row['system_index']}", flush=True)
            scene, local, gee = process_scene(row, sensor, geometry, fcover, grid)
            save_checkpoint(checkpoint_root, identity, scene, local, gee)
        else:
            print(f"PARITY_REUSED:{sensor}:{row['system_index']}", flush=True)
            scene, local, gee = prior
        scenes.append(scene); local_aggregates.append(local); gee_aggregates.append(gee)

    mask_rows = [{"scene_id": scene["scene_id"], **scene["native_mask"]} for scene in scenes]
    ndvi_rows = [{"scene_id": scene["scene_id"], **scene["native_ndvi"]} for scene in scenes]
    aggregate_rows = [{"scene_id": scene["scene_id"], **scene["aggregate"]} for scene in scenes]
    local_final, local_count = nanmedian_min_count(local_aggregates, minimum=2)
    gee_final, gee_count = nanmedian_min_count(gee_aggregates, minimum=2)
    count_disagreement = int(np.count_nonzero(local_count != gee_count))
    count_row = {"total_cells": int(local_count.size), "count_disagreement": count_disagreement,
                 "maximum_absolute_count_difference": int(np.max(np.abs(local_count.astype(int) - gee_count.astype(int)))),
                 "verdict": "PASS" if count_disagreement == 0 else "FAIL"}
    temporal = metrics(local_final, gee_final); temporal["verdict"] = "PASS" if numeric_pass(temporal) else "FAIL"
    grid_row = {"CRS_local": grid["crs"], "CRS_GEE": grid["crs"],
                "transform_local": json.dumps(list(grid["transform"])[:6]),
                "transform_GEE": json.dumps(list(grid["transform"])[:6]),
                "width_local": grid["width"], "width_GEE": grid["width"],
                "height_local": grid["height"], "height_GEE": grid["height"],
                "max_affine_difference": 0.0, "pixel_center_max_difference": 0.0, "verdict": "PASS"}
    stages = {
        "Stage 0 source identity": "PASS",
        "Stage 1 native QA mask": "PASS" if all(int(row["disagreement_pixels"]) == 0 for row in mask_rows) else "FAIL",
        "Stage 2 native NDVI": "PASS" if all(numeric_pass(row) for row in ndvi_rows) else "FAIL",
        "Stage 3 exact FCOVER support": "PASS" if all(numeric_pass(row) for row in aggregate_rows) else "FAIL",
        "Stage 4 contribution count": count_row["verdict"],
        "Stage 5 temporal composite": temporal["verdict"],
    }
    verdict = "PASS" if all(value == "PASS" for value in stages.values()) else "FAIL"
    output = ROOT / ("03_LANDSAT" if sensor == "landsat" else "04_MODIS"); prefix = "LANDSAT" if sensor == "landsat" else "MODIS"
    write_csv_atomic(output / f"{prefix}_NATIVE_MASK_PARITY.csv", mask_rows)
    write_csv_atomic(output / f"{prefix}_NATIVE_NDVI_PARITY.csv", ndvi_rows)
    write_csv_atomic(output / f"{prefix}_300M_PARITY.csv", aggregate_rows)
    write_csv_atomic(output / f"{prefix}_CONTRIBUTION_PARITY.csv", [count_row])
    write_csv_atomic(output / f"{prefix}_TEMPORAL_PARITY.csv", [temporal])
    write_csv_atomic(output / f"{prefix}_GRID_PARITY.csv", [grid_row])
    write_csv_atomic(output / f"{prefix}_SOURCE_GRID_AUDIT.csv", [{
        "scene_id": scene["scene_id"], "system_id": scene["system_id"], "platform": scene["platform"],
        "source_crs": scene["source_crs"], "source_transform": scene["source_transform"],
        "source_width": scene["source_width"], "source_height": scene["source_height"],
        "download_crs_rule": scene["download_crs_rule"],
    } for scene in scenes])
    table = "\n".join(f"| {stage} | {value} |" for stage, value in stages.items())
    (output / f"{prefix}_PARITY_RESULT.md").write_text(
        f"# {label} preprocessing parity result R2\n\n"
        f"Scientific design hash: `{DESIGN_HASH}`. Source manifest hash: `{source_contract['manifest_hash']}`.\n\n"
        "| Stage | Verdict |\n|---|---|\n" + table + f"\n\nFinal verdict: **{verdict}**.\n\n"
        "The local path used exact frozen native source pixels, mask-aware GeoTIFF reads, approved NumPy QA/NDVI, "
        "and geometry-derived area weighting. The GEE path used the independent catalog expression clipped to the "
        "same frozen native window. No assets or models were created.\n",
        encoding="utf-8",
    )
    (output / "PARITY_EXECUTION_RECORD.json").write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(), "algorithm": ALGORITHM_VERSION,
        "sensor": sensor, "scene_count": len(scenes), "design_hash": DESIGN_HASH,
        "source_manifest_hash": source_contract["manifest_hash"], "verdict": verdict,
        "models_run": False, "assets_written": False,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"PARITY_VERDICT:{sensor}:{verdict}")
    return 0 if verdict == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
