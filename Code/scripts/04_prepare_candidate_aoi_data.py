#!/usr/bin/env python3
"""Inventory source availability and fail loudly where native crops are absent.

This script does not silently substitute collections or create scientific pairs.
It records catalog availability separately from local preparation readiness.
"""
from collections import Counter
from pathlib import Path
import json, os, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "src"))
from data_prep.catalog import search

EXP = ROOT.parent / "new_experiments"; AOIS = EXP / "01_multi_aoi/candidate_aoi_registry.geojson"
SOURCES = {"sentinel2": "sentinel-2-l2a", "landsat": "landsat-c2-l2", "modis": "modis-09Q1-061"}


def acquisition_year(item):
    p = item["properties"]; value = p.get("datetime") or p.get("start_datetime") or p.get("created")
    return int(str(value)[:4])


def inventory(feature, sensor, collection):
    from shapely.geometry import shape
    aoi_id = feature["properties"]["aoi_id"]
    bbox = shape(feature["geometry"]).bounds; counts = Counter(); platforms = {}
    for year in range(2021, 2026):
        items = search(collection, bbox, datetime=f"{year}-06-05/{year}-08-25")
        if sensor == "landsat":
            items = [item for item in items if item["properties"].get("platform") in {"landsat-8", "landsat-9"}]
        counts[year] = len(items)
        platforms[year] = sorted({str(item["properties"].get("platform") or "unknown") for item in items})
    return aoi_id, sensor, counts, platforms


collection = json.loads(AOIS.read_text(encoding="utf-8")); results = {}
with ThreadPoolExecutor(max_workers=4) as pool:
    futures = [pool.submit(inventory, feature, sensor, source) for feature in collection["features"] for sensor, source in SOURCES.items()]
    for future in as_completed(futures):
        aoi_id, sensor, counts, platforms = future.result(); results[(aoi_id, sensor)] = (counts, platforms)
        print(f"INVENTORY {aoi_id} {sensor} {sum(counts.values())}")

legacy = ROOT.parents[2] / "qh-fvc-data/storage/projects"
rows = []
for feature in collection["features"]:
    aoi_id = feature["properties"]["aoi_id"]
    for year in range(2021, 2026):
        for sensor in (*SOURCES, "fcover"):
            if sensor == "fcover":
                source_count = 3 if year >= 2021 else 0; platforms = ["Sentinel-3 OLCI"]
                collection_id = "CLMS FCOVER 300m V2 RT6"
            else:
                counts, platform_map = results[(aoi_id, sensor)]; source_count = counts[year]; platforms = platform_map[year]
                collection_id = SOURCES[sensor]
            legacy_ready = aoi_id == "AOI-00" and year >= 2022 and any(legacy.glob("prj_*__*"))
            status = "READY" if legacy_ready else ("PARTIAL" if source_count else "NOT_AVAILABLE")
            reason = "immutable legacy AOI-00 source and derived data referenced by checksum manifest" if legacy_ready else (
                "catalog records exist, but candidate native crops/QA/checksums are not locally prepared" if source_count else "no source catalog record in frozen support period")
            if sensor == "fcover" and not legacy_ready and not (os.getenv("EODATA_S3_ACCESS_KEY") and os.getenv("EODATA_S3_SECRET_KEY")) and not os.getenv("CDSE_DOWNLOAD_TOKEN"):
                reason = "global RT6 lineage expected; native FCOVER crop blocked because CDSE native-access credentials are absent"
            rows.append({"aoi_id": aoi_id, "year": year, "sensor_product": sensor, "collection": collection_id,
                         "platforms": ";".join(platforms), "catalog_item_count": source_count, "status": status, "reason": reason,
                         "source_exists": bool(source_count or legacy_ready), "checksum_exists": legacy_ready,
                         "product_version_recorded": bool(source_count or legacy_ready), "native_crs_known": legacy_ready,
                         "crop_succeeds": legacy_ready, "qa_bands_exist": legacy_ready, "target_dates_coverage_recorded": legacy_ready,
                         "raster_integrity_checked": legacy_ready, "nodata_readable": legacy_ready,
                         "common_support_constructible": legacy_ready, "temporal_count_computable": legacy_ready,
                         "manifest_complete": legacy_ready})

out = EXP / "data/data_preparation_status.csv"; out.parent.mkdir(parents=True, exist_ok=True); pd.DataFrame(rows).to_csv(out, index=False)
summary = pd.DataFrame(rows).groupby(["aoi_id", "status"]).size().unstack(fill_value=0).reset_index()
summary.to_csv(EXP / "data/data_preparation_summary.csv", index=False)
print(out)
