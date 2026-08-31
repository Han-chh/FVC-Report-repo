from __future__ import annotations


def folds_for_years(years):
    years = tuple(sorted(set(int(y) for y in years)))
    if len(years) < 2: return {"status": "NOT_APPLICABLE", "folds": []}
    return {"status": "PLANNED", "folds": [{"train_years": [x for x in years if x != y], "held_out_year": y} for y in years]}

