"""Non-overlapping temporal assignment while retaining the primary median reducer."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable, Sequence

import pandas as pd

from data_prep.temporal_composite import nanmedian_min_count


def _date(value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return pd.Timestamp(value).date()


def nominal_dates_for_year(year: int, month_days: Sequence[str] = ("07-20", "07-31", "08-10")) -> tuple[date, ...]:
    return tuple(date.fromisoformat(f"{year}-{month_day}") for month_day in month_days)


def in_original_union(observation_date: object, *, nominals: Sequence[date], window_days: int) -> bool:
    observed = _date(observation_date)
    return any(abs((observed - nominal).days) <= window_days for nominal in nominals)


def nearest_nominal_assignment(observation_date: object, *, nominals: Sequence[date], window_days: int) -> date | None:
    """Choose the nearest nominal date; ties deterministically choose the earlier date."""
    observed = _date(observation_date)
    if not in_original_union(observed, nominals=nominals, window_days=window_days):
        return None
    return min(nominals, key=lambda nominal: (abs((observed - nominal).days), nominal))


def assign_non_overlapping(observations: pd.DataFrame, *, date_column: str = "acquisition_date",
                           identity_column: str = "source_identity", window_days: int = 15,
                           mode: str = "nearest_nominal_nonoverlap",
                           explicit_windows: dict[str, tuple[str, str]] | None = None) -> pd.DataFrame:
    """Assign every source identity to at most one target, without changing product dates.

    Explicit windows are inclusive and must be non-overlapping; they are present
    for future configuration but are not the scientific default.
    """
    required = {date_column, identity_column}
    missing = sorted(required - set(observations.columns))
    if missing:
        raise ValueError(f"TEMPORAL_SOURCE_FIELDS_MISSING:{','.join(missing)}")
    output = observations.copy()
    years = output[date_column].map(_date).map(lambda value: value.year)
    assigned: list[str | None] = []
    for observed, year in zip(output[date_column], years, strict=True):
        nominals = nominal_dates_for_year(int(year))
        if mode == "nearest_nominal_nonoverlap":
            target = nearest_nominal_assignment(observed, nominals=nominals, window_days=window_days)
        elif mode == "explicit_windows":
            if not explicit_windows:
                raise ValueError("EXPLICIT_WINDOWS_REQUIRED")
            matches = [label for label, (start, end) in explicit_windows.items()
                       if date.fromisoformat(start) <= _date(observed) <= date.fromisoformat(end)]
            if len(matches) > 1:
                raise ValueError("EXPLICIT_WINDOWS_OVERLAP")
            target = date.fromisoformat(matches[0]) if matches else None
        elif mode == "overlapping_pm15_primary":
            raise ValueError("PRIMARY_OVERLAPPING_MODE_NOT_A_NONOVERLAP_ASSIGNMENT")
        else:
            raise ValueError(f"TEMPORAL_MODE_INVALID:{mode}")
        assigned.append(target.isoformat() if target else None)
    output["assigned_nominal_date"] = assigned
    # Identity duplicates in the input remain visible; an identity cannot gain
    # a second target under this assignment rule.
    assigned_rows = output.dropna(subset=["assigned_nominal_date"])
    if assigned_rows.groupby(identity_column)["assigned_nominal_date"].nunique().gt(1).any():
        raise ValueError("SOURCE_IDENTITY_ASSIGNED_TO_MULTIPLE_NOMINAL_DATES")
    return output


def temporal_dry_run_summary(assignments: pd.DataFrame, *, identity_column: str = "source_identity") -> dict[str, object]:
    kept = assignments.dropna(subset=["assigned_nominal_date"])
    return {
        "source_observations_before_assignment": int(len(assignments)),
        "observations_assigned_by_nominal_date": {str(key): int(value) for key, value in
                                                    kept.groupby("assigned_nominal_date").size().items()},
        "observations_rejected": int(assignments["assigned_nominal_date"].isna().sum()),
        "duplicate_source_identities_across_nominal_dates": int(
            kept.groupby(identity_column)["assigned_nominal_date"].nunique().gt(1).sum()),
    }


def temporal_median(observation_level_fcover_arrays: Sequence[object], minimum_contributions: int = 2):
    """Delegate to the frozen primary cell-wise temporal median implementation."""
    return nanmedian_min_count(observation_level_fcover_arrays, minimum=minimum_contributions)
