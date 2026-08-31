from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

from execution.contract import actual_design_hash, assert_design_contract


DESIGN_HASH = "b21c8cc7f3d4d35e1db4dfa1c8245ff10ba657c0a0a001992b552808766cc49b"
FORBIDDEN_PROCESS_TOKENS = (
    "20_run_multi_aoi_experiment.py",
    "21_run_rolling_origin_experiment.py",
    "15_run_sentinel_parity.py",
    "15_run_sentinel_tiled_native_parity.py",
    "--execute",
)
DEPRECATED_MARKERS = (
    "DEPRECATED_INVALID_SCIENTIFIC_INPUT",
    "legacy_dataMask_unacceptable",
    "RGBA uint8",
)


def sha256_file(path: Path, block_bytes: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(block_bytes):
            digest.update(chunk)
    return digest.hexdigest()


def assert_preparation_lock(contract: dict[str, Any]) -> str:
    design_hash = assert_design_contract(contract)
    if design_hash != DESIGN_HASH or actual_design_hash(contract) != DESIGN_HASH:
        raise RuntimeError("PHASE0_DESIGN_HASH_DRIFT")
    if contract.get("phase") != "preparation_only":
        raise RuntimeError("PHASE0_REQUIRES_PREPARATION_ONLY")
    if contract.get("scientific_execution_enabled") is not False:
        raise RuntimeError("PHASE0_SCIENTIFIC_EXECUTION_MUST_BE_DISABLED")
    if contract.get("execution_acknowledged") is not False:
        raise RuntimeError("PHASE0_EXECUTION_ACKNOWLEDGEMENT_MUST_BE_FALSE")
    return design_hash


def running_forbidden_processes(process_text: str | None = None) -> list[str]:
    if process_text is None:
        process_text = subprocess.run(
            ["ps", "-ax", "-o", "command="], check=True, capture_output=True, text=True
        ).stdout
    current_pid = str(__import__("os").getpid())
    hits = []
    for line in process_text.splitlines():
        if current_pid in line and "22_phase0_preparation_lock.py" in line:
            continue
        if any(token in line for token in FORBIDDEN_PROCESS_TOKENS):
            hits.append(line.strip())
    return hits


def assert_no_forbidden_processes(process_text: str | None = None) -> None:
    hits = running_forbidden_processes(process_text)
    if hits:
        raise RuntimeError("PHASE0_FORBIDDEN_PROCESS_RUNNING:" + " | ".join(hits[:3]))


def assert_phase1_storage(path: Path, *, minimum_free_bytes: int) -> dict[str, int]:
    usage = shutil.disk_usage(path)
    if usage.free < minimum_free_bytes:
        raise RuntimeError(
            f"PHASE1_STORAGE_HEADROOM_INSUFFICIENT:free={usage.free}:required={minimum_free_bytes}"
        )
    return {"total_bytes": usage.total, "used_bytes": usage.used, "free_bytes": usage.free,
            "minimum_phase1_free_bytes": minimum_free_bytes}


def protected_inventory(paths: Iterable[Path], root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(set(paths)):
        if not path.is_file():
            raise RuntimeError(f"PHASE0_PROTECTED_EVIDENCE_MISSING:{path}")
        records.append({
            "path": str(path.relative_to(root)),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "status": "PROTECTED_READ_ONLY_EVIDENCE",
        })
    return records


def deprecated_registry_paths(path: Path) -> list[Path]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    result = []
    for row in rows:
        if row.get("old_status") != "DEPRECATED_INVALID_SCIENTIFIC_INPUT":
            raise RuntimeError("PHASE0_DEPRECATED_REGISTRY_STATUS_DRIFT")
        old = Path(row["old_input"])
        if not old.exists():
            raise RuntimeError(f"PHASE0_DEPRECATED_EVIDENCE_MISSING:{old}")
        result.append(old)
    return result


def assert_active_sentinel_revision(path: Path, *, expected_revision: str) -> None:
    if expected_revision not in str(path):
        raise RuntimeError(f"STALE_SENTINEL_INPUT_REJECTED:{path}")
    if any(marker.lower() in str(path).lower() for marker in DEPRECATED_MARKERS):
        raise RuntimeError(f"DEPRECATED_SENTINEL_INPUT_REJECTED:{path}")


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
