#!/usr/bin/env python3
"""Build the active three-sensor parity gate from metric-level R2 evidence."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PUBLICATION = Path(__file__).resolve().parents[2]
WORKSPACE = PUBLICATION.parents[1]
sys.path.insert(0, str(PUBLICATION / "code" / "src"))

from execution.contract import assert_parity_validation_contract, load_contract, processing_hash  # noqa: E402

EXP = PUBLICATION / "new_experiments" / "15_three_sensor_parity"
ROOT = EXP / "16_THREE_SENSOR_PARITY_R2"
CONTRACT = EXP / "15_ACTIVE_SOURCE_IDENTITY_CONTRACT" / "SOURCE_IDENTITY_CONTRACT.json"
PHASE1 = EXP / "14_SENTINEL_SOURCE_SUPPORT_DECOMPOSITION" / "16_FINAL_SUPPORT_DECOMPOSITION_REPORT.md"
ACTIVE = EXP / "07_FINAL_GATE"
DESIGN_HASH = "b21c8cc7f3d4d35e1db4dfa1c8245ff10ba657c0a0a001992b552808766cc49b"

SENSORS = {
    "Sentinel-2": {
        "root": ROOT / "02_SENTINEL", "prefix": "SENTINEL", "suffix": "_v4",
        "report": "SENTINEL_PARITY_RESULT.md", "scene_count": 11,
    },
    "Landsat-8/9": {
        "root": ROOT / "03_LANDSAT", "prefix": "LANDSAT", "suffix": "",
        "report": "LANDSAT_PARITY_RESULT.md", "scene_count": 12,
    },
    "MODIS": {
        "root": ROOT / "04_MODIS", "prefix": "MODIS", "suffix": "",
        "report": "MODIS_PARITY_RESULT.md", "scene_count": 4,
    },
}


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def numeric_pass(row: dict[str, str]) -> bool:
    if int(row["mask_disagreement"]) != 0:
        return False
    if int(row["valid_local"]) == 0 and int(row["valid_GEE"]) == 0:
        return True
    return (float(row["mean_absolute_difference"]) <= 1e-6 and
            float(row["implementation_RMSE"]) <= 1e-6 and
            float(row["max_absolute_difference"]) <= 1e-5)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_sensor(name: str, config: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    root, prefix, suffix = config["root"], config["prefix"], config["suffix"]
    mask_path = root / f"{prefix}_NATIVE_MASK_PARITY{suffix}.csv"
    ndvi_path = root / f"{prefix}_NATIVE_NDVI_PARITY{suffix}.csv"
    aggregate_path = root / f"{prefix}_300M_PARITY{suffix}.csv"
    count_path = root / f"{prefix}_CONTRIBUTION_PARITY{suffix}.csv"
    temporal_path = root / f"{prefix}_TEMPORAL_PARITY{suffix}.csv"
    grid_path = root / f"{prefix}_GRID_PARITY{suffix}.csv"
    report_path = root / config["report"]
    paths = [mask_path, ndvi_path, aggregate_path, count_path, temporal_path, grid_path, report_path]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise RuntimeError(f"PARITY_GATE_EVIDENCE_MISSING:{name}:{missing}")
    mask = rows(mask_path); ndvi = rows(ndvi_path); aggregate = rows(aggregate_path)
    count = rows(count_path); temporal = rows(temporal_path); grid = rows(grid_path)
    expected = config["scene_count"]
    if name == "Sentinel-2" and len(mask) == expected + 1:
        mask = [row for row in mask if row.get("scene_id") != "AGGREGATE"]
    checks = [
        {"sensor": name, "stage": "Stage 0 source identity", "verdict": "PASS", "detail": "active R2 asset-verified contract"},
        {"sensor": name, "stage": "Stage 1 native QA mask",
         "verdict": "PASS" if len(mask) == expected and all(int(row["disagreement_pixels"]) == 0 for row in mask) else "FAIL",
         "detail": f"scenes={len(mask)}; max_disagreement={max(int(row['disagreement_pixels']) for row in mask)}"},
        {"sensor": name, "stage": "Stage 2 native NDVI",
         "verdict": "PASS" if len(ndvi) == expected and all(numeric_pass(row) for row in ndvi) else "FAIL",
         "detail": f"scenes={len(ndvi)}; max_abs={max((float(row['max_absolute_difference']) for row in ndvi if not math.isnan(float(row['max_absolute_difference']))), default=0)}"},
        {"sensor": name, "stage": "Stage 3 exact FCOVER support",
         "verdict": "PASS" if len(aggregate) == expected and all(numeric_pass(row) for row in aggregate) else "FAIL",
         "detail": f"scenes={len(aggregate)}; max_abs={max((float(row['max_absolute_difference']) for row in aggregate if not math.isnan(float(row['max_absolute_difference']))), default=0)}"},
        {"sensor": name, "stage": "Stage 4 contribution count",
         "verdict": "PASS" if len(count) == 1 and int(count[0]["count_disagreement"]) == 0 else "FAIL",
         "detail": f"count_disagreement={count[0].get('count_disagreement')}"},
        {"sensor": name, "stage": "Stage 5 temporal composite",
         "verdict": "PASS" if len(temporal) == 1 and numeric_pass(temporal[0]) else "FAIL",
         "detail": f"mask_disagreement={temporal[0].get('mask_disagreement')}; max_abs={temporal[0].get('max_absolute_difference')}"},
        {"sensor": name, "stage": "Exact target grid",
         "verdict": "PASS" if len(grid) == 1 and grid[0].get("verdict") == "PASS" and float(grid[0]["max_affine_difference"]) <= 1e-12 else "FAIL",
         "detail": f"affine_difference={grid[0].get('max_affine_difference')}"},
    ]
    if "Final verdict: **PASS**." not in report_path.read_text(encoding="utf-8"):
        checks.append({"sensor": name, "stage": "Sensor final report", "verdict": "FAIL", "detail": "report not PASS"})
    summary = {
        "sensor": name, "scene_count": expected,
        "max_native_mask_disagreement": max(int(row["disagreement_pixels"]) for row in mask),
        "max_native_ndvi_abs_difference": max((float(row["max_absolute_difference"]) for row in ndvi if not math.isnan(float(row["max_absolute_difference"]))), default=0),
        "max_300m_abs_difference": max((float(row["max_absolute_difference"]) for row in aggregate if not math.isnan(float(row["max_absolute_difference"]))), default=0),
        "contribution_count_disagreement": int(count[0]["count_disagreement"]),
        "temporal_mask_disagreement": int(temporal[0]["mask_disagreement"]),
        "temporal_max_abs_difference": float(temporal[0]["max_absolute_difference"]),
        "evidence_hashes": {path.name: file_hash(path) for path in paths},
    }
    summary["verdict"] = "PASS" if all(row["verdict"] == "PASS" for row in checks) else "FAIL"
    return checks, summary


def write_csv(path: Path, values: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in values for key in row})
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(values)


def main() -> int:
    runtime = load_contract(PUBLICATION / "code" / "configs" / "scientific_execution.yaml")
    assert_parity_validation_contract(runtime)
    source = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if (source["scientific_design_hash"] != DESIGN_HASH or source["row_count"] != 27 or
            source["sensor_counts"] != {"Sentinel-2": 11, "Landsat-8/9": 12, "MODIS": 4}):
        raise RuntimeError("THREE_SENSOR_GATE_SOURCE_CONTRACT_FAIL")
    if "SENTINEL_STAGE1_SUPPORT_CERTIFIED: TRUE" not in PHASE1.read_text(encoding="utf-8"):
        raise RuntimeError("THREE_SENSOR_GATE_SENTINEL_SUPPORT_NOT_CERTIFIED")
    matrix: list[dict[str, Any]] = []; summaries = []
    for name, config in SENSORS.items():
        checks, summary = validate_sensor(name, config); matrix.extend(checks); summaries.append(summary)
    overall = "PASS" if all(summary["verdict"] == "PASS" for summary in summaries) else "FAIL"
    processing = processing_hash()
    audit = ROOT / "05_CROSS_SENSOR_AUDIT"
    write_csv(audit / "THREE_SENSOR_PARITY_MATRIX.csv", matrix)
    write_csv(audit / "THREE_SENSOR_PARITY_SUMMARY.csv", summaries)
    (audit / "PROCESSING_REVISION_IMPACT.md").write_text(
        "# Processing-revision impact\n\n"
        "The R2 revision repairs only source identity, mask-aware GeoTIFF interpretation, exact native-window "
        "support, and cross-CRS coverage weighting. It does not change scene inclusion, QA rules, reflectance "
        "scaling, NDVI, FCOVER grid, temporal order, minimum contribution count, tolerances, or scientific design.\n",
        encoding="utf-8",
    )
    record = {
        "generated_at": datetime.now(timezone.utc).isoformat(), "status": overall,
        "three_sensor_parity_gate": overall, "scientific_design_hash": DESIGN_HASH,
        "source_manifest_hash": source["manifest_hash"], "processing_hash": processing,
        "sensor_summaries": summaries, "models_run": False, "assets_written": False,
        "multi_aoi_run": False, "rolling_origin_run": False,
    }
    gate_root = ROOT / "07_FINAL_GATE"; gate_root.mkdir(parents=True, exist_ok=True)
    (gate_root / "ACTIVE_GATE.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    sensor_lines = "\n".join(f"| {row['sensor']} | {row['scene_count']} | {row['verdict']} |" for row in summaries)
    gate_text = (
        "# Active three-sensor preprocessing parity gate R2\n\n"
        f"THREE_SENSOR_PARITY_GATE = **{overall}**\n\n"
        f"Scientific design hash: `{DESIGN_HASH}`. Source manifest hash: `{source['manifest_hash']}`. "
        f"Processing hash: `{processing}`.\n\n"
        "| Sensor | Frozen observations | Final verdict |\n|---|---:|---|\n" + sensor_lines + "\n\n"
        "PASS is derived from metric-level Stage 0–5 evidence with zero mask/count disagreement and the frozen "
        "numeric tolerances. No model, Multi-AOI, Rolling-Origin, paired cube, final FCOVER build, or GEE asset write occurred.\n"
    )
    (gate_root / "THREE_SENSOR_PARITY_GATE.md").write_text(gate_text, encoding="utf-8")
    (gate_root / "FINAL_THREE_SENSOR_PARITY_REPORT.md").write_text(
        gate_text + "\nSee `../05_CROSS_SENSOR_AUDIT/THREE_SENSOR_PARITY_MATRIX.csv` for every stage-level decision.\n",
        encoding="utf-8",
    )

    # Preserve the former canonical blocker before publishing a pointer to the
    # active revision.  Historical evidence is never silently erased.
    ACTIVE.mkdir(parents=True, exist_ok=True)
    old_gate = ACTIVE / "THREE_SENSOR_PARITY_GATE.md"
    old_report = ACTIVE / "FINAL_THREE_SENSOR_PARITY_REPORT.md"
    if old_gate.exists() and not (ACTIVE / "THREE_SENSOR_PARITY_GATE_v1_BLOCKED.md").exists():
        (ACTIVE / "THREE_SENSOR_PARITY_GATE_v1_BLOCKED.md").write_text(old_gate.read_text(encoding="utf-8"), encoding="utf-8")
    if old_report.exists() and not (ACTIVE / "FINAL_THREE_SENSOR_PARITY_REPORT_v1_BLOCKED.md").exists():
        (ACTIVE / "FINAL_THREE_SENSOR_PARITY_REPORT_v1_BLOCKED.md").write_text(old_report.read_text(encoding="utf-8"), encoding="utf-8")
    old_gate.write_text(gate_text + "\nActive evidence: `../16_THREE_SENSOR_PARITY_R2/07_FINAL_GATE/`.\n", encoding="utf-8")
    old_report.write_text(gate_text + "\nActive evidence: `../16_THREE_SENSOR_PARITY_R2/07_FINAL_GATE/`.\n", encoding="utf-8")
    (ACTIVE / "ACTIVE_GATE.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"THREE_SENSOR_PARITY_GATE:{overall}")
    return 0 if overall == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
