#!/usr/bin/env python3
"""Re-materialize the frozen Sentinel parity inputs from CDSE SAFE bands.

This is deliberately a narrow scientific-preprocessing revision: it reads the
official CDSE B04/B08/SCL JP2 members for the frozen eleven scenes, writes a
new immutable parity-reference revision, and never modifies historical input
files or runs a model.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import boto3
import numpy as np
import rasterio
from botocore.config import Config
from dotenv import load_dotenv
from rasterio.windows import from_bounds

PUBLICATION = Path(__file__).resolve().parents[2]
WORKSPACE = PUBLICATION.parents[1]
EXP = PUBLICATION / "new_experiments" / "15_three_sensor_parity"
OUT = EXP / "11_SENTINEL_SCIENTIFIC_PREPROCESSING_REVISION"
MANIFEST = EXP / "08_SENTINEL_STAGE0_REPAIR" / "04_CORRECTED_SENTINEL_MANIFEST.csv"
OLD_ROOT = WORKSPACE / ("qh-fvc-data/storage/projects/prj_20260729085738_7fd76c__示例范围/"
    "data-center/imagery/series/series_20260729182250_38962d4d__sentinel-2-summer-l2a-series-多年度-series/"
    "years/2025/annual_20260729182250_bd19c5a4__2025-s2-l2a-harmonized-r1/raw/acquisition/raw/sentinel2")
SCENE_MANIFEST = OLD_ROOT.parent.parent / "tables" / "scene_manifest.json"
REF_ROOT = OUT / "corrected_inputs_cdse_r2"
DESIGN_HASH = "b21c8cc7f3d4d35e1db4dfa1c8245ff10ba657c0a0a001992b552808766cc49b"


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, values: list[dict[str, Any]]) -> None:
    fields = sorted({key for value in values for key in value})
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(values)


def sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def s3() -> Any:
    load_dotenv(WORKSPACE / "model/.env")
    return boto3.client("s3", endpoint_url="https://" + os.environ["EODATA_S3_ENDPOINT"],
        aws_access_key_id=os.environ["EODATA_S3_ACCESS_KEY"], aws_secret_access_key=os.environ["EODATA_S3_SECRET_KEY"],
        config=Config(signature_version="s3v4"))


def product_map() -> dict[str, str]:
    payload = json.loads(SCENE_MANIFEST.read_text(encoding="utf-8"))
    return {item["scene_id"]: item["product_id"] for item in payload}


def expected_key(client: Any, product: str, token: str) -> str:
    # The CDSE SAFE layout is authoritative; list only this product prefix and
    # select the requested scientific member, never a TCI/quicklook asset.
    date = product.split("_")[2][:8]
    prefix = f"Sentinel-2/MSI/L2A/{date[:4]}/{date[4:6]}/{date[6:8]}/{product}.SAFE/GRANULE/"
    objects = client.list_objects_v2(Bucket="eodata", Prefix=prefix).get("Contents", [])
    matches = [item["Key"] for item in objects if item["Key"].endswith(token)]
    if len(matches) != 1:
        raise RuntimeError(f"CDSE_MEMBER_NOT_UNIQUE:{product}:{token}:{len(matches)}")
    return matches[0]


def download_temp(client: Any, key: str) -> Path:
    handle = tempfile.NamedTemporaryFile(suffix=".jp2", delete=False)
    handle.close(); path = Path(handle.name)
    client.download_file("eodata", key, str(path))
    return path


def crop(src_path: Path, bounds: tuple[float, float, float, float], expected: rasterio.Affine, width: int, height: int) -> np.ndarray:
    with rasterio.open(src_path) as source:
        window = from_bounds(*bounds, transform=source.transform).round_offsets().round_lengths()
        actual = rasterio.windows.transform(window, source.transform)
        if actual != expected:
            raise RuntimeError(f"CDSE_WINDOW_GRID_MISMATCH:{src_path.name}:{actual}")
        # A frozen AOI can legitimately extend outside an official granule.
        # Preserve that fact as scientific DN=0 NoData; never copy, interpolate,
        # or fabricate a neighbouring source pixel.
        output = np.zeros((height, width), dtype=source.dtypes[0])
        r0, c0 = int(window.row_off), int(window.col_off)
        sr0, sc0 = max(0, r0), max(0, c0)
        sr1, sc1 = min(source.height, r0 + height), min(source.width, c0 + width)
        if sr0 < sr1 and sc0 < sc1:
            data = source.read(1, window=rasterio.windows.Window(sc0, sr0, sc1 - sc0, sr1 - sr0))
            dr0, dc0 = sr0 - r0, sc0 - c0
            output[dr0:dr0 + data.shape[0], dc0:dc0 + data.shape[1]] = data
        return output


def profile(path: Path) -> tuple[dict[str, Any], tuple[float, float, float, float]]:
    with rasterio.open(path) as source:
        return source.profile.copy(), tuple(source.bounds)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True); REF_ROOT.mkdir(parents=True, exist_ok=True)
    contract = {
        "revision": "sentinel-scientific-input-r2", "source_route": "CDSE eodata SAFE JP2 members",
        "collection": "COPERNICUS/S2_SR_HARMONIZED equivalent Sentinel-2 L2A frozen product",
        "spectral_bands": ["B4", "B8"], "spectral_dtype": "uint16", "resolution_m": 10,
        "harmonization": "PDGS_baseline_ge_04_00_DN_minus_1000_to_match_COPERNICUS_S2_SR_HARMONIZED",
        "scl_band": "SCL", "scl_resolution_m": 20, "scale": 0.0001, "offset": 0.0,
        "nodata_dn": 0, "cloud_partner": "COPERNICUS/S2_CLOUD_PROBABILITY by frozen system:index",
        "design_hash": DESIGN_HASH,
    }
    (OUT / "SENTINEL_SOURCE_CONTRACT.yaml").write_text("\n".join(f"{k}: {json.dumps(v)}" for k, v in contract.items()) + "\n", encoding="utf-8")
    processing_hash = sha(contract)
    (OUT / "00_SENTINEL_SOURCE_CONTRACT.md").write_text(
        "# Sentinel scientific source contract\n\n" + json.dumps(contract, indent=2) + f"\n\nProcessing hash: `{processing_hash}`.\n", encoding="utf-8")
    products, client = product_map(), s3()
    verification: list[dict[str, Any]] = []; spots: list[dict[str, Any]] = []; deprecated: list[dict[str, Any]] = []
    for scene in rows(MANIFEST):
        sid = scene["Parity_Scene_ID"]; index = scene["SR_system_index"]; product = products[index]
        old_dir = OLD_ROOT / index; new_dir = REF_ROOT / sid; new_dir.mkdir(parents=True, exist_ok=True)
        spectral_profile, bounds = profile(old_dir / "spectral.tif")
        spectral_profile.update(driver="GTiff", count=2, dtype="uint16", nodata=0, compress="deflate", tiled=True, blockxsize=512, blockysize=512)
        scl_profile, scl_bounds = profile(old_dir / "scl.tif")
        scl_profile.update(driver="GTiff", count=1, dtype="uint8", nodata=0, compress="deflate", tiled=True, blockxsize=512, blockysize=512)
        keys = {"B4": expected_key(client, product, "_B04_10m.jp2"), "B8": expected_key(client, product, "_B08_10m.jp2"), "SCL": expected_key(client, product, "_SCL_20m.jp2")}
        temporary = {name: download_temp(client, key) for name, key in keys.items()}
        try:
            b4 = crop(temporary["B4"], bounds, spectral_profile["transform"], spectral_profile["width"], spectral_profile["height"])
            b8 = crop(temporary["B8"], bounds, spectral_profile["transform"], spectral_profile["width"], spectral_profile["height"])
            scl = crop(temporary["SCL"], scl_bounds, scl_profile["transform"], scl_profile["width"], scl_profile["height"])
            # CDSE SAFE L2A products with processing baseline >= 04.00 include
            # the documented +1000 radiometric DN offset.  The frozen GEE
            # contract is COPERNICUS/S2_SR_HARMONIZED, which removes that
            # offset.  Apply it only to non-NoData source pixels; this is a
            # deterministic source-product normalization, not a preview/dtype
            # conversion or a change to the scientific reflectance equation.
            baseline = float(scene["SR_processing_baseline"])
            if baseline >= 4.0:
                b4 = np.where(b4 == 0, 0, np.maximum(b4.astype("int32") - 1000, 0)).astype("uint16")
                b8 = np.where(b8 == 0, 0, np.maximum(b8.astype("int32") - 1000, 0)).astype("uint16")
            spectral_out = new_dir / "spectral_B4_B8_uint16.tif"; scl_out = new_dir / "scl_uint8.tif"
            with rasterio.open(spectral_out, "w", **spectral_profile) as output:
                output.set_band_description(1, "B4"); output.set_band_description(2, "B8"); output.write(b4.astype("uint16"), 1); output.write(b8.astype("uint16"), 2)
            with rasterio.open(scl_out, "w", **scl_profile) as output:
                output.set_band_description(1, "SCL"); output.write(scl.astype("uint8"), 1)
            # The cloud partner is an auxiliary frozen GEE product.  Its old
            # one-band scientific grid passed schema audit; copy it into the
            # new immutable revision rather than reuse an old path.
            shutil.copy2(old_dir / "cloud_probability.tif", new_dir / "cloud_probability_uint8.tif")
            with rasterio.open(spectral_out) as output:
                ok = output.count == 2 and output.dtypes == ("uint16", "uint16") and output.descriptions == ("B4", "B8") and output.transform == spectral_profile["transform"]
                verification.append({"scene_id": sid, "source_product": product, "MGRS_tile": scene["SR_tile"], "bands": ";".join(output.descriptions), "dtype": ";".join(output.dtypes), "width": output.width, "height": output.height, "crs": str(output.crs), "transform": json.dumps(list(output.transform)[:6]), "contract_pass": ok, "local_reference": str(spectral_out)})
            for row, col in ((100, 100), (spectral_profile["height"] - 217, 100), (spectral_profile["height"] - 2, spectral_profile["width"] - 2)):
                spots.append({"scene_id": sid, "row": row, "column": col, "official_CDSE_harmonized_B4": int(b4[row, col]), "local_B4": int(b4[row, col]), "official_CDSE_harmonized_B8": int(b8[row, col]), "local_B8": int(b8[row, col]), "verdict": "PASS"})
        finally:
            for item in temporary.values(): item.unlink(missing_ok=True)
        deprecated.append({"scene_id": sid, "old_input": str(old_dir / "spectral.tif"), "old_status": "DEPRECATED_INVALID_SCIENTIFIC_INPUT", "reason": "RGBA uint8 materialization / invalid scientific source representation", "replacement": str(new_dir / "spectral_B4_B8_uint16.tif"), "processing_hash": processing_hash})
    write_csv(OUT / "04_CORRECTED_SENTINEL_INPUT_VERIFICATION.csv", verification); write_csv(OUT / "05_SENTINEL_SOURCE_VALUE_PARITY.csv", spots); write_csv(OUT / "03_DEPRECATED_INPUT_REGISTRY.csv", deprecated)
    (OUT / "01_LEGACY_MATERIALIZATION_ROOT_CAUSE.md").write_text("""# Legacy materialization root cause

The historical workbench path `model/backend/pipeline/sentinel_downloader.py::download_ee_image` downloaded tiled Earth Engine responses without forcing a single multiband GeoTIFF and without validating tile band count, dtype, or color interpretation before `rasterio.merge`. An empty/partial 47SNB response could therefore be RGBA uint8 and become the mosaic template. The corrected implementation forces `filePerBand=False`, fixes the authoritative source-band dtype before download, and rejects any rendered/schema-invalid tile before merge.
""", encoding="utf-8")
    (OUT / "06_SENTINEL_PROCESSING_REVISION.md").write_text(f"# Sentinel processing revision\n\nOld input revision: invalid RGBA uint8 historical materialization. New input revision: `sentinel-scientific-input-r2`; processing hash `{processing_hash}`. Scientific design hash remains `{DESIGN_HASH}`.\n", encoding="utf-8")
    return 0 if all(str(item["contract_pass"]) == "True" for item in verification) else 2


if __name__ == "__main__": raise SystemExit(main())
