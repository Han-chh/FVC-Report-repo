# Canonical non-overlap primary-result audit

## Protocol
The canonical preprocessing assigns each eligible source observation to its nearest 20 July, 31 July, or 10 August nominal date within the inclusive 15-day support. Ties are assigned to the earlier nominal date. An identity is assigned to no more than one nominal date; the temporal reducer remains the existing cell-wise median with at least two contributions.

## Run inventory
- Source pair rows: 681,545; unique target identities across sensor-specific records: 681,545.
- Multi-AOI OLS configurations: 72; Rolling-Origin OLS configurations: 72; DPM endpoint configurations: 48.
- Paired block contrasts: 72; Holm-supported: 36; longer-window lower-error: 28; longer-window higher-error: 8.

## Sensor-level 2025 Multi-AOI means
- landsat: RMSE=0.037984, MAE=0.029918, Bias=0.004490 (24 runs).
- modis: RMSE=0.034141, MAE=0.026122, Bias=0.003962 (24 runs).
- sentinel2: RMSE=0.045182, MAE=0.034550, Bias=-0.011185 (24 runs).

## Preferred 2025 histories

- landsat, AOI-00: W2022 (RMSE=0.049230).
- landsat, AOI-01: W2023 (RMSE=0.001210).
- landsat, AOI-02: W2022_2023 (RMSE=0.057445).
- landsat, AOI-03: W2022 (RMSE=0.036780).
- modis, AOI-00: W2023 (RMSE=0.041835).
- modis, AOI-01: W2022 (RMSE=0.001404).
- modis, AOI-02: W2022_2023 (RMSE=0.056367).
- modis, AOI-03: W2023 (RMSE=0.032099).
- sentinel2, AOI-00: W2022 (RMSE=0.072786).
- sentinel2, AOI-01: W2023 (RMSE=0.001335).
- sentinel2, AOI-02: W2022_2024 (RMSE=0.059645).
- sentinel2, AOI-03: W2024 (RMSE=0.041776).

## DPM/OLS comparison
- OLS has lower selected RMSE in 12/12 sensor--AOI comparisons; DPM/OLS RMSE ratio=2.44--407.60.

## Provenance
- Non-overlap pair input SHA-256: `c29c5458535b9e5275c8efc581d7dd4f25836783e2b7787a1f9c6d0197dcc0a3`.
- This directory was regenerated from those pairs; no frozen overlapping-primary output was overwritten.
