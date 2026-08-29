from __future__ import annotations

from pathlib import Path

FORBIDDEN_AOI_TERMS = ("rmse", "mae", "bias", "r2", "pearson", "ols", "2025_fcover", "model_results")


def assert_chronology(history_years, target_year):
    if not history_years or any(int(year) >= int(target_year) for year in history_years):
        raise ValueError("ROLLING_ORIGIN_CHRONOLOGY_VIOLATION")


def audit_aoi_source(source: str):
    lowered = source.lower()
    hits = [term for term in FORBIDDEN_AOI_TERMS if term in lowered]
    if hits: raise ValueError(f"AOI_SELECTION_FORBIDDEN_INPUT:{','.join(hits)}")


def assert_no_model_result_path(paths):
    for path in paths:
        lowered = str(Path(path)).lower()
        if any(token in lowered for token in ("model", "result", "comparison", "metric")):
            raise ValueError(f"AOI_SELECTION_PATH_FORBIDDEN:{path}")

