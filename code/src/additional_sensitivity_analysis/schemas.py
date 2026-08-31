"""Schemas shared by the three additional sensitivity pipelines."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


PAIR_COLUMN_ORDER = (
    "aoi_id", "sensor", "year", "nominal_date", "pixel_id", "NDVI", "FCOVER",
    "contribution_count", "block_id", "sensitivity_name", "sensitivity_variant",
)
PAIR_REQUIRED_COLUMNS = frozenset(PAIR_COLUMN_ORDER[:9])


def empty_pair_frame():
    """A valid zero-support pair table; metadata belongs in its manifest."""
    import pandas as pd
    return pd.DataFrame({
        "aoi_id": pd.Series(dtype="string"), "sensor": pd.Series(dtype="string"),
        "year": pd.Series(dtype="int64"), "nominal_date": pd.Series(dtype="string"),
        "pixel_id": pd.Series(dtype="string"), "NDVI": pd.Series(dtype="float64"),
        "FCOVER": pd.Series(dtype="float64"), "contribution_count": pd.Series(dtype="int64"),
        "block_id": pd.Series(dtype="string"), "sensitivity_name": pd.Series(dtype="string"),
        "sensitivity_variant": pd.Series(dtype="string"),
    })[list(PAIR_COLUMN_ORDER)]


@dataclass(frozen=True)
class SensitivityDatasetConfig:
    """Identity and location of one future, downstream-compatible data product."""

    sensitivity_name: str
    sensitivity_variant: str
    sensor: str
    aoi: str
    year: int
    nominal_date: str
    source_data_path: str
    output_data_path: str
    processing_hash: str
    primary_vs_sensitivity: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def assert_pair_schema(columns: Mapping[str, Any] | set[str] | list[str]) -> None:
    """Reject incomplete data rather than silently adapting it for model runners."""
    observed = set(columns)
    missing = sorted(PAIR_REQUIRED_COLUMNS - observed)
    if missing:
        raise ValueError(f"PAIR_SCHEMA_FIELDS_MISSING:{','.join(missing)}")
