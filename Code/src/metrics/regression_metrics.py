from __future__ import annotations

import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


def regression_metrics(reference, prediction):
    y = np.asarray(reference, dtype=float); p = np.asarray(prediction, dtype=float)
    keep = np.isfinite(y) & np.isfinite(p); y = y[keep]; p = p[keep]
    return {"RMSE": float(np.sqrt(mean_squared_error(y, p))), "MAE": float(mean_absolute_error(y, p)),
            "Bias": float(np.mean(p - y)), "R2": float(r2_score(y, p)),
            "Pearson_r": float(np.corrcoef(y, p)[0, 1]), "n": int(len(y))}

