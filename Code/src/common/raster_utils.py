from __future__ import annotations

import numpy as np
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.warp import reproject
from shapely import area, box, intersection
from shapely.geometry import Polygon

from .grid import GridContract


def average_to_fcover(values, source, fcover_profile):
    """Map already-QA-masked source-pixel NDVI directly to native FCOVER support."""
    output = np.full((fcover_profile["height"], fcover_profile["width"]), np.nan, dtype="float32")
    reproject(
        values.astype("float32"), output,
        src_transform=source.transform, src_crs=source.crs, src_nodata=np.nan,
        dst_transform=fcover_profile["transform"], dst_crs=fcover_profile["crs"], dst_nodata=np.nan,
        resampling=Resampling.average,
    )
    return output


def area_weighted_to_fcover(values, source, fcover_profile, *, edge_samples: int = 8):
    """Match Earth Engine ``reduceResolution(mean)`` coverage weighting.

    GDAL's average warp and Earth Engine use different cross-CRS boundary
    semantics.  This implementation intersects the exact frozen source pixel
    squares with each densified target-cell polygon in source CRS, weights
    only finite source observations by overlap area, and therefore preserves
    both masks and partial-pixel weights without empirical edge rules.
    """
    transform = source.transform
    if transform.b != 0 or transform.d != 0 or transform.a <= 0 or transform.e >= 0:
        raise RuntimeError("AREA_WEIGHTED_AGGREGATION_REQUIRES_NORTH_UP_SOURCE_GRID")
    if edge_samples < 2:
        raise RuntimeError("AREA_WEIGHTED_AGGREGATION_EDGE_SAMPLES_TOO_SMALL")
    height, width = values.shape
    target_transform = fcover_profile["transform"]
    target_height, target_width = fcover_profile["height"], fcover_profile["width"]
    transformer = Transformer.from_crs(fcover_profile["crs"], source.crs, always_xy=True)
    output = np.full((target_height, target_width), np.nan, dtype="float32")

    for row in range(target_height):
        for column in range(target_width):
            x0 = target_transform.c + column * target_transform.a
            x1 = x0 + target_transform.a
            y0 = target_transform.f + row * target_transform.e
            y1 = y0 + target_transform.e
            samples = edge_samples
            xs = np.r_[
                np.linspace(x0, x1, samples), np.full(samples, x1),
                np.linspace(x1, x0, samples), np.full(samples, x0),
            ]
            ys = np.r_[
                np.full(samples, y0), np.linspace(y0, y1, samples),
                np.full(samples, y1), np.linspace(y1, y0, samples),
            ]
            source_x, source_y = transformer.transform(xs, ys)
            target_polygon = Polygon(np.c_[source_x, source_y])
            min_x, min_y, max_x, max_y = target_polygon.bounds
            column_start = max(0, int(np.floor((min_x - transform.c) / transform.a)))
            column_end = min(width, int(np.ceil((max_x - transform.c) / transform.a)))
            row_start = max(0, int(np.floor((max_y - transform.f) / transform.e)))
            row_end = min(height, int(np.ceil((min_y - transform.f) / transform.e)))
            if column_end <= column_start or row_end <= row_start:
                continue
            source_rows, source_columns = np.mgrid[row_start:row_end, column_start:column_end]
            candidates = values[source_rows, source_columns]
            valid = np.isfinite(candidates)
            if not np.any(valid):
                continue
            left = transform.c + source_columns[valid] * transform.a
            right = left + transform.a
            top = transform.f + source_rows[valid] * transform.e
            bottom = top + transform.e
            source_cells = box(left, bottom, right, top)
            weights = area(intersection(source_cells, target_polygon))
            contributes = weights > 0
            if np.any(contributes):
                selected = candidates[valid][contributes].astype("float64")
                selected_weights = weights[contributes]
                output[row, column] = np.sum(selected * selected_weights) / np.sum(selected_weights)
    return output


def assert_native_fcover_output(dataset, contract: GridContract) -> None:
    contract.assert_same(GridContract.from_dataset(dataset))
