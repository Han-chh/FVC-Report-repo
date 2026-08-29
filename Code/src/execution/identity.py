"""Stable identities for preparation assets used by scientific execution.

This module contains no model code and performs no Earth Engine writes.  It
centralises the active source-manifest revision and the canonical processing
identity so preparation, readiness validation, and later execution all bind
to the same immutable inputs.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from execution.contract import ROOT, actual_design_hash, sha256


ACTIVE_SOURCE_REVISION = "final-source-scenes-r2-asset-verified"


def workspace_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT.parents[2] / path


def source_manifest_parent(contract: dict[str, Any]) -> Path:
    return workspace_path(contract["gee_data_center"]["source_scene_manifest_root"])


def active_source_root(contract: dict[str, Any]) -> Path:
    return source_manifest_parent(contract) / "active_r2"


def source_manifest_path(contract: dict[str, Any], sensor: str) -> Path:
    names = {
        "sentinel2": "ACTIVE_SENTINEL_SCENE_MANIFEST.csv",
        "landsat": "ACTIVE_LANDSAT_SCENE_MANIFEST.csv",
        "modis": "ACTIVE_MODIS_SCENE_MANIFEST.csv",
    }
    return active_source_root(contract) / names[sensor]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def active_source_rows(contract: dict[str, Any], sensor: str) -> list[dict[str, str]]:
    return read_csv(source_manifest_path(contract, sensor))


def source_manifest_index_hash(contract: dict[str, Any]) -> str:
    path = active_source_root(contract) / "ACTIVE_SOURCE_MANIFEST_INDEX.csv"
    rows = read_csv(path)
    rows.sort(key=lambda row: (row["AOI_ID"], row["sensor"], int(row["year"]), row["nominal_date"]))
    return sha256(rows)


def processing_identity_payload(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "design_hash": actual_design_hash(contract),
        "source_manifest_revision": ACTIVE_SOURCE_REVISION,
        "source_manifest_index_hash": source_manifest_index_hash(contract),
        "collections": contract["sensors"],
        "fcover": contract["fcover_reference"],
        "processing_order": contract["methodology"]["processing_order"],
        "minimum_contributions": contract["methodology"]["minimum_finite_contributions"],
        "temporal_window": contract["temporal_window_days"],
        "modis_rule": contract["modis_temporal_support_rule"],
        "grid": contract["methodology"]["target_support"],
        "block": contract["methodology"]["spatial_blocks"],
        "execution_contract_version": contract["execution_contract_version"],
    }


def active_processing_hash(contract: dict[str, Any]) -> str:
    return sha256(processing_identity_payload(contract))
