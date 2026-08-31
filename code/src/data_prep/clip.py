from __future__ import annotations

from rasterio.windows import from_bounds


def native_window(dataset, bounds_in_dataset_crs):
    """Return a pixel-aligned window without changing the source grid."""
    return from_bounds(*bounds_in_dataset_crs, transform=dataset.transform).round_offsets().round_lengths()

