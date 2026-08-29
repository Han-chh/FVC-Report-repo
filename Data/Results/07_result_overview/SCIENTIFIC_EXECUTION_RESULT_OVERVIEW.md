# Scientific execution result overview

## 1. Executive Status

`SCIENTIFIC EXECUTION COMPLETE`

This is a factual execution/data overview, not manuscript Results or Discussion prose.

## 2. Execution Integrity

- Design hash: `b21c8cc7f3d4d35e1db4dfa1c8245ff10ba657c0a0a001992b552808766cc49b` (unchanged).
- Processing hash: `3fab57b81623045f745beeaa0c1615c51b0d44344beaa74a1025ee4450b699c7` (unchanged).
- Protected evidence: 84/84 unchanged.
- Multi-AOI: 72/72 validated; failed 0; missing 0; duplicate 0.
- Rolling-Origin: 72/72 validated; failed 0; missing 0; duplicate 0.
- FCOVER QA sensitivity: excluded by frozen active design; 0 runs.
- Active GEE tasks: 0.
- Manuscript files modified: 0.

## 3. Data Overview

| sensor | valid_rows | blocks_sum |
|---|---|---|
| landsat | 267762 | 650 |
| modis | 360062 | 725 |
| sentinel2 | 367236 | 734 |

The validated paired cache contains 995,060 sensor-specific observations and 386,649 unique AOI × year × date × FCOVER-grid-cell support identities across all 60 AOI × sensor × year groups.

### Valid paired support by AOI and year

| aoi_id | year | landsat_valid_rows | modis_valid_rows | sentinel2_valid_rows | unique_fcover_pair_support |
|---|---|---|---|---|---|
| AOI-00 | 2021 | 18094 | 20248 | 19974 | 20256 |
| AOI-00 | 2022 | 18588 | 20256 | 18240 | 20256 |
| AOI-00 | 2023 | 19556 | 20256 | 20246 | 20256 |
| AOI-00 | 2024 | 20186 | 20256 | 15819 | 20256 |
| AOI-00 | 2025 | 20251 | 20256 | 19233 | 20256 |
| AOI-01 | 2021 | 11150 | 19878 | 19878 | 19878 |
| AOI-01 | 2022 | 19149 | 19878 | 19878 | 19878 |
| AOI-01 | 2023 | 19878 | 19878 | 19729 | 19878 |
| AOI-01 | 2024 | 19872 | 19878 | 19878 | 19878 |
| AOI-01 | 2025 | 14738 | 19878 | 19878 | 19878 |
| AOI-02 | 2021 | 1040 | 8572 | 17869 | 18129 |
| AOI-02 | 2022 | 15357 | 18558 | 18847 | 18995 |
| AOI-02 | 2023 | 2686 | 9553 | 7586 | 13753 |
| AOI-02 | 2024 | 1542 | 17909 | 18284 | 18780 |
| AOI-02 | 2025 | 7600 | 16568 | 18534 | 18864 |
| AOI-03 | 2021 | 714 | 14860 | 19366 | 19578 |
| AOI-03 | 2022 | 16230 | 18858 | 19267 | 19594 |
| AOI-03 | 2023 | 11178 | 17967 | 16731 | 19103 |
| AOI-03 | 2024 | 15551 | 18695 | 19142 | 19591 |
| AOI-03 | 2025 | 14402 | 17860 | 18857 | 19592 |

One nominal-date group (AOI-02 / Landsat / 2021-08-10) has no eligible row and was not imputed; its registered year group and every run remain nonempty.

## 4. Multi-AOI Results

### Sensor summary across the 24 registered runs per sensor

| sensor | runs | RMSE_mean | RMSE_median | RMSE_min | RMSE_max | MAE_mean | Bias_mean | R2_mean | Pearson_r_mean |
|---|---|---|---|---|---|---|---|---|---|
| landsat | 24 | 0.03684 | 0.04500 | 0.00136 | 0.06222 | 0.02862 | 0.00309 | 0.70324 | 0.84820 |
| modis | 24 | 0.03079 | 0.03612 | 0.00140 | 0.05466 | 0.02403 | 0.00572 | 0.74152 | 0.87990 |
| sentinel2 | 24 | 0.04102 | 0.04911 | 0.00132 | 0.06578 | 0.03134 | -0.00700 | 0.67490 | 0.87838 |

### Mean performance by frozen historical window

| sensor | window | AOIs | N | Blocks | RMSE | MAE | Bias | R2 | Pearson_r | Slope | Intercept |
|---|---|---|---|---|---|---|---|---|---|---|---|
| landsat | W2022 | 4 | 56991 | 145 | 0.03542 | 0.02710 | -0.00157 | 0.70782 | 0.85144 | 0.71472 | -0.05092 |
| landsat | W2022_2023 | 4 | 56991 | 145 | 0.03575 | 0.02771 | 0.00305 | 0.71192 | 0.84951 | 0.72471 | -0.04684 |
| landsat | W2022_2024 | 4 | 56991 | 145 | 0.03611 | 0.02795 | 0.00136 | 0.70822 | 0.84816 | 0.71357 | -0.04256 |
| landsat | W2023 | 4 | 56991 | 145 | 0.03840 | 0.03038 | 0.01110 | 0.69869 | 0.84775 | 0.74031 | -0.04187 |
| landsat | W2023_2024 | 4 | 56991 | 145 | 0.03780 | 0.02959 | 0.00590 | 0.69984 | 0.84670 | 0.72008 | -0.03975 |
| landsat | W2024 | 4 | 56991 | 145 | 0.03756 | 0.02897 | -0.00131 | 0.69298 | 0.84563 | 0.70600 | -0.04149 |
| modis | W2022 | 4 | 74562 | 147 | 0.03093 | 0.02435 | 0.00885 | 0.75410 | 0.87888 | 0.79494 | -0.09257 |
| modis | W2022_2023 | 4 | 74562 | 147 | 0.03060 | 0.02411 | 0.00834 | 0.75189 | 0.88025 | 0.79111 | -0.08908 |
| modis | W2022_2024 | 4 | 74562 | 147 | 0.03049 | 0.02379 | 0.00583 | 0.74293 | 0.88001 | 0.77252 | -0.08584 |
| modis | W2023 | 4 | 74562 | 147 | 0.03047 | 0.02405 | 0.00593 | 0.74865 | 0.88167 | 0.79799 | -0.09432 |
| modis | W2023_2024 | 4 | 74562 | 147 | 0.03030 | 0.02352 | 0.00431 | 0.73771 | 0.88039 | 0.76663 | -0.08479 |
| modis | W2024 | 4 | 74562 | 147 | 0.03193 | 0.02437 | 0.00105 | 0.71381 | 0.87820 | 0.75241 | -0.08324 |
| sentinel2 | W2022 | 4 | 76502 | 147 | 0.04112 | 0.03139 | -0.01078 | 0.68271 | 0.87675 | 0.61481 | 0.02383 |
| sentinel2 | W2022_2023 | 4 | 76502 | 147 | 0.04075 | 0.03098 | -0.00879 | 0.68081 | 0.87833 | 0.61815 | 0.02304 |
| sentinel2 | W2022_2024 | 4 | 76502 | 147 | 0.04073 | 0.03110 | -0.00766 | 0.67608 | 0.87853 | 0.60827 | 0.02942 |
| sentinel2 | W2023 | 4 | 76502 | 147 | 0.04129 | 0.03144 | -0.00348 | 0.67724 | 0.87898 | 0.62213 | 0.02582 |
| sentinel2 | W2023_2024 | 4 | 76502 | 147 | 0.04090 | 0.03130 | -0.00512 | 0.67295 | 0.87892 | 0.60342 | 0.03423 |
| sentinel2 | W2024 | 4 | 76502 | 147 | 0.04135 | 0.03184 | -0.00616 | 0.65960 | 0.87878 | 0.58373 | 0.04428 |

### Best RMSE within each sensor and AOI

| sensor | AOI | window | n | block_n | RMSE | MAE | Bias | R2 | Pearson_r | slope | intercept |
|---|---|---|---|---|---|---|---|---|---|---|---|
| landsat | AOI-00 | W2023 | 20251 | 39 | 0.04762 | 0.03889 | -0.00314 | 0.76512 | 0.87530 | 0.85448 | 0.00110 |
| landsat | AOI-01 | W2023 | 14738 | 35 | 0.00136 | 0.00060 | 0.00013 | 0.37078 | 0.64896 | 0.10954 | -0.00569 |
| landsat | AOI-02 | W2022 | 7600 | 36 | 0.05642 | 0.04349 | 0.00225 | 0.86395 | 0.92962 | 0.97781 | -0.07893 |
| landsat | AOI-03 | W2022 | 14402 | 35 | 0.03525 | 0.02539 | 0.00009 | 0.87843 | 0.93732 | 0.87948 | -0.07694 |
| modis | AOI-00 | W2022_2023 | 20256 | 39 | 0.03887 | 0.03096 | -0.00058 | 0.84437 | 0.91894 | 0.99879 | -0.11578 |
| modis | AOI-01 | W2022 | 19878 | 35 | 0.00140 | 0.00057 | 0.00016 | 0.35692 | 0.67180 | 0.09568 | -0.00529 |
| modis | AOI-02 | W2023 | 16568 | 38 | 0.04815 | 0.03700 | 0.00293 | 0.91812 | 0.95881 | 1.09980 | -0.16752 |
| modis | AOI-03 | W2024 | 17860 | 35 | 0.02829 | 0.02038 | -0.00426 | 0.92427 | 0.96658 | 0.94272 | -0.10776 |
| sentinel2 | AOI-00 | W2022 | 19233 | 39 | 0.06308 | 0.05115 | -0.02488 | 0.58548 | 0.80663 | 0.67632 | 0.12990 |
| sentinel2 | AOI-01 | W2022 | 19878 | 35 | 0.00132 | 0.00035 | -0.00017 | 0.42256 | 0.83884 | 0.07362 | -0.00217 |
| sentinel2 | AOI-02 | W2022_2024 | 18534 | 38 | 0.05844 | 0.04501 | -0.00255 | 0.88218 | 0.93941 | 0.87156 | 0.01870 |
| sentinel2 | AOI-03 | W2022 | 18857 | 35 | 0.03952 | 0.02736 | -0.00205 | 0.84928 | 0.92211 | 0.83720 | -0.03734 |

### Best-window frequency

| sensor | window | AOIs_best |
|---|---|---|
| landsat | W2022 | 2 |
| landsat | W2023 | 2 |
| modis | W2022 | 1 |
| modis | W2022_2023 | 1 |
| modis | W2023 | 1 |
| modis | W2024 | 1 |
| sentinel2 | W2022 | 3 |
| sentinel2 | W2022_2024 | 1 |

### AOI-level error summary

| AOI | RMSE_mean | RMSE_median | RMSE_max | MAE_mean | abs_Bias_mean |
|---|---|---|---|---|---|
| AOI-00 | 0.05113 | 0.04901 | 0.06578 | 0.04112 | 0.01480 |
| AOI-01 | 0.00139 | 0.00137 | 0.00153 | 0.00048 | 0.00013 |
| AOI-02 | 0.05674 | 0.05786 | 0.06222 | 0.04396 | 0.01414 |
| AOI-03 | 0.03560 | 0.03639 | 0.04238 | 0.02644 | 0.00776 |

Overall lowest Multi-AOI RMSE: 0.001324 (sentinel2, AOI-01, W2022); highest: 0.065780 (sentinel2, AOI-00, W2024).

### Coefficient variation

| sensor | slope_min | slope_max | slope_sd | intercept_min | intercept_max |
|---|---|---|---|---|---|
| landsat | 0.08804 | 1.03284 | 0.37011 | -0.08838 | 0.00150 |
| modis | 0.05111 | 1.09980 | 0.41676 | -0.16752 | -0.00282 |
| sentinel2 | 0.06445 | 0.88122 | 0.32681 | -0.03734 | 0.17772 |

## 5. Rolling-Origin Results

### Mean performance by target and history length

| sensor | target_year | history_length | AOIs | N_test | RMSE | MAE | Bias | R2 | Pearson_r |
|---|---|---|---|---|---|---|---|---|---|
| landsat | 2024 | 1 | 4 | 57151 | 0.03809 | 0.02980 | 0.01234 | 0.72277 | 0.87280 |
| landsat | 2024 | 2 | 4 | 57151 | 0.03653 | 0.02808 | 0.00388 | 0.73101 | 0.87538 |
| landsat | 2024 | 3 | 4 | 57151 | 0.03647 | 0.02803 | 0.00364 | 0.73213 | 0.87738 |
| landsat | 2025 | 1 | 4 | 56991 | 0.03756 | 0.02897 | -0.00131 | 0.69298 | 0.84563 |
| landsat | 2025 | 2 | 4 | 56991 | 0.03747 | 0.02926 | 0.00495 | 0.70158 | 0.84670 |
| landsat | 2025 | 3 | 4 | 56991 | 0.03595 | 0.02782 | 0.00034 | 0.70897 | 0.84816 |
| modis | 2024 | 1 | 4 | 76738 | 0.03491 | 0.02720 | 0.00530 | 0.68306 | 0.84204 |
| modis | 2024 | 2 | 4 | 76738 | 0.03277 | 0.02513 | 0.00737 | 0.69405 | 0.84022 |
| modis | 2024 | 3 | 4 | 76738 | 0.03146 | 0.02395 | 0.00526 | 0.70639 | 0.84484 |
| modis | 2025 | 1 | 4 | 74562 | 0.03193 | 0.02437 | 0.00105 | 0.71381 | 0.87820 |
| modis | 2025 | 2 | 4 | 74562 | 0.03032 | 0.02354 | 0.00438 | 0.73763 | 0.88039 |
| modis | 2025 | 3 | 4 | 74562 | 0.03050 | 0.02380 | 0.00584 | 0.74290 | 0.88001 |
| sentinel2 | 2024 | 1 | 4 | 73123 | 0.03932 | 0.02960 | 0.00205 | 0.66850 | 0.84066 |
| sentinel2 | 2024 | 2 | 4 | 73123 | 0.03921 | 0.02967 | -0.00312 | 0.66464 | 0.83441 |
| sentinel2 | 2024 | 3 | 4 | 73123 | 0.03918 | 0.02971 | 0.00389 | 0.66972 | 0.84014 |
| sentinel2 | 2025 | 1 | 4 | 76502 | 0.04135 | 0.03184 | -0.00616 | 0.65960 | 0.87878 |
| sentinel2 | 2025 | 2 | 4 | 76502 | 0.04091 | 0.03131 | -0.00502 | 0.67290 | 0.87892 |
| sentinel2 | 2025 | 3 | 4 | 76502 | 0.04073 | 0.03109 | -0.00757 | 0.67609 | 0.87853 |

### Target-year summary

| sensor | target_year | RMSE_mean | RMSE_min | RMSE_max | MAE_mean | Bias_mean |
|---|---|---|---|---|---|---|
| landsat | 2024 | 0.03703 | 0.00117 | 0.06115 | 0.02864 | 0.00662 |
| landsat | 2025 | 0.03700 | 0.00137 | 0.06087 | 0.02868 | 0.00132 |
| modis | 2024 | 0.03304 | 0.00137 | 0.04987 | 0.02543 | 0.00598 |
| modis | 2025 | 0.03092 | 0.00145 | 0.05466 | 0.02390 | 0.00375 |
| sentinel2 | 2024 | 0.03924 | 0.00126 | 0.06241 | 0.02966 | 0.00094 |
| sentinel2 | 2025 | 0.04100 | 0.00136 | 0.06578 | 0.03142 | -0.00625 |

Overall lowest Rolling-Origin RMSE: 0.001167 (landsat, AOI-01, R2024-H1); highest: 0.065780 (sentinel2, AOI-00, R2025-H1).

Monotonic non-increasing RMSE with more history occurred in 12/24 sensor × AOI × target sequences; therefore the frozen results do not support 'more historical data is always better' as a universal descriptive pattern.

### Rolling coefficient ranges

| sensor | target_year | slope_min | slope_max | slope_sd | intercept_min | intercept_max |
|---|---|---|---|---|---|---|
| landsat | 2024 | 0.09663 | 1.03284 | 0.38066 | -0.08795 | 0.00110 |
| landsat | 2025 | 0.09870 | 1.03416 | 0.37541 | -0.09232 | 0.00150 |
| modis | 2024 | 0.08499 | 1.09980 | 0.42614 | -0.16752 | -0.00476 |
| modis | 2025 | 0.05111 | 1.07917 | 0.42510 | -0.13642 | -0.00282 |
| sentinel2 | 2024 | 0.07345 | 0.89056 | 0.33601 | -0.03676 | 0.13483 |
| sentinel2 | 2025 | 0.06445 | 0.87256 | 0.33248 | -0.03507 | 0.17772 |

The frozen within-sensor block tests contain 40/72 Holm-adjusted significant contrasts at alpha=0.05.

## 6. FCOVER QA Sensitivity

Normal-vs-Strict sensitivity was excluded by `removed_experiments` in the frozen active design. No sensitivity run was added or inferred.

## 7. Block-Level Results

| sensor | AOI | block_RMSE_mean | block_RMSE_median | block_RMSE_SD | block_RMSE_min | block_RMSE_max | block_RMSE_IQR |
|---|---|---|---|---|---|---|---|
| landsat | AOI-00 | 0.04517 | 0.04440 | 0.01201 | 0.01969 | 0.07939 | 0.01456 |
| landsat | AOI-01 | 0.00115 | 0.00060 | 0.00143 | 0 | 0.00631 | 0.00149 |
| landsat | AOI-02 | 0.05849 | 0.05634 | 0.01524 | 0.02010 | 0.11186 | 0.01659 |
| landsat | AOI-03 | 0.03944 | 0.03737 | 0.01433 | 0.01753 | 0.10353 | 0.01671 |
| modis | AOI-00 | 0.03709 | 0.03631 | 0.01071 | 0.01538 | 0.07182 | 0.01411 |
| modis | AOI-01 | 0.00107 | 0.00047 | 0.00139 | 0 | 0.00650 | 0.00164 |
| modis | AOI-02 | 0.05019 | 0.04974 | 0.01222 | 0.01918 | 0.08438 | 0.01524 |
| modis | AOI-03 | 0.02929 | 0.02802 | 0.00813 | 0.01204 | 0.05790 | 0.00978 |
| sentinel2 | AOI-00 | 0.05840 | 0.05668 | 0.01555 | 0.02242 | 0.09992 | 0.02341 |
| sentinel2 | AOI-01 | 0.00100 | 0.00021 | 0.00154 | 0 | 0.00686 | 0.00167 |
| sentinel2 | AOI-02 | 0.05705 | 0.05398 | 0.01167 | 0.02944 | 0.08857 | 0.01654 |
| sentinel2 | AOI-03 | 0.03886 | 0.03151 | 0.01877 | 0.01117 | 0.08431 | 0.02164 |

Block records: 2,634 Multi-AOI and 2,616 Rolling-Origin. Two GroupKFold Pearson-r values are undefined because a fold has zero variance; all 144 primary run-level metric rows are complete.

## 8. Cross-Sensor Descriptive Summary

Cross-sensor values are reported descriptively only. No cross-sensor significance test was introduced.

| sensor | RMSE_mean | MAE_mean | Bias_mean | R2_mean | Pearson_r_mean |
|---|---|---|---|---|---|
| landsat | 0.03684 | 0.02862 | 0.00309 | 0.70324 | 0.84820 |
| modis | 0.03079 | 0.02403 | 0.00572 | 0.74152 | 0.87990 |
| sentinel2 | 0.04102 | 0.03134 | -0.00700 | 0.67490 | 0.87838 |

## 9. Unexpected Findings

- Historical-data effects are non-monotonic in 12/24 sensor × AOI × target sequences.
- Largest Multi-AOI absolute bias: -0.030175 (sentinel2, AOI-00, W2024).
- Largest Rolling-Origin absolute bias: -0.030175 (sentinel2, AOI-00, R2025-H1).
- AOI-01 has unusually low absolute errors for several combinations; this is retained as a numerical result and not interpreted causally here.

## 10. Data/Execution Anomalies

Scientific findings above are separated from execution diagnostics:

- 2 undefined GroupKFold Pearson-r values: mathematically undefined zero-variance folds, not silent joins.
- 36 one-year LOYO records are pre-specified `NOT_APPLICABLE`, not failed runs.
- No missing primary run metrics, duplicate run IDs, orphan block records, temporal leakage, block namespace collision, or source-lineage break was detected.

## 11. Candidate Manuscript Findings

Candidate Finding 1: Multi-AOI RMSE ranged from 0.001324 to 0.065780 across the 72 registered runs.

Candidate Finding 2: Only 12/24 rolling sequences improved monotonically or tied as history increased.

Candidate Finding 3: 40/72 frozen within-sensor block contrasts were significant after Holm correction.

## 12. Artifact Index

- `02_multi_aoi_results/`: raw Multi-AOI result tables.
- `03_rolling_origin_results/`: raw Rolling-Origin result tables.
- `04_master_tables/`: machine-readable master tables.
- `04_figures/`: diagnostic scientific-result figures.
- `05_validation/`: completeness and integrity audits.
- `06_result_manifest/SCIENTIFIC_RESULT_MANIFEST.json`: SHA-256 artifact manifest.
