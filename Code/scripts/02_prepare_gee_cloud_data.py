#!/usr/bin/env python3
"""Prepare all report data in GEE Assets; never run scientific models."""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[2]
EXP = ROOT.parent / "new_experiments"
sys.path.insert(0, str(ROOT / "src"))
from data_prep.gee_cloud import (build_pair_cube, export_aoi_tables,
                                 export_manifest_table, ingest_fcover, initialize)


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("tables", "fcover", "pairs", "manifest", "all"), default="all")
    parser.add_argument("--aoi", action="append")
    parser.add_argument("--year", action="append", type=int)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--limit-units", type=int)
    parser.add_argument("--poll-seconds", type=int, default=10)
    parser.add_argument("--run-id", default="main", help="Use a distinct manifest/log shard for concurrent acquisition workers")
    parser.add_argument("--env-file", type=Path, default=WORKSPACE / "model/.env")
    return parser.parse_args()


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    args = arguments(); initialize(args.env_file)
    registry = json.loads((EXP / "01_multi_aoi/final_four_aoi_registry.geojson").read_text(encoding="utf-8"))
    selected = set(args.aoi or [f["properties"]["aoi_id"] for f in registry["features"]])
    features = [f for f in registry["features"] if f["properties"]["aoi_id"] in selected]
    years = args.year or list(range(2021, 2026))
    suffix = "" if args.run_id == "main" else f"_{args.run_id}"
    manifest_path = EXP / f"data/manifests/gee_cloud_preparation_manifest{suffix}.json"
    failure_path = EXP / f"data/logs/gee_cloud_failures{suffix}.json"
    records = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else []
    failures = []

    def record(value: dict) -> None:
        nonlocal records
        key = (value.get("kind"), value.get("aoi_id"), value.get("year"),
               value.get("nominal_date"), value.get("asset_id"))
        mapping = {(row.get("kind"), row.get("aoi_id"), row.get("year"),
                    row.get("nominal_date"), row.get("asset_id")): row for row in records}
        value["recorded_at"] = datetime.now(timezone.utc).isoformat()
        mapping[key] = value; records = sorted(mapping.values(), key=lambda row: str(row.get("asset_id")))
        save(manifest_path, records)

    if args.phase in ("tables", "all"):
        rows = pd.read_csv(EXP / "01_multi_aoi/environmental_features.csv").to_dict("records")
        for value in export_aoi_tables(registry, rows, args.overwrite, args.poll_seconds): record(value)

    units = 0
    if args.phase in ("fcover", "all"):
        for feature in features:
            for year in years:
                for month, day in ((7, 20), (7, 31), (8, 10)):
                    if args.limit_units is not None and units >= args.limit_units: break
                    units += 1; nominal = date(year, month, day).isoformat()
                    label = {"phase": "fcover", "aoi_id": feature["properties"]["aoi_id"], "nominal_date": nominal}
                    print(json.dumps({**label, "status": "STARTED"}), flush=True)
                    try:
                        value = ingest_fcover(feature, nominal, args.overwrite, args.poll_seconds); record(value)
                        print(json.dumps({**label, "status": value["status"]}), flush=True)
                    except Exception as exc:
                        failure = {**label, "status": "FAILED", "error_type": type(exc).__name__,
                                   "error": str(exc), "traceback": traceback.format_exc(limit=8)}
                        failures.append(failure); save(failure_path, failures)
                        print(json.dumps({k: v for k, v in failure.items() if k != "traceback"}), flush=True)
                        if not args.continue_on_error: return 2
                if args.limit_units is not None and units >= args.limit_units: break
            if args.limit_units is not None and units >= args.limit_units: break

    units = 0
    if args.phase in ("pairs", "all"):
        for feature in features:
            for year in years:
                if args.limit_units is not None and units >= args.limit_units: break
                units += 1; label = {"phase": "pairs", "aoi_id": feature["properties"]["aoi_id"], "year": year}
                print(json.dumps({**label, "status": "STARTED"}), flush=True)
                try:
                    value = build_pair_cube(feature, year, overwrite=args.overwrite,
                                            poll_seconds=args.poll_seconds); record(value)
                    print(json.dumps({**label, "status": value["status"]}), flush=True)
                except Exception as exc:
                    failure = {**label, "status": "FAILED", "error_type": type(exc).__name__,
                               "error": str(exc), "traceback": traceback.format_exc(limit=8)}
                    failures.append(failure); save(failure_path, failures)
                    print(json.dumps({k: v for k, v in failure.items() if k != "traceback"}), flush=True)
                    if not args.continue_on_error: return 2
            if args.limit_units is not None and units >= args.limit_units: break

    if args.phase in ("manifest", "all"):
        value = export_manifest_table(records, True, args.poll_seconds); record(value)
    save(failure_path, failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
