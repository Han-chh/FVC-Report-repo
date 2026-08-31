import pandas as pd
import pytest

from additional_sensitivity_analysis.schemas import PAIR_COLUMN_ORDER, assert_pair_schema, empty_pair_frame


def test_nonempty_pair_schema_passes():
    row = dict(zip(PAIR_COLUMN_ORDER, ["AOI-00", "landsat", 2021, "2021-07-20", "p", .2, .3, 2, "b", "x", "y"]))
    assert_pair_schema(pd.DataFrame([row]).columns)


def test_empty_full_schema_is_valid_zero_support():
    assert_pair_schema(empty_pair_frame().columns)
    assert empty_pair_frame().empty


def test_empty_without_schema_fails():
    with pytest.raises(ValueError, match="PAIR_SCHEMA_FIELDS_MISSING"):
        assert_pair_schema(pd.DataFrame().columns)


def test_nonempty_missing_field_fails():
    with pytest.raises(ValueError, match="PAIR_SCHEMA_FIELDS_MISSING"):
        assert_pair_schema(pd.DataFrame([{"aoi_id": "AOI-00"}]).columns)


def test_mixed_concat_keeps_only_real_rows():
    row = dict(zip(PAIR_COLUMN_ORDER, ["AOI-00", "landsat", 2021, "2021-07-20", "p", .2, .3, 2, "b", "x", "y"]))
    joined = pd.concat([pd.DataFrame([row]), empty_pair_frame()], ignore_index=True)
    assert len(joined) == 1
    assert_pair_schema(joined.columns)
