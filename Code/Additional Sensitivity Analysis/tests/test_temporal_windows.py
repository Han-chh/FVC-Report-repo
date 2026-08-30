from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from additional_sensitivity_analysis.temporal import assign_non_overlapping, temporal_dry_run_summary
from additional_sensitivity_analysis.validation import assert_no_target_or_later_year_leakage


def test_nearest_assignment_tie_and_union_rejection() -> None:
    rows = pd.DataFrame({"source_identity": ["a", "b", "c", "outside"],
                         "acquisition_date": ["2024-07-20", "2024-07-25", "2024-08-10", "2024-09-01"]})
    assigned = assign_non_overlapping(rows)
    assert assigned.assigned_nominal_date.iloc[:3].tolist() == ["2024-07-20", "2024-07-20", "2024-08-10"]
    assert pd.isna(assigned.assigned_nominal_date.iloc[3])
    assert temporal_dry_run_summary(assigned)["duplicate_source_identities_across_nominal_dates"] == 0


def test_each_identity_has_at_most_one_target() -> None:
    rows = pd.DataFrame({"source_identity": ["shared", "shared"],
                         "acquisition_date": ["2024-07-25", "2024-08-05"]})
    with pytest.raises(ValueError, match="SOURCE_IDENTITY_ASSIGNED_TO_MULTIPLE_NOMINAL_DATES"):
        assign_non_overlapping(rows)


def test_later_year_leakage_is_rejected() -> None:
    with pytest.raises(ValueError, match="LATER_YEAR_LEAKAGE"):
        assert_no_target_or_later_year_leakage(pd.DataFrame({"year": [2024, 2025]}), target_year=2024)
