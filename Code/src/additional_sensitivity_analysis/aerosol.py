"""Verified Landsat 8/9 C2 L2 ``SR_QA_AEROSOL`` decoding and screening.

Source: USGS, *Landsat Collection 2 Quality Assessment Bands*, accessed
2026-08-30.  For Landsat 8/9 Collection 2 Level-2 LaSRC products: bit 0 is
fill; bit 1 is valid aerosol retrieval; bit 5 is interpolated aerosol; bits
6--7 encode aerosol level (0 climatology, 1 low, 2 medium, 3 high).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np


AEROSOL_DOCUMENTATION_URL = "https://www.usgs.gov/landsat-missions/landsat-collection-2-quality-assessment-bands"
AEROSOL_LEVELS = {0: "climatology", 1: "low", 2: "medium", 3: "high"}
AEROSOL_MODES = frozenset({"primary_no_aerosol_filter", "exclude_high_aerosol", "valid_retrieval_no_high", "strict_aerosol"})
AEROSOL_OBSERVATION_FIELDS = (
    "scene_id", "acquisition_date", "AOI", "pixel_id", "primary_qa_pass",
    "aerosol_retrieval_valid", "aerosol_level", "aerosol_interpolated",
    "aerosol_mode", "aerosol_qa_pass", "retained_observation_count",
)
AEROSOL_SUMMARY_FIELDS = (
    "sensor", "AOI", "year", "aerosol_mode", "observations_before_aerosol_qa",
    "observations_after_aerosol_qa", "fraction_removed", "fcover_300m_identities_retained",
)


@dataclass(frozen=True)
class AerosolQa:
    fill: bool
    valid_retrieval: bool
    interpolated: bool
    aerosol_level_code: int
    aerosol_level: str


def decode_sr_qa_aerosol(values: np.ndarray | Iterable[int]) -> dict[str, np.ndarray]:
    """Decode only the official Collection 2 Landsat 8/9 L2 fields used here."""
    qa = np.asarray(values, dtype="uint16")
    level = ((qa >> 6) & 0b11).astype("uint8")
    return {
        "fill": ((qa >> 0) & 1).astype(bool),
        "valid_retrieval": ((qa >> 1) & 1).astype(bool),
        "interpolated": ((qa >> 5) & 1).astype(bool),
        "aerosol_level_code": level,
    }


def aerosol_pass_mask(values: np.ndarray | Iterable[int] | None, *, mode: str,
                      missing_policy: str = "reject") -> np.ndarray:
    """Return extra aerosol screening only; callers must still apply primary QA."""
    if mode not in AEROSOL_MODES:
        raise ValueError(f"AEROSOL_MODE_INVALID:{mode}")
    if values is None:
        if missing_policy == "reject":
            raise ValueError("AEROSOL_QA_MISSING")
        if missing_policy == "allow_only_primary_mode" and mode == "primary_no_aerosol_filter":
            return np.ones(0, dtype=bool)
        raise ValueError("AEROSOL_QA_MISSING")
    fields = decode_sr_qa_aerosol(values)
    base = ~fields["fill"]
    if mode == "primary_no_aerosol_filter":
        return np.ones(base.shape, dtype=bool)
    no_high = fields["aerosol_level_code"] != 3
    if mode == "exclude_high_aerosol":
        return base & no_high
    # A valid retrieval is distinct from an interpolated value.  These modes
    # require a valid retrieval and reject interpolation to make the stricter
    # sensitivity unambiguous and directly traceable to USGS bit semantics.
    valid_direct = fields["valid_retrieval"] & ~fields["interpolated"]
    if mode == "valid_retrieval_no_high":
        return base & valid_direct & no_high
    return base & valid_direct & (fields["aerosol_level_code"] <= 1)


def assert_scene_join(scene_ids: Iterable[str], aerosol_scene_ids: Iterable[str]) -> None:
    """Prevent a same-date but wrong-scene QA join."""
    if list(scene_ids) != list(aerosol_scene_ids):
        raise ValueError("AEROSOL_QA_SCENE_ID_MISMATCH")


def gee_retrieval_band_spec() -> tuple[str, ...]:
    """Exact same-scene source bands required for future GEE export/materialization."""
    return ("SR_B4", "SR_B5", "QA_PIXEL", "QA_RADSAT", "SR_QA_AEROSOL")
