"""Configuration and provenance helpers; all paths remain repository-relative."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


CODE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = CODE_ROOT.parent


def load_yaml(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    with config_path.open(encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"CONFIG_NOT_MAPPING:{config_path}")
    return value


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def git_commit() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT,
                            check=False, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else "UNAVAILABLE"


def future_manifest(*, config: dict[str, Any], script_versions: dict[str, str],
                    source_data_identifiers: list[str], input_paths: list[str],
                    output_paths: list[str], counts_processed: dict[str, int],
                    validation_status: str) -> dict[str, Any]:
    """Build (but do not write) a run manifest for a future authorized run."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit(),
        "config_hash": canonical_hash(config),
        "script_versions": script_versions,
        "source_data_identifiers": source_data_identifiers,
        "input_paths": input_paths,
        "output_paths": output_paths,
        "aoi": config.get("aoi"),
        "sensor": config.get("sensor"),
        "year": config.get("year"),
        "sensitivity_variant": config.get("variant"),
        "counts_processed": counts_processed,
        "validation_status": validation_status,
    }
