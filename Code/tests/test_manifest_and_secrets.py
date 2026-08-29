from pathlib import Path
import re
import pytest

from common.manifests import validate_record, REQUIRED_FIELDS

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_requires_complete_lineage():
    with pytest.raises(ValueError, match="MANIFEST_FIELDS_MISSING"):
        validate_record({"aoi_id": "AOI-00"})
    validate_record({key: "x" for key in REQUIRED_FIELDS})


def test_no_tracked_secret_assignments():
    patterns = re.compile(r"(?i)(api[_-]?token|access[_-]?key|secret[_-]?key|password)\s*[:=]\s*['\"][^'\"]+['\"]")
    hits = []
    for path in ROOT.rglob("*"):
        if path.is_file() and path.suffix in {".py", ".yaml", ".yml", ".json", ".toml"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            if patterns.search(text): hits.append(str(path))
    assert hits == []

