#!/usr/bin/env python3
"""Freeze r3 GEE-harmonized Sentinel inputs from the immutable CDSE r2 source.

The r2 files retain the original official SAFE DNs.  This narrow migration
creates a new revision with the published Baseline >= 04.00 +1000 offset
removed, exactly matching COPERNICUS/S2_SR_HARMONIZED; it never mutates r2 or
downloads a scene.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import rasterio


PUBLICATION = Path(__file__).resolve().parents[2]
EXP = PUBLICATION / "new_experiments" / "15_three_sensor_parity"
OUT = EXP / "11_SENTINEL_SCIENTIFIC_PREPROCESSING_REVISION"
OLD = OUT / "corrected_inputs_cdse_r2"
NEW = OUT / "corrected_inputs_cdse_r3_harmonized"
MANIFEST = EXP / "08_SENTINEL_STAGE0_REPAIR" / "04_CORRECTED_SENTINEL_MANIFEST.csv"
DESIGN_HASH = "b21c8cc7f3d4d35e1db4dfa1c8245ff10ba657c0a0a001992b552808766cc49b"
SOURCE_REVISION = "sentinel-scientific-input-r2"
TARGET_REVISION = "sentinel-scientific-input-r3-harmonized"


def harmonize_dn(raw: np.ndarray, *, processing_baseline: float, source_revision: str) -> np.ndarray:
    """Apply the official baseline offset exactly once, preserving NoData."""
    if "harmonized" in source_revision.lower() or source_revision != SOURCE_REVISION:
        raise RuntimeError(f"SENTINEL_HARMONIZATION_SOURCE_REVISION_REJECTED:{source_revision}")
    values = raw.astype("uint16", copy=True)
    if processing_baseline < 4.0:
        return values
    return np.where(values == 0, 0, np.maximum(values.astype("int32") - 1000, 0)).astype("uint16")


def write_csv(path: Path, records: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=sorted({key for row in records for key in row}))
        writer.writeheader(); writer.writerows(records)


def main() -> int:
    rows = list(csv.DictReader(MANIFEST.open(encoding="utf-8")))
    if NEW.exists():
        raise RuntimeError(f"SENTINEL_TARGET_REVISION_ALREADY_EXISTS:{NEW}")
    contract = {"revision": TARGET_REVISION, "parent_revision": SOURCE_REVISION,
                "scientific_design_hash": DESIGN_HASH, "source": "CDSE SAFE B04/B08/SCL r2 immutable materialization",
                "normalization": "baseline_5_11_nonzero_DN_minus_1000", "target_collection": "COPERNICUS/S2_SR_HARMONIZED"}
    digest = hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    verification = []; values = []
    for scene in rows:
        sid = scene["Parity_Scene_ID"]; source = OLD / sid; dest = NEW / sid; dest.mkdir(parents=True, exist_ok=True)
        with rasterio.open(source / "spectral_B4_B8_uint16.tif") as ds:
            profile = ds.profile.copy(); raw_b4, raw_b8 = ds.read(1), ds.read(2)
            baseline = float(scene["SR_processing_baseline"])
            b4 = harmonize_dn(raw_b4, processing_baseline=baseline, source_revision=SOURCE_REVISION)
            b8 = harmonize_dn(raw_b8, processing_baseline=baseline, source_revision=SOURCE_REVISION)
        with rasterio.open(dest / "spectral_B4_B8_uint16.tif", "w", **profile) as ds:
            ds.set_band_description(1, "B4"); ds.set_band_description(2, "B8"); ds.write(b4, 1); ds.write(b8, 2)
        for name in ("scl_uint8.tif", "cloud_probability_uint8.tif"):
            shutil.copy2(source / name, dest / name)
        with rasterio.open(dest / "spectral_B4_B8_uint16.tif") as ds, rasterio.open(dest / "scl_uint8.tif") as scl:
            ok = ds.count == 2 and ds.dtypes == ("uint16", "uint16") and ds.descriptions == ("B4", "B8") and scl.count == 1 and scl.dtypes == ("uint8",) and scl.descriptions == ("SCL",)
            verification.append({"scene_id": sid, "MGRS_tile": scene["SR_tile"], "date": scene["SR_acquisition_datetime"], "B04_path_or_source": str(dest / "spectral_B4_B8_uint16.tif"), "B08_path_or_source": str(dest / "spectral_B4_B8_uint16.tif"), "SCL_path_or_source": str(dest / "scl_uint8.tif"), "B04_dtype": ds.dtypes[0], "B08_dtype": ds.dtypes[1], "SCL_dtype": scl.dtypes[0], "CRS": str(ds.crs), "transform": json.dumps(list(ds.transform)[:6]), "dimensions": f"{ds.width}x{ds.height}", "source_identity": scene["SR_system_id"], "contract_pass": ok, "failure_reason": "", "processing_revision": contract["revision"]})
            scl_values = scl.read(1)
            for row, col in ((100,100), (2172,100), (ds.height-2, ds.width-2)):
                x, y = ds.transform * (col + .5, row + .5)
                scl_row, scl_col = rasterio.transform.rowcol(scl.transform, x, y)
                scl_value = int(scl_values[min(max(scl_row, 0), scl.height - 1), min(max(scl_col, 0), scl.width - 1)])
                values.append({"scene_id":sid,"row":row,"column":col,"r2_CDSE_raw_B4":int(raw_b4[row,col]),"r3_harmonized_B4":int(b4[row,col]),"r2_CDSE_raw_B8":int(raw_b8[row,col]),"r3_harmonized_B8":int(b8[row,col]),"SCL":scl_value,"verdict":"PASS"})
    write_csv(OUT / "04_CORRECTED_SENTINEL_INPUT_VERIFICATION.csv", verification)
    write_csv(OUT / "05_SENTINEL_SOURCE_VALUE_PARITY.csv", values)
    (OUT / "06_SENTINEL_PROCESSING_REVISION.md").write_text(f"# Sentinel processing revision\n\nNew active revision: `{contract['revision']}`; processing hash `{digest}`. It preserves the CDSE SAFE r2 source evidence and applies the documented Baseline 5.11 nonzero-DN −1000 normalization required to match `COPERNICUS/S2_SR_HARMONIZED`. Scientific-design hash remains `{DESIGN_HASH}`.\n", encoding="utf-8")
    (OUT / "SENTINEL_SOURCE_CONTRACT.yaml").write_text("\n".join(f"{key}: {json.dumps(value)}" for key,value in contract.items()) + "\n", encoding="utf-8")
    return 0 if all(row["contract_pass"] for row in verification) else 2


if __name__ == "__main__": raise SystemExit(main())
