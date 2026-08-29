from __future__ import annotations

import numpy as np


def eligible_pairs(ndvi, fcover, contribution_count, minimum=2):
    mask = np.isfinite(ndvi) & np.isfinite(fcover) & (contribution_count >= minimum)
    return ndvi[mask], fcover[mask], mask

