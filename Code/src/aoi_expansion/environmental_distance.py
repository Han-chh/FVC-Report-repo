from __future__ import annotations
import numpy as np


def standardized_euclidean(a, b, scale):
    scale = np.where(np.asarray(scale) == 0, 1, scale)
    return float(np.linalg.norm((np.asarray(a) - np.asarray(b)) / scale))

