from __future__ import annotations

import importlib.util
import csv
import json
from pathlib import Path

import numpy as np
import pytest

from execution.contract import assert_parity_validation_contract, assert_readiness_contract, load_contract
from execution.preparation_guard import (
    assert_active_sentinel_revision,
    assert_preparation_lock,
    running_forbidden_processes,
)


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_readiness_contract_preserves_design_and_keeps_models_locked():
    contract = load_contract(ROOT / "configs" / "scientific_execution.yaml")
    assert assert_readiness_contract(contract) == contract["frozen_design_hash"]
    with pytest.raises(RuntimeError, match="PARITY_VALIDATION_PHASE_NOT_ACTIVE"):
        assert_parity_validation_contract(contract)
    assert contract["scientific_execution_enabled"] is False
    assert contract["execution_acknowledged"] is False
    with pytest.raises(RuntimeError, match="PHASE0_REQUIRES_PREPARATION_ONLY"):
        assert_preparation_lock(contract)
    assert contract["phase"] == "scientific_execution_ready"
    assert contract["scientific_execution_enabled"] is False
    assert contract["execution_acknowledged"] is False


def test_phase0_detects_forbidden_execution_processes():
    process = "python scripts/20_run_multi_aoi_experiment.py --execute"
    assert running_forbidden_processes(process) == [process]
    assert running_forbidden_processes("python scripts/23_decompose_sentinel_source_support.py") == []


def test_stale_sentinel_revision_is_rejected():
    assert_active_sentinel_revision(
        Path("corrected_inputs_cdse_r3_harmonized/SR-01"),
        expected_revision="corrected_inputs_cdse_r3_harmonized",
    )
    with pytest.raises(RuntimeError, match="STALE_SENTINEL_INPUT_REJECTED"):
        assert_active_sentinel_revision(
            Path("corrected_inputs_cdse_r2/SR-01"),
            expected_revision="corrected_inputs_cdse_r3_harmonized",
        )


def test_harmonization_baseline_and_double_application_guards():
    module = load_script("18_harmonize_existing_sentinel_parity_inputs.py")
    raw = np.array([[0, 999, 1000, 2450]], dtype="uint16")
    shifted = module.harmonize_dn(raw, processing_baseline=5.11, source_revision=module.SOURCE_REVISION)
    assert shifted.tolist() == [[0, 0, 0, 1450]]
    unchanged = module.harmonize_dn(raw, processing_baseline=3.01, source_revision=module.SOURCE_REVISION)
    assert np.array_equal(unchanged, raw)
    with pytest.raises(RuntimeError, match="SOURCE_REVISION_REJECTED"):
        module.harmonize_dn(raw, processing_baseline=5.11, source_revision=module.TARGET_REVISION)


def test_phase1_pixel_categories_conserve_disagreement():
    module = load_script("23_decompose_sentinel_source_support.py")
    disagreement = np.array([[True, True], [True, False]])
    detector = np.array([[False, True], [False, False]])
    support = np.array([[False, True], [True, False]])
    valid = np.array([[False, True], [False, False]])
    scl = np.array([[False, True], [True, False]])
    export_mask = np.array([[False, True], [True, False]])
    raw = np.array([[-9999.0, 1.0], [1.0, 0.0]], dtype="float32")
    counts = module.category_counts(disagreement, detector, support, valid, scl, export_mask, raw)
    assert sum(counts.values()) == int(disagreement.sum())
    assert counts["GEE_EXPORT_MASK_FALSE+RAW_NODATA_NONZERO+BOOL_TRUE+LOCAL_INVALID"] == 1
    assert counts["DETFOO_TRUE+CDSE_REFLECTANCE_VALID+SCL_SUPPORTED+LOCAL_INVALID+GEE_VALID"] == 1
    assert counts["DETFOO_FALSE+CDSE_REFLECTANCE_INVALID+LOCAL_INVALID+GEE_VALID"] == 1


def test_full_parity_runner_remains_locked_at_stage3_to_5():
    source = (ROOT / "scripts" / "15_run_sentinel_parity.py").read_text(encoding="utf-8")
    assert "SENTINEL_STAGE3_TO_5_LOCKED_PENDING_PHASE1_SUPPORT_CERTIFICATION" in source
    assert "corrected_inputs_cdse_r3_harmonized" in source
    assert "assert_parity_validation_contract(contract)" in source
    assert "dataset.read_masks()" in source
    assert '.unmask(0, False)' in source


def test_tiled_parity_runner_requires_execution_and_mask_aware_downloads():
    source = (ROOT / "scripts" / "15_run_sentinel_tiled_native_parity.py").read_text(encoding="utf-8")
    assert "assert_parity_validation_contract(contract)" in source
    assert "GEE_DOWNLOAD_CONTAINS_MASKED_SAMPLES" in source
    assert "valid.unmask(0, False)" in source


def test_completed_phase1_evidence_conserves_all_affected_pixels():
    evidence = ROOT.parent / "new_experiments" / "15_three_sensor_parity" / "14_SENTINEL_SOURCE_SUPPORT_DECOMPOSITION"
    record = json.loads((evidence / "PHASE1_EXECUTION_RECORD.json").read_text(encoding="utf-8"))
    assert record["scene_count"] == 11
    assert record["classification"] == "GEE_EXPORT_NODATA_BOOLEAN_CAST_IMPLEMENTATION_ERROR"
    assert not record["models_run"] and not record["assets_written"]
    categories = list(csv.DictReader((evidence / "04_PIXEL_SUPPORT_CATEGORIES.csv").open(encoding="utf-8")))
    assert len(categories) == 6
    assert {row["scene_id"] for row in categories} == {"SR-01", "SR-03", "SR-05", "SR-07", "SR-08", "SR-10"}
    assert all(int(row["pixel_count"]) == 768_614 for row in categories)
    report = (evidence / "16_FINAL_SUPPORT_DECOMPOSITION_REPORT.md").read_text(encoding="utf-8")
    assert "SENTINEL_STAGE1_SUPPORT_CERTIFIED: TRUE" in report
