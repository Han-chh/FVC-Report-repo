from __future__ import annotations

import json
import math
from pathlib import Path

import yaml
from pyproj import CRS, Geod, Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform


def _aeqd(lon: float, lat: float) -> CRS:
    return CRS.from_proj4(f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m +no_defs")


def translated_geometry(template, lon: float, lat: float):
    c = template.centroid
    to_source = Transformer.from_crs(4326, _aeqd(c.x, c.y), always_xy=True).transform
    from_target = Transformer.from_crs(_aeqd(lon, lat), 4326, always_xy=True).transform
    local = transform(to_source, template)
    return transform(from_target, local)


def geodesic_area_km2(geometry) -> float:
    geod = Geod(ellps="WGS84")
    area, _ = geod.geometry_area_perimeter(geometry)
    return abs(area) / 1e6


def expected_intersecting_blocks(geometry, size_m: float = 5000.0) -> int:
    c = geometry.centroid
    to_local = Transformer.from_crs(4326, _aeqd(c.x, c.y), always_xy=True).transform
    local = transform(to_local, geometry)
    minx, miny, maxx, maxy = local.bounds
    from shapely.geometry import box
    count = 0
    for col in range(math.floor(minx / size_m), math.floor(maxx / size_m) + 1):
        for row in range(math.floor(miny / size_m), math.floor(maxy / size_m) + 1):
            if local.intersects(box(col * size_m, row * size_m, (col + 1) * size_m, (row + 1) * size_m)):
                count += 1
    return count


def generate(config_path: Path, template_path: Path, output_path: Path):
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    source = json.loads(template_path.read_text(encoding="utf-8"))
    template = shape(source.get("geometry", source))
    features = [{"type": "Feature", "properties": {
        "aoi_id": "AOI-00", "role": "original", "area_km2": geodesic_area_km2(template),
        "expected_5km_block_count": expected_intersecting_blocks(template), "geometry_version": "aoi00-immutable-v1",
    }, "geometry": mapping(template)}]
    for aoi_id, centre in config["centres_epsg4326"].items():
        geometry = translated_geometry(template, float(centre[0]), float(centre[1]))
        features.append({"type": "Feature", "properties": {
            "aoi_id": aoi_id, "role": "candidate", "centroid_lon": geometry.centroid.x,
            "centroid_lat": geometry.centroid.y, "area_km2": geodesic_area_km2(geometry),
            "expected_5km_block_count": expected_intersecting_blocks(geometry),
            "geometry_version": "translated-aoi00-shape-v1",
        }, "geometry": mapping(geometry)})
    collection = {"type": "FeatureCollection", "name": "fvc_aoi_candidates_v1", "features": features}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(collection, ensure_ascii=False, indent=2), encoding="utf-8")
    return collection

