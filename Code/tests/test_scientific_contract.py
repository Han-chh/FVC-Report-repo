from pathlib import Path
import inspect
import numpy as np
import pandas as pd
import pytest

from audit.methodology_contract import validate, REQUIRED_ORDER
from common.blocks import block_id, reserve_blocks
from common.grid import GridContract
from data_prep import landsat, sentinel2
from data_prep.fcover import valid_reference_mask
from data_prep.processing import OPERATION_ORDER
from data_prep.temporal_composite import nanmedian_min_count
from rolling_origin.windows import primary_windows
from rolling_origin.runner import require_scientific_acknowledgement
from execution.contract import actual_design_hash, assert_design_contract, assert_execution_contract, load_contract
from validation.leakage_audit import assert_chronology, audit_aoi_source, assert_no_model_result_path
from validation.loyo import folds_for_years
from validation.split_blocks import split_complete_blocks, assert_development_only

ROOT = Path(__file__).resolve().parents[1]


def test_grid_contract_rejects_changed_grid():
    expected = GridContract("EPSG:4326", (1, 0, 0, 0, -1, 0), 10, 10)
    with pytest.raises(ValueError, match="FCOVER_NATIVE_GRID_CHANGED"):
        expected.assert_same(GridContract("EPSG:32647", (1, 0, 0, 0, -1, 0), 10, 10))


def test_operation_order_frozen():
    assert list(OPERATION_ORDER) == REQUIRED_ORDER
    validate(ROOT / "configs/base_methodology.yaml")


def test_observation_count_excludes_n_lt_2():
    median, count = nanmedian_min_count([np.array([[1.0, 1.0]]), np.array([[np.nan, 3.0]])])
    assert np.isnan(median[0, 0]) and median[0, 1] == 2.0
    assert count.tolist() == [[1, 2]]


def test_block_id_is_cross_year_deterministic():
    assert block_id(531234, 4200123) == block_id(531234, 4200123)


def test_reserve_seed42_sha256_is_deterministic():
    blocks = [f"b_{i}_0" for i in range(20)]
    assert reserve_blocks(blocks) == reserve_blocks(reversed(blocks))
    assert len(reserve_blocks(blocks)) == 4


def test_reserve_does_not_enter_development_diagnostics():
    split = split_complete_blocks([f"b_{i}_0" for i in range(20)])
    rows = pd.DataFrame({"block_id": list(split["development"])})
    assert_development_only(rows, split["reserve"])
    with pytest.raises(ValueError, match="RESERVE_LEAKAGE"):
        assert_development_only(pd.DataFrame({"block_id": [next(iter(split["reserve"]))]}), split["reserve"])


def test_final_refit_contract_recombines_development_and_reserve():
    config = validate(ROOT / "configs/base_methodology.yaml")
    assert config["historical_partition"]["final_refit_domain"] == "development_plus_reserve"


def test_rolling_chronology_and_matrix():
    rows = primary_windows(); assert len(rows) == 6
    assert [r["history_length"] for r in rows] == [1, 2, 3, 1, 2, 3]
    for row in rows: assert_chronology(row["history_years"], row["target_year"])
    with pytest.raises(ValueError): assert_chronology([2025], 2025)


def test_target_label_not_part_of_window_contract():
    source = inspect.getsource(__import__("rolling_origin.windows", fromlist=["*"]))
    assert "FCOVER" not in source and "metric" not in source.lower()


def test_aoi_selection_forbidden_inputs():
    audit_aoi_source("Copernicus DEM + WorldCover + historical NDVI 2021-2024")
    with pytest.raises(ValueError): audit_aoi_source("choose by RMSE")
    with pytest.raises(ValueError): assert_no_model_result_path(["output/model_results"])


def test_2025_fcover_forbidden_in_aoi_selection():
    with pytest.raises(ValueError): audit_aoi_source("2025_FCOVER")


def test_baseline_reference_mask_uses_derived_validity_domain():
    q = np.arange(256, dtype="uint16")
    f = np.full(256, 100, dtype="uint16"); n = np.ones(256, dtype="uint16"); m = np.ones(256, dtype="uint16")
    valid = valid_reference_mask(f, q, n, m)
    assert valid[0]
    assert not valid[255]
    assert not valid_reference_mask(f, q, n, np.zeros(256, dtype="uint16")).any()


def test_reference_preprocessing_configuration_has_no_strict_profile():
    import yaml
    q = yaml.safe_load((ROOT / "configs/fcover_reference_preprocessing.yaml").read_text())
    assert q["product_provided_quality_fields"] == ["QFLAG", "NOBS"]
    assert q["derived_validity_domain"]["api_name"] == "valid_domain_mask"
    assert "strict" not in str(q).lower()


def test_sensor_method_consistency():
    config = validate(ROOT / "configs/base_methodology.yaml")
    assert config["processing_order"] == REQUIRED_ORDER


def test_2021_has_no_special_preprocessing_and_landsat9_absent():
    assert landsat.platforms_for_year(2021) == ("LANDSAT_8",)
    assert landsat.platforms_for_year(2022) == ("LANDSAT_8", "LANDSAT_9")
    assert "year" not in inspect.signature(landsat.ndvi).parameters
    assert "year" not in inspect.signature(sentinel2.ndvi).parameters


def test_single_year_loyo_not_applicable():
    assert folds_for_years([2023])["status"] == "NOT_APPLICABLE"
    assert len(folds_for_years([2022, 2023])["folds"]) == 2


def test_scientific_execution_phase_guard():
    with pytest.raises(RuntimeError, match="DISABLED"):
        require_scientific_acknowledgement({"phase": "preparation_only", "scientific_execution_enabled": False, "execution_acknowledged": True})


def test_reconciled_execution_contract_has_a_frozen_matching_design_hash():
    contract = load_contract(ROOT / "configs/scientific_execution.yaml")
    assert contract["frozen_design_hash"] == actual_design_hash(contract)
    assert assert_design_contract(contract) == contract["frozen_design_hash"]
    with pytest.raises(RuntimeError, match="EXECUTION_PHASE_NOT_SCIENTIFIC"):
        assert_execution_contract(contract)
