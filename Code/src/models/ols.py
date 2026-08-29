from __future__ import annotations

import numpy as np
from sklearn.linear_model import LinearRegression


def fit_ols(ndvi, fcover):
    x = np.asarray(ndvi, dtype=float).reshape(-1, 1)
    y = np.asarray(fcover, dtype=float)
    valid = np.isfinite(x[:, 0]) & np.isfinite(y)
    if not valid.any():
        raise ValueError("NO_ELIGIBLE_TRAINING_SAMPLES")
    return LinearRegression(fit_intercept=True).fit(x[valid], y[valid])


def predict_clipped(model, ndvi):
    return np.clip(model.predict(np.asarray(ndvi, dtype=float).reshape(-1, 1)), 0.0, 1.0)

