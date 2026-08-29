"""Fail-closed metadata contracts for scientific raster materializations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ScientificRasterContract:
    sensor: str
    bands: tuple[str, ...]
    dtype: str
    resolution_m: float
    require_source_identity: bool = True


def validate_scientific_materialization(*, contract: ScientificRasterContract,
                                        band_count: int, dtypes: Iterable[str],
                                        color_interpretations: Iterable[str], resolution_m: float,
                                        source_identity: str | None) -> list[str]:
    """Return stable rejection codes; callers must reject any non-empty list."""
    errors: list[str] = []
    observed = tuple(dtypes); colors = tuple(color_interpretations)
    if band_count != len(contract.bands): errors.append("BAND_COUNT_INVALID")
    if any(dtype != contract.dtype for dtype in observed): errors.append("DTYPE_INVALID")
    if colors == ("red", "green", "blue", "alpha"): errors.append("RGBA_PREVIEW_INVALID")
    if abs(float(resolution_m) - contract.resolution_m) > 1e-9: errors.append("RESOLUTION_INVALID")
    if contract.require_source_identity and not source_identity: errors.append("SOURCE_IDENTITY_MISSING")
    return errors
