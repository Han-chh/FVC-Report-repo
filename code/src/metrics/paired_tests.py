from __future__ import annotations
from scipy.stats import ttest_rel


def paired_two_sided(a, b):
    result = ttest_rel(a, b, nan_policy="omit")
    return {"t": float(result.statistic), "p": float(result.pvalue)}

