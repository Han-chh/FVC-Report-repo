from __future__ import annotations

import io
import time
from datetime import date
from collections import defaultdict

import numpy as np
import rasterio
import requests
from rasterio.io import MemoryFile
from shapely.geometry import mapping

from data_prep.catalog import search

DATA_API = "https://planetarycomputer.microsoft.com/api/data/v1/item"
WC_CLASSES = {10: "tree", 20: "shrub", 30: "grassland", 40: "cropland", 50: "built", 60: "bare_sparse",
              70: "snow_ice", 80: "water", 90: "wetland", 95: "mangrove", 100: "moss_lichen"}


def _post(url, feature, *, binary=False, retries=6):
    for attempt in range(retries):
        try:
            response = requests.post(url, json=feature, timeout=180)
            if response.ok: return response.content if binary else response.json()
            if response.status_code not in (429, 500, 502, 503, 504): response.raise_for_status()
        except requests.RequestException:
            if attempt + 1 == retries: raise
        time.sleep(2 ** attempt)
    raise RuntimeError("PLANETARY_COMPUTER_DATA_API_UNAVAILABLE")


def _feature(geometry, properties=None):
    return {"type": "Feature", "properties": properties or {}, "geometry": mapping(geometry)}


def _item_stats(collection, item_id, asset, feature, categorical=False):
    url = f"{DATA_API}/statistics?collection={collection}&item={item_id}&assets={asset}&max_size=512"
    if categorical: url += "&categorical=true"
    response = _post(url, feature)
    values = next(iter(response["properties"]["statistics"].values()))
    return values


def dem_profile(geometry):
    arrays = []; slopes = []; ruggedness = []; items = search("cop-dem-glo-90", geometry.bounds)
    zone = int((geometry.centroid.x + 180) // 6) + 1; epsg = 32600 + zone
    for item in items:
        url = f"{DATA_API}/feature.tif?collection=cop-dem-glo-90&item={item['id']}&assets=data&max_size=512&dst_crs=EPSG:{epsg}"
        content = _post(url, _feature(geometry), binary=True)
        with MemoryFile(content) as memory, memory.open() as src:
            elevation = src.read(1).astype("float32")
            valid = src.read(2) > 0 if src.count > 1 else np.isfinite(elevation)
            elevation[~valid] = np.nan
            dx, dy = abs(src.transform.a), abs(src.transform.e)
            gy, gx = np.gradient(elevation, dy, dx)
            slope = np.degrees(np.arctan(np.sqrt(gx * gx + gy * gy)))
            rough = np.nanmedian(np.stack([np.abs(elevation - np.roll(elevation, 1, 0)), np.abs(elevation - np.roll(elevation, 1, 1))]), axis=0)
            arrays.append(elevation[valid]); slopes.append(slope[valid]); ruggedness.append(rough[valid])
    values = np.concatenate(arrays); slope_values = np.concatenate(slopes); rough_values = np.concatenate(ruggedness)
    return {"elevation_median_m": float(np.nanmedian(values)),
            "elevation_iqr_m": float(np.nanpercentile(values, 75) - np.nanpercentile(values, 25)),
            "elevation_range_m": float(np.nanpercentile(values, 95) - np.nanpercentile(values, 5)),
            "slope_median_degrees": float(np.nanmedian(slope_values)),
            "terrain_ruggedness_m": float(np.nanmedian(rough_values)), "dem_items": len(items)}


def worldcover_profile(geometry):
    items = [item for item in search("esa-worldcover", geometry.bounds) if "2021_v200" in item["id"]]
    counts = defaultdict(float)
    for item in items:
        stats = _item_stats("esa-worldcover", item["id"], "map", _feature(geometry), categorical=True)
        histogram_counts, categories = stats["histogram"]
        for category, count in zip(categories, histogram_counts): counts[int(category)] += float(count)
    total = sum(counts.values()) or 1.0
    result = {f"{name}_fraction": counts[code] / total for code, name in WC_CLASSES.items()}
    result["vegetation_fraction"] = sum(result[f"{name}_fraction"] for name in ("tree", "shrub", "grassland", "wetland", "moss_lichen"))
    result["worldcover_items"] = len(items)
    return result


def ndvi_profile(geometry):
    annual = []; item_count = 0
    for year in range(2021, 2025):
        items = search("modis-13Q1-061", geometry.bounds, datetime=f"{year}-07-01/{year}-08-31")
        def acquisition_day(item):
            properties = item["properties"]
            return str(properties.get("datetime") or properties.get("start_datetime"))[:10]
        available_dates = sorted({acquisition_day(item) for item in items})
        if available_dates:
            chosen_date = min(available_dates, key=lambda value: abs((date.fromisoformat(value) - date(year, 7, 31)).days))
            items = [item for item in items if acquisition_day(item) == chosen_date]
        by_date = defaultdict(list)
        for item in items:
            url = f"{DATA_API}/feature.tif?collection=modis-13Q1-061&item={item['id']}&assets=250m_16_days_NDVI&max_size=512&dst_crs=EPSG:4326"
            content = _post(url, _feature(geometry), binary=True)
            with MemoryFile(content) as memory, memory.open() as src:
                values = src.read(1).astype("float32")
                valid = src.read(2) > 0 if src.count > 1 else np.isfinite(values)
                values = values[valid]
                values = values[(values >= -2000) & (values <= 10000)]
            if not values.size: continue
            acquisition_date = acquisition_day(item)
            by_date[acquisition_date].append((float(np.nanmedian(values)) * 0.0001, float(values.size)))
            item_count += 1
        dates = []
        for observations in by_date.values():
            numerator = sum(value * count for value, count in observations); denominator = sum(count for _, count in observations)
            if denominator: dates.append(numerator / denominator)
        if dates: annual.append(float(np.nanmedian(dates)))
    return {"historical_ndvi_median": float(np.nanmedian(annual)) if annual else np.nan,
            "historical_ndvi_iqr": float(np.nanpercentile(annual, 75) - np.nanpercentile(annual, 25)) if annual else np.nan,
            "historical_ndvi_years": len(annual), "historical_ndvi_items": item_count}


def profile(geometry):
    return {**dem_profile(geometry), **worldcover_profile(geometry), **ndvi_profile(geometry)}
