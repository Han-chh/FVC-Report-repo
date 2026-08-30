from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from additional_sensitivity_analysis.schemas import assert_pair_schema


def test_downstream_pair_schema_contract() -> None:
    columns = {"aoi_id", "sensor", "year", "nominal_date", "pixel_id", "NDVI", "FCOVER", "contribution_count", "block_id"}
    assert_pair_schema(columns)
    with pytest.raises(ValueError, match="PAIR_SCHEMA_FIELDS_MISSING"):
        assert_pair_schema(columns - {"block_id"})
