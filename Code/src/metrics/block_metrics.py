from __future__ import annotations
import pandas as pd
from .regression_metrics import regression_metrics


def by_block(frame):
    return pd.DataFrame([{"block_id": block_id, **regression_metrics(group.reference, group.prediction)} for block_id, group in frame.groupby("block_id")])

