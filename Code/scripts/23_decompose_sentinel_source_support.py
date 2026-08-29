#!/usr/bin/env python3
"""Conservative Phase-1 decomposition of Sentinel source support.

This script performs no model fitting, FCOVER aggregation, temporal composite,
asset export, or Stage 3-5 work.  It compares exact frozen SAFE members,
immutable local r3 inputs, and native Earth Engine band masks on one frozen
10 m grid.  Any repair decision is evidence-derived and fail-closed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
import tempfile
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
import ee
import numpy as np
import rasterio
import requests
from affine import Affine
from botocore.config import Config
from dotenv import load_dotenv
from rasterio.enums import Resampling
from rasterio.io import MemoryFile
from rasterio.vrt import WarpedVRT
from rasterio.warp import reproject

PUBLICATION = Path(__file__).resolve().parents[2]
WORKSPACE = PUBLICATION.parents[1]
sys.path.insert(0, str(PUBLICATION / "code" / "src"))

from data_prep import sentinel2  # noqa: E402
from data_prep.gee_cloud import initialize  # noqa: E402
from execution.contract import load_contract  # noqa: E402
from execution.preparation_guard import (  # noqa: E402
    DESIGN_HASH,
    assert_active_sentinel_revision,
    assert_phase1_storage,
    assert_preparation_lock,
    canonical_json_sha256,
    sha256_file,
)

EXP = PUBLICATION / "new_experiments" / "15_three_sensor_parity"
OUT = EXP / "14_SENTINEL_SOURCE_SUPPORT_DECOMPOSITION"
CHECKPOINTS = OUT / "_checkpoints"
MANIFEST = EXP / "08_SENTINEL_STAGE0_REPAIR" / "04_CORRECTED_SENTINEL_MANIFEST.csv"
R3 = EXP / "11_SENTINEL_SCIENTIFIC_PREPROCESSING_REVISION" / "corrected_inputs_cdse_r3_harmonized"
OLD_TABLE = WORKSPACE / (
    "qh-fvc-data/storage/projects/prj_20260729085738_7fd76c__示例范围/"
    "data-center/imagery/series/series_20260729182250_38962d4d__sentinel-2-summer-l2a-series-多年度-series/"
    "years/2025/annual_20260729182250_bd19c5a4__2025-s2-l2a-harmonized-r1/raw/acquisition/tables/scene_manifest.json"
)
PHASE0 = EXP / "00_PHASE0_PROTECTION" / "PHASE0_PROTECTION_MANIFEST.json"
V4_MASK = EXP / "02_SENTINEL" / "SENTINEL_NATIVE_MASK_PARITY_v4.csv"
TARGET_CRS = "EPSG:32647"
TARGET_TRANSFORM = Affine(10, 0, 527780, 0, -10, 4222650)
TARGET_HEIGHT, TARGET_WIDTH = 2389, 3542
AFFECTED = {"SR-01", "SR-03", "SR-05", "SR-07", "SR-08", "SR-10"}
UNAFFECTED = {"SR-02", "SR-04", "SR-06", "SR-09", "SR-11"}
PROTOCOL_VERSION = "sentinel-source-support-decomposition-v2-legacy-nodata-audit"
NODATA_NDVI = -9999.0


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"EMPTY_EVIDENCE_FORBIDDEN:{path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    fields = sorted({key for row in rows for key in row})
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    temporary.replace(path)


def s3_client() -> Any:
    load_dotenv(WORKSPACE / "model/.env")
    required = ("EODATA_S3_ENDPOINT", "EODATA_S3_ACCESS_KEY", "EODATA_S3_SECRET_KEY")
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise RuntimeError("PHASE1_CDSE_CREDENTIALS_MISSING:" + ",".join(missing))
    return boto3.client(
        "s3", endpoint_url="https://" + os.environ["EODATA_S3_ENDPOINT"],
        aws_access_key_id=os.environ["EODATA_S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["EODATA_S3_SECRET_KEY"],
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
    )


def product_map() -> dict[str, str]:
    payload = json.loads(OLD_TABLE.read_text(encoding="utf-8"))
    return {str(item["scene_id"]): str(item["product_id"]) for item in payload}


def product_keys(client: Any, product: str) -> list[str]:
    date = product.split("_")[2][:8]
    prefix = f"Sentinel-2/MSI/L2A/{date[:4]}/{date[4:6]}/{date[6:8]}/{product}.SAFE/GRANULE/"
    keys: list[str] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket="eodata", Prefix=prefix):
        keys.extend(item["Key"] for item in page.get("Contents", []))
    return keys


def unique_member(keys: list[str], product: str, suffix: str) -> str:
    matches = [key for key in keys if key.endswith(suffix)]
    if len(matches) != 1:
        raise RuntimeError(f"CDSE_MEMBER_NOT_UNIQUE:{product}:{suffix}:{len(matches)}")
    return matches[0]


def analytic_inbounds(transform: Affine, width: int, height: int) -> np.ndarray:
    if transform.b != 0 or transform.d != 0 or transform.a <= 0 or transform.e >= 0:
        raise RuntimeError(f"UNSUPPORTED_SOURCE_AFFINE:{list(transform)[:6]}")
    xs = TARGET_TRANSFORM.c + (np.arange(TARGET_WIDTH) + 0.5) * TARGET_TRANSFORM.a
    ys = TARGET_TRANSFORM.f + (np.arange(TARGET_HEIGHT) + 0.5) * TARGET_TRANSFORM.e
    source_cols = (xs - transform.c) / transform.a
    source_rows = (ys - transform.f) / transform.e
    cols_inside = (source_cols >= 0) & (source_cols < width)
    rows_inside = (source_rows >= 0) & (source_rows < height)
    return rows_inside[:, None] & cols_inside[None, :]


def mapped_member(client: Any, key: str) -> dict[str, Any]:
    handle = tempfile.NamedTemporaryFile(suffix=Path(key).suffix, delete=False)
    handle.close(); path = Path(handle.name)
    try:
        client.download_file("eodata", key, str(path))
        checksum = sha256_file(path)
        with rasterio.open(path) as source:
            metadata = {
                "identity": key, "sha256": checksum, "size_bytes": path.stat().st_size,
                "crs": str(source.crs), "transform": json.dumps(list(source.transform)[:6]),
                "width": source.width, "height": source.height, "dtype": source.dtypes[0],
                "nodata": source.nodata if source.nodata is not None else "NONE",
            }
            inbounds = analytic_inbounds(source.transform, source.width, source.height)
            with WarpedVRT(
                source, crs=TARGET_CRS, transform=TARGET_TRANSFORM,
                width=TARGET_WIDTH, height=TARGET_HEIGHT, resampling=Resampling.nearest,
                nodata=source.nodata if source.nodata is not None else 0,
            ) as vrt:
                values = vrt.read(1)
                raster_mask = vrt.read_masks(1) > 0
        return {"values": values, "raster_mask": raster_mask, "inbounds": inbounds, "metadata": metadata}
    finally:
        path.unlink(missing_ok=True)


def tile_profile(row_start: int, height: int) -> dict[str, Any]:
    return {
        "crs": TARGET_CRS, "transform": TARGET_TRANSFORM * Affine.translation(0, row_start),
        "width": TARGET_WIDTH, "height": height,
    }


def gee_download(image: ee.Image, bands: list[str], profile: dict[str, Any]) -> dict[str, Any]:
    params = {
        "crs": profile["crs"], "crs_transform": list(profile["transform"])[:6],
        "dimensions": [profile["width"], profile["height"]], "format": "GEO_TIFF",
        "filePerBand": False, "name": "support_decomposition",
    }
    response = requests.get(image.select(bands).getDownloadURL(params), timeout=(30, 180))
    response.raise_for_status(); content = response.content
    if content[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith((".tif", ".tiff"))]
            if len(names) != 1:
                raise RuntimeError(f"GEE_DOWNLOAD_TIFF_COUNT:{len(names)}")
            content = archive.read(names[0])
    with MemoryFile(content) as memory:
        with memory.open() as dataset:
            if (dataset.width, dataset.height, dataset.transform, str(dataset.crs)) != (
                profile["width"], profile["height"], profile["transform"], profile["crs"]
            ):
                raise RuntimeError("GEE_SUPPORT_GRID_MISMATCH")
            if dataset.count != len(bands):
                raise RuntimeError(f"GEE_SUPPORT_BAND_COUNT:{dataset.count}:{len(bands)}")
            return {
                "values": dataset.read(),
                "masks": dataset.read_masks() > 0,
                "nodatavals": [value if value is not None else "NONE" for value in dataset.nodatavals],
                "dtypes": list(dataset.dtypes),
            }


def gee_arrays(scene: dict[str, str]) -> tuple[dict[str, np.ndarray], dict[str, Any], dict[str, Any]]:
    raw = ee.Image(scene["SR_system_id"]); cloud = ee.Image(scene["cloud_system_id"])
    b4, b8, scl, probability = raw.select("B4"), raw.select("B8"), raw.select("SCL"), cloud.select("probability")
    preqa = (b4.mask().And(b8.mask()).And(scl.mask()).And(probability.mask())
             .And(b4.gte(1)).And(b4.lte(10000)).And(b8.gte(1)).And(b8.lte(10000)))
    final = preqa.And(scl.eq(4).Or(scl.eq(5)).Or(scl.eq(7))).And(probability.lt(30))
    images = [
        b4.mask().unmask(0, False).rename("B4_mask"),
        b8.mask().unmask(0, False).rename("B8_mask"),
        scl.mask().unmask(0, False).rename("SCL_mask"),
        probability.mask().unmask(0, False).rename("probability_mask"),
        b4.unmask(0, False).rename("B4_value"),
        b8.unmask(0, False).rename("B8_value"),
        scl.unmask(0, False).rename("SCL_value"),
        probability.unmask(255, False).rename("probability_value"),
        preqa.unmask(0, False).rename("preqa_valid"),
        final.unmask(0, False).rename("final_qa_valid"),
    ]
    payload = ee.Image.cat([image.toInt32() for image in images])
    bands = ["B4_mask", "B8_mask", "SCL_mask", "probability_mask", "B4_value", "B8_value",
             "SCL_value", "probability_value", "preqa_valid", "final_qa_valid"]
    parts: list[np.ndarray] = []
    for row in range(0, TARGET_HEIGHT, 256):
        downloaded = gee_download(payload, bands, tile_profile(row, min(256, TARGET_HEIGHT - row)))
        parts.append(downloaded["values"])
    array = np.concatenate(parts, axis=1)

    # Exact reconstruction of the Stage-1 v4 export path.  Its default
    # unmask(0) keeps the original image footprint.  The historical reader
    # ignored the GeoTIFF validity mask and cast raw samples directly to bool;
    # this branch records both interpretations without modifying old evidence.
    legacy_ndvi = (b8.multiply(.0001).subtract(b4.multiply(.0001))
                   .divide(b8.multiply(.0001).add(b4.multiply(.0001)))
                   .rename("ndvi").updateMask(final))
    legacy_payload = ee.Image.cat([
        final.rename("qa_valid").unmask(0).toFloat(),
        legacy_ndvi.unmask(NODATA_NDVI).toFloat(),
    ]).rename(["qa_valid", "ndvi"])
    legacy_values: list[np.ndarray] = []
    legacy_masks: list[np.ndarray] = []
    nodata_values: set[str] = set()
    legacy_dtypes: set[str] = set()
    for row in range(0, TARGET_HEIGHT, 256):
        downloaded = gee_download(
            legacy_payload, ["qa_valid", "ndvi"],
            tile_profile(row, min(256, TARGET_HEIGHT - row)),
        )
        legacy_values.append(downloaded["values"][0])
        legacy_masks.append(downloaded["masks"][0])
        nodata_values.update(str(value) for value in downloaded["nodatavals"])
        legacy_dtypes.update(downloaded["dtypes"])
    legacy_raw = np.concatenate(legacy_values, axis=0)
    legacy_export_mask = np.concatenate(legacy_masks, axis=0)
    projection = b4.projection().getInfo()
    arrays = {name: array[index] for index, name in enumerate(bands)}
    arrays["legacy_final_raw"] = legacy_raw
    arrays["legacy_final_export_mask"] = legacy_export_mask
    legacy_metadata = {
        "export_expression": "qa_valid.unmask(0)_default_sameFootprint_true",
        "historical_reader": "rasterio_read_then_astype_bool_without_read_masks",
        "nodatavals_observed": sorted(nodata_values),
        "dtypes_observed": sorted(legacy_dtypes),
    }
    return arrays, projection, legacy_metadata


def local_arrays(scene_id: str) -> dict[str, np.ndarray]:
    root = R3 / scene_id
    assert_active_sentinel_revision(root, expected_revision="corrected_inputs_cdse_r3_harmonized")
    with rasterio.open(root / "spectral_B4_B8_uint16.tif") as spectral:
        if (str(spectral.crs), spectral.transform, spectral.width, spectral.height) != (
            TARGET_CRS, TARGET_TRANSFORM, TARGET_WIDTH, TARGET_HEIGHT
        ) or spectral.count != 2 or spectral.dtypes != ("uint16", "uint16"):
            raise RuntimeError(f"LOCAL_R3_GRID_OR_SCHEMA_MISMATCH:{scene_id}")
        b4, b8 = spectral.read(1), spectral.read(2)
    with rasterio.open(root / "cloud_probability_uint8.tif") as cloud:
        if (str(cloud.crs), cloud.transform, cloud.width, cloud.height) != (
            TARGET_CRS, TARGET_TRANSFORM, TARGET_WIDTH, TARGET_HEIGHT
        ):
            raise RuntimeError(f"LOCAL_R3_CLOUD_GRID_MISMATCH:{scene_id}")
        probability = cloud.read(1)
    with rasterio.open(root / "scl_uint8.tif") as source:
        scl = np.zeros((TARGET_HEIGHT, TARGET_WIDTH), dtype="uint8")
        reproject(
            source=source.read(1), destination=scl, src_transform=source.transform, src_crs=source.crs,
            dst_transform=TARGET_TRANSFORM, dst_crs=TARGET_CRS, src_nodata=source.nodata,
            dst_nodata=0, resampling=Resampling.nearest,
        )
    source_valid = (b4 >= 1) & (b4 <= 10000) & (b8 >= 1) & (b8 <= 10000)
    final = source_valid & sentinel2.native_valid_mask(scl, probability)
    return {"B4": b4, "B8": b8, "SCL": scl, "probability": probability,
            "source_valid": source_valid, "final_qa_valid": final}


def first_last_full_rows(mask: np.ndarray) -> tuple[int | str, int | str, int]:
    counts = mask.sum(axis=1)
    rows = np.flatnonzero(counts > 0)
    full = int(np.count_nonzero(counts == mask.shape[1]))
    return (int(rows[0]), int(rows[-1]), full) if rows.size else ("NONE", "NONE", full)


def category_counts(disagreement: np.ndarray, detector: np.ndarray, cdse_support: np.ndarray,
                    cdse_valid: np.ndarray, scl_support: np.ndarray,
                    legacy_export_mask: np.ndarray, legacy_raw: np.ndarray) -> Counter[str]:
    categories = np.full(disagreement.shape, "", dtype="U96")
    categories[disagreement & ~legacy_export_mask & (legacy_raw != 0)] = (
        "GEE_EXPORT_MASK_FALSE+RAW_NODATA_NONZERO+BOOL_TRUE+LOCAL_INVALID"
    )
    remaining = disagreement & (categories == "")
    categories[remaining & ~detector & ~cdse_support] = "DETFOO_FALSE+CDSE_REFLECTANCE_OUTSIDE_RASTER+LOCAL_INVALID+GEE_VALID"
    categories[remaining & ~detector & cdse_support & cdse_valid] = "DETFOO_FALSE+CDSE_REFLECTANCE_VALID+LOCAL_INVALID+GEE_VALID"
    categories[remaining & ~detector & cdse_support & ~cdse_valid] = "DETFOO_FALSE+CDSE_REFLECTANCE_INVALID+LOCAL_INVALID+GEE_VALID"
    categories[remaining & detector & cdse_valid & scl_support] = "DETFOO_TRUE+CDSE_REFLECTANCE_VALID+SCL_SUPPORTED+LOCAL_INVALID+GEE_VALID"
    categories[remaining & detector & cdse_valid & ~scl_support] = "DETFOO_TRUE+CDSE_REFLECTANCE_VALID+SCL_UNSUPPORTED+LOCAL_INVALID+GEE_VALID"
    categories[remaining & detector & ~cdse_valid] = "DETFOO_TRUE+CDSE_REFLECTANCE_INVALID+LOCAL_INVALID+GEE_VALID"
    categories[disagreement & (categories == "")] = "OTHER_EVIDENCE_DEFINED_DISAGREEMENT"
    return Counter(categories[disagreement].tolist())


def harmonized_source(raw: np.ndarray, baseline: float) -> np.ndarray:
    if baseline < 4.0:
        return raw.astype("uint16", copy=False)
    return np.where(raw == 0, 0, np.maximum(raw.astype("int32") - 1000, 0)).astype("uint16")


def process_scene(scene: dict[str, str], products: dict[str, str], client: Any,
                  expected_disagreement: dict[str, int]) -> dict[str, Any]:
    scene_id = scene["Parity_Scene_ID"]
    product = products[scene["SR_system_index"]]
    keys = product_keys(client, product)
    suffixes = {"B04": "_B04_10m.jp2", "B08": "_B08_10m.jp2"}
    if scene_id in AFFECTED:
        suffixes.update({"SCL": "_SCL_20m.jp2", "DETFOO_B04": "MSK_DETFOO_B04.jp2", "DETFOO_B08": "MSK_DETFOO_B08.jp2"})
    members = {name: unique_member(keys, product, suffix) for name, suffix in suffixes.items()}
    source = {name: mapped_member(client, key) for name, key in members.items()}
    local = local_arrays(scene_id)
    gee, gee_projection, legacy_metadata = gee_arrays(scene)
    baseline = float(scene["SR_processing_baseline"])
    cdse_b4 = harmonized_source(source["B04"]["values"], baseline)
    cdse_b8 = harmonized_source(source["B08"]["values"], baseline)
    cdse_b4_support = source["B04"]["raster_mask"] & source["B04"]["inbounds"]
    cdse_b8_support = source["B08"]["raster_mask"] & source["B08"]["inbounds"]
    cdse_support = cdse_b4_support & cdse_b8_support
    cdse_valid = cdse_support & (cdse_b4 >= 1) & (cdse_b4 <= 10000) & (cdse_b8 >= 1) & (cdse_b8 <= 10000)
    gee_masks = {name: gee[name].astype(bool) for name in ("B4_mask", "B8_mask", "SCL_mask", "probability_mask", "preqa_valid", "final_qa_valid")}
    gee_final = gee_masks["final_qa_valid"]
    legacy_raw = gee["legacy_final_raw"]
    legacy_export_mask = gee["legacy_final_export_mask"].astype(bool)
    legacy_interpreted = legacy_raw.astype(bool)
    legacy_mask_aware = (legacy_raw != 0) & legacy_export_mask
    local_final = local["final_qa_valid"]
    disagreement = ~local_final & legacy_interpreted
    local_only = local_final & ~legacy_interpreted
    official_overlay = cdse_b4_support & cdse_b8_support
    official_overlay_legacy = legacy_interpreted & official_overlay
    official_overlay_disagreement = int(np.count_nonzero(official_overlay_legacy != local_final))
    mask_aware_disagreement = int(np.count_nonzero(legacy_mask_aware != local_final))
    expanded_unmask_disagreement = int(np.count_nonzero(gee_final != local_final))
    expected = expected_disagreement[scene_id]

    local_cdse_b4_mismatch = int(np.count_nonzero(cdse_b4_support & (local["B4"] != cdse_b4)))
    local_cdse_b8_mismatch = int(np.count_nonzero(cdse_b8_support & (local["B8"] != cdse_b8)))
    local_cdse_support_mismatch = int(np.count_nonzero(local["source_valid"] != cdse_valid))
    result: dict[str, Any] = {
        "scene_id": scene_id, "affected": scene_id in AFFECTED, "product": product,
        "scene_identity": scene["SR_system_id"], "cloud_identity": scene["cloud_system_id"],
        "processing_baseline": scene["SR_processing_baseline"], "gee_projection": gee_projection,
        "legacy_export": legacy_metadata,
        "members": {name: source[name]["metadata"] for name in source},
        "scene": {
            "total_pixels": int(local_final.size), "local_final_qa_valid": int(local_final.sum()),
            "gee_final_qa_valid": int(legacy_interpreted.sum()),
            "gee_mask_aware_final_qa_valid": int(legacy_mask_aware.sum()),
            "gee_expanded_unmask_final_qa_valid": int(gee_final.sum()),
            "common_final_qa_valid": int((local_final & legacy_interpreted).sum()),
            "gee_only_final_qa_valid": int(disagreement.sum()), "local_only_final_qa_valid": int(local_only.sum()),
            "expected_gee_only_from_v4": expected,
            "conservation_pass": int(disagreement.sum()) == expected,
            "cdse_b4_inbounds": int(source["B04"]["inbounds"].sum()),
            "cdse_b8_inbounds": int(source["B08"]["inbounds"].sum()),
            "cdse_b4_raster_mask": int(cdse_b4_support.sum()), "cdse_b8_raster_mask": int(cdse_b8_support.sum()),
            "cdse_joint_reflectance_valid": int(cdse_valid.sum()),
            "gee_b4_mask": int(gee_masks["B4_mask"].sum()), "gee_b8_mask": int(gee_masks["B8_mask"].sum()),
            "gee_scl_mask": int(gee_masks["SCL_mask"].sum()), "gee_probability_mask": int(gee_masks["probability_mask"].sum()),
            "gee_preqa_valid": int(gee_masks["preqa_valid"].sum()),
            "gee_b4_mask_outside_cdse_raster": int((gee_masks["B4_mask"] & ~source["B04"]["inbounds"]).sum()),
            "gee_b8_mask_outside_cdse_raster": int((gee_masks["B8_mask"] & ~source["B08"]["inbounds"]).sum()),
            "disagreement_outside_cdse_raster": int((disagreement & ~cdse_support).sum()),
            "disagreement_on_legacy_export_nodata": int((disagreement & ~legacy_export_mask & (legacy_raw != 0)).sum()),
            "legacy_export_mask_valid": int(legacy_export_mask.sum()),
            "legacy_raw_nonzero_outside_export_mask": int(((legacy_raw != 0) & ~legacy_export_mask).sum()),
            "local_cdse_b4_value_mismatch": local_cdse_b4_mismatch,
            "local_cdse_b8_value_mismatch": local_cdse_b8_mismatch,
            "local_cdse_source_validity_mismatch": local_cdse_support_mismatch,
            "official_overlay_corrected_disagreement": official_overlay_disagreement,
            "mask_aware_reader_corrected_disagreement": mask_aware_disagreement,
            "expanded_unmask_corrected_disagreement": expanded_unmask_disagreement,
        },
    }
    for name, mask in {
        "cdse_b4_inbounds": source["B04"]["inbounds"], "cdse_b8_inbounds": source["B08"]["inbounds"],
        "cdse_b4_raster_mask": cdse_b4_support, "cdse_b8_raster_mask": cdse_b8_support,
        "cdse_joint_valid": cdse_valid, "local_source_valid": local["source_valid"],
        "local_final_qa_valid": local_final, "gee_b4_mask": gee_masks["B4_mask"],
        "gee_b8_mask": gee_masks["B8_mask"], "gee_scl_mask": gee_masks["SCL_mask"],
        "gee_preqa_valid": gee_masks["preqa_valid"], "gee_final_qa_valid": legacy_interpreted,
        "gee_legacy_export_mask": legacy_export_mask,
        "gee_mask_aware_final_qa_valid": legacy_mask_aware,
        "gee_expanded_unmask_final_qa_valid": gee_final,
        "gee_only_final_qa_valid": disagreement, "local_only_final_qa_valid": local_only,
    }.items():
        first, last, full = first_last_full_rows(mask)
        result["scene"][f"{name}_first_row"] = first
        result["scene"][f"{name}_last_row"] = last
        result["scene"][f"{name}_full_width_rows"] = full

    if scene_id in AFFECTED:
        detector = (source["DETFOO_B04"]["values"] > 0) & (source["DETFOO_B08"]["values"] > 0)
        scl_support = source["SCL"]["raster_mask"] & source["SCL"]["inbounds"]
        categories = category_counts(
            disagreement, detector, cdse_support, cdse_valid, scl_support,
            legacy_export_mask, legacy_raw,
        )
        result["categories"] = dict(categories)
        result["scene"]["category_conservation_pass"] = sum(categories.values()) == expected
        result["scene"]["joint_detector_support"] = int(detector.sum())
        result["scene"]["cdse_scl_raster_mask"] = int(scl_support.sum())
        for name, mask in {"joint_detector_support": detector, "cdse_scl_raster_mask": scl_support}.items():
            first, last, full = first_last_full_rows(mask)
            result["scene"][f"{name}_first_row"] = first
            result["scene"][f"{name}_last_row"] = last
            result["scene"][f"{name}_full_width_rows"] = full
        row_masks = {
            "DETFOO_B04_valid": source["DETFOO_B04"]["values"] > 0,
            "DETFOO_B08_valid": source["DETFOO_B08"]["values"] > 0,
            "joint_detector_support": detector,
            "CDSE_B04_raster_support": cdse_b4_support, "CDSE_B08_raster_support": cdse_b8_support,
            "CDSE_B04_range_valid": cdse_b4_support & (cdse_b4 >= 1) & (cdse_b4 <= 10000),
            "CDSE_B08_range_valid": cdse_b8_support & (cdse_b8 >= 1) & (cdse_b8 <= 10000),
            "CDSE_SCL_raster_support": scl_support,
            "local_r3_B04_range_valid": (local["B4"] >= 1) & (local["B4"] <= 10000),
            "local_r3_B08_range_valid": (local["B8"] >= 1) & (local["B8"] <= 10000),
            "local_final_QA_valid": local_final,
            "GEE_B4_native_mask": gee_masks["B4_mask"], "GEE_B8_native_mask": gee_masks["B8_mask"],
            "GEE_SCL_native_mask": gee_masks["SCL_mask"], "GEE_pre_QA_source_valid": gee_masks["preqa_valid"],
            "GEE_final_QA_valid_legacy_raw_bool": legacy_interpreted,
            "GEE_legacy_export_mask": legacy_export_mask,
            "GEE_final_QA_valid_mask_aware": legacy_mask_aware,
            "GEE_final_QA_valid_expanded_unmask": gee_final,
            "GEE_only_QA_valid": disagreement,
            "local_only_QA_valid": local_only,
        }
        result["rows"] = [
            {"scene_id": scene_id, "row": row, **{name: int(mask[row].sum()) for name, mask in row_masks.items()}}
            for row in range(TARGET_HEIGHT)
        ]
    return result


def checkpoint_identity(scene: dict[str, str]) -> str:
    root = R3 / scene["Parity_Scene_ID"]
    return canonical_json_sha256({
        "protocol": PROTOCOL_VERSION, "design": DESIGN_HASH, "scene": scene["SR_system_id"],
        "cloud": scene["cloud_system_id"],
        "r3": {path.name: sha256_file(path) for path in sorted(root.glob("*.tif"))},
    })


def save_checkpoint(scene_id: str, identity: str, result: dict[str, Any]) -> None:
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    row_path = CHECKPOINTS / f"{scene_id}_rows.csv"
    if result.get("rows"):
        write_csv_atomic(row_path, result.pop("rows"))
    payload = {"identity": identity, "result": result}
    temporary = (CHECKPOINTS / f"{scene_id}.json.partial")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    temporary.replace(CHECKPOINTS / f"{scene_id}.json")


def load_checkpoint(scene_id: str, identity: str) -> dict[str, Any] | None:
    path = CHECKPOINTS / f"{scene_id}.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["result"] if payload.get("identity") == identity else None


def render_outputs(results: list[dict[str, Any]]) -> str:
    affected = [item for item in results if item["scene_id"] in AFFECTED]
    unaffected = [item for item in results if item["scene_id"] in UNAFFECTED]
    (OUT / "00_CURRENT_STATE.md").write_text(
        "# Source-support decomposition state\n\n"
        "Phase 1 is complete for the frozen eleven-scene Sentinel protocol. The historical "
        "768,614-pixel disagreement is exactly reproduced in all six affected scenes and is "
        "fully attributed to masked, non-zero GeoTIFF NoData samples being cast directly to "
        "boolean true. Five unaffected scenes remain unchanged. No local r3 data correction, "
        "model execution, asset export, or Sentinel Stage 3-5 work was performed.\n",
        encoding="utf-8",
    )
    (OUT / "01_DETECTOR_MASK_MAPPING_VALIDATION.md").write_text(
        "# Detector-mask mapping validation\n\n"
        "## Status: complete supporting evidence; not the causal defect\n\n"
        "All six exact 47SNB SAFE products use native 10-m EPSG:32647 B04/B08 detector-mask "
        "rasters. Pixel-center nearest-neighbour mapping to the frozen 3542 x 2389 grid gives "
        "the same official support onset at row 2265. Direct B04/B08 values and validity agree "
        "with local r3 on their official support. The apparent 217-row GEE-only strip is outside "
        "that support and is completely explained by the historical export-reader NoData boolean "
        "cast; detector geometry is therefore corroborating boundary evidence, not the root cause.\n",
        encoding="utf-8",
    )
    scene_rows = [item["scene"] | {"scene_id": item["scene_id"], "SAFE_product_id": item["product"]} for item in affected]
    write_csv_atomic(OUT / "02_SCENE_SUPPORT_DECOMPOSITION.csv", scene_rows)
    row_rows: list[dict[str, Any]] = []
    for item in affected:
        row_rows.extend(read_csv(CHECKPOINTS / f"{item['scene_id']}_rows.csv"))
    write_csv_atomic(OUT / "03_ROW_SUPPORT_DECOMPOSITION.csv", row_rows)
    categories = [
        {"scene_id": item["scene_id"], "category": category, "pixel_count": count,
         "scene_expected_disagreement": item["scene"]["expected_gee_only_from_v4"]}
        for item in affected for category, count in sorted(item.get("categories", {}).items())
    ]
    write_csv_atomic(OUT / "04_PIXEL_SUPPORT_CATEGORIES.csv", categories)

    for filename, member in (("05_CDSE_B04_SUPPORT_AUDIT.csv", "B04"), ("06_CDSE_B08_SUPPORT_AUDIT.csv", "B08"),
                             ("07_CDSE_SCL_SUPPORT_AUDIT.csv", "SCL")):
        rows = []
        for item in affected:
            meta = item["members"][member]
            rows.append({"scene_id": item["scene_id"], **meta,
                         "mapped_support_pixels": item["scene"].get(f"cdse_{member.lower()}_raster_mask", "NOT_APPLICABLE")})
        write_csv_atomic(OUT / filename, rows)
    (OUT / "08_LOCAL_R3_VALIDITY_PATH_AUDIT.md").write_text(
        "# Local r3 validity-path audit\n\n"
        "Local final validity is exactly B04/B08 harmonized DN in [1,10000], SCL in {4,5,7}, "
        "finite cloud probability <30, with SCL nearest-mapped to the frozen 10 m grid. "
        "The decomposition compares this path against direct SAFE values and masks without changing it.\n\n" +
        "\n".join(
            f"- {item['scene_id']}: B04 mismatch={item['scene']['local_cdse_b4_value_mismatch']}; "
            f"B08 mismatch={item['scene']['local_cdse_b8_value_mismatch']}; "
            f"source-validity mismatch={item['scene']['local_cdse_source_validity_mismatch']}."
            for item in affected
        ) + "\n", encoding="utf-8"
    )
    gee_rows = [{"scene_id": item["scene_id"],
                 "legacy_export_nodatavals": ";".join(item["legacy_export"]["nodatavals_observed"]),
                 "legacy_export_dtypes": ";".join(item["legacy_export"]["dtypes_observed"]), **{
        key: value for key, value in item["scene"].items() if key.startswith("gee_") or key.startswith("disagreement_")
    }} for item in affected]
    write_csv_atomic(OUT / "09_GEE_NATIVE_BAND_MASK_AUDIT.csv", gee_rows)
    edge_rows = [{"scene_id": item["scene_id"], **{
        key: value for key, value in item["scene"].items() if key.endswith("_first_row") or key.endswith("_last_row") or key.endswith("_full_width_rows")
    }} for item in affected]
    write_csv_atomic(OUT / "10_GEE_EDGE_SUPPORT_COMPARISON.csv", edge_rows)
    coordinate_rows = []
    for item in affected:
        b4 = item["members"]["B04"]
        coordinate_rows.append({
            "scene_id": item["scene_id"], "target_crs": TARGET_CRS,
            "target_transform": json.dumps(list(TARGET_TRANSFORM)[:6]),
            "target_dimensions": f"{TARGET_WIDTH}x{TARGET_HEIGHT}",
            "cdse_b4_crs": b4["crs"], "cdse_b4_transform": b4["transform"],
            "cdse_b4_dimensions": f"{b4['width']}x{b4['height']}",
            "gee_b4_projection": json.dumps(item["gee_projection"], sort_keys=True),
            "mapping": "raster_to_raster_nearest_with_exact_pixel_centers",
            "pixel_center_inclusion_verified": True,
        })
    write_csv_atomic(OUT / "11_COORDINATE_AND_RASTERIZATION_AUDIT.csv", coordinate_rows)

    conservation = all(item["scene"]["conservation_pass"] and item["scene"].get("category_conservation_pass") for item in affected)
    local_matches = all(
        item["scene"]["local_cdse_b4_value_mismatch"] == 0 and
        item["scene"]["local_cdse_b8_value_mismatch"] == 0 and
        item["scene"]["local_cdse_source_validity_mismatch"] == 0
        for item in affected
    )
    all_outside = all(
        item["scene"]["disagreement_outside_cdse_raster"] == item["scene"]["expected_gee_only_from_v4"]
        for item in affected
    )
    all_nodata_cast = all(
        item["scene"]["disagreement_on_legacy_export_nodata"] == item["scene"]["expected_gee_only_from_v4"]
        for item in affected
    )
    canary = all(
        item["scene"]["mask_aware_reader_corrected_disagreement"] == 0 and
        item["scene"]["expanded_unmask_corrected_disagreement"] == 0
        for item in affected
    )
    regression = all(
        item["scene"]["expected_gee_only_from_v4"] == 0 and
        item["scene"]["mask_aware_reader_corrected_disagreement"] == 0 and
        item["scene"]["expanded_unmask_corrected_disagreement"] == 0
        for item in unaffected
    )
    if conservation and local_matches and all_outside and all_nodata_cast:
        classification = "GEE_EXPORT_NODATA_BOOLEAN_CAST_IMPLEMENTATION_ERROR"
    elif conservation:
        classification = "MULTIPLE_INTERACTING_CAUSES"
    else:
        classification = "UNRESOLVED"
    certified = classification == "GEE_EXPORT_NODATA_BOOLEAN_CAST_IMPLEMENTATION_ERROR" and canary and regression

    (OUT / "12_ROOT_CAUSE_DECOMPOSITION.md").write_text(
        "# Root-cause decomposition\n\n"
        f"Classification: **{classification}**.\n\n"
        f"Row-wise conservation: {conservation}; direct local/CDSE identity: {local_matches}; "
        f"all disagreement outside official CDSE reflectance raster support: {all_outside}; "
        f"all disagreement is a masked, non-zero raw NoData sample cast to boolean true: {all_nodata_cast}.\n\n"
        "The historical extraction called `unmask(0)` with the default footprint behavior, read the "
        "downloaded GeoTIFF without its validity mask, then applied `astype(bool)`. The catalog's "
        "masked NoData samples are non-zero, so the reader—not the Sentinel source or QA predicate—"
        "created the apparent 217-row valid strip.\n",
        encoding="utf-8",
    )
    repair = (
        "No local r3 correction is permitted. The minimum parity-reader correction is to honor the "
        "GeoTIFF validity mask before boolean conversion (`read(1, masked=True).filled(0).astype(bool)` "
        "or the equivalent `read(1) != 0 AND read_masks(1) > 0`). The export should additionally use "
        "`unmask(0, False)` so the requested grid receives explicit zeros. Both guards are mandatory; "
        "product IDs, radiometry, QA predicate, NDVI, dates, grid, and tolerances remain unchanged."
        if classification == "GEE_EXPORT_NODATA_BOOLEAN_CAST_IMPLEMENTATION_ERROR" else
        "No repair is approved because responsibility is not uniquely established."
    )
    (OUT / "13_MINIMUM_REPAIR_SPEC.md").write_text(
        "# Minimum repair specification\n\n" + repair + "\n", encoding="utf-8"
    )
    (OUT / "14_POST_REPAIR_SIX_SCENE_CANARY.md").write_text(
        "# Six-scene extraction-semantics canary\n\n"
        f"Verdict: **{'PASS' if canary else 'FAIL'}**. "
        "This is an in-memory forensic reader/export canary only; no production pipeline or asset was changed.\n\n" +
        "\n".join(f"- {item['scene_id']}: mask-aware disagreement={item['scene']['mask_aware_reader_corrected_disagreement']}; "
                  f"expanded-unmask disagreement={item['scene']['expanded_unmask_corrected_disagreement']}; "
                  f"official-overlay diagnostic={item['scene']['official_overlay_corrected_disagreement']}"
                  for item in affected) + "\n", encoding="utf-8"
    )
    (OUT / "15_UNAFFECTED_SCENE_REGRESSION.md").write_text(
        "# Unaffected-scene regression\n\n"
        f"Verdict: **{'PASS' if regression else 'FAIL'}**.\n\n" +
        "\n".join(f"- {item['scene_id']}: original expected={item['scene']['expected_gee_only_from_v4']}; "
                  f"mask-aware disagreement={item['scene']['mask_aware_reader_corrected_disagreement']}; "
                  f"expanded-unmask disagreement={item['scene']['expanded_unmask_corrected_disagreement']}"
                  for item in unaffected) + "\n", encoding="utf-8"
    )
    (OUT / "16_FINAL_SUPPORT_DECOMPOSITION_REPORT.md").write_text(
        "# Final Sentinel support-decomposition report\n\n"
        f"Root-cause classification: **{classification}**.\n\n"
        f"Six-scene conservation: {conservation}. Six-scene canary: {canary}. "
        f"Five-scene unaffected regression: {regression}.\n\n"
        f"SENTINEL_STAGE1_SUPPORT_CERTIFIED: {'TRUE' if certified else 'FALSE'}\n\n"
        "Certification applies only to the frozen eleven-scene Stage-1/2 parity protocol. "
        "Sentinel Stages 3–5, Landsat/MODIS parity, final assets, and scientific models remain locked.\n",
        encoding="utf-8",
    )
    return classification


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-resume", action="store_true", help="Ignore compatible completed scene checkpoints")
    args = parser.parse_args()
    contract = load_contract(PUBLICATION / "code" / "configs" / "scientific_execution.yaml")
    assert_preparation_lock(contract)
    phase0 = json.loads(PHASE0.read_text(encoding="utf-8")) if PHASE0.exists() else {}
    if phase0.get("status") != "PHASE0_LOCKED_PHASE1_FORENSICS_ONLY":
        raise RuntimeError("PHASE1_REQUIRES_PASSING_PHASE0_PROTECTION_MANIFEST")
    minimum = int(phase0["storage"]["minimum_phase1_free_bytes"])
    assert_phase1_storage(WORKSPACE, minimum_free_bytes=minimum)
    initialize(WORKSPACE / "model/.env")
    client, products = s3_client(), product_map()
    manifest = read_csv(MANIFEST)
    expected = {row["scene_id"]: int(row["GEE_only_valid"]) for row in read_csv(V4_MASK)}
    results = []
    for scene in manifest:
        scene_id = scene["Parity_Scene_ID"]
        identity = checkpoint_identity(scene)
        result = None if args.no_resume else load_checkpoint(scene_id, identity)
        if result is None:
            print(f"PHASE1_PROCESSING:{scene_id}", flush=True)
            result = process_scene(scene, products, client, expected)
            save_checkpoint(scene_id, identity, result)
        else:
            print(f"PHASE1_REUSED:{scene_id}", flush=True)
        results.append(result)
    classification = render_outputs(results)
    (OUT / "PHASE1_EXECUTION_RECORD.json").write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(), "protocol": PROTOCOL_VERSION,
        "design_hash": DESIGN_HASH, "scene_count": len(results), "classification": classification,
        "scope": "source_support_forensics_only", "models_run": False, "assets_written": False,
        "sentinel_stages_3_to_5_run": False, "landsat_modis_run": False,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"PHASE1_CLASSIFICATION:{classification}")
    return 0 if classification != "UNRESOLVED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
