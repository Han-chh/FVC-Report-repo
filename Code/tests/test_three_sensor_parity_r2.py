from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from affine import Affine

from common.raster_utils import area_weighted_to_fcover


ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT.parent / "new_experiments" / "15_three_sensor_parity"


def test_area_weighted_aggregation_on_aligned_fixture():
    values = np.arange(16, dtype="float32").reshape(4, 4)
    source = SimpleNamespace(transform=Affine(1, 0, 0, 0, -1, 4), crs="EPSG:4326")
    target = {"transform": Affine(2, 0, 0, 0, -2, 4), "crs": "EPSG:4326", "width": 2, "height": 2}
    observed = area_weighted_to_fcover(values, source, target)
    expected = np.array([[2.5, 4.5], [10.5, 12.5]], dtype="float32")
    assert np.allclose(observed, expected, atol=1e-7, rtol=0)


def test_active_source_contract_repairs_all_landsat_identities():
    root = EXP / "15_ACTIVE_SOURCE_IDENTITY_CONTRACT"
    contract = json.loads((root / "SOURCE_IDENTITY_CONTRACT.json").read_text(encoding="utf-8"))
    assert contract["row_count"] == 27
    assert contract["all_assets_resolve"] and contract["all_required_bands_present"]
    rows = list(csv.DictReader((root / "PARITY_SOURCE_INPUTS_R2.csv").open(encoding="utf-8")))
    landsat = [row for row in rows if row["sensor"] == "Landsat-8/9"]
    assert len(landsat) == 12
    assert all("/1_LC08_" not in row["system_id"] and "/2_LC09_" not in row["system_id"] for row in landsat)
    assert all(("/LC09/" in row["collection"]) == (row["platform"] == "LANDSAT_9") for row in landsat)


def test_active_three_sensor_gate_is_metric_derived_and_model_free():
    gate = json.loads((EXP / "07_FINAL_GATE/ACTIVE_GATE.json").read_text(encoding="utf-8"))
    assert gate["three_sensor_parity_gate"] == "PASS"
    assert not gate["models_run"] and not gate["assets_written"]
    assert {row["sensor"]: row["verdict"] for row in gate["sensor_summaries"]} == {
        "Sentinel-2": "PASS", "Landsat-8/9": "PASS", "MODIS": "PASS",
    }
    matrix = list(csv.DictReader((EXP / "16_THREE_SENSOR_PARITY_R2/05_CROSS_SENSOR_AUDIT/THREE_SENSOR_PARITY_MATRIX.csv").open(encoding="utf-8")))
    assert len(matrix) == 21
    assert all(row["verdict"] == "PASS" for row in matrix)
