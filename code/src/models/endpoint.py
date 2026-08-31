from __future__ import annotations

import numpy as np


def endpoint_predict(ndvi, low: float, high: float):
    if not high > low:
        raise ValueError("ENDPOINT_ORDER_INVALID")
    return np.clip((np.asarray(ndvi) - low) / (high - low), 0.0, 1.0)

