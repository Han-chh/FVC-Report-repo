from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from pyproj import Geod
from shapely.geometry import shape


def distance_km(a, b):
    return Geod(ellps="WGS84").inv(a[0], a[1], b[0], b[1])[2] / 1000.0


def eligibility(row, rules, original):
    reasons = []
    for field, key in (("water_fraction", "maximum_water_fraction"), ("snow_ice_fraction", "maximum_snow_ice_fraction"),
                       ("cropland_fraction", "maximum_cropland_fraction"), ("built_fraction", "maximum_built_fraction")):
        if row[field] > rules[key]: reasons.append(f"{field}>{rules[key]}")
    if row["vegetation_fraction"] + row["bare_sparse_fraction"] < rules["minimum_vegetation_plus_bare_fraction"]:
        reasons.append("vegetation_plus_bare_below_minimum")
    if distance_km((row.centroid_lon, row.centroid_lat), original) < rules["minimum_centroid_separation_from_aoi00_km"]:
        reasons.append("too_close_to_AOI-00")
    if row.historical_ndvi_years < 4 or row.dem_items < 1 or row.worldcover_items < 1:
        reasons.append("environmental_data_incomplete")
    return not reasons, ";".join(reasons)


def select(features_csv: Path, candidates_geojson: Path, config_path: Path, output_dir: Path):
    df = pd.read_csv(features_csv)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")); rules = config["eligibility"]
    original_row = df[df.aoi_id == "AOI-00"].iloc[0]
    original = (original_row.centroid_lon, original_row.centroid_lat)
    df["eligibility"] = False; df["exclusion_reason"] = ""
    for i, row in df.iterrows():
        if row.aoi_id == "AOI-00": df.loc[i, "eligibility"] = True; continue
        eligible, reason = eligibility(row, rules, original); df.loc[i, "eligibility"] = eligible; df.loc[i, "exclusion_reason"] = reason
    columns = config["selection_features"]
    eligible = df[(df.aoi_id != "AOI-00") & df.eligibility].copy()
    if len(eligible) < 3: raise RuntimeError("FEWER_THAN_THREE_ELIGIBLE_CANDIDATES")
    all_for_scale = df[[*columns]].astype(float)
    mean = all_for_scale.mean(); std = all_for_scale.std(ddof=0).replace(0, 1)
    vectors = {row.aoi_id: ((row[columns] - mean) / std).to_numpy(dtype=float) for _, row in df.iterrows()}
    selected = ["AOI-00"]; log = []
    while len(selected) < 4:
        scored = []
        for _, row in eligible[~eligible.aoi_id.isin(selected)].iterrows():
            env_min = min(float(np.linalg.norm(vectors[row.aoi_id] - vectors[s])) for s in selected)
            geo_min = min(distance_km((row.centroid_lon, row.centroid_lat),
                                      tuple(df[df.aoi_id == s][["centroid_lon", "centroid_lat"]].iloc[0])) for s in selected)
            allowed = geo_min >= rules["minimum_pairwise_selected_centroid_separation_km"]
            scored.append((allowed, env_min, geo_min, row.aoi_id))
        feasible = [value for value in scored if value[0]] or scored
        chosen = max(feasible, key=lambda value: (value[1], value[2], value[3]))
        selected.append(chosen[3]); log.append({"step": len(selected) - 1, "selected_candidate": chosen[3], "minimum_environmental_distance": chosen[1], "minimum_geographic_distance_km": chosen[2], "distance_rule_met": chosen[0]})
    final_mapping = {candidate: f"AOI-{index:02d}" for index, candidate in enumerate(selected[1:], 1)}
    df["selection_status"] = df.aoi_id.map(lambda value: "ORIGINAL" if value == "AOI-00" else ("SELECTED" if value in final_mapping else "NOT_SELECTED"))
    df["final_aoi_id"] = df.aoi_id.map(lambda value: value if value == "AOI-00" else final_mapping.get(value, ""))
    original_vector = vectors["AOI-00"]
    df["environmental_distance_to_AOI00"] = df.aoi_id.map(lambda value: float(np.linalg.norm(vectors[value] - original_vector)))
    df["geographic_distance_to_AOI00_km"] = df.apply(lambda row: distance_km((row.centroid_lon, row.centroid_lat), original), axis=1)
    candidate_ids = [value for value in df.aoi_id if value != "AOI-00"]
    df["minimum_environmental_distance_to_other_candidates"] = df.aoi_id.map(
        lambda value: min(float(np.linalg.norm(vectors[value] - vectors[other])) for other in candidate_ids if other != value)
        if value in candidate_ids else min(float(np.linalg.norm(vectors[value] - vectors[other])) for other in candidate_ids))
    def minimum_geo(row):
        others = df[df.aoi_id != row.aoi_id]
        return min(distance_km((row.centroid_lon, row.centroid_lat), (other.centroid_lon, other.centroid_lat)) for other in others.itertuples())
    df["minimum_geographic_distance_to_other_aois_km"] = df.apply(minimum_geo, axis=1)
    status_path = output_dir.parent / "data/data_preparation_status.csv"
    if status_path.exists():
        status = pd.read_csv(status_path)
        for sensor in ("sentinel2", "landsat", "modis", "fcover"):
            subset = status[status.sensor_product == sensor]
            lookup = subset.groupby("aoi_id").apply(
                lambda group: ";".join(f"{int(row.year)}:{row.status}:{int(row.catalog_item_count)}" for row in group.sort_values("year").itertuples()),
                include_groups=False,
            )
            df[f"{sensor}_2021_2025_availability"] = df.aoi_id.map(lookup).fillna("NOT_AUDITED")
    output_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_dir / "candidate_aoi_registry.csv", index=False)
    pd.DataFrame(log).to_csv(output_dir / "selection_log.csv", index=False)
    collection = json.loads(candidates_geojson.read_text(encoding="utf-8"))
    by_id = {f["properties"]["aoi_id"]: f for f in collection["features"]}
    for feature in collection["features"]:
        row = df[df.aoi_id == feature["properties"]["aoi_id"]].iloc[0]
        for key, value in row.items():
            if pd.isna(value): value = ""
            elif isinstance(value, np.bool_): value = bool(value)
            elif isinstance(value, np.integer): value = int(value)
            elif isinstance(value, np.floating): value = float(value)
            feature["properties"][key] = value
    candidates_geojson.write_text(json.dumps(collection, ensure_ascii=False, indent=2), encoding="utf-8")
    final_features = []
    for value in selected:
        feature = by_id[value]; feature["properties"]["source_candidate_id"] = value; feature["properties"]["aoi_id"] = value if value == "AOI-00" else final_mapping[value]
        final_features.append(feature)
    final_collection = {"type": "FeatureCollection", "features": final_features}
    (output_dir / "final_four_aoi_registry.geojson").write_text(json.dumps(final_collection, ensure_ascii=False, indent=2), encoding="utf-8")
    df[df.selection_status.isin(["ORIGINAL", "SELECTED"])].to_csv(output_dir / "final_four_aoi_registry.csv", index=False)
    return df, log
