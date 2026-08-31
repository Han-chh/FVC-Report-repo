"""Matched NDVI-first versus reflectance-first aggregation routines."""
from __future__ import annotations

import numpy as np


AGGREGATION_COMPARISON_FIELDS = (
    "sensor", "AOI", "year", "nominal_date", "fcover_cell_id", "route_a_ndvi",
    "route_b_ndvi", "delta_ndvi", "native_valid_pixel_count", "red_aggregate", "nir_aggregate",
)


def _matched_valid(red: np.ndarray, nir: np.ndarray, primary_qa_mask: np.ndarray) -> np.ndarray:
    red_array = np.asarray(red, dtype="float32")
    nir_array = np.asarray(nir, dtype="float32")
    qa = np.asarray(primary_qa_mask, dtype=bool)
    if red_array.shape != nir_array.shape or red_array.shape != qa.shape:
        raise ValueError("NATIVE_REFLECTANCE_SHAPE_MISMATCH")
    # The primary source-pixel NDVI excludes zero denominators.  Retain that
    # exact native-pixel eligibility for both routes so order is the only
    # changing factor.
    return qa & np.isfinite(red_array) & np.isfinite(nir_array) & ((red_array + nir_array) != 0)


def aggregate_ndvi_first(red: np.ndarray, nir: np.ndarray, primary_qa_mask: np.ndarray) -> tuple[float, int]:
    """Route A: average source-pixel NDVI using the matched QA-retained support."""
    valid = _matched_valid(red, nir, primary_qa_mask)
    denominator = np.asarray(nir, dtype="float32") + np.asarray(red, dtype="float32")
    valid &= denominator != 0
    if not valid.any():
        return float("nan"), 0
    ndvi = (np.asarray(nir, dtype="float32")[valid] - np.asarray(red, dtype="float32")[valid]) / denominator[valid]
    return float(np.mean(ndvi)), int(valid.sum())


def aggregate_reflectance_first(red: np.ndarray, nir: np.ndarray, primary_qa_mask: np.ndarray,
                                *, denominator_tolerance: float = 0.0) -> tuple[float, float, float, int]:
    """Route B: aggregate matched RED/NIR support then calculate NDVI once."""
    valid = _matched_valid(red, nir, primary_qa_mask)
    if not valid.any():
        return float("nan"), float("nan"), float("nan"), 0
    mean_red = float(np.mean(np.asarray(red, dtype="float32")[valid]))
    mean_nir = float(np.mean(np.asarray(nir, dtype="float32")[valid]))
    denominator = mean_nir + mean_red
    ndvi = float("nan") if abs(denominator) <= denominator_tolerance else (mean_nir - mean_red) / denominator
    return float(ndvi), mean_red, mean_nir, int(valid.sum())


def compare_aggregation_orders(red: np.ndarray, nir: np.ndarray, primary_qa_mask: np.ndarray,
                               *, denominator_tolerance: float = 0.0) -> dict[str, float | int]:
    route_a, count_a = aggregate_ndvi_first(red, nir, primary_qa_mask)
    route_b, mean_red, mean_nir, count_b = aggregate_reflectance_first(
        red, nir, primary_qa_mask, denominator_tolerance=denominator_tolerance)
    if count_a != count_b:
        raise ValueError("AGGREGATION_ROUTE_SUPPORT_MISMATCH")
    return {"route_a_ndvi": route_a, "route_b_ndvi": route_b,
            "delta_ndvi": route_a - route_b, "native_valid_pixel_count": count_a,
            "red_aggregate": mean_red, "nir_aggregate": mean_nir}
