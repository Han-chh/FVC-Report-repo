from __future__ import annotations

import numpy as np

from .processing import scaled_ndvi


def native_valid_mask(qa_pixel, qa_radsat):
    pixel = qa_pixel.astype("uint32")
    invalid = np.zeros(pixel.shape, dtype=bool)
    for bit in (0, 1, 2, 3, 4, 5, 7):
        invalid |= ((pixel >> bit) & 1).astype(bool)
    invalid |= qa_radsat.astype("uint32") != 0
    return ~invalid


def platforms_for_year(year: int) -> tuple[str, ...]:
    return ("LANDSAT_8",) if year == 2021 else ("LANDSAT_8", "LANDSAT_9")


def ndvi(red_dn, nir_dn, qa_pixel, qa_radsat):
    return scaled_ndvi(red_dn, nir_dn, native_valid_mask(qa_pixel, qa_radsat), scale=0.0000275, offset=-0.2, valid_dn=(7273, 43636), nodata=0)

