# Data guide

This directory holds only the data, results, and provenance needed to reproduce or audit the submitted manuscript. The active analysis is based on `Inputs/paired_observations.csv.gz`; do not substitute files from `Legacy_AOI00/` for it.

## Active analysis data

| Location | Description |
|---|---|
| `Inputs/paired_observations.csv.gz` | Frozen NDVI--FCOVER pair table used by all Multi-AOI, Rolling-Origin, and all-AOI DPM computations. |
| `Results/02_multi_aoi_results/` | Complete outputs for the 72 Multi-AOI OLS evaluations, including GroupKFold, LOYO, reserve, coefficients, and block metrics. |
| `Results/03_rolling_origin_results/` | Complete outputs for the 72 chronological Rolling-Origin OLS evaluations and Holm-adjusted block contrasts. |
| `Results/04_master_tables/` | Canonical tables used by the manuscript and DPM comparison. |
| `Results/05_validation/` | Data-completeness and scientific-result integrity audits. |
| `Results/06_result_manifest/` | Result-level SHA-256 manifest and human-readable inventory. |
| `Results/07_result_overview/` | Factual execution and result overview. |
| `Results/04_figures/` | Machine-generated supporting figures from the executed analysis. |

## Design and provenance

`Design/` contains the final AOI registry, the rolling-origin plan, and the frozen active-design records. `Provenance/` contains the block manifest, processing identity, execution manifest, source-scene records, and authorization record. `Collection_metadata/` contains the GEE/FCOVER preparation inventories and status tables.

These records establish that the active design contains four AOIs, three sensors, 72 Multi-AOI runs, and 72 Rolling-Origin runs. The frozen design hash is `b21c8cc7f3d4d35e1db4dfa1c8245ff10ba657c0a0a001992b552808766cc49b`; the frozen processing hash is `3fab57b81623045f745beeaa0c1615c51b0d44344beaa74a1025ee4450b699c7`.

## DPM and legacy material

`DPM_stage2/` contains the all-AOI DPM candidate tables, DPM-versus-OLS summary, and integrity audit. `Legacy_AOI00/` retains the historical AOI-00 support-grid data and endpoint reference files needed for that explicit legacy check. It is clearly separated because the manuscript's main geographic and temporal results are computed from the active paired table, not from the legacy files.

## External source products

The original satellite products remain with their public providers. This repository supplies the derived table actually analysed and source-scene/asset inventories sufficient to trace the extraction. It does not redistribute the providers' raw global products or credentials.
