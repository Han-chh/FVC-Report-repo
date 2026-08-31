from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from shapely.geometry import shape


def candidate_map(province_geojson: Path, candidates_geojson: Path, registry_csv: Path, output: Path):
    import pandas as pd
    province = json.loads(province_geojson.read_text(encoding="utf-8"))
    qinghai = next(f for f in province["features"] if "qinghai" in str(f["properties"].get("shapeName", "")).lower())
    candidates = json.loads(candidates_geojson.read_text(encoding="utf-8")); registry = pd.read_csv(registry_csv).set_index("aoi_id")
    fig, ax = plt.subplots(figsize=(10, 8), dpi=180)
    boundary = shape(qinghai["geometry"])
    polygons = list(boundary.geoms) if boundary.geom_type == "MultiPolygon" else [boundary]
    for poly in polygons:
        x, y = poly.exterior.xy; ax.fill(x, y, color="#f3efe4", ec="#6f6b62", lw=0.8, zorder=0)
    for feature in candidates["features"]:
        aoi_id = feature["properties"]["aoi_id"]; geometry = shape(feature["geometry"])
        selected = aoi_id == "AOI-00" or registry.loc[aoi_id, "selection_status"] == "SELECTED"
        color = "#124559" if aoi_id == "AOI-00" else ("#d95f02" if selected else "#8da0a6")
        x, y = geometry.exterior.xy; ax.fill(x, y, facecolor=color, edgecolor="white", lw=0.7, alpha=0.90, zorder=2)
        ax.text(geometry.centroid.x, geometry.centroid.y, aoi_id.replace("AOI-", ""), fontsize=7, ha="center", va="center", color="white", weight="bold", zorder=3)
    ax.set(xlabel="Longitude (EPSG:4326)", ylabel="Latitude (EPSG:4326)", title="Frozen environmental candidate AOIs in Qinghai (no model results used)")
    ax.set_aspect("equal", adjustable="box"); ax.grid(color="white", lw=0.4, alpha=0.7)
    ax.legend(handles=[Patch(color="#124559", label="AOI-00 original"), Patch(color="#d95f02", label="Selected candidates"), Patch(color="#8da0a6", label="Not selected")], loc="lower left")
    output.parent.mkdir(parents=True, exist_ok=True); fig.tight_layout(); fig.savefig(output); plt.close(fig)
