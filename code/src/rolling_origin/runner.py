from __future__ import annotations


def execution_plan(aoi_ids, sensors, windows):
    return [{"aoi_id": aoi, "sensor": sensor, **window, "status": "NOT_RUN"}
            for aoi in aoi_ids for sensor in sensors for window in windows]


def require_scientific_acknowledgement(config: dict):
    """Compatibility guard driven only by the reconciled runtime contract."""
    if config.get("phase") != "scientific_execution" or config.get("scientific_execution_enabled") is not True:
        raise RuntimeError("SCIENTIFIC_EXECUTION_DISABLED_BY_RUNTIME_CONTRACT")
    if config.get("execution_acknowledged") is not True:
        raise RuntimeError("EXPLICIT_SCIENTIFIC_EXECUTION_ACKNOWLEDGEMENT_REQUIRED")
