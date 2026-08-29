# Final active experiment design

## 1. Multi-AOI environmental generalization

AOI-00 is the unchanged original study area. Three additional study areas are selected from a frozen pool of ten candidates before any model performance is produced. Selection is based on fixed physical scale, geographic separation, publicly derived environmental descriptors, eligibility criteria, and deterministic environmental contrast; it is independent of RMSE, MAE, Bias, R², model rank, significance results, or 2025 FCOVER performance.

The four areas are selected environmentally contrasting plateau study domains within Qinghai, not a statistically representative sample of Qinghai Province or the entire Qinghai Plateau. The same nominal dates, sensor preprocessing, common 300 m FCOVER support, temporal rules, blocks, validation procedure, and model specification apply to every AOI. Reporting is AOI-by-sensor-by-target-year; blocks remain nested within AOI, and cross-AOI interpretation is replication/consistency rather than iid pooling.

## 2. Rolling-origin temporal evaluation

Data coverage is 2021--2025. The only primary rows are:

| Target | One year | Two years | Three years |
|---|---|---|---|
| 2024 | 2023 -> 2024 | 2022--2023 -> 2024 | 2021--2023 -> 2024 |
| 2025 | 2024 -> 2025 | 2023--2024 -> 2025 | 2022--2024 -> 2025 |

Every training year precedes its target year. The 2024 rows are retrospective rolling-origin (forward-chaining) evaluations, not fully untouched final tests. The 2025 rows remain the primary independent future-year evaluations because 2025 FCOVER does not enter historical OLS calibration. The optional 2021--2024 -> 2025 window is excluded from the primary design.

## 3. Validation hierarchy

1. Common spatial support: remove support mismatch as a confounder.
2. Within-AOI spatial transfer: GroupKFold.
3. Historical interannual diagnostic: LOYO.
4. Historical spatial reserve: pre-refit held-out diagnostic.
5. Cross-environment replication: the selected AOIs.
6. Chronological forward transfer: rolling-origin targets.

These are complementary validation axes, not competing model-selection procedures.

## Final statement

The publication extension now contains two active new experiments:

1. Multi-AOI environmental generalization across four selected study areas in Qinghai.
2. Rolling-origin temporal evaluation using 2021--2025 data, with retrospective 2024 and primary independent 2025 forward targets.

The FCOVER Normal/Strict quality-sensitivity experiment has been removed from the active study design. FCOVER baseline quality screening and source-validity handling remain part of the preprocessing pipeline.

