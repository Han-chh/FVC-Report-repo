from pathlib import Path

import numpy as np
import pytest

from data_prep.parity_engine import (ExactQuantileStore, PixelRequestPlanner,
                                     SQLiteCheckpoint, StreamingMetrics,
                                     Tile, classify_request_error,
                                     validate_tile_coverage)


def test_byte_estimator_and_tiled_plan_are_deterministic():
    planner = PixelRequestPlanner(budget_bytes=1024 * 1024, max_tile_edge=256)
    first = planner.plan(prefix="S2_scene", width=1000, height=800, requested_bands=("qa_valid", "ndvi"), dtype_bytes_per_pixel=8)
    second = planner.plan(prefix="S2_scene", width=1000, height=800, requested_bands=("qa_valid", "ndvi"), dtype_bytes_per_pixel=8)
    assert first.estimated_bytes == 6_400_000
    assert first.mode == "TILED"
    assert first.tiles == second.tiles
    assert all(tile.width * tile.height * 8 <= first.budget_bytes for tile in first.tiles)


def test_full_window_when_under_budget():
    plan = PixelRequestPlanner(budget_bytes=1000).plan(prefix="M", width=10, height=10, requested_bands=("x",), dtype_bytes_per_pixel=4)
    assert plan.mode == "FULL_WINDOW"
    assert len(plan.tiles) == 1


def test_tile_coverage_rejects_gap_and_overlap():
    with pytest.raises(ValueError, match="GAP_OR_OVERLAP"):
        validate_tile_coverage((Tile("a", 0, 2, 0, 2),), 3, 2)
    with pytest.raises(ValueError, match="GAP_OR_OVERLAP"):
        validate_tile_coverage((Tile("a", 0, 2, 0, 2), Tile("b", 0, 2, 1, 3)), 3, 2)


def test_deterministic_subdivision_has_complete_coverage():
    parent = Tile("root", 5, 12, 9, 18)
    children = PixelRequestPlanner.subdivide(parent)
    validate_tile_coverage(children, parent.width, parent.height, origin=(parent.row_start, parent.col_start))
    assert all(child.parent_tile_id == "root" for child in children)


def test_error_classification_distinguishes_engineering_failures():
    assert classify_request_error("Total request size 50331648") == "REQUEST_TOO_LARGE"
    assert classify_request_error("HTTP 429 quota") == "RATE_LIMITED"
    assert classify_request_error("request timed out") == "TIMEOUT"
    assert classify_request_error("HTTP 403 auth") == "AUTH_ERROR"


def test_checkpoint_reuses_only_exact_identity(tmp_path: Path):
    checkpoint = SQLiteCheckpoint(tmp_path / "check.sqlite")
    identity = {"protocol": "p1", "processing": "h1", "grid": "g1"}
    checkpoint.save("tile", identity, {"metric": 1})
    assert checkpoint.verified("tile", identity) == {"metric": 1}
    assert checkpoint.verified("tile", {**identity, "processing": "different"}) is None
    status = checkpoint.connection.execute("SELECT status FROM tile_checkpoint WHERE tile_id='tile'").fetchone()[0]
    checkpoint.close()
    assert status == "STALE"


def test_streaming_metrics_equal_whole_array_exactly(tmp_path: Path):
    local = np.array([[1.0, np.nan, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0]], dtype="float32")
    gee = np.array([[1.0, 2.0, 2.5, 4.5], [5.0, 5.5, 7.0, 8.25]], dtype="float32")
    store = ExactQuantileStore(tmp_path / "quantiles")
    streaming = StreamingMetrics(store)
    streaming.add("a", local[:, :2], gee[:, :2]); streaming.add("b", local[:, 2:], gee[:, 2:])
    result = streaming.result()
    common = np.isfinite(local) & np.isfinite(gee); delta = local[common] - gee[common]; absolute = np.abs(delta)
    assert result["common_valid"] == int(common.sum())
    assert result["mask_disagreement"] == int(np.count_nonzero(np.isfinite(local) != np.isfinite(gee)))
    assert result["mean_absolute_difference"] == pytest.approx(float(absolute.mean()))
    assert result["implementation_RMSE"] == pytest.approx(float(np.sqrt(np.mean(delta ** 2))))
    assert result["median_absolute_difference"] == pytest.approx(float(np.quantile(absolute, .5)))
    assert result["P95_absolute_difference"] == pytest.approx(float(np.quantile(absolute, .95)))
    assert result["Pearson_correlation"] == pytest.approx(float(np.corrcoef(local[common], gee[common])[0, 1]))

