from __future__ import annotations

from sklearn.model_selection import GroupKFold


def folds(rows, n_splits=5):
    if "spatial_role" in rows and (rows.spatial_role != "development").any():
        raise ValueError("GROUPKFOLD_REQUIRES_DEVELOPMENT_ONLY")
    splitter = GroupKFold(n_splits=n_splits)
    return splitter.split(rows, groups=rows.block_id)

