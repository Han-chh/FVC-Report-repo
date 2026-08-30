# PRIMARY ROUTE REPRODUCTION REPORT

Generated: 2026-08-30T07:16:19.878483+00:00

## Tolerance

All direct numerical comparisons use an absolute tolerance of `1e-12`. Derived paired t/p/Holm values use `5e-12` only because their standard-error division amplifies <2e-15 matched block-RMSE rounding; it is not a scientific-effect tolerance.

## Required checks

| Check | Status | Detail |
|---|---|---|
| Checkpoint completeness and manifest hashes | PASS | expected=60; actual=60; valid=60 |
| Paired identity counts | PASS | groups=60; maximum absolute count difference=0 |
| Paired identity-set agreement | PASS | primary=995060; route_a=995060; missing=0; extra=0; identity_match_rate=1.000000000000 |
| NDVI values | PASS | tolerance=1e-12; max_abs=0; mean_abs=0 |
| FCOVER values | PASS | tolerance=1e-12; max_abs=0; mean_abs=0 |
| Nominal-date labels and block IDs | PASS | nominal labels are identity keys; block mismatches=0 |
| 2025 Multi-AOI metrics | PASS | tolerance=1e-12; maximum absolute deltas={'RMSE': 1.942890293094024e-16, 'MAE': 1.0408340855860843e-16, 'Bias': 3.0010716134398763e-16, 'R2': 4.884981308350689e-15, 'Pearson_r': 4.440892098500626e-15, 'n': 0.0} |
| 2025 Multi-AOI OLS coefficients | PASS | tolerance=1e-12; maximum absolute deltas={'slope': 1.199040866595169e-14, 'intercept': 7.202571872255703e-15} |
| Preferred historical window | PASS | groups=12; mismatches=0 |
| Rolling-Origin H1/H2/H3 metrics and coefficients | PASS | tolerance=1e-12; maximum absolute deltas={'RMSE': 2.0122792321330962e-16, 'MAE': 2.0122792321330962e-16, 'Bias': 4.0072112295064244e-16, 'R2': 4.884981308350689e-15, 'Pearson_r': 9.103828801926284e-15, 'n': 0.0, 'slope': 1.1435297153639112e-14, 'intercept': 7.202571872255703e-15} |
| Rolling-Origin block metrics and block counts | PASS | tolerance=1e-12; maximum absolute deltas={'block_rmse': 1.4988010832439613e-15, 'block_mae': 1.4988010832439613e-15, 'block_bias': 4.1000189354711836e-15, 'block_n': 0.0} |
| Block ΔRMSE and Holm-adjusted contrasts | PASS | input tolerance=1e-12; derived contrast tolerance=5e-12; maximum absolute deltas={'paired_block_n': 0.0, 'mean_difference_RMSE': 3.0010716134398763e-16, 't': 1.623590151211829e-12, 'p': 3.2357450052700187e-13, 'Holm_adjusted_p': 3.566036355096003e-13} |
| Frozen-primary file integrity | PASS | git diff for Data/Inputs and Data/Results is clean; SHA-256 ledger recorded below. |

## Frozen-primary SHA-256 ledger

| File | SHA-256 |
|---|---|
| `Data/Inputs/paired_observations.csv.gz` | `cb439b63d5d346abdc8d2b8bf0e1a2204045c784e73ab8225e67c4fa47cbccfb` |
| `Data/Results/02_multi_aoi_results/MULTI_AOI_2025_METRICS.csv` | `6551407131d6f7b8db540fe2cf6e9c98cd7a920ef85c21ed6a4150ef9a77e3c7` |
| `Data/Results/02_multi_aoi_results/MULTI_AOI_MODEL_COEFFICIENTS.csv` | `f15519f628f8c8447b1dd9412ee79d92a909983bbfcc6ba36ff3d9058cb7d171` |
| `Data/Results/03_rolling_origin_results/ROLLING_ORIGIN_METRICS.csv` | `b613571b24a093e9a7a5701930d03ac54b32366daa15f5acdb55cea2a05ef589` |
| `Data/Results/03_rolling_origin_results/ROLLING_ORIGIN_BLOCK_METRICS.csv` | `a5b6ee263fa96b21db29a59855f17bd4f9f1e8461785501aceb9f08e81d24608` |
| `Data/Results/03_rolling_origin_results/ROLLING_ORIGIN_PAIRED_TESTS.csv` | `59121c56d42f3ecb79f9646f1ac3745f7cc874d170f99917afd10a328938bb38` |

## Not evaluable

No required comparison was non-evaluable. A pre-run hash ledger was not available, so integrity is established by the clean tracked-path diff plus the recorded post-run SHA-256 ledger.

OVERALL ROUTE A REPRODUCTION: PASS
REPRODUCTION PASS RATE: 100.00%
