"""Safe output helpers for future sensitivity products."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def repository_path(relative_path: str | Path) -> Path:
    from .config import REPOSITORY_ROOT
    path = Path(relative_path)
    return path if path.is_absolute() else REPOSITORY_ROOT / path


def assert_sensitivity_output_path(path: str | Path) -> Path:
    """Allow writes only to an explicit reconstruction directory outside the repository."""
    resolved = repository_path(path).resolve()
    repository = repository_path(".").resolve()
    if repository == resolved or repository in resolved.parents:
        raise ValueError(f"OUTPUT_MUST_BE_OUTSIDE_REPOSITORY:{resolved}")
    return resolved


def write_json(path: str | Path, value: dict[str, Any]) -> Path:
    destination = assert_sensitivity_output_path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return destination
