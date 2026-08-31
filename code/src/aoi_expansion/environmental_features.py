from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import rasterio
from pyproj import CRS, Transformer
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.transform import from_origin
from rasterio.warp import reproject
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window, from_bounds
from affine import Affine
from shapely.geometry import mapping, shape
from shapely.ops import transform

from data_prep.catalog import search, signed_href


WORLDCOVER_CLASSES = {10: "tree", 20: "shrub", 30: "grassland", 40: "cropland", 50: "built",
                      60: "bare_sparse", 70: "snow_ice", 80: "water", 90: "wetland", 95: "mangrove", 100: "moss_lichen"}


def _local_grid(geometry, resolution: float):
    c = geometry.centroid
    crs = CRS.from_proj4(f"+proj=aeqd +lat_0={c.y} +lon_0={c.x} +datum=WGS84 +units=m +no_defs")
    to_local = Transformer.from_crs(4326, crs, always_xy=True).transform
    local = transform(to_local, geometry)
    minx, miny, maxx, maxy = local.bounds
    width = math.ceil((maxx - minx) / resolution); height = math.ceil((maxy - miny) / resolution)
    affine = from_origin(minx, maxy, resolution, resolution)
    inside = geometry_mask([mapping(local)], (height, width), affine, invert=True)
    return crs, affine, inside


def _mosaic(items, asset: str, crs, transform_out, shape_out, resampling, nodata=np.nan, bbox=None):
    output = np.full(shape_out, nodata, dtype="float32")
    for item in items:
        href = signed_href(item["assets"][asset]["href"])
        with rasterio.open(href) as src:
            temp = np.full(shape_out, nodata, dtype="float32")
            if bbox is not None and str(src.crs) == "EPSG:4326":
                requested = from_bounds(*bbox, transform=src.transform)
                full = Window(0, 0, src.width, src.height)
                try: window = requested.intersection(full).round_offsets().round_lengths()
                except Exception: continue
                # Downsample the native geographic window before reprojection;
                # this keeps COG reads bounded to the AOI and target resolution.
                out_h = max(1, min(shape_out[0] * 2, int(window.height)))
                out_w = max(1, min(shape_out[1] * 2, int(window.width)))
                small = src.read(1, window=window, out_shape=(out_h, out_w), resampling=resampling, out_dtype="float32")
                small_transform = src.window_transform(window) * Affine.scale(window.width / out_w, window.height / out_h)
                reproject(small, temp, src_transform=small_transform, src_crs=src.crs, src_nodata=src.nodata,
                          dst_transform=transform_out, dst_crs=crs, dst_nodata=nodata, resampling=resampling)
            else:
                with WarpedVRT(src, crs=crs, transform=transform_out, width=shape_out[1], height=shape_out[0],
                               src_nodata=src.nodata, nodata=nodata, resampling=resampling) as vrt:
                    temp = vrt.read(1, out_dtype="float32")
            valid = np.isfinite(temp) if np.isnan(nodata) else temp != nodata
            output[valid] = temp[valid]
    return output


def _fractions(values, inside):
    valid = inside & np.isfinite(values) & (values > 0)
    denominator = max(int(valid.sum()), 1)
    return {f"{name}_fraction": float(((values == code) & valid).sum() / denominator) for code, name in WORLDCOVER_CLASSES.items()}


def profile(geometry, cache_dir: Path | None = None):
    bbox = geometry.bounds
    crs, affine, inside = _local_grid(geometry, 120.0)
    shape_out = inside.shape
    dem_items = search("cop-dem-glo-30", bbox)
    wc_items = [item for item in search("esa-worldcover", bbox) if "2021_v200" in item["id"]]
    dem = _mosaic(dem_items, "data", crs, affine, shape_out, Resampling.bilinear, bbox=bbox)
    cover = _mosaic(wc_items, "map", crs, affine, shape_out, Resampling.nearest, nodata=0, bbox=bbox)
    valid_dem = inside & np.isfinite(dem)
    gy, gx = np.gradient(np.where(valid_dem, dem, np.nan), 120.0, 120.0)
    slope = np.degrees(np.arctan(np.sqrt(gx * gx + gy * gy)))
    neighbour_delta = np.nanmedian(np.stack([np.abs(np.roll(dem, 1, 0) - dem), np.abs(np.roll(dem, 1, 1) - dem)]), axis=0)
    land = _fractions(cover, inside)
    ndvi_years = []
    ndvi_item_count = 0
    crs_ndvi, affine_ndvi, inside_ndvi = _local_grid(geometry, 250.0)
    for year in range(2021, 2025):
        items = search("modis-13Q1-061", bbox, datetime=f"{year}-07-01/{year}-08-31")
        ndvi_item_count += len(items)
        observations = []
        for item in items:
            ndvi = _mosaic([item], "250m_16_days_NDVI", crs_ndvi, affine_ndvi, inside_ndvi.shape, Resampling.nearest)
            reliability = _mosaic([item], "250m_16_days_pixel_reliability", crs_ndvi, affine_ndvi, inside_ndvi.shape, Resampling.nearest)
            values = ndvi * 0.0001
            values[(reliability > 1) | (reliability < 0) | (values < -0.2) | (values > 1.0) | ~inside_ndvi] = np.nan
            observations.append(values)
        if observations:
            ndvi_years.append(float(np.nanmedian(np.stack(observations))))
    result = {
        "elevation_median_m": float(np.nanmedian(dem[valid_dem])),
        "elevation_iqr_m": float(np.nanpercentile(dem[valid_dem], 75) - np.nanpercentile(dem[valid_dem], 25)),
        "elevation_range_m": float(np.nanpercentile(dem[valid_dem], 95) - np.nanpercentile(dem[valid_dem], 5)),
        "slope_median_degrees": float(np.nanmedian(slope[valid_dem])),
        "terrain_ruggedness_m": float(np.nanmedian(neighbour_delta[valid_dem])),
        **land,
        "vegetation_fraction": sum(land.get(f"{name}_fraction", 0.0) for name in ("tree", "shrub", "grassland", "wetland", "moss_lichen")),
        "historical_ndvi_median": float(np.nanmedian(ndvi_years)) if ndvi_years else np.nan,
        "historical_ndvi_iqr": float(np.nanpercentile(ndvi_years, 75) - np.nanpercentile(ndvi_years, 25)) if ndvi_years else np.nan,
        "historical_ndvi_years": len(ndvi_years), "historical_ndvi_items": ndvi_item_count,
        "dem_items": len(dem_items), "worldcover_items": len(wc_items),
    }
    return result


def profile_collection(collection_path: Path, output_csv: Path):
    import pandas as pd
    collection = json.loads(collection_path.read_text(encoding="utf-8"))
    rows = []
    for feature in collection["features"]:
        row = dict(feature["properties"]); row.update(profile(shape(feature["geometry"])))
        row.setdefault("centroid_lon", shape(feature["geometry"]).centroid.x)
        row.setdefault("centroid_lat", shape(feature["geometry"]).centroid.y)
        rows.append(row)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output_csv, index=False)
    return rows
