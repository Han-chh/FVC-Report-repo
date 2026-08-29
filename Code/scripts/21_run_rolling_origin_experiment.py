#!/usr/bin/env python3
"""Run the frozen 2024/2025 rolling-origin temporal evaluation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from execution.contract import assert_execution_contract, assert_readiness_contract, load_contract
from execution.identity import active_processing_hash
from execution.gate import run_pre_execution_gate
from execution.science import SENSORS, run_rolling_origin
from rolling_origin.runner import require_scientific_acknowledgement
from validation.leakage_audit import assert_chronology


def _load_validated_preflight(contract: dict, design_hash: str) -> dict:
    """Bind formal execution to the last readiness-mode preflight snapshot."""
    output = Path(contract["output_root"])
    output = output if output.is_absolute() else ROOT.parents[2] / output
    path = output / "00_execution_manifest/PRE_EXECUTION_GATE.json"
    gate = json.loads(path.read_text(encoding="utf-8"))
    if gate.get("status") != "PASS" or gate.get("actual_design_hash") != design_hash:
        raise RuntimeError("VALIDATED_PREFLIGHT_SNAPSHOT_REQUIRED:rolling_origin")
    return gate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--config", type=Path, default=ROOT / "configs/scientific_execution.yaml")
    args = parser.parse_args()
    contract = load_contract(args.config)
    if args.execute:
        require_scientific_acknowledgement(contract)
        design_hash = assert_execution_contract(contract)
        gate = _load_validated_preflight(contract, design_hash)
    else:
        design_hash = assert_readiness_contract(contract)
        gate = run_pre_execution_gate(contract, write=True)
    for window in contract["rolling_origin"]["primary"]:
        assert_chronology(window["history_years"], window["target_year"])
    if args.validate:
        print(json.dumps(gate, indent=2)); return 0 if gate["status"] == "PASS" else 2
    if args.dry_run:
        plan = [{"aoi": aoi, "sensor": sensor, **window} for aoi in contract["final_aoi_ids"] for sensor in SENSORS for window in contract["rolling_origin"]["primary"]]
        output = Path(contract["output_root"])
        output = output if output.is_absolute() else ROOT.parents[2] / output
        destination = output / "00_execution_manifest/ROLLING_ORIGIN_DRY_RUN.json"
        destination.write_text(json.dumps({"design_hash": design_hash, "processing_hash": active_processing_hash(contract), "gate_status": gate["status"], "expected_runs": plan, "scientific_results_executed": False}, indent=2), encoding="utf-8")
        print(json.dumps({"gate_status": gate["status"], "expected_run_count": len(plan), "path": str(destination)}, indent=2)); return 0
    if gate["status"] != "PASS":
        raise RuntimeError("PRE_EXECUTION_GATE_FAILED:rolling_origin")
    frames = run_rolling_origin(contract)
    print(json.dumps({name: len(frame) for name, frame in frames.items()}, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
