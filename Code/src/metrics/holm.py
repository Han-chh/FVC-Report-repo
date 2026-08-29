from __future__ import annotations

import numpy as np


def holm_adjust(p_values):
    values = np.asarray(p_values, dtype=float)
    order = np.argsort(values); adjusted = np.empty_like(values); running = 0.0; m = len(values)
    for rank, index in enumerate(order):
        running = max(running, (m - rank) * values[index])
        adjusted[index] = min(running, 1.0)
    return adjusted

