"""Schemas shared by the three additional sensitivity pipelines."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


PAIR_REQUIRED_COLUMNS = frozenset({
    "aoi_id", "sensor", "year", "nominal_date", "pixel_id", "NDVI", "FCOVER",
    "contribution_count", "block_id",
})


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
