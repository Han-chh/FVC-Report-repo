from __future__ import annotations

import numpy as np


OPERATION_ORDER = (
    "reflectance_scaling", "native_qa", "source_pixel_ndvi",
    "average_to_native_fcover_grid", "temporal_nanmedian_on_fcover_grid",
)


def bits(values: np.ndarray, offset: int, width: int) -> np.ndarray:
    return (values.astype("uint32") >> offset) & ((1 << width) - 1)


def scaled_ndvi(red_dn, nir_dn, valid, *, scale: float, offset: float, valid_dn: tuple[int, int], nodata: int):
    range_valid = (
        (red_dn >= valid_dn[0]) & (red_dn <= valid_dn[1]) &
        (nir_dn >= valid_dn[0]) & (nir_dn <= valid_dn[1]) &
        (red_dn != nodata) & (nir_dn != nodata)
    )
    red = red_dn.astype("float32") * scale + offset
    nir = nir_dn.astype("float32") * scale + offset
    keep = valid & range_valid & np.isfinite(red) & np.isfinite(nir) & ((red + nir) != 0)
    output = np.full(red.shape, np.nan, dtype="float32")
    np.divide(nir - red, nir + red, out=output, where=keep)
    return output
