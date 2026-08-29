from __future__ import annotations

import math
import json
from pathlib import Path

import numpy as np
import pytest

from execution.science import (
    expected_pair_band_names,
    iter_feature_pages,
    paired_row_decision,
    sensor_band_prefix,
)


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[2]


def test_exact_36_band_schema_and_sensor_prefix_mapping():
    bands = expected_pair_band_names()
    assert len(bands) == 36
    assert len(set(bands)) == 36
    assert sensor_band_prefix("sentinel2") == "s2"
    assert sensor_band_prefix("landsat") == "landsat"
    assert sensor_band_prefix("modis") == "modis"
    for suffix in ("0720", "0731", "0810"):
        for prefix in ("s2", "landsat", "modis"):
            assert f"{prefix}_ndvi_{suffix}" in bands
            assert f"{prefix}_count_{suffix}" in bands
    with pytest.raises(RuntimeError, match="UNKNOWN_SENSOR_BAND_PREFIX"):
        sensor_band_prefix("unknown")


def _values(suffix="0720"):
    return {
        f"valid_reference_{suffix}": 1,
        f"fcover_{suffix}": 0.4,
        f"s2_ndvi_{suffix}": 0.3,
        f"s2_count_{suffix}": 2,
        f"landsat_ndvi_{suffix}": 0.2,
        f"landsat_count_{suffix}": 3,
        f"modis_ndvi_{suffix}": 0.1,
        f"modis_count_{suffix}": 4,
    }


def test_partial_sensor_null_does_not_delete_other_sensor_row():
    values = _values()
    values["s2_ndvi_0720"] = None
    assert paired_row_decision(values, "sentinel2", "0720")[0] == "invalid_ndvi"
    reason, paired = paired_row_decision(values, "landsat", "0720")
    assert reason == "accepted" and paired == {"FCOVER": 0.4, "NDVI": 0.2, "contribution_count": 3}


def test_partial_date_null_does_not_delete_other_date_row():
    values = {**_values("0720"), **_values("0731")}
    values["fcover_0720"] = None
    assert paired_row_decision(values, "modis", "0720")[0] == "invalid_fcover"
    assert paired_row_decision(values, "modis", "0731")[0] == "accepted"


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ({"valid_reference_0720": 0}, "invalid_reference"),
        ({"fcover_0720": None}, "invalid_fcover"),
        ({"fcover_0720": 1.1}, "invalid_fcover"),
        ({"s2_ndvi_0720": np.nan}, "invalid_ndvi"),
        ({"s2_count_0720": None}, "invalid_count"),
        ({"s2_count_0720": 1}, "count_lt_2"),
    ],
)
def test_frozen_pair_predicates_fail_closed_without_zero_fill(mutation, reason):
    values = _values(); values.update(mutation)
    observed, paired = paired_row_decision(values, "sentinel2", "0720")
    assert observed == reason and paired is None


def _fetcher(items, calls):
    def fetch(request):
        calls.append(dict(request))
        start = int(request.get("pageToken", "0"))
        stop = min(start + int(request["pageSize"]), len(items))
        result = {"features": items[start:stop]}
        if stop < len(items):
            result["nextPageToken"] = str(stop)
        return result
    return fetch


@pytest.mark.parametrize("count", [0, 1, 4_999, 5_000, 5_001, 12_001])
def test_pagination_exact_counts_and_terminal_page(count):
    items = [{"id": index} for index in range(count)]; calls = []
    pages = list(iter_feature_pages("collection", _fetcher(items, calls), page_size=5_000))
    observed = [item for _, page in pages for item in page]
    assert observed == items
    assert len(calls) == max(1, math.ceil(count / 5_000))
    assert "pageToken" not in calls[0]


def test_pagination_identity_is_page_size_independent_and_retry_idempotent():
    items = [{"id": index} for index in range(12_345)]
    def collect(page_size):
        calls = []
        return [item for _, page in iter_feature_pages(
            "collection", _fetcher(items, calls), page_size=page_size) for item in page]
    assert collect(1_000) == collect(4_999) == collect(5_000) == items
    assert collect(5_000) == collect(5_000)


def test_repeated_pagination_token_hard_fails():
    calls = 0
    def fetch(_request):
        nonlocal calls
        calls += 1
        return {"features": [{"id": calls}], "nextPageToken": "same"}
    with pytest.raises(RuntimeError, match="REPEATED_PAGINATION_TOKEN"):
        list(iter_feature_pages("collection", fetch))


def test_execution_interlock_and_invalid_cache_quarantine():
    import yaml
    contract = yaml.safe_load((ROOT / "configs/scientific_execution.yaml").read_text())
    assert contract["scientific_execution_enabled"] is False
    assert contract["execution_acknowledged"] is False
    output = WORKSPACE / contract["output_root"]
    runtime_cache = output / "raw_machine_outputs/paired_observations.csv.gz"
    quarantine = output / "08_implementation_remediation/02_invalid_cache_quarantine/INVALID_CACHE_QUARANTINE_MANIFEST.json"
    record = json.loads(quarantine.read_text())
    assert record["status"] == "PRESERVED_AND_DISABLED"
    assert record["sha256"] == "c2aa8fcdde6bc09479982aeb3cf7cd11f2502b3252ab8d72e8bfbfff0521a842"
    assert record["valid_for_scientific_model"] is False and record["reuse_forbidden"] is True
    assert runtime_cache.is_file()
    assert runtime_cache.resolve() != (WORKSPACE / record["quarantine_path"]).resolve()


def test_extraction_and_run_feasibility_artifacts_pass_without_models():
    output = WORKSPACE / "report/publication/new_experiments/08_scientific_execution/08_implementation_remediation"
    extraction = json.loads((output / "05_extraction_validation/PAIRED_ROW_EXTRACTION_MANIFEST.json").read_text())
    feasibility = json.loads((output / "06_run_feasibility/RUN_MATRIX_FEASIBILITY_AUDIT.json").read_text())
    assert extraction["status"] == "PASS" and extraction["passing_aoi_sensor_year_groups"] == 60
    assert extraction["duplicate_observation_rows"] == 0
    assert extraction["scientific_models_run"] is False and extraction["formal_metrics_computed"] is False
    assert feasibility["status"] == "PASS"
    assert feasibility["multi_aoi"]["feasible"] == 72
    assert feasibility["rolling_origin"]["feasible"] == 72
    assert feasibility["scientific_models_run"] is False
    assert feasibility["formal_metrics_computed"] is False
