"""Regression controls for the corrected FCOVER input contract.

These are deliberately offline tests: they prevent a future code change from
turning a missing evidence artifact into a passing pre-execution gate.
"""
from pathlib import Path

import numpy as np
import pytest

from common.grid import GridContract
from data_prep.download import _fcover_assets
from data_prep.fcover import valid_reference_mask
from data_prep.gee_cloud import FCOVER_ACTIVE_COLLECTION, FCOVER_SOURCE_BANDS, fcover_asset_id


ROOT = Path(__file__).resolve().parents[1]


def _asset(name: str) -> dict:
    return {"href": f"s3://example/{name}.tiff", "proj:shape": [2, 2],
            "proj:transform": [1, 0, 0, 0, -1, 2]}


def test_fake_source_datamask_claim_fails():
    item = {"assets": {"fcover300_fcover": _asset("FCOVER"), "fcover300_rmse": _asset("RMSE"),
                       "fcover300_nobs": _asset("NOBS"), "fcover300_lbefore": _asset("LBEFORE"),
                       "fcover300_lafter": _asset("LAFTER"), "fcover300_qflag": _asset("QFLAG"),
                       "dataMask": _asset("dataMask")}}
    selected = _fcover_assets(item)
    assert len(selected) == 6
    assert all("DATAMASK" not in value["href"].upper() for value in selected)


def test_wrong_valid_domain_mask_fails_reference_mask():
    f = np.array([100], dtype="uint16"); q = np.array([0], dtype="uint16"); n = np.array([2], dtype="uint16")
    assert not valid_reference_mask(f, q, n, np.array([0], dtype="uint8")).item()


def test_shifted_origin_is_not_grid_parity():
    reference = GridContract("EPSG:4326", (0.002976, 0, 99.3, 0, -0.002976, 38.2), 10, 10)
    shifted = GridContract("EPSG:4326", (0.002976, 0, 99.3001, 0, -0.002976, 38.2), 10, 10)
    with pytest.raises(ValueError, match="FCOVER_NATIVE_GRID_CHANGED"):
        reference.assert_same(shifted)


def test_immutable_revision_does_not_target_legacy_collection():
    assert fcover_asset_id("AOI-00", "2021-07-20").startswith(FCOVER_ACTIVE_COLLECTION + "/")
    assert "/fcover_native/" not in fcover_asset_id("AOI-00", "2021-07-20")


def test_full_verified_official_schema_is_preserved():
    assert FCOVER_SOURCE_BANDS == ("FCOVER", "RMSE", "NOBS", "LBEFORE", "LAFTER", "QFLAG")


def test_gee_code_forbids_effective_resolution_fallback_and_masks_n1():
    source = (ROOT / "src/data_prep/gee_cloud.py").read_text(encoding="utf-8")
    assert "bestEffort=False" in source
    assert ".updateMask(count.gte(2))" in source
    assert "valid_image" in source and "updateMask(valid_image)" in source


def test_gate_demands_actual_current_evidence_not_a_boolean():
    source = (ROOT / "src/execution/gate.py").read_text(encoding="utf-8")
    assert "FCOVER_ASSET_VERIFICATION.csv" in source
    assert "ACTIVE_GATE.json" in source
    assert "PAIRED_CUBE_IMPACT_AUDIT.csv" in source
