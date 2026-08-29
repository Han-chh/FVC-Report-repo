from __future__ import annotations

import warnings
import numpy as np


def nanmedian_min_count(observation_level_fcover_arrays, minimum: int = 2):
    stack = np.stack(observation_level_fcover_arrays).astype("float32")
    count = np.isfinite(stack).sum(axis=0).astype("uint16")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        median = np.nanmedian(stack, axis=0).astype("float32")
    median[count < minimum] = np.nan
    return median, count

