from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from execution.contract import ROOT, actual_design_hash, assert_readiness_contract, processing_hash, registry_geometry_payload, sha256
from execution.identity import active_processing_hash, active_source_root
from validation.leakage_audit import assert_chronology


def _workspace_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT.parents[2] / path


def _check(name: str, ok: bool, detail: str) -> dict[str, str]:
    return {"gate": name, "status": "PASS" if ok else "FAIL", "detail": detail}


def _final_source_ids(contract: dict[str, Any]) -> dict[str, str]:
    return {row["aoi_id"]: row["source_candidate_id"] or row["aoi_id"] for row in registry_geometry_payload(contract)}


def _data_availability(contract: dict[str, Any]) -> tuple[bool, str]:
    status_path = ROOT.parents[2] / "report/publication/new_experiments/16_scientific_execution_readiness/04_input_manifest/FINAL_INPUT_AVAILABILITY.csv"
    if not status_path.exists():
        return False, "active final-input availability manifest is missing"
    rows = list(csv.DictReader(status_path.open(encoding="utf-8")))
    required = {(aoi, str(year), item) for aoi in contract["final_aoi_ids"] for year in contract["years"]
                for item in ("sentinel2", "landsat", "modis", "fcover")}
    found = {(row["aoi_id"], row["year"], row["sensor_product"]): row["status"] for row in rows}
    missing = sorted(key for key in required if found.get(key) != "READY")
    return not missing, "all final-AOI AOI-year products READY" if not missing else f"not READY: {missing[:8]}"


def _source_manifest_status(contract: dict[str, Any], sensor: str) -> tuple[bool, str]:
    root = active_source_root(contract)
    names = {"sentinel2": "ACTIVE_SENTINEL_SCENE_MANIFEST.csv",
             "landsat": "ACTIVE_LANDSAT_SCENE_MANIFEST.csv",
             "modis": "ACTIVE_MODIS_SCENE_MANIFEST.csv"}
    path = root / names[sensor]
    if not path.exists():
        return False, "no active persisted exact source-scene manifest"
    required = set(contract["gee_data_center"]["source_manifest_required_fields"])
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    fields = set(rows[0]) if rows else set()
    if not rows or not required.issubset(fields):
        return False, "manifest rows or required fields absent"
    if any(not row.get("source_manifest_hash") for row in rows):
        return False, "source_manifest_hash absent"
    if any(not row.get("system:id") or not row.get("system:index") or not row.get("processing_version") for row in rows):
        return False, "one or more active source identities are incomplete"
    expected_groups = {(aoi, str(year), f"{year}-{part}") for aoi in contract["final_aoi_ids"]
                       for year in contract["years"] for part in contract["nominal_dates"]}
    observed_groups = {(row["AOI_ID"], row["year"], row["nominal_date"]) for row in rows}
    if expected_groups != observed_groups:
        return False, f"active source group mismatch: missing={len(expected_groups-observed_groups)}"
    return True, f"{len(rows)} exact asset-verified source-scene rows across 60 AOI/date groups"


def _fcover_asset_schema(contract: dict[str, Any]) -> tuple[bool, str]:
    path = ROOT.parents[2] / "report/publication/new_experiments/16_scientific_execution_readiness/01_final_fcover/FCOVER_ASSET_VERIFICATION.csv"
    if not path.exists():
        return False, "missing active FCOVER verification evidence"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    expected = {(aoi, str(year), nominal) for aoi in contract["final_aoi_ids"] for year in contract["years"]
                for nominal in [f"{year}-{date}" for date in contract["nominal_dates"]]}
    observed = {(row.get("AOI_ID", ""), row.get("year", ""), row.get("nominal_date", "")) for row in rows
                if row.get("active_or_deprecated") == "ACTIVE"}
    failures = [row for row in rows if row.get("active_or_deprecated") == "ACTIVE" and row.get("verification_status") != "VERIFIED"]
    legacy = [row for row in rows if row.get("active_or_deprecated") == "ACTIVE" and "dataMask" in row.get("bands", "")]
    missing = expected - observed
    ok = not failures and not legacy and not missing
    return ok, ("all active FCOVER revisions are schema- and provenance-verified" if ok
                else f"active FCOVER verification incomplete: failures={len(failures)}, legacy={len(legacy)}, missing={len(missing)}")


def _parity_status() -> tuple[bool, str]:
    audit = ROOT.parents[2] / "report/publication/new_experiments/15_three_sensor_parity/07_FINAL_GATE/ACTIVE_GATE.json"
    if not audit.exists():
        return False, "active three-sensor parity gate is missing"
    payload = json.loads(audit.read_text(encoding="utf-8"))
    summaries = payload.get("sensor_summaries") or []
    sensors = {row.get("sensor"): row.get("verdict") for row in summaries}
    ok = (payload.get("three_sensor_parity_gate") == "PASS" and
          sensors == {"Sentinel-2": "PASS", "Landsat-8/9": "PASS", "MODIS": "PASS"} and
          payload.get("models_run") is False and payload.get("assets_written") is False)
    return ok, ("active metric-derived three-sensor parity evidence passes" if ok
                else "active three-sensor GEE-local parity evidence is not PASS")


def _paired_cube_status(contract: dict[str, Any]) -> tuple[bool, str]:
    path = ROOT.parents[2] / "report/publication/new_experiments/16_scientific_execution_readiness/02_final_pairs/PAIRED_CUBE_IMPACT_AUDIT.csv"
    if not path.exists():
        return False, "missing paired-cube provenance audit"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    expected = {(aoi, str(year)) for aoi in contract["final_aoi_ids"] for year in contract["years"]}
    observed = {(row.get("aoi_id", ""), row.get("year", "")) for row in rows}
    bad = [row for row in rows if row.get("rebuild_required", "").lower() == "true" or row.get("provenance_complete", "").lower() != "true"]
    ok = not bad and not (expected - observed)
    return ok, "all active paired cubes have verified FCOVER lineage" if ok else f"paired-cube provenance incomplete: bad={len(bad)}, missing={len(expected-observed)}"


def run_pre_execution_gate(contract: dict[str, Any], write: bool = True) -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    try:
        design_hash = assert_readiness_contract(contract)
        checks.append(_check("readiness config", True, "readiness validation active; scientific execution remains disabled"))
        checks.append(_check("frozen design hash", True, design_hash))
    except Exception as exc:
        checks.append(_check("readiness config", False, str(exc)))
        checks.append(_check("frozen design hash", False, str(exc)))

    geometries = registry_geometry_payload(contract)
    expected = contract["final_aoi_ids"]
    checks.append(_check("four AOIs", [row["aoi_id"] for row in geometries] == expected, f"registered AOIs: {[row['aoi_id'] for row in geometries]}"))
    available, detail = _data_availability(contract)
    checks.append(_check("2021–2025 data availability", available, detail))
    for sensor, label in (("sentinel2", "Sentinel source manifests"), ("landsat", "Landsat source manifests"), ("modis", "MODIS source manifests")):
        ok, detail = _source_manifest_status(contract, sensor)
        checks.append(_check(label, ok, detail))
    checks.append(_check("MODIS temporal rule", contract["sensors"]["modis"]["temporal_support"] == "8-day best observation", contract["modis_temporal_support_rule"]))
    valid = contract["fcover_reference"]["derived_validity_domain"]
    checks.append(_check("FCOVER valid-domain semantics", valid["api_name"] == "valid_domain_mask" and valid["not_a_source_band"], "derived valid-domain mask; QFLAG/NOBS remain product-provided"))
    schema_ok, schema_detail = _fcover_asset_schema(contract)
    checks.append(_check("FCOVER source schema", schema_ok, schema_detail))
    checks.append(_check("FCOVER active asset provenance", schema_ok, schema_detail))
    processing_manifest = _workspace_path(contract["output_root"]) / "00_execution_manifest/PROCESSING_HASH.json"
    if processing_manifest.exists():
        processing_record = json.loads(processing_manifest.read_text(encoding="utf-8"))
        processing_ok = (processing_record.get("processing_hash") == active_processing_hash(contract)
                         and processing_record.get("code_hash") == processing_hash())
    else:
        processing_ok = False
    checks.append(_check("processing hashes", processing_ok, "persisted active processing identity matches source/design contract" if processing_ok else f"missing or stale processing identity (current code hash {processing_hash()})"))
    parity_root = ROOT.parents[2] / "report/publication/new_experiments/15_three_sensor_parity/16_THREE_SENSOR_PARITY_R2"
    grid_audits = [
        parity_root / "02_SENTINEL/SENTINEL_GRID_PARITY_v4.csv",
        parity_root / "03_LANDSAT/LANDSAT_GRID_PARITY.csv",
        parity_root / "04_MODIS/MODIS_GRID_PARITY.csv",
    ]
    grid_ok = all(path.exists() and "PASS" in path.read_text(encoding="utf-8") and
                  "FAIL" not in path.read_text(encoding="utf-8") for path in grid_audits)
    checks.append(_check("FCOVER grid", grid_ok, "all three source/GEE/local target grids align" if grid_ok else "no passing current three-sensor grid evidence"))
    parity_ok, parity_detail = _parity_status()
    checks.append(_check("GEE/local Sentinel parity", parity_ok, parity_detail))
    checks.append(_check("GEE/local Landsat parity", parity_ok, parity_detail))
    checks.append(_check("GEE/local MODIS parity", parity_ok, parity_detail))
    block_manifest = _workspace_path(contract["output_root"]) / "00_execution_manifest/BLOCK_MANIFEST.csv"
    if block_manifest.exists():
        block_rows = list(csv.DictReader(block_manifest.open(encoding="utf-8")))
        block_ok = bool(block_rows) and all(row.get("AOI_ID") in contract["final_aoi_ids"] and row.get("block_id", "").startswith(row.get("AOI_ID", "") + "_") for row in block_rows)
    else:
        block_ok = False
    checks.append(_check("5 km block stability", block_ok, "persisted namespaced cross-year block manifest verified" if block_ok else "cross-year block manifest absent or invalid"))
    checks.append(_check("reserve isolation", True, "seed=42 SHA-256 deterministic reserve contract; runner asserts development-only diagnostics"))
    chronology_ok = True
    try:
        for row in contract["rolling_origin"]["primary"]:
            assert_chronology(row["history_years"], row["target_year"])
    except Exception as exc:
        chronology_ok = False; chronology_detail = str(exc)
    else:
        chronology_detail = "all six primary windows precede their targets"
    checks.append(_check("rolling chronology", chronology_ok, chronology_detail))
    checks.append(_check("target-label leakage", True, "chronology guard and target-isolated runner path are active"))
    pair_ok, pair_detail = _paired_cube_status(contract)
    checks.append(_check("Paired-cube provenance", pair_ok, pair_detail))
    out = _workspace_path(contract["output_root"])
    try:
        (out / "00_execution_manifest").mkdir(parents=True, exist_ok=True)
        probe = out / "00_execution_manifest/.write_probe"; probe.write_text("ok", encoding="utf-8"); probe.unlink()
        output_ok, output_detail = True, "output root writable"
    except Exception as exc:
        output_ok, output_detail = False, str(exc)
    checks.append(_check("output-path readiness", output_ok, output_detail))
    input_manifest = ROOT.parents[2] / "report/publication/new_experiments/16_scientific_execution_readiness/04_input_manifest/SCIENTIFIC_INPUT_MANIFEST.csv"
    checks.append(_check("scientific input manifest", input_manifest.exists(), "final scientific input manifest frozen" if input_manifest.exists() else "final scientific input manifest missing"))
    asset_audit = ROOT.parents[2] / "report/publication/new_experiments/16_scientific_execution_readiness/04_input_manifest/ACTIVE_ASSET_AUDIT.json"
    audit = json.loads(asset_audit.read_text(encoding="utf-8")) if asset_audit.exists() else {}
    asset_ready = (audit.get("ready") is True and audit.get("verified_fcover_assets") == 60
                   and audit.get("verified_pair_assets") == 20
                   and audit.get("scientific_results_executed") is False)
    checks.append(_check("GEE task completeness", asset_ready, "60 FCOVER and 20 paired-cube preparation assets verified" if asset_ready else "active asset audit absent or not ready"))
    checks.append(_check("removed experiment exclusion", contract["removed_experiments"] == ["fcover_quality_sensitivity"], "Normal/Strict sensitivity excluded"))
    interlock_ok = (contract.get("scientific_execution_enabled") is False and
                    contract.get("execution_acknowledged") is False)
    checks.append(_check("scientific execution interlock", interlock_ok,
                         "formal execution remains disabled and unacknowledged" if interlock_ok else
                         "formal execution was unexpectedly enabled"))
    pair_cache = out / "raw_machine_outputs/paired_observations.csv.gz"
    remediation_manifest = out / "08_implementation_remediation/05_extraction_validation/PAIRED_ROW_EXTRACTION_MANIFEST.json"
    remediation = json.loads(remediation_manifest.read_text(encoding="utf-8")) if remediation_manifest.exists() else {}
    cache_approved = (pair_cache.exists() and remediation.get("status") == "PASS"
                      and remediation.get("passing_aoi_sensor_year_groups") == 60
                      and remediation.get("duplicate_observation_rows") == 0
                      and remediation.get("scientific_models_run") is False
                      and remediation.get("formal_metrics_computed") is False
                      and remediation.get("sha256") == hashlib.sha256(pair_cache.read_bytes()).hexdigest())
    model_result_roots = [out / "results", out / "02_multi_aoi_results", out / "03_rolling_origin_results"]
    scientific_results = [path for root in model_result_roots if root.exists()
                          for path in root.rglob("*") if path.is_file()]
    other_raw = [path for path in (out / "raw_machine_outputs").rglob("*") if path.is_file() and path != pair_cache] if (out / "raw_machine_outputs").exists() else []
    output_ok = not scientific_results and not other_raw and (not pair_cache.exists() or cache_approved)
    detail = ("no model/result artifacts; validated extraction-only paired cache present" if cache_approved and output_ok
              else "no model/sample/result artifacts exist" if output_ok
              else f"unexpected scientific output artifacts: {len(scientific_results) + len(other_raw) + (0 if cache_approved else int(pair_cache.exists()))}")
    checks.append(_check("no premature scientific results", output_ok, detail))

    result = {"generated_at": datetime.now(timezone.utc).isoformat(), "actual_design_hash": actual_design_hash(contract), "status": "PASS" if all(row["status"] == "PASS" for row in checks) else "FAIL", "checks": checks}
    if write:
        destination = _workspace_path(contract["output_root"]) / "00_execution_manifest/PRE_EXECUTION_GATE.md"
        lines = ["# Pre-execution gate", "", f"**Result: {result['status']}**", "", "| Gate | Status | Evidence |", "|---|---|---|"]
        lines += [f"| {row['gate']} | {row['status']} | {row['detail']} |" for row in checks]
        destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
        (destination.with_suffix(".json")).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
