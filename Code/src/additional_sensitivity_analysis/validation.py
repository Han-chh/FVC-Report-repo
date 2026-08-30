"""Invariant checks shared by sensitivity routes."""
from __future__ import annotations

from datetime import date
from typing import Iterable

import pandas as pd

from .schemas import assert_pair_schema


def assert_no_target_or_later_year_leakage(rows: pd.DataFrame, *, target_year: int) -> None:
    if (rows["year"].astype(int) > int(target_year)).any():
        raise ValueError("LATER_YEAR_LEAKAGE")


def assert_nominal_dates(rows: pd.DataFrame, *, nominal_dates: Iterable[str]) -> None:
    allowed = set(nominal_dates)
    observed = set(rows["nominal_date"].astype(str))
    unexpected = sorted(observed - allowed)
    if unexpected:
        raise ValueError(f"NOMINAL_DATE_LABEL_INVALID:{','.join(unexpected)}")


def validate_downstream_pair_frame(rows: pd.DataFrame) -> None:
    assert_pair_schema(rows.columns)
    if rows.duplicated(["aoi_id", "sensor", "year", "nominal_date", "pixel_id"]).any():
        raise ValueError("DUPLICATE_DOWNSTREAM_PAIR_IDENTITIES")
