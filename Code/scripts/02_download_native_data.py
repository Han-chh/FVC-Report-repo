#!/usr/bin/env python3
"""Download all missing native publication inputs without running models."""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from data_prep.download import (acquire_unit, initialize_earth_engine, load_credentials,
                                load_manifest, merge_records, require_credentials, write_json_atomic)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths", type=Path, default=ROOT / "configs/paths.external.yaml")
    parser.add_argument("--output-root", type=Path, help="Override external_native_data_root (useful for a small local smoke test)")
    parser.add_argument("--aoi", action="append", help="Repeatable AOI ID; default is AOI-00 and all ten candidates")
    parser.add_argument("--year", action="append", type=int, help="Repeatable year; default 2021-2025")
    parser.add_argument("--sensor", action="append", choices=("sentinel2", "landsat", "modis", "fcover"))
    parser.add_argument("--limit-items", type=int, help="Connectivity/smoke-test limit per AOI-year-sensor")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--include-existing-aoi00", action="store_true",
                        help="Download AOI-00 2022-2025 instead of retaining immutable legacy references")
    parser.add_argument("--acknowledge-deprecated-local-backend", action="store_true",
                        help="Required because the active publication backend is GEE cloud processing")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.acknowledge_deprecated_local_backend:
        raise SystemExit("LOCAL_NATIVE_BACKEND_DISABLED: use 02_prepare_gee_cloud_data.py")
    paths = yaml.safe_load(args.paths.read_text(encoding="utf-8"))
    workspace = Path(paths["workspace_root"]); output_root = args.output_root or Path(paths["external_native_data_root"])
    manifest_root = Path(paths["local_manifest_root"]); env_file = Path(paths["credential_env_file"])
    output_root.mkdir(parents=True, exist_ok=True); (output_root / "logs").mkdir(parents=True, exist_ok=True)
    load_credentials(env_file); require_credentials(); initialize_earth_engine()
    registry = json.loads((workspace / "report/publication/new_experiments/01_multi_aoi/candidate_aoi_registry.geojson").read_text(encoding="utf-8"))
    selected_aois = set(args.aoi or [feature["properties"]["aoi_id"] for feature in registry["features"]])
    features = [feature for feature in registry["features"] if feature["properties"]["aoi_id"] in selected_aois]
    missing = selected_aois - {feature["properties"]["aoi_id"] for feature in features}
    if missing:
        raise SystemExit(f"UNKNOWN_AOI:{','.join(sorted(missing))}")
    years = args.year or list(range(2021, 2026)); sensors = args.sensor or ["fcover", "modis", "landsat", "sentinel2"]
    manifest_path = manifest_root / "native_asset_manifest.json"
    external_manifest = output_root / "manifests/native_asset_manifest.json"
    records = load_manifest(manifest_path); failures: list[dict] = []
    log_path = output_root / "logs" / "native_download_events.jsonl"
    for feature in features:
        aoi_id = feature["properties"]["aoi_id"]
        for year in years:
            for sensor in sensors:
                if aoi_id == "AOI-00" and year >= 2022 and not args.include_existing_aoi00:
                    event = {"time": datetime.now(timezone.utc).isoformat(), "aoi_id": aoi_id, "year": year,
                             "sensor": sensor, "status": "SKIPPED_IMMUTABLE_LEGACY_REFERENCE"}
                    with log_path.open("a", encoding="utf-8") as stream: stream.write(json.dumps(event) + "\n")
                    print(json.dumps(event), flush=True); continue
                event = {"time": datetime.now(timezone.utc).isoformat(), "aoi_id": aoi_id,
                         "year": year, "sensor": sensor, "status": "STARTED"}
                with log_path.open("a", encoding="utf-8") as stream: stream.write(json.dumps(event) + "\n")
                print(json.dumps(event), flush=True)
                try:
                    added = acquire_unit(feature, year, sensor, output_root, args.limit_items)
                    records = merge_records(records, added)
                    write_json_atomic(manifest_path, records); write_json_atomic(external_manifest, records)
                    event.update(time=datetime.now(timezone.utc).isoformat(), status="COMPLETED", asset_records=len(added))
                except Exception as exc:
                    event.update(time=datetime.now(timezone.utc).isoformat(), status="FAILED",
                                 error_type=type(exc).__name__, error=str(exc), traceback=traceback.format_exc(limit=8))
                    failures.append(event)
                with log_path.open("a", encoding="utf-8") as stream: stream.write(json.dumps(event, ensure_ascii=False) + "\n")
                print(json.dumps({k: v for k, v in event.items() if k != "traceback"}, ensure_ascii=False), flush=True)
                if event["status"] == "FAILED" and not args.continue_on_error:
                    write_json_atomic(output_root / "logs/native_download_failures.json", failures)
                    return 2
    write_json_atomic(output_root / "logs/native_download_failures.json", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
