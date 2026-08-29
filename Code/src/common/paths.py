from pathlib import Path


def require_existing(path: str | Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists(): raise FileNotFoundError(f"REQUIRED_PATH_MISSING:{resolved}")
    return resolved

