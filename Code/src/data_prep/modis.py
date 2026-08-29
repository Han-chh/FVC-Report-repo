from __future__ import annotations

import numpy as np

from .processing import bits, scaled_ndvi

STATE_RULES = {
    "cloud_state": (0, 2, (0,)), "cloud_shadow": (2, 1, (0,)), "land_water": (3, 3, (1,)),
    "aerosol": (6, 2, (0, 1, 2)), "cirrus": (8, 2, (0,)), "internal_cloud": (10, 1, (0,)),
    "internal_fire": (11, 1, (0,)), "snow": (12, 1, (0,)), "adjacent_cloud": (13, 1, (0,)),
    "internal_snow": (15, 1, (0,)),
}
QC_RULES = {
    "modland": (0, 2, (0, 1)), "band1": (4, 4, (0,)), "band2": (8, 4, (0,)),
    "atmospheric_correction": (12, 1, (1,)),
}


def native_valid_mask(state, qc_250m):
    valid = (state != 65535) & (qc_250m != 65535)
    for offset, width, keep in STATE_RULES.values():
        valid &= np.isin(bits(state, offset, width), keep)
    for offset, width, keep in QC_RULES.values():
        valid &= np.isin(bits(qc_250m, offset, width), keep)
    return valid


def ndvi(red_dn, nir_dn, state, qc_250m):
    return scaled_ndvi(red_dn, nir_dn, native_valid_mask(state, qc_250m), scale=0.0001, offset=0.0, valid_dn=(-100, 16000), nodata=-28672)

