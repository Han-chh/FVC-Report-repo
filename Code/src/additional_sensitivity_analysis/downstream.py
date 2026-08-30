"""Small adapter that preserves use of the frozen model and metric functions."""
from __future__ import annotations

from typing import Any

import pandas as pd

from metrics.block_metrics import by_block
from metrics.regression_metrics import regression_metrics
from models.ols import fit_ols, predict_clipped

from .schemas import assert_pair_schema


def score_with_primary_ols(train: pd.DataFrame, target: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame, dict[str, float]]:
    """Use existing OLS, clipping, metric, and block functions without forks.

    This is intentionally a narrow bridge: future runners retain their
    existing historical-window / LOYO orchestration and pass sensitivity pairs
    through this interface rather than changing the scientific formulation.
    """
    assert_pair_schema(train.columns)
    assert_pair_schema(target.columns)
    model = fit_ols(train.NDVI, train.FCOVER)
    prediction = predict_clipped(model, target.NDVI)
    scored = target[["block_id"]].copy()
    scored["reference"] = target.FCOVER.to_numpy(float)
    scored["prediction"] = prediction
    return regression_metrics(scored.reference, scored.prediction), by_block(scored), {
        "slope": float(model.coef_[0]), "intercept": float(model.intercept_),
    }
