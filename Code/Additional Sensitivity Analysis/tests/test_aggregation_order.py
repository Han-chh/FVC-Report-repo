from __future__ import annotations

from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from additional_sensitivity_analysis.aggregation import compare_aggregation_orders


def test_identical_native_pixels_match() -> None:
    result = compare_aggregation_orders(np.array([0.2, 0.2]), np.array([0.6, 0.6]), np.array([True, True]))
    assert np.isclose(result["route_a_ndvi"], result["route_b_ndvi"])


def test_heterogeneous_native_pixels_can_differ() -> None:
    result = compare_aggregation_orders(np.array([0.1, 0.4]), np.array([0.4, 0.5]), np.array([True, True]))
    assert not np.isclose(result["route_a_ndvi"], result["route_b_ndvi"])


def test_invalid_band_uses_intersection_and_zero_aggregate_denominator_is_nodata() -> None:
    result = compare_aggregation_orders(np.array([0.2, np.nan, -0.1]), np.array([0.6, 0.3, 0.3]), np.array([True, True, True]))
    assert result["native_valid_pixel_count"] == 2
    zero = compare_aggregation_orders(np.array([1.0, -2.0]), np.array([3.0, -2.0]), np.array([True, True]))
    assert np.isnan(zero["route_b_ndvi"])
