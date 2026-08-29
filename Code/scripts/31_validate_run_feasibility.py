#!/usr/bin/env python3
"""Validate all frozen run inputs without fitting, predicting, or scoring."""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[2]
sys.path.insert(0, str(ROOT / "src"))

from execution.contract import assert_design_contract, load_contract  # noqa: E402
from execution.science import SENSORS, _complete_history_blocks, _roles, sensor_band_prefix  # noqa: E402
from validation.leakage_audit import assert_chronology  # noqa: E402


def main() -> int:
    contract = load_contract(ROOT / "configs/scientific_execution.yaml")
    design_hash = assert_design_contract(contract)
    if contract.get("scientific_execution_enabled") is not False or contract.get("execution_acknowledged") is not False:
        raise RuntimeError("FEASIBILITY_REQUIRES_EXECUTION_INTERLOCK")
    output = WORKSPACE / contract["output_root"]
    pairs = pd.read_csv(output / "raw_machine_outputs/paired_observations.csv.gz")
    pair_audit_path = WORKSPACE / "report/publication/new_experiments/16_scientific_execution_readiness/02_final_pairs/PAIRED_CUBE_IMPACT_AUDIT.csv"
    pair_assets = {(row["aoi_id"], int(row["year"])): row["asset_id"] for row in
                   csv.DictReader(pair_audit_path.open(encoding="utf-8"))}
    registered = json.loads((output / "00_execution_manifest/SCIENTIFIC_EXECUTION_MANIFEST.json").read_text(encoding="utf-8"))
    registered_ids = {row["run_id"] for row in registered["units"]}
    multi_rows = []
    for aoi in contract["final_aoi_ids"]:
        for sensor in SENSORS:
            prefix = sensor_band_prefix(sensor)
            sensor_rows = pairs[(pairs.aoi_id == aoi) & (pairs.sensor == sensor)]
            for window in contract["multi_aoi_historical_windows"]:
                years = [int(year) for year in window["train_years"]]
                run_id = f"multi_aoi--{aoi}--{sensor}--{window['id']}"
                errors = []
                try:
                    historical = _complete_history_blocks(sensor_rows[sensor_rows.year.isin(years)], years)
                    historical = _roles(historical, contract)
                except RuntimeError as exc:
                    historical = pd.DataFrame(); errors.append(str(exc))
                target = sensor_rows[sensor_rows.year == 2025]
                development = historical[historical.spatial_role == "development"] if len(historical) else historical
                reserve = historical[historical.spatial_role == "reserve"] if len(historical) else historical
                if len(target) == 0: errors.append("EMPTY_TARGET")
                if len(development) == 0: errors.append("EMPTY_DEVELOPMENT")
                if len(reserve) == 0: errors.append("EMPTY_RESERVE")
                if len(development) and development.block_id.nunique() < 5: errors.append("GROUPKFOLD_LT_5_BLOCKS")
                for year in years:
                    if len(historical) and len(historical[historical.year == year]) == 0:
                        errors.append(f"EMPTY_COMPLETE_BLOCK_YEAR:{year}")
                if run_id not in registered_ids: errors.append("UNREGISTERED_RUN_ID")
                multi_rows.append({"run_id": run_id, "aoi_id": aoi, "sensor": sensor,
                                   "band_prefix": prefix, "window": window["id"],
                                   "train_years": ";".join(map(str, years)), "target_year": 2025,
                                   "train_rows": len(historical),
                                   "complete_train_blocks": historical.block_id.nunique() if len(historical) else 0,
                                   "development_rows": len(development),
                                   "development_blocks": development.block_id.nunique() if len(development) else 0,
                                   "reserve_rows": len(reserve),
                                   "reserve_blocks": reserve.block_id.nunique() if len(reserve) else 0,
                                   "target_rows": len(target), "target_blocks": target.block_id.nunique(),
                                   "input_artifact_ids": ";".join(pair_assets[(aoi, year)] for year in sorted(set(years + [2025]))),
                                   "errors": ";".join(errors), "status": "PASS" if not errors else "FAIL"})

    rolling_rows = []
    for aoi in contract["final_aoi_ids"]:
        for sensor in SENSORS:
            prefix = sensor_band_prefix(sensor)
            sensor_rows = pairs[(pairs.aoi_id == aoi) & (pairs.sensor == sensor)]
            for window in contract["rolling_origin"]["primary"]:
                years = [int(year) for year in window["history_years"]]; target_year = int(window["target_year"])
                run_id = f"rolling_origin--{aoi}--{sensor}--{window['id']}"
                errors = []
                try: assert_chronology(years, target_year)
                except ValueError as exc: errors.append(str(exc))
                train = sensor_rows[sensor_rows.year.isin(years)]; target = sensor_rows[sensor_rows.year == target_year]
                if len(train) == 0: errors.append("EMPTY_HISTORY")
                if len(target) == 0: errors.append("EMPTY_TARGET")
                for year in years:
                    if len(sensor_rows[sensor_rows.year == year]) == 0: errors.append(f"EMPTY_HISTORY_YEAR:{year}")
                if run_id not in registered_ids: errors.append("UNREGISTERED_RUN_ID")
                rolling_rows.append({"run_id": run_id, "aoi_id": aoi, "sensor": sensor,
                                     "band_prefix": prefix, "rolling_id": window["id"],
                                     "history_years": ";".join(map(str, years)), "target_year": target_year,
                                     "history_rows": len(train), "history_blocks": train.block_id.nunique(),
                                     "target_rows": len(target), "target_blocks": target.block_id.nunique(),
                                     "input_artifact_ids": ";".join(pair_assets[(aoi, year)] for year in sorted(set(years + [target_year]))),
                                     "errors": ";".join(errors), "status": "PASS" if not errors else "FAIL"})

    destination = output / "08_implementation_remediation/06_run_feasibility"
    destination.mkdir(parents=True, exist_ok=True)
    multi = pd.DataFrame(multi_rows); rolling = pd.DataFrame(rolling_rows)
    multi.to_csv(destination / "MULTI_AOI_RUN_FEASIBILITY.csv", index=False)
    rolling.to_csv(destination / "ROLLING_ORIGIN_RUN_FEASIBILITY.csv", index=False)
    observed_ids = set(multi.run_id) | set(rolling.run_id)
    result = {"generated_at": datetime.now(timezone.utc).isoformat(), "design_hash": design_hash,
              "multi_aoi": {"expected": 72, "observed": len(multi), "feasible": int((multi.status == "PASS").sum()),
                            "empty_or_failed": int((multi.status != "PASS").sum()), "duplicate_run_ids": int(multi.run_id.duplicated().sum())},
              "rolling_origin": {"expected": 72, "observed": len(rolling), "feasible": int((rolling.status == "PASS").sum()),
                                 "empty_or_failed": int((rolling.status != "PASS").sum()), "duplicate_run_ids": int(rolling.run_id.duplicated().sum())},
              "registered_run_ids_exact": observed_ids == registered_ids,
              "scientific_models_run": False, "predictions_computed": False,
              "formal_metrics_computed": False, "statistical_tests_run": False}
    result["status"] = "PASS" if (result["multi_aoi"]["feasible"] == 72 and
                                    result["rolling_origin"]["feasible"] == 72 and
                                    result["registered_run_ids_exact"]) else "FAIL"
    (destination / "RUN_MATRIX_FEASIBILITY_AUDIT.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
