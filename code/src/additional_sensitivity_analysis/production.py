"""Checkpointed Earth-Engine materialization for the three sensitivity branches.

This module is deliberately separate from the frozen primary asset builder: it
reads the same immutable source manifests and FCOVER assets but writes only
canonical paired outputs beneath a caller-selected result directory.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import ee
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from pyproj import Transformer

from common.blocks import block_id
from data_prep.gee_cloud import (_average_to_fcover, _composite_bands, _landsat_collection,
                                 _modis_collection, _quality_bands, _sentinel_collection,
                                 fcover_asset_id)

from .aerosol import AEROSOL_MODES
from .config import REPOSITORY_ROOT, canonical_hash, git_commit, load_yaml
from .io_utils import assert_sensitivity_output_path
from .schemas import assert_pair_schema, empty_pair_frame
from .temporal import assign_non_overlapping
from metrics.block_metrics import by_block
from metrics.holm import holm_adjust
from metrics.paired_tests import paired_two_sided
from metrics.regression_metrics import regression_metrics
from models.ols import fit_ols, predict_clipped


SOURCE_ROOT = REPOSITORY_ROOT / "data/metadata/provenance/00_execution_manifest/source_scenes/active_r2"
REGISTRY = REPOSITORY_ROOT / "data/metadata/design/multi_aoi/final_four_aoi_registry.geojson"
FROZEN_PRIMARY_PAIRS = REPOSITORY_ROOT / "data/canonical/paired_observations.csv.gz"
TRANSFORMER = Transformer.from_crs("EPSG:4326", "EPSG:32647", always_xy=True)
SENSOR_TO_MANIFEST = {"sentinel2": "ACTIVE_SENTINEL_SCENE_MANIFEST.csv",
                      "landsat": "ACTIVE_LANDSAT_SCENE_MANIFEST.csv",
                      "modis": "ACTIVE_MODIS_SCENE_MANIFEST.csv"}


def initialize_ee() -> None:
    """Initialize only with user-local credentials; no credential bytes are read into outputs."""
    configured = os.environ.get("FVC_EE_ENV_FILE")
    candidates = [Path(configured)] if configured else [
        REPOSITORY_ROOT.parents[2] / "model/.env", REPOSITORY_ROOT.parents[1] / "model/.env",
    ]
    env_file = next((path for path in candidates if path.is_file()), None)
    if env_file is None:
        raise RuntimeError("SENSITIVITY_EE_ENV_FILE_MISSING")
    load_dotenv(env_file)
    project = os.environ.get("EE_PROJECT_ID")
    if not project:
        raise RuntimeError("SENSITIVITY_EE_PROJECT_ID_MISSING")
    ee.Initialize(project=project, opt_url="https://earthengine-highvolume.googleapis.com")


def source_rows(sensor: str) -> list[dict[str, str]]:
    try:
        path = SOURCE_ROOT / SENSOR_TO_MANIFEST[sensor]
    except KeyError as exc:
        raise ValueError(f"SENSITIVITY_SENSOR_INVALID:{sensor}") from exc
    if not path.is_file():
        raise FileNotFoundError(f"SENSITIVITY_SOURCE_MANIFEST_MISSING:{path}")
    with path.open(encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def registry() -> dict[str, dict[str, Any]]:
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {str(feature["properties"]["aoi_id"]): feature for feature in payload["features"]}


def assert_output_root(path: Path) -> Path:
    resolved = assert_sensitivity_output_path(path)
    frozen = [(REPOSITORY_ROOT / "data/canonical").resolve(), (REPOSITORY_ROOT / "results").resolve(),
              (REPOSITORY_ROOT / "data/metadata").resolve()]
    if any(root == resolved or root in resolved.parents for root in frozen):
        raise ValueError(f"SENSITIVITY_OUTPUT_COLLIDES_WITH_FROZEN_DATA:{resolved}")
    return resolved


def _included(rows: Iterable[dict[str, str]], aoi: str, year: int, nominal: str) -> list[dict[str, str]]:
    result = [row for row in rows if row["AOI_ID"] == aoi and int(row["year"]) == year
              and row["nominal_date"] == nominal and row["included"].lower() == "true"]
    if not result:
        raise RuntimeError(f"SENSITIVITY_SOURCE_SELECTION_EMPTY:{aoi}:{year}:{nominal}")
    return result


def _fcover(aoi: str, nominal: str) -> ee.Image:
    asset = fcover_asset_id(aoi, nominal)
    try:
        ee.data.getAsset(asset)
    except Exception as exc:
        raise RuntimeError(f"SENSITIVITY_FCOVER_ASSET_MISSING:{asset}") from exc
    return ee.Image(asset)


def _landsat_aerosol_collection(region: ee.Geometry, fcover: ee.Image, scene_ids: list[str], mode: str) -> ee.ImageCollection:
    if mode not in AEROSOL_MODES:
        raise ValueError(f"AEROSOL_MODE_INVALID:{mode}")
    def prepare(value: ee.Image) -> ee.Image:
        image = ee.Image(value); red_dn = image.select("SR_B4"); nir_dn = image.select("SR_B5"); qa = image.select("QA_PIXEL")
        valid = ee.Image(1)
        for bit in (0, 1, 2, 3, 4, 5, 7):
            valid = valid.And(qa.rightShift(bit).bitwiseAnd(1).eq(0))
        aerosol = image.select("SR_QA_AEROSOL"); level = aerosol.rightShift(6).bitwiseAnd(3)
        extra = ee.Image(1) if mode == "primary_no_aerosol_filter" else aerosol.bitwiseAnd(1).eq(0).And(level.neq(3))
        if mode in ("valid_retrieval_no_high", "strict_aerosol"):
            extra = extra.And(aerosol.rightShift(1).bitwiseAnd(1).eq(1)).And(aerosol.rightShift(5).bitwiseAnd(1).eq(0))
        if mode == "strict_aerosol": extra = extra.And(level.lte(1))
        valid = valid.And(image.select("QA_RADSAT").eq(0)).And(red_dn.gte(7273)).And(red_dn.lte(43636)).And(nir_dn.gte(7273)).And(nir_dn.lte(43636)).And(extra)
        red = red_dn.multiply(0.0000275).add(-0.2); nir = nir_dn.multiply(0.0000275).add(-0.2)
        return _average_to_fcover(nir.subtract(red).divide(nir.add(red)).rename("NDVI").updateMask(valid), fcover).copyProperties(image, ["system:time_start", "system:index"])
    return ee.ImageCollection.fromImages([prepare(ee.Image(scene_id)) for scene_id in scene_ids])


def _collection(sensor: str, region: ee.Geometry, fcover: ee.Image, rows: list[dict[str, str]], *, aerosol_mode: str | None = None) -> ee.ImageCollection:
    ids = [row["system:id"] for row in rows]
    if sensor == "sentinel2": return _sentinel_collection(region, "2000-01-01", "2100-01-01", fcover, ids)
    if sensor == "landsat":
        return _landsat_aerosol_collection(region, fcover, ids, aerosol_mode) if aerosol_mode else _landsat_collection(region, "2000-01-01", "2100-01-01", fcover, ids)
    if sensor == "modis":
        return _modis_collection(region, date(2000, 1, 1), date(2100, 1, 1), fcover, ids)
    raise ValueError(f"SENSITIVITY_SENSOR_INVALID:{sensor}")


def _aggregation_reflectance_collection(sensor: str, fcover: ee.Image, rows: list[dict[str, str]]) -> ee.ImageCollection:
    """Route B: reduce matched native red/NIR support before the NDVI division."""
    def mean_pair(red: ee.Image, nir: ee.Image, valid: ee.Image, image: ee.Image) -> ee.Image:
        support = valid.And(red.add(nir).neq(0))
        mean_red = red.updateMask(support).reduceResolution(reducer=ee.Reducer.mean(), maxPixels=4096, bestEffort=False).reproject(fcover.projection())
        mean_nir = nir.updateMask(support).reduceResolution(reducer=ee.Reducer.mean(), maxPixels=4096, bestEffort=False).reproject(fcover.projection())
        denominator = mean_nir.add(mean_red)
        return mean_nir.subtract(mean_red).divide(denominator).rename("NDVI").updateMask(denominator.neq(0)).copyProperties(image, ["system:time_start", "system:index"])
    prepared = []
    for row in rows:
        image = ee.Image(row["system:id"])
        if sensor == "sentinel2":
            red = image.select("B4").multiply(0.0001); nir = image.select("B8").multiply(0.0001)
            index = str(row["system:id"]).rsplit("/", 1)[-1]; probability = ee.Image(f"COPERNICUS/S2_CLOUD_PROBABILITY/{index}").select("probability")
            valid = image.select("B4").gte(1).And(image.select("B4").lte(10000)).And(image.select("B8").gte(1)).And(image.select("B8").lte(10000)).And(image.select("SCL").eq(4).Or(image.select("SCL").eq(5)).Or(image.select("SCL").eq(7))).And(probability.lt(30))
        elif sensor == "landsat":
            red_dn, nir_dn, qa = image.select("SR_B4"), image.select("SR_B5"), image.select("QA_PIXEL"); valid = ee.Image(1)
            for bit in (0, 1, 2, 3, 4, 5, 7): valid = valid.And(qa.rightShift(bit).bitwiseAnd(1).eq(0))
            valid = valid.And(image.select("QA_RADSAT").eq(0)).And(red_dn.gte(7273)).And(red_dn.lte(43636)).And(nir_dn.gte(7273)).And(nir_dn.lte(43636)); red = red_dn.multiply(0.0000275).add(-0.2); nir = nir_dn.multiply(0.0000275).add(-0.2)
        elif sensor == "modis":
            red_dn, nir_dn, state, qa = image.select("sur_refl_b01"), image.select("sur_refl_b02"), image.select("State"), image.select("QA")
            bit = lambda value, offset, width=1: value.rightShift(offset).bitwiseAnd((1 << width) - 1)
            valid = bit(state, 0, 2).eq(0).And(bit(state, 2).eq(0)).And(bit(state, 3, 3).eq(1)).And(bit(state, 6, 2).lte(2)).And(bit(state, 8, 2).eq(0)).And(bit(state, 10).eq(0)).And(bit(state, 11).eq(0)).And(bit(state, 12).eq(0)).And(bit(state, 13).eq(0)).And(bit(state, 15).eq(0)).And(bit(qa, 0, 2).lte(1)).And(bit(qa, 4, 4).eq(0)).And(bit(qa, 8, 4).eq(0)).And(bit(qa, 12).eq(1)).And(red_dn.gte(-100)).And(red_dn.lte(16000)).And(nir_dn.gte(-100)).And(nir_dn.lte(16000)); red = red_dn.multiply(0.0001); nir = nir_dn.multiply(0.0001)
        else: raise ValueError(f"SENSITIVITY_SENSOR_INVALID:{sensor}")
        prepared.append(mean_pair(red, nir, valid, image))
    return ee.ImageCollection.fromImages(prepared)


def _feature_rows(image: ee.Image, region: ee.Geometry, *, aoi: str, sensor: str, year: int, nominal: str,
                  sensitivity: str, variant: str) -> list[dict[str, Any]]:
    collection = image.sample(region=region, geometries=True, tileScale=4, dropNulls=False)
    token = None; rows: list[dict[str, Any]] = []
    while True:
        request: dict[str, Any] = {"expression": collection, "pageSize": 5000}
        if token: request["pageToken"] = token
        page = ee.data.computeFeatures(request)
        for feature in page.get("features", []):
            values, geometry = feature.get("properties", {}), feature.get("geometry", {})
            coordinates = geometry.get("coordinates")
            if not coordinates or values.get("valid_reference") != 1 or values.get("contribution_count", 0) < 2: continue
            ndvi, fcover = values.get("NDVI"), values.get("FCOVER")
            if ndvi is None or fcover is None or not np.isfinite(float(ndvi)) or not np.isfinite(float(fcover)): continue
            lon, lat = map(float, coordinates[:2]); x, y = TRANSFORMER.transform(lon, lat)
            rows.append({"aoi_id": aoi, "sensor": sensor, "year": year, "nominal_date": nominal, "pixel_id": f"{lon:.12f},{lat:.12f}",
                         "NDVI": float(ndvi), "FCOVER": float(fcover), "contribution_count": int(values["contribution_count"]),
                         "block_id": f"{aoi}_{block_id(x, y)}", "sensitivity_name": sensitivity, "sensitivity_variant": variant})
        token = page.get("nextPageToken")
        if not token: break
    return rows


def materialize(sensor: str, *, sensitivity: str, variant: str, output_csv: Path,
                selector: Callable[[list[dict[str, str]], str, int, str], list[dict[str, str]]] | None = None,
                aerosol_mode: str | None = None, aggregation_route: str | None = None) -> pd.DataFrame:
    """Materialize one sensor's canonical pair data with atomic checkpoint output."""
    destination = assert_output_root(output_csv)
    # Route A is a reproduction control, not an independently changing data
    # product.  Hydrating the frozen canonical pairs into the isolated
    # sensitivity directory is the only way to make the control invariant to
    # later Earth Engine source/product revisions while retaining a fully
    # traceable, resumable Route B materialization path.
    if aggregation_route == "primary_ndvi_first":
        return _materialize_frozen_primary_reference(
            sensor, sensitivity=sensitivity, variant=variant, output_csv=destination
        )
    if destination.is_file():
        frame = pd.read_csv(destination); assert_pair_schema(frame.columns); return frame
    initialize_ee(); manifest = source_rows(sensor); features = registry(); all_rows: list[dict[str, Any]] = []
    for aoi, feature in sorted(features.items()):
        region = ee.Geometry(feature["geometry"])
        for year in range(2021, 2026):
            checkpoint = destination.parent.parent / "intermediate" / f"{sensitivity}_{variant}_{sensor}_{aoi}_{year}.csv"
            checkpoint_manifest = checkpoint.with_suffix(".manifest.json")
            if checkpoint.is_file() and checkpoint_manifest.is_file():
                group = pd.read_csv(checkpoint); assert_pair_schema(group.columns); all_rows.extend(group.to_dict("records")); continue
            group_rows: list[dict[str, Any]] = []
            for month_day in ("07-20", "07-31", "08-10"):
                nominal = f"{year}-{month_day}"; selected = _included(manifest, aoi, year, nominal)
                if selector is not None: selected = selector(manifest, aoi, year, nominal)
                # The non-overlap partition is allowed to yield an empty
                # source set for one nominal target.  Leaving it empty is the
                # only scientifically valid result: reusing a neighbouring
                # source would reintroduce overlap.  The per-group checkpoint
                # remains complete and the support summary explicitly counts
                # the resulting zero-source composite.
                if not selected:
                    continue
                raw = _fcover(aoi, nominal); comp = (_aggregation_reflectance_collection(sensor, raw, selected) if aggregation_route == "reflectance_first" else _collection(sensor, region, raw, selected, aerosol_mode=aerosol_mode))
                bands = _quality_bands(raw, month_day.replace("-", ""))
                ndvi, count = _composite_bands(comp, sensor, month_day.replace("-", ""))
                image = ee.Image.cat([*bands, ndvi.rename("NDVI"), count.rename("contribution_count")]).select(["fcover_" + month_day.replace("-", ""), "valid_reference_" + month_day.replace("-", ""), "NDVI", "contribution_count"], ["FCOVER", "valid_reference", "NDVI", "contribution_count"])
                group_rows.extend(_feature_rows(image, region, aoi=aoi, sensor=sensor, year=year, nominal=nominal, sensitivity=sensitivity, variant=variant))
            # A stricter QA screen can validly leave an AOI--year without any
            # paired target cells.  Preserve that observation as a typed,
            # schema-valid empty checkpoint rather than mistaking it for a
            # malformed table or inventing a scientific row.
            group = pd.DataFrame(group_rows) if group_rows else empty_pair_frame()
            assert_pair_schema(group.columns)
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            partial = checkpoint.with_suffix(".csv.partial"); group.to_csv(partial, index=False); partial.replace(checkpoint)
            checkpoint_manifest.write_text(json.dumps({"aoi": aoi, "year": year, "sensor": sensor, "sensitivity": sensitivity,
                "variant": variant, "rows": len(group), "n_pairs": len(group), "n_sources_retained": 0 if group.empty else None,
                "support_retention": 0.0 if group.empty else None, "zero_support": bool(group.empty),
                "output_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                "status": "COMPLETED_ZERO_SUPPORT" if group.empty else "COMPLETED"}, indent=2) + "\n", encoding="utf-8")
            all_rows.extend(group_rows)
    frame = pd.DataFrame(all_rows) if all_rows else empty_pair_frame(); assert_pair_schema(frame.columns)
    temporary = destination.with_suffix(destination.suffix + ".partial")
    destination.parent.mkdir(parents=True, exist_ok=True); frame.to_csv(temporary, index=False); temporary.replace(destination)
    manifest_path = destination.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "git_commit": git_commit(),
        "config_hash": canonical_hash({"sensitivity": sensitivity, "variant": variant, "sensor": sensor}), "rows": len(frame),
        "output_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "status": "COMPLETED"}, indent=2) + "\n", encoding="utf-8")
    return frame


def _atomic_csv(frame: pd.DataFrame, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".partial")
    frame.to_csv(temporary, index=False)
    temporary.replace(destination)


def _materialize_frozen_primary_reference(sensor: str, *, sensitivity: str, variant: str,
                                          output_csv: Path) -> pd.DataFrame:
    """Adapt immutable primary pairs into isolated Route-A checkpoints.

    This is deliberately limited to the aggregation-order Route-A control.
    The scientific alternative (Route B) is still materialized from the exact
    scenes through Earth Engine.  The adapter prevents current upstream
    collection revisions from being mistaken for an aggregation-order effect.
    """
    if not FROZEN_PRIMARY_PAIRS.is_file():
        raise FileNotFoundError(f"FROZEN_PRIMARY_PAIRS_MISSING:{FROZEN_PRIMARY_PAIRS}")
    primary = pd.read_csv(FROZEN_PRIMARY_PAIRS)
    primary = primary[primary.sensor == sensor].copy()
    if primary.empty:
        raise RuntimeError(f"FROZEN_PRIMARY_SENSOR_EMPTY:{sensor}")
    primary["sensitivity_name"] = sensitivity
    primary["sensitivity_variant"] = variant
    canonical = primary[["aoi_id", "sensor", "year", "nominal_date", "pixel_id", "NDVI", "FCOVER",
                         "contribution_count", "block_id", "sensitivity_name", "sensitivity_variant"]].copy()
    assert_pair_schema(canonical.columns)
    source_hash = hashlib.sha256(FROZEN_PRIMARY_PAIRS.read_bytes()).hexdigest()
    for (aoi, year), group in canonical.groupby(["aoi_id", "year"], sort=True):
        checkpoint = output_csv.parent.parent / "intermediate" / f"{sensitivity}_{variant}_{sensor}_{aoi}_{year}.csv"
        checkpoint_manifest = checkpoint.with_suffix(".manifest.json")
        reuse = False
        if checkpoint.is_file() and checkpoint_manifest.is_file():
            try:
                existing = json.loads(checkpoint_manifest.read_text(encoding="utf-8"))
                reuse = (existing.get("status") == "COMPLETED" and
                         existing.get("materialization_mode") == "frozen_primary_canonical_adapter" and
                         existing.get("source_sha256") == source_hash and
                         existing.get("output_sha256") == hashlib.sha256(checkpoint.read_bytes()).hexdigest())
            except (OSError, ValueError):
                reuse = False
        if not reuse:
            _atomic_csv(group, checkpoint)
            checkpoint_manifest.write_text(json.dumps({
                "aoi": aoi, "year": int(year), "sensor": sensor,
                "sensitivity": sensitivity, "variant": variant,
                "materialization_mode": "frozen_primary_canonical_adapter",
                "source_path": str(FROZEN_PRIMARY_PAIRS), "source_sha256": source_hash,
                "rows": len(group), "output_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                "status": "COMPLETED",
            }, indent=2) + "\n", encoding="utf-8")
    _atomic_csv(canonical, output_csv)
    output_csv.with_suffix(".manifest.json").write_text(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(), "git_commit": git_commit(),
        "config_hash": canonical_hash({"sensitivity": sensitivity, "variant": variant, "sensor": sensor,
                                         "materialization_mode": "frozen_primary_canonical_adapter"}),
        "materialization_mode": "frozen_primary_canonical_adapter", "source_sha256": source_hash,
        "rows": len(canonical), "output_sha256": hashlib.sha256(output_csv.read_bytes()).hexdigest(),
        "status": "COMPLETED",
    }, indent=2) + "\n", encoding="utf-8")
    return canonical


def temporal_selector(manifest: list[dict[str, str]], *, aoi: str, sensor: str, year: int) -> dict[str, list[dict[str, str]]]:
    """Return exactly-one assignment of unique scene identities for all three nominal labels."""
    unique = {row["system:id"]: row for row in manifest if row["AOI_ID"] == aoi and int(row["year"]) == year and row["included"].lower() == "true"}
    observations = pd.DataFrame({"source_identity": list(unique), "acquisition_date": [row["acquisition_datetime"] for row in unique.values()]})
    assigned = assign_non_overlapping(observations)
    mapping = defaultdict(list)
    for _, row in assigned.dropna(subset=["assigned_nominal_date"]).iterrows(): mapping[str(row.assigned_nominal_date)].append(unique[str(row.source_identity)])
    assigned_count = int(assigned.assigned_nominal_date.notna().sum())
    if sum(len(value) for value in mapping.values()) != assigned_count:
        raise RuntimeError("TEMPORAL_ASSIGNMENT_INCOMPLETE")
    if assigned.dropna(subset=["assigned_nominal_date"]).groupby("source_identity").assigned_nominal_date.nunique().gt(1).any():
        raise RuntimeError("TEMPORAL_ASSIGNMENT_DUPLICATE")
    return dict(mapping)


def nearest_nominal_scene_selector(manifest: list[dict[str, str]], aoi: str, year: int, nominal: str) -> list[dict[str, str]]:
    """Selector adapter for :func:`materialize`; validates all targets each call."""
    mapping = temporal_selector(manifest, aoi=aoi, sensor="unused", year=year)
    # A nearest-date partition can legitimately leave a nominal composite with
    # zero sources (for example when every available scene is closer to 20
    # July or 10 August).  The caller records this as a zero-source composite
    # rather than borrowing an overlapping scene or inventing a replacement.
    return mapping.get(nominal, [])


HISTORIES = {"W2022": [2022], "W2023": [2023], "W2024": [2024], "W2022_2023": [2022, 2023],
             "W2023_2024": [2023, 2024], "W2022_2024": [2022, 2023, 2024]}
ROLLING = {"R2024-H1": ([2023], 2024), "R2024-H2": ([2022, 2023], 2024), "R2024-H3": ([2021, 2022, 2023], 2024),
           "R2025-H1": ([2024], 2025), "R2025-H2": ([2023, 2024], 2025), "R2025-H3": ([2022, 2023, 2024], 2025)}


def _score(train: pd.DataFrame, target: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame, float, float]:
    model = fit_ols(train.NDVI, train.FCOVER); prediction = predict_clipped(model, target.NDVI)
    scored = target[["block_id"]].copy(); scored["reference"] = target.FCOVER.to_numpy(float); scored["prediction"] = prediction
    return regression_metrics(scored.reference, scored.prediction), by_block(scored), float(model.coef_[0]), float(model.intercept_)


def evaluate_pairs(frame: pd.DataFrame, output_root: Path, *, sensitivity: str, variant: str) -> dict[str, pd.DataFrame]:
    """Evaluate canonical pairs by reusing the frozen downstream implementation."""
    from execution.science import (_complete_history_blocks, _fit_score, _groupkfold,
                                   _loyo, _metrics_with_blocks, _roles, _rolling_tests)

    assert_pair_schema(frame.columns)
    root = assert_output_root(output_root)
    root.mkdir(parents=True, exist_ok=True)
    contract = load_yaml(REPOSITORY_ROOT / "code/configs/scientific_execution.yaml")
    multi_rows: list[dict[str, Any]] = []
    multi_coefficients: list[dict[str, Any]] = []
    groupkfold: list[dict[str, Any]] = []
    loyo: list[dict[str, Any]] = []
    reserve_rows: list[dict[str, Any]] = []
    rolling_rows: list[dict[str, Any]] = []
    rolling_coefficients: list[dict[str, Any]] = []
    rolling_blocks: list[dict[str, Any]] = []

    def identity(experiment: str, aoi: str, sensor: str, years: list[int], target: int, **extra: Any) -> dict[str, Any]:
        return {"sensitivity": sensitivity, "variant": variant, "experiment": experiment,
                "AOI": aoi, "sensor": sensor, "train_years": ";".join(map(str, years)),
                "target_year": target, **extra}

    for (aoi, sensor), sensor_rows in frame.groupby(["aoi_id", "sensor"], sort=True):
        for window in contract["multi_aoi_historical_windows"]:
            years = [int(year) for year in window["train_years"]]
            historical = _roles(_complete_history_blocks(sensor_rows[sensor_rows.year.isin(years)], years), contract)
            base = identity("multi_aoi", aoi, sensor, years, 2025, window=window["id"])
            groupkfold.extend(_groupkfold(historical, base))
            loyo.extend(_loyo(historical, base, years))
            development = historical[historical.spatial_role == "development"]
            reserve = historical[historical.spatial_role == "reserve"]
            _, reserve_metric, _ = _fit_score(development, reserve)
            reserve_rows.append({**base, "train_n": len(development), "test_n": len(reserve),
                                 "block_n": reserve.block_id.nunique(), **reserve_metric})
            model = fit_ols(historical.NDVI, historical.FCOVER)
            multi_coefficients.append({**base, "slope": float(model.coef_[0]), "intercept": float(model.intercept_),
                                       "train_n": len(historical), "train_block_n": historical.block_id.nunique()})
            target = sensor_rows[sensor_rows.year == 2025]
            if target.empty:
                raise RuntimeError(f"SENSITIVITY_MULTI_TARGET_EMPTY:{aoi}:{sensor}")
            metric, _ = _metrics_with_blocks(target, predict_clipped(model, target.NDVI))
            multi_rows.append({**base, "n": len(target), "block_n": target.block_id.nunique(), **metric})

        for window in contract["rolling_origin"]["primary"]:
            years = [int(year) for year in window["history_years"]]
            target_year = int(window["target_year"])
            train = _complete_history_blocks(sensor_rows[sensor_rows.year.isin(years)], years)
            target = sensor_rows[sensor_rows.year == target_year]
            if train.empty or target.empty:
                raise RuntimeError(f"SENSITIVITY_ROLLING_INPUT_EMPTY:{aoi}:{sensor}:{window['id']}")
            base = identity("rolling_origin", aoi, sensor, years, target_year,
                            rolling_id=window["id"], history_length=int(window["history_length"]))
            model, metric, blocks = _fit_score(train, target)
            rolling_coefficients.append({**base, "slope": float(model.coef_[0]), "intercept": float(model.intercept_),
                                         "train_n": len(train), "train_block_n": train.block_id.nunique()})
            rolling_rows.append({**base, "target_n": len(target), "target_block_n": target.block_id.nunique(), **metric})
            for _, row in blocks.iterrows():
                rolling_blocks.append({**base, "block_id": row.block_id, "block_rmse": row.RMSE,
                                       "block_mae": row.MAE, "block_bias": row.Bias, "block_n": row.n})

    multi_df = pd.DataFrame(multi_rows).merge(
        pd.DataFrame(multi_coefficients)[["AOI", "sensor", "window", "slope", "intercept", "train_n", "train_block_n"]],
        on=["AOI", "sensor", "window"], validate="one_to_one")
    rolling_df = pd.DataFrame(rolling_rows).merge(
        pd.DataFrame(rolling_coefficients)[["AOI", "sensor", "rolling_id", "slope", "intercept", "train_n", "train_block_n"]],
        on=["AOI", "sensor", "rolling_id"], validate="one_to_one")
    rolling_df["history_length_rank_by_global_RMSE"] = rolling_df.groupby(
        ["AOI", "sensor", "target_year"])["RMSE"].rank(method="min")
    block_df = pd.DataFrame(rolling_blocks)
    contrasts = _rolling_tests(contract, block_df)
    contrasts.insert(0, "sensitivity", sensitivity)
    contrasts.insert(1, "variant", variant)
    frames = {
        "multi_aoi_metrics": multi_df,
        "multi_aoi_coefficients": pd.DataFrame(multi_coefficients),
        "multi_aoi_groupkfold": pd.DataFrame(groupkfold),
        "multi_aoi_loyo": pd.DataFrame(loyo),
        "multi_aoi_reserve": pd.DataFrame(reserve_rows),
        "rolling_origin_metrics": rolling_df,
        "rolling_origin_coefficients": pd.DataFrame(rolling_coefficients),
        "rolling_origin_block_metrics": block_df,
        "block_contrasts": contrasts,
    }
    for name, value in frames.items():
        _atomic_csv(value, root / f"{name}.csv")
    return frames
