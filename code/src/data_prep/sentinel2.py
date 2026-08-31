from __future__ import annotations

import numpy as np

from .processing import scaled_ndvi

EXCLUDED_SCL = frozenset({0, 1, 2, 3, 6, 8, 9, 10, 11})
CLOUD_PROBABILITY_EXCLUDE_GTE = 30.0


def native_valid_mask(scl, cloud_probability):
    return (~np.isin(scl, list(EXCLUDED_SCL))) & np.isfinite(cloud_probability) & (cloud_probability < CLOUD_PROBABILITY_EXCLUDE_GTE)


def ndvi(red_dn, nir_dn, scl, cloud_probability):
    return scaled_ndvi(red_dn, nir_dn, native_valid_mask(scl, cloud_probability), scale=0.0001, offset=0.0, valid_dn=(1, 10000), nodata=0)

