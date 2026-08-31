from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .checksum import sha256_file


REQUIRED_FIELDS = {
    "aoi_id", "sensor", "platform", "year", "nominal_fcover_date", "acquisition_datetime",
    "product_id", "collection", "version", "processing_level", "source_catalog", "source_uri",
    "local_path", "file_size", "checksum", "crs", "transform", "width", "height", "nodata",
    "scale", "offset", "qa_band", "download_timestamp", "clipping_geometry_version",
}


def validate_record(record: dict[str, Any]) -> None:
    missing = sorted(REQUIRED_FIELDS - record.keys())
    if missing:
        raise ValueError(f"MANIFEST_FIELDS_MISSING:{','.join(missing)}")


def write_manifest(path: Path, records: list[dict[str, Any]]) -> None:
    for record in records:
        validate_record(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".json":
        path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=sorted(REQUIRED_FIELDS))
            writer.writeheader(); writer.writerows(records)


def file_record(path: Path, **metadata: Any) -> dict[str, Any]:
    record = dict(metadata)
    record.update(local_path=str(path.resolve()), file_size=path.stat().st_size, checksum=sha256_file(path))
    record.setdefault("download_timestamp", datetime.now(timezone.utc).isoformat())
    validate_record(record)
    return record

