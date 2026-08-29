#!/usr/bin/env python3
"""Freeze the Phase-0 safety interlock and immutable forensic evidence inventory."""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PUBLICATION = Path(__file__).resolve().parents[2]
WORKSPACE = PUBLICATION.parents[1]
sys.path.insert(0, str(PUBLICATION / "code" / "src"))

from execution.contract import load_contract  # noqa: E402
from execution.preparation_guard import (  # noqa: E402
    assert_no_forbidden_processes,
    assert_phase1_storage,
    assert_preparation_lock,
    canonical_json_sha256,
    deprecated_registry_paths,
    protected_inventory,
)

EXP = PUBLICATION / "new_experiments" / "15_three_sensor_parity"
OUT = EXP / "00_PHASE0_PROTECTION"
REVISION = EXP / "11_SENTINEL_SCIENTIFIC_PREPROCESSING_REVISION"


def main() -> int:
    contract = load_contract(PUBLICATION / "code" / "configs" / "scientific_execution.yaml")
    design_hash = assert_preparation_lock(contract)
    assert_no_forbidden_processes()

    r2 = sorted((REVISION / "corrected_inputs_cdse_r2").glob("SR-*/*.tif"))
    r3 = sorted((REVISION / "corrected_inputs_cdse_r3_harmonized").glob("SR-*/*.tif"))
    if len(r2) != 33 or len(r3) != 33:
        raise RuntimeError(f"PHASE0_SENTINEL_REVISION_INCOMPLETE:r2={len(r2)}:r3={len(r3)}")
    registry = REVISION / "03_DEPRECATED_INPUT_REGISTRY.csv"
    deprecated = deprecated_registry_paths(registry)
    key_evidence = [
        registry,
        REVISION / "SENTINEL_SOURCE_CONTRACT.yaml",
        EXP / "08_SENTINEL_STAGE0_REPAIR" / "04_CORRECTED_SENTINEL_MANIFEST.csv",
        EXP / "02_SENTINEL" / "SENTINEL_NATIVE_MASK_PARITY_v4.csv",
        EXP / "02_SENTINEL" / "SENTINEL_NATIVE_NDVI_PARITY_v4.csv",
        EXP / "09_EXTRACTION_ENGINE" / "SENTINEL_PARITY_CHECKPOINT.sqlite",
        EXP / "13_SENTINEL_SOURCE_SUPPORT_FORENSICS" / "03_DETECTOR_FOOTPRINT_AUDIT.csv",
    ]
    inventory = protected_inventory([*r2, *r3, *deprecated, *key_evidence], WORKSPACE)
    largest = max(row["size_bytes"] for row in inventory)
    minimum_phase1 = max(4 * 1024**3, 2 * largest + 1024**3)
    storage = assert_phase1_storage(WORKSPACE, minimum_free_bytes=minimum_phase1)

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "PROTECTED_EVIDENCE.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(inventory[0])); writer.writeheader(); writer.writerows(inventory)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "preparation_only",
        "scientific_execution_locked": True,
        "scientific_model_execution_authorized": False,
        "mass_asset_build_authorized": False,
        "allowed_scope": [
            "phase0_integrity_checks",
            "sentinel_source_support_forensics",
            "sentinel_stage1_stage2_canary_only_after_evidence_gate",
        ],
        "forbidden_scope": [
            "sentinel_stage3_stage4_stage5",
            "landsat_parity",
            "modis_parity",
            "final_fcover_build",
            "paired_cube_build",
            "multi_aoi_execution",
            "rolling_origin_execution",
        ],
        "design_hash": design_hash,
        "protected_file_count": len(inventory),
        "protected_inventory_hash": canonical_json_sha256(inventory),
        "storage": storage,
        "status": "PHASE0_LOCKED_PHASE1_FORENSICS_ONLY",
    }
    (OUT / "PHASE0_PROTECTION_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (OUT / "PHASE0_STATUS.md").write_text(
        "# Phase 0 protection status\n\n"
        "Status: **PASS — PHASE 1 FORENSICS ONLY**.\n\n"
        f"Frozen design hash: `{design_hash}`. Scientific execution, mass asset production, "
        "Sentinel Stages 3–5, Landsat/MODIS parity, Multi-AOI, and Rolling-Origin remain locked. "
        f"Protected evidence files: {len(inventory)}. Free bytes at audit: {storage['free_bytes']}.\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
