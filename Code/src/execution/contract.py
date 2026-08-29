from __future__ import annotations

import hashlib
import json
import copy
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def load_contract(path: Path | None = None) -> dict[str, Any]:
    return _load_yaml(path or ROOT / "configs/scientific_execution.yaml")


def _assert_subset(expected: Any, observed: Any, label: str) -> None:
    if isinstance(expected, dict):
        if not isinstance(observed, dict):
            raise RuntimeError(f"CONTRACT_MISMATCH:{label}")
        for key, value in expected.items():
            if key not in observed:
                raise RuntimeError(f"CONTRACT_MISMATCH:{label}.{key}:missing")
            _assert_subset(value, observed[key], f"{label}.{key}")
    elif expected != observed:
        raise RuntimeError(f"CONTRACT_MISMATCH:{label}")


def registry_geometry_payload(contract: dict[str, Any]) -> list[dict[str, Any]]:
    registry = Path(contract["frozen_design_references"]["final_aoi_registry"])
    if not registry.is_absolute():
        registry = ROOT.parents[2] / registry
    collection = json.loads(registry.read_text(encoding="utf-8"))
    payload = []
    for feature in collection["features"]:
        properties = feature["properties"]
        payload.append({
            "aoi_id": properties["aoi_id"],
            "source_candidate_id": properties.get("source_candidate_id"),
            "geometry_version": properties.get("geometry_version"),
            "geometry": feature["geometry"],
        })
    return sorted(payload, key=lambda row: row["aoi_id"])


def design_payload(contract: dict[str, Any]) -> dict[str, Any]:
    """All result-affecting frozen inputs, serialised independently of the hash."""
    return {
        "execution_contract_version": contract["execution_contract_version"],
        "active_experiments": contract["active_experiments"],
        "removed_experiments": contract["removed_experiments"],
        "final_aoi_ids": contract["final_aoi_ids"],
        "final_aoi_geometries": registry_geometry_payload(contract),
        "years": contract["years"],
        "nominal_dates": contract["nominal_dates"],
        "temporal_window_days": contract["temporal_window_days"],
        "modis_temporal_support_rule": contract["modis_temporal_support_rule"],
        "multi_aoi_historical_windows": contract["multi_aoi_historical_windows"],
        "methodology": contract["methodology"],
        "sensors": contract["sensors"],
        "fcover_reference": contract["fcover_reference"],
        "rolling_origin": contract["rolling_origin"],
        "multi_aoi_statistics": contract["multi_aoi_statistics"],
        "gee_data_center": contract["gee_data_center"],
    }


def actual_design_hash(contract: dict[str, Any]) -> str:
    return sha256(design_payload(contract))


def assert_design_contract(contract: dict[str, Any]) -> str:
    """Validate the frozen scientific design without granting execution authority."""
    if contract.get("active_experiments") != ["multi_aoi", "rolling_origin"]:
        raise RuntimeError("ACTIVE_EXPERIMENT_SCOPE_DRIFT")
    if contract.get("removed_experiments") != ["fcover_quality_sensitivity"]:
        raise RuntimeError("REMOVED_EXPERIMENT_SCOPE_DRIFT")
    if contract.get("final_aoi_ids") != ["AOI-00", "AOI-01", "AOI-02", "AOI-03"]:
        raise RuntimeError("FINAL_AOI_SCOPE_DRIFT")

    base = _load_yaml(ROOT / "configs/base_methodology.yaml")
    if contract.get("methodology") != base:
        raise RuntimeError("CONTRACT_MISMATCH:base_methodology")
    sensors = _load_yaml(ROOT / "configs/sensors.yaml")
    # The cloud-probability collection is a GEE join input, configured in the
    # data-centre contract rather than the sensor-methodology file.
    sensor_contract = copy.deepcopy(contract["sensors"])
    cloud_product = sensor_contract["sentinel2"].pop("cloud_probability_product")
    _assert_subset(sensor_contract, sensors, "sensors")
    gee = _load_yaml(ROOT / "configs/gee_cloud.yaml")
    if gee["source_collections"]["sentinel2_cloud_probability"] != cloud_product:
        raise RuntimeError("CONTRACT_MISMATCH:sentinel2_cloud_probability")
    fcover = _load_yaml(ROOT / "configs/fcover_reference_preprocessing.yaml")
    _assert_subset(contract["fcover_reference"], fcover, "fcover_reference")
    rolling = _load_yaml(ROOT / "configs/rolling_origin.yaml")
    rolling_contract = copy.deepcopy(contract["rolling_origin"])
    # Alpha is fixed in the approved statistical-plan document; the legacy
    # YAML stores only the family definition.
    alpha = rolling_contract.pop("alpha")
    if alpha != 0.05:
        raise RuntimeError("CONTRACT_MISMATCH:rolling_origin.alpha")
    _assert_subset(rolling_contract, rolling, "rolling_origin")

    actual = actual_design_hash(contract)
    if contract.get("frozen_design_hash") != actual:
        raise RuntimeError(f"DESIGN_DRIFT:expected={contract.get('frozen_design_hash')}:actual={actual}")
    return actual


def assert_execution_contract(contract: dict[str, Any]) -> str:
    """Validate design identity and the separate, explicit execution interlock."""
    actual = assert_design_contract(contract)
    if contract.get("phase") != "scientific_execution":
        raise RuntimeError("EXECUTION_PHASE_NOT_SCIENTIFIC")
    if contract.get("scientific_execution_enabled") is not True:
        raise RuntimeError("SCIENTIFIC_EXECUTION_DISABLED")
    if contract.get("execution_acknowledged") is not True:
        raise RuntimeError("EXPLICIT_SCIENTIFIC_EXECUTION_ACKNOWLEDGEMENT_REQUIRED")
    return actual


def assert_parity_validation_contract(contract: dict[str, Any]) -> str:
    """Authorize preprocessing parity only, never scientific model execution."""
    actual = assert_design_contract(contract)
    if contract.get("phase") != "parity_validation_only":
        raise RuntimeError("PARITY_VALIDATION_PHASE_NOT_ACTIVE")
    if contract.get("parity_validation_enabled") is not True:
        raise RuntimeError("PARITY_VALIDATION_DISABLED")
    if contract.get("parity_validation_acknowledged") is not True:
        raise RuntimeError("EXPLICIT_PARITY_VALIDATION_ACKNOWLEDGEMENT_REQUIRED")
    if contract.get("scientific_execution_enabled") is not False:
        raise RuntimeError("PARITY_MODE_REQUIRES_SCIENTIFIC_EXECUTION_DISABLED")
    if contract.get("execution_acknowledged") is not False:
        raise RuntimeError("PARITY_MODE_REQUIRES_SCIENTIFIC_ACKNOWLEDGEMENT_FALSE")
    return actual


def assert_readiness_contract(contract: dict[str, Any]) -> str:
    """Authorize final-input/readiness validation while execution stays off."""
    actual = assert_design_contract(contract)
    if contract.get("phase") != "scientific_execution_ready":
        raise RuntimeError("SCIENTIFIC_EXECUTION_READY_PHASE_NOT_ACTIVE")
    if contract.get("readiness_validation_enabled") is not True:
        raise RuntimeError("READINESS_VALIDATION_DISABLED")
    if contract.get("readiness_validation_acknowledged") is not True:
        raise RuntimeError("READINESS_VALIDATION_ACKNOWLEDGEMENT_REQUIRED")
    if contract.get("scientific_execution_enabled") is not False:
        raise RuntimeError("READINESS_MODE_REQUIRES_SCIENTIFIC_EXECUTION_DISABLED")
    if contract.get("execution_acknowledged") is not False:
        raise RuntimeError("READINESS_MODE_REQUIRES_EXECUTION_ACKNOWLEDGEMENT_FALSE")
    return actual


def processing_hash() -> str:
    """Current code/config identity; input assets are separately guarded by manifests."""
    digest = hashlib.sha256()
    paths = sorted((ROOT / "src").rglob("*.py")) + sorted((ROOT / "configs").glob("*.yaml"))
    for path in paths:
        digest.update(str(path.relative_to(ROOT)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()
