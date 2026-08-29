#!/usr/bin/env python3
"""Rebuild and audit paired rows without fitting or scoring a model."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[2]
sys.path.insert(0, str(ROOT / "src"))

from execution.contract import assert_design_contract, load_contract  # noqa: E402
from execution.science import extract_paired_observations  # noqa: E402


def main() -> int:
    contract = load_contract(ROOT / "configs/scientific_execution.yaml")
    assert_design_contract(contract)
    if contract.get("scientific_execution_enabled") is not False:
        raise RuntimeError("REMEDIATION_REQUIRES_EXECUTION_DISABLED")
    if contract.get("execution_acknowledged") is not False:
        raise RuntimeError("REMEDIATION_REQUIRES_EXECUTION_UNACKNOWLEDGED")
    output = WORKSPACE / contract["output_root"]
    quarantine = output / "08_implementation_remediation/02_invalid_cache_quarantine/INVALID_CACHE_QUARANTINE_MANIFEST.json"
    record = json.loads(quarantine.read_text(encoding="utf-8"))
    if record.get("status") != "PRESERVED_AND_DISABLED" or record.get("reuse_forbidden") is not True:
        raise RuntimeError("INVALID_CACHE_NOT_SAFELY_QUARANTINED")
    audit = output / "08_implementation_remediation/05_extraction_validation"
    frame = extract_paired_observations(contract, audit_directory=audit)
    groups = frame.groupby(["aoi_id", "sensor", "year"]).ngroups
    print(json.dumps({"status": "EXTRACTION_ONLY_COMPLETE", "rows": len(frame),
                      "aoi_sensor_year_groups": groups,
                      "scientific_models_run": False,
                      "formal_metrics_computed": False,
                      "audit_directory": str(audit)}, indent=2))
    return 0 if groups == 60 else 2


if __name__ == "__main__":
    raise SystemExit(main())
