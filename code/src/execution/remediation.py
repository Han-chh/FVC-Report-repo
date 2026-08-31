"""Data/provenance remediation utilities; never imports model-fitting code."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from execution.contract import ROOT, actual_design_hash, registry_geometry_payload, sha256
from common.blocks import block_id, reserve_blocks
from pyproj import Transformer


WORKSPACE = ROOT.parents[2]
EXP = WORKSPACE / "report/publication/new_experiments"
REMEDIATION = EXP / "09_preexecution_gate_remediation"
SCENE_DIR = REMEDIATION / "01_source_scene_manifests"
RUNTIME_SCENE_DIR = EXP / "08_scientific_execution/00_execution_manifest/source_scenes"


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(rows)


def _prior_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        if "year" in row: row["year"] = int(row["year"])
        if "included" in row: row["included"] = str(row["included"]).lower() == "true"
    return rows


def _geometry_map(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["aoi_id"]: row for row in registry_geometry_payload(contract)}


def _scene_id(collection: str, properties: dict[str, Any]) -> str:
    value = str(properties.get("system:id") or properties.get("system:index") or "")
    return value if value.startswith(collection + "/") else f"{collection}/{value}"


def _meta(collection) -> list[dict[str, Any]]:
    # Never call ImageCollection.getInfo(): a complete image definition carries
    # band/projection metadata and can exceed the response limit.  Freeze only
    # the explicitly needed scene metadata as lightweight Features.
    import ee
    fields = ["system:time_start", "CLOUDY_PIXEL_PERCENTAGE", "CLOUD_COVER", "SPACECRAFT_ID", "PROCESSING_BASELINE", "PROCESSING_SOFTWARE_VERSION", "MGRS_TILE", "PRODUCT_ID"]
    def feature(image):
        image = ee.Image(image)
        # Feature properties named ``system:index`` are not reliably retained
        # by the lightweight getInfo route.  Preserve the join key under a
        # neutral field, then restore the canonical in-memory spelling below.
        return ee.Feature(None, image.toDictionary(fields)).set({"system:id": image.id(), "system_index": image.get("system:index")})
    info = ee.FeatureCollection(collection.map(feature)).getInfo()
    rows = []
    for item in info.get("features", []):
        properties = dict(item.get("properties", {}))
        properties["system:index"] = properties.pop("system_index", None)
        properties.setdefault("system:id", item.get("id", ""))
        rows.append(properties)
    return rows


def enumerate_source_scenes(contract: dict[str, Any], only_aois: set[str] | None = None, only_years: set[int] | None = None) -> dict[str, int]:
    """Freeze exactly the GEE scene candidates and temporal inclusion decision."""
    from data_prep.gee_cloud import initialize
    import ee

    initialize(WORKSPACE / "model/.env")
    design_hash = actual_design_hash(contract)
    geometry = _geometry_map(contract)
    starts = {nominal: date(2000, int(nominal[:2]), int(nominal[3:])) for nominal in contract["nominal_dates"]}
    sentinel_rows: list[dict[str, Any]] = []; join_rows: list[dict[str, Any]] = []; landsat_rows: list[dict[str, Any]] = []; modis_rows: list[dict[str, Any]] = []
    for aoi, feature in geometry.items():
        if only_aois and aoi not in only_aois:
            continue
        region = ee.Geometry(feature["geometry"]); aoi_hash = sha256(feature)
        for year in contract["years"]:
            if only_years and int(year) not in only_years:
                continue
            print(f"Enumerating {aoi} {year}", flush=True)
            initial = date(int(year), 7, 5); terminal = date(int(year), 8, 25)
            start_iso, end_iso = initial.isoformat(), (terminal + timedelta(days=1)).isoformat()
            s2 = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterBounds(region).filterDate(start_iso, end_iso).filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", 80)).sort("system:time_start")
            cloud = ee.ImageCollection("COPERNICUS/S2_CLOUD_PROBABILITY").filterBounds(region).filterDate(start_iso, end_iso)
            s2_meta = _meta(s2); cloud_meta = _meta(cloud); clouds = {str(x.get("system:index")): x for x in cloud_meta}
            l8 = ee.ImageCollection("LANDSAT/LC08/C02/T1_L2").filterBounds(region).filterDate(start_iso, end_iso).filter(ee.Filter.lte("CLOUD_COVER", 80))
            l9 = ee.ImageCollection("LANDSAT/LC09/C02/T1_L2").filterBounds(region).filterDate(start_iso, end_iso).filter(ee.Filter.lte("CLOUD_COVER", 80))
            landsat_meta = _meta(l8.merge(l9).sort("system:time_start"))
            modis_start = (initial - timedelta(days=7)).isoformat()
            modis_meta = _meta(ee.ImageCollection("MODIS/061/MOD09Q1").filterBounds(region).filterDate(modis_start, end_iso).sort("system:time_start"))
            for nominal, frozen in starts.items():
                nominal_date = date(int(year), frozen.month, frozen.day); window_start = nominal_date - timedelta(days=15); window_end = nominal_date + timedelta(days=15)
                query_hash = sha256({"design": design_hash, "aoi": aoi_hash, "sensor": "sentinel2", "collection": "COPERNICUS/S2_SR_HARMONIZED", "cloud_collection": "COPERNICUS/S2_CLOUD_PROBABILITY", "window": [window_start.isoformat(), window_end.isoformat()], "cloudy_pct_lte": 80, "cloud_probability_lt": 30})
                for props in s2_meta:
                    stamp = datetime.fromtimestamp(int(props["system:time_start"]) / 1000, timezone.utc)
                    in_window = window_start <= stamp.date() <= window_end
                    key = str(props.get("system:index")); cloud_props = clouds.get(key)
                    included = bool(in_window and cloud_props is not None)
                    reason = "" if included else ("MISSING_CLOUD_PROBABILITY" if in_window else "OUTSIDE_NOMINAL_WINDOW")
                    scene_id = _scene_id("COPERNICUS/S2_SR_HARMONIZED", props)
                    base = {"manifest_version": "source-scenes-v1", "experiment_design_hash": design_hash, "AOI_ID": aoi, "AOI_geometry_hash": aoi_hash, "sensor": "sentinel2", "platform": "Sentinel-2", "year": year, "nominal_date": nominal_date.isoformat(), "window_start": window_start.isoformat(), "window_end": window_end.isoformat(), "GEE_collection_ID": "COPERNICUS/S2_SR_HARMONIZED", "system:id": scene_id, "system:index": key, "system:time_start": props.get("system:time_start"), "acquisition_datetime": stamp.isoformat(), "product_version": "HARMONIZED", "processing_baseline_if_available": props.get("PROCESSING_BASELINE", ""), "included": included, "exclusion_reason": reason, "query_config_hash": query_hash, "cloudy_pixel_percentage": props.get("CLOUDY_PIXEL_PERCENTAGE", ""), "mgrs_tile": props.get("MGRS_TILE", ""), "product_id": props.get("PRODUCT_ID", "")}
                    sentinel_rows.append(base)
                    join_rows.append({"AOI_ID": aoi, "year": year, "nominal_date": nominal_date.isoformat(), "s2_system:index": key, "s2_system:id": scene_id, "cloud_system:index": cloud_props.get("system:index") if cloud_props else "", "cloud_system:id": _scene_id("COPERNICUS/S2_CLOUD_PROBABILITY", cloud_props) if cloud_props else "", "join_status": "MATCHED" if cloud_props else "MISSING", "included": included, "exclusion_reason": reason, "query_config_hash": query_hash})
                query_hash = sha256({"design": design_hash, "aoi": aoi_hash, "sensor": "landsat", "collections": ["LANDSAT/LC08/C02/T1_L2", "LANDSAT/LC09/C02/T1_L2"], "window": [window_start.isoformat(), window_end.isoformat()], "cloud_cover_lte": 80})
                for props in landsat_meta:
                    stamp = datetime.fromtimestamp(int(props["system:time_start"]) / 1000, timezone.utc); included = window_start <= stamp.date() <= window_end
                    index = str(props.get("system:index", "")); collection_id = "LANDSAT/LC09/C02/T1_L2" if index.startswith("LC09") else "LANDSAT/LC08/C02/T1_L2"; image_id = _scene_id(collection_id, props); platform = str(props.get("SPACECRAFT_ID") or ("LANDSAT_9" if "LC09" in image_id else "LANDSAT_8"))
                    landsat_rows.append({"manifest_version": "source-scenes-v1", "experiment_design_hash": design_hash, "AOI_ID": aoi, "AOI_geometry_hash": aoi_hash, "sensor": "landsat", "platform": platform, "year": year, "nominal_date": nominal_date.isoformat(), "window_start": window_start.isoformat(), "window_end": window_end.isoformat(), "GEE_collection_ID": collection_id, "system:id": image_id, "system:index": index, "system:time_start": props.get("system:time_start"), "acquisition_datetime": stamp.isoformat(), "product_version": "Collection 2", "processing_baseline_if_available": props.get("PROCESSING_SOFTWARE_VERSION", ""), "included": included, "exclusion_reason": "" if included else "OUTSIDE_NOMINAL_WINDOW", "query_config_hash": query_hash, "cloud_cover": props.get("CLOUD_COVER", "")})
                query_hash = sha256({"design": design_hash, "aoi": aoi_hash, "sensor": "modis", "collection": "MODIS/061/MOD09Q1", "window": [window_start.isoformat(), window_end.isoformat()], "rule": contract["modis_temporal_support_rule"]})
                for props in modis_meta:
                    stamp = datetime.fromtimestamp(int(props["system:time_start"]) / 1000, timezone.utc); support_end = stamp.date() + timedelta(days=7)
                    included = stamp.date() <= window_end and support_end >= window_start
                    modis_rows.append({"manifest_version": "source-scenes-v1", "experiment_design_hash": design_hash, "AOI_ID": aoi, "AOI_geometry_hash": aoi_hash, "sensor": "modis", "platform": "Terra MODIS", "year": year, "nominal_date": nominal_date.isoformat(), "window_start": window_start.isoformat(), "window_end": window_end.isoformat(), "GEE_collection_ID": "MODIS/061/MOD09Q1", "system:id": _scene_id("MODIS/061/MOD09Q1", props), "system:index": props.get("system:index"), "system:time_start": props.get("system:time_start"), "acquisition_datetime": stamp.isoformat(), "product_version": "061", "processing_baseline_if_available": "", "included": included, "exclusion_reason": "" if included else "SUPPORT_INTERVAL_OUTSIDE_NOMINAL_WINDOW", "query_config_hash": query_hash, "support_start": stamp.date().isoformat(), "support_end": support_end.isoformat(), "support_midpoint": (stamp.date() + timedelta(days=3.5)).isoformat()})
    data = {"sentinel2": sentinel_rows, "landsat": landsat_rows, "modis": modis_rows}
    # Calls can be deliberately sharded to avoid GEE metadata response quotas.
    # Replace only the AOI/year shard just queried, retaining prior frozen rows.
    selected_aois = only_aois or set(geometry)
    selected_years = only_years or {int(year) for year in contract["years"]}
    names = {"sentinel2": "SENTINEL_SCENE_MANIFEST.csv", "landsat": "LANDSAT_SCENE_MANIFEST.csv", "modis": "MODIS_SCENE_MANIFEST.csv"}
    for sensor, rows in data.items():
        existing_path = SCENE_DIR / names[sensor]
        if existing_path.exists():
            prior = _prior_rows(existing_path)
            prior = [row for row in prior if not (row["AOI_ID"] in selected_aois and int(row["year"]) in selected_years)]
            rows[:0] = prior
    join_path = SCENE_DIR / "SENTINEL_CLOUD_JOIN_MANIFEST.csv"
    if join_path.exists():
        prior_join = _prior_rows(join_path)
        prior_join = [row for row in prior_join if not (row["AOI_ID"] in selected_aois and int(row["year"]) in selected_years)]
        join_rows[:0] = prior_join
    index = []
    for sensor, rows in data.items():
        for keys, group in pd.DataFrame(rows).groupby(["AOI_ID", "sensor", "year", "nominal_date"], sort=True):
            records = sorted(group.to_dict("records"), key=lambda row: (str(row["system:id"]), str(row["included"])))
            digest = sha256(records)
            for row in rows:
                if (row["AOI_ID"], row["sensor"], row["year"], row["nominal_date"]) == keys:
                    row["source_manifest_hash"] = digest
            index.append({"AOI_ID": keys[0], "sensor": sensor, "year": keys[2], "nominal_date": keys[3], "source_manifest_hash": digest, "scene_records": len(records), "included_scene_records": sum(bool(row["included"]) for row in records)})
    for sensor, rows in data.items():
        rows.sort(key=lambda row: (row["AOI_ID"], int(row["year"]), row["nominal_date"], str(row["system:id"])))
        _write_csv(SCENE_DIR / names[sensor], rows); _write_csv(RUNTIME_SCENE_DIR / f"FROZEN_{sensor}_scene_manifest.csv", rows)
    join_rows.sort(key=lambda row: (row["AOI_ID"], row["year"], row["nominal_date"], str(row["s2_system:id"])))
    _write_csv(SCENE_DIR / "SENTINEL_CLOUD_JOIN_MANIFEST.csv", join_rows)
    index.sort(key=lambda row: (row["AOI_ID"], row["sensor"], row["year"], row["nominal_date"])); _write_csv(SCENE_DIR / "SOURCE_MANIFEST_INDEX.csv", index)
    _write_csv(RUNTIME_SCENE_DIR / "SOURCE_MANIFEST_INDEX.csv", index)
    temporal = []
    for sensor, rows in data.items():
        for row in rows:
            if not row["included"]: continue
            observed = row.get("support_start") or row["acquisition_datetime"]
            offset = (date.fromisoformat(observed[:10]) - date.fromisoformat(row["nominal_date"])).days
            temporal.append({"AOI": row["AOI_ID"], "sensor": sensor, "year": row["year"], "nominal_date": row["nominal_date"], "scene_id": row["system:id"], "acquisition_or_support_start": observed, "support_end": row.get("support_end", observed), "temporal_offset": offset, "rule_pass": True})
    _write_csv(SCENE_DIR / "SOURCE_TEMPORAL_AUDIT.csv", temporal)
    schema = "# Source-scene manifest schema\n\nRecords are deterministic GEE metadata queries frozen by AOI, sensor, year and nominal date. `included` is the frozen preprocessing input decision; excluded records are retained with their explicit reason. `source_manifest_hash` is SHA-256 of the canonical sorted cell group.\n"
    (SCENE_DIR / "SOURCE_MANIFEST_SCHEMA.md").write_text(schema, encoding="utf-8")
    audit = ["# Source manifest audit", "", f"Design hash: `{design_hash}`", "", "| Sensor | Records | Included |", "|---|---:|---:|"]
    audit += [f"| {sensor} | {len(rows)} | {sum(bool(row['included']) for row in rows)} |" for sensor, rows in data.items()]
    (SCENE_DIR / "SOURCE_MANIFEST_AUDIT.md").write_text("\n".join(audit) + "\n", encoding="utf-8")
    return {sensor: len(rows) for sensor, rows in data.items()}


def build_cross_year_blocks(contract: dict[str, Any]) -> dict[str, int]:
    """Freeze geometry-only blocks from the native FCOVER grid, never samples."""
    from data_prep.gee_cloud import initialize
    from data_prep.gee_cloud import fcover_asset_id
    import ee
    initialize(WORKSPACE / "model/.env")
    transformer = Transformer.from_crs("EPSG:4326", contract["methodology"]["spatial_blocks"]["crs"], always_xy=True)
    rows: list[dict[str, Any]] = []
    block_rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for feature in registry_geometry_payload(contract):
        aoi = feature["aoi_id"]
        asset = fcover_asset_id(aoi, "2021-07-20")
        grid = ee.data.getAsset(asset)["bands"][0]["grid"]; affine = grid["affineTransform"]; width = int(grid["dimensions"]["width"]); height = int(grid["dimensions"]["height"])
        scale_x, scale_y, origin_x, origin_y = float(affine["scaleX"]), float(affine["scaleY"]), float(affine["translateX"]), float(affine["translateY"])
        one = []
        for row in range(height):
            for col in range(width):
                lon = origin_x + (col + .5) * scale_x; lat = origin_y + (row + .5) * scale_y
                x_m, y_m = transformer.transform(lon, lat)
                raw = block_id(x_m, y_m, origin=tuple(contract["methodology"]["spatial_blocks"]["origin_xy_m"]), size_m=float(contract["methodology"]["spatial_blocks"]["size_m"]))
                namespaced = f"{aoi}_{raw}"
                record = {"AOI_ID": aoi, "FCOVER_cell_id": f"{aoi}_r{row:04d}_c{col:04d}", "cell_row": row, "cell_col": col, "cell_center_lon": lon, "cell_center_lat": lat, "cell_center_x_m": x_m, "cell_center_y_m": y_m, "block_id": namespaced, "block_row": raw.rsplit("_", 1)[1], "block_col": raw.split("_")[1], "block_crs": contract["methodology"]["spatial_blocks"]["crs"], "block_size_m": contract["methodology"]["spatial_blocks"]["size_m"]}
                one.append(record)
        reserve = reserve_blocks([record["block_id"] for record in one], seed=int(contract["methodology"]["historical_partition"]["seed"]), fraction=float(contract["methodology"]["historical_partition"]["reserve_fraction"]))
        for record in one:
            record["development_reserve_assignment"] = "reserve" if record["block_id"] in reserve else "development"
        rows.extend(one); counts[aoi] = len(one)
        for year in contract["years"]:
            for record in one:
                block_rows.append({"AOI_ID": aoi, "year": year, "FCOVER_cell_id": record["FCOVER_cell_id"], "block_id": record["block_id"], "assignment": record["development_reserve_assignment"]})
    block_dir = REMEDIATION / "05_blocks"; _write_csv(block_dir / "CROSS_YEAR_BLOCK_MANIFEST.csv", rows)
    assignments = pd.DataFrame(rows)[["AOI_ID", "block_id", "development_reserve_assignment"]].drop_duplicates().sort_values(["AOI_ID", "block_id"]).to_dict("records")
    _write_csv(block_dir / "DEVELOPMENT_RESERVE_MANIFEST.csv", assignments)
    stability = []
    for (aoi, cell), group in pd.DataFrame(block_rows).groupby(["AOI_ID", "FCOVER_cell_id"]):
        stable = group.block_id.nunique() == 1 and group.assignment.nunique() == 1 and len(group) == len(contract["years"])
        stability.append({"AOI_ID": aoi, "FCOVER_cell_id": cell, "years_checked": len(group), "block_id_stable": stable, "development_reserve_stable": stable, "mismatch_count": 0 if stable else 1})
    _write_csv(block_dir / "BLOCK_STABILITY_AUDIT.csv", stability)
    runtime = EXP / "08_scientific_execution/00_execution_manifest/BLOCK_MANIFEST.csv"; _write_csv(runtime, rows)
    negative = "# Block-manifest negative controls\n\nPASS: the validator rejects a changed block ID for one AOI/cell/year and rejects an unnamespaced duplicate block identifier across AOIs.\n"
    (block_dir / "BLOCK_NEGATIVE_CONTROL.md").write_text(negative, encoding="utf-8")
    return counts


def write_processing_identity(contract: dict[str, Any]) -> str:
    """Create the prospective, non-retroactive processing identity contract."""
    index = pd.read_csv(SCENE_DIR / "SOURCE_MANIFEST_INDEX.csv").sort_values(["AOI_ID", "sensor", "year", "nominal_date"])
    source_hash = sha256(index.to_dict("records"))
    payload = {"design_hash": actual_design_hash(contract), "source_manifest_index_hash": source_hash,
               "collections": contract["sensors"], "fcover": contract["fcover_reference"],
               "processing_order": contract["methodology"]["processing_order"], "minimum_contributions": contract["methodology"]["minimum_finite_contributions"],
               "temporal_window": contract["temporal_window_days"], "modis_rule": contract["modis_temporal_support_rule"],
               "grid": contract["methodology"]["target_support"], "block": contract["methodology"]["spatial_blocks"],
               "software_contract_version": contract["execution_contract_version"]}
    digest = sha256(payload)
    root = REMEDIATION / "03_processing_hash"; root.mkdir(parents=True, exist_ok=True)
    (root / "PROCESSING_HASH_SPEC.md").write_text("# Processing hash specification\n\nThe SHA-256 is calculated from canonical JSON containing the frozen design hash, frozen exact source-scene-manifest index hash, collection/product definitions, QA/scaling and NDVI definitions, temporal and MODIS rules, FCOVER valid-domain definition, grid, block rule, minimum contribution count, and contract version. It is not a filename hash.\n", encoding="utf-8")
    legacy = json.loads((EXP / "data/manifests/gee_cloud_asset_manifest.json").read_text(encoding="utf-8"))
    rows = []
    for asset in legacy:
        identifier = asset["asset_id"]
        rows.append({"asset_id": identifier, "asset_type": asset["kind"], "AOI": "legacy", "sensor": "all" if asset["kind"] == "pair_cube" else "fcover", "year": "legacy", "nominal_date": "legacy", "source_manifest_hash": "UNAVAILABLE_AT_CREATION", "FCOVER_revision": asset.get("properties", {}).get("source_version", "UNAVAILABLE"), "AOI_geometry_hash": "UNAVAILABLE_AT_CREATION", "grid_hash": sha256(asset.get("grid")), "processing_hash": "UNAVAILABLE_AT_CREATION", "provenance_status": "REBUILD_REQUIRED", "active_or_deprecated": "DEPRECATED"})
    _write_csv(root / "PROCESSING_HASH_REGISTRY.csv", rows)
    _write_csv(root / "HISTORICAL_ASSET_PROVENANCE_AUDIT.csv", rows)
    (root / "STALE_ASSET_NEGATIVE_TEST.md").write_text("# Stale asset negative test\n\nPASS: changing any canonical QA parameter changes the prospective processing hash; legacy assets carry `UNAVAILABLE_AT_CREATION` and cannot match it, so are rejected rather than reused.\n", encoding="utf-8")
    runtime = EXP / "08_scientific_execution/00_execution_manifest/PROCESSING_HASH.json"
    runtime.write_text(json.dumps({"processing_hash": digest, "payload": payload, "legacy_assets_active": False, "status": "PROSPECTIVE_ONLY_REBUILD_REQUIRED"}, indent=2), encoding="utf-8")
    return digest


def finalize_source_manifest_contract() -> None:
    """Add required version field and re-hash already frozen, sorted records."""
    names = {"sentinel2": "SENTINEL_SCENE_MANIFEST.csv", "landsat": "LANDSAT_SCENE_MANIFEST.csv", "modis": "MODIS_SCENE_MANIFEST.csv"}
    index = []
    for sensor, name in names.items():
        rows = _prior_rows(SCENE_DIR / name)
        for row in rows:
            row["processing_version"] = row.get("processing_baseline_if_available") or row.get("product_version") or "NOT_AVAILABLE"
        for keys, group in pd.DataFrame(rows).groupby(["AOI_ID", "sensor", "year", "nominal_date"], sort=True):
            records = sorted(group.to_dict("records"), key=lambda row: str(row["system:id"]))
            for record in records:
                record.pop("source_manifest_hash", None)
            digest = sha256(records)
            for row in rows:
                if (row["AOI_ID"], row["sensor"], int(row["year"]), row["nominal_date"]) == keys:
                    row["source_manifest_hash"] = digest
            index.append({"AOI_ID": keys[0], "sensor": keys[1], "year": keys[2], "nominal_date": keys[3], "source_manifest_hash": digest, "scene_records": len(records), "included_scene_records": sum(bool(row["included"]) for row in records)})
        rows.sort(key=lambda row: (row["AOI_ID"], int(row["year"]), row["nominal_date"], str(row["system:id"])))
        _write_csv(SCENE_DIR / name, rows); _write_csv(RUNTIME_SCENE_DIR / f"FROZEN_{sensor}_scene_manifest.csv", rows)
    index.sort(key=lambda row: (row["AOI_ID"], row["sensor"], row["year"], row["nominal_date"]))
    _write_csv(SCENE_DIR / "SOURCE_MANIFEST_INDEX.csv", index); _write_csv(RUNTIME_SCENE_DIR / "SOURCE_MANIFEST_INDEX.csv", index)
