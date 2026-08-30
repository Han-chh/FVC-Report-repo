# FVC Report repo

Reproducibility package for the manuscript *Multi-Sensor NDVI-Based FVC Retrieval Agreement with Copernicus FCOVER on a Common 300 m Target Grid: Geographic Heterogeneity and Historical-Window Transfer across Qinghai Plateau AOIs*.

This repository contains the exact derived analysis input, frozen design and provenance records, executable analysis code, and tabular results used by the submitted manuscript. It is organised so that a reviewer can independently verify the numerical results without cloud credentials or a new satellite-data download.

## Repository layout

| Path | Contents | Reviewer use |
|---|---|---|
| `Code/` | Active Python implementation, configurations, tests, and a portable result-verification runner. | Recompute and compare the 72 Multi-AOI runs, 72 Rolling-Origin runs, and 48 DPM candidates. |
| `Data/Inputs/` | The frozen, derived NDVI--FCOVER paired-observation table. | Exact numerical input to the active analyses. |
| `Data/Results/` | Run-level, block-level, coefficient, validation, manifest, and overview outputs. | Inspect every reported result and its integrity checks. |
| `Data/Provenance/` | Frozen source-scene inventories, block manifest, execution manifest, processing identity, and authorization record. | Trace every input and result to the frozen design. |
| `Data/Design/` | AOI registries and approved experiment-design records. | Check the geography, windows, and active experimental scope. |
| `Data/DPM_stage2/` | Stage-2 all-AOI DPM benchmark outputs and audit. | Check the 48 endpoint candidates and the DPM--OLS comparison. |
| `Data/Legacy_AOI00/` | Earlier AOI-00 support-grid data and code inputs retained only for the DPM legacy-reproduction check. | Audit the preserved historical consistency check separately from the four-AOI main analysis. |

## Quick verification

The quick check is fully local and does not contact Google Earth Engine or any other service.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r Code/requirements-reproduction.txt
python Code/reproduce_results.py
```

The command recomputes the 72 Multi-AOI OLS evaluations, the 72 Rolling-Origin OLS evaluations, and the 48 all-AOI DPM endpoint evaluations from `Data/Inputs/paired_observations.csv.gz`. It compares the computed values against the committed machine-readable result tables and exits non-zero if any check fails.

## Data scope and provenance

The committed paired table is the exact derived input used for the published statistical analyses. It contains 995,060 sensor-specific observations after the frozen quality, support, temporal-compositing, and block-assignment rules. Its SHA-256 value is recorded in `Data/DPM_stage2/dpm_execution_log.json` and in the scientific execution manifests.

The source satellite products are accessed from their public providers rather than redistributed here: Sentinel-2 Harmonized surface reflectance through Google Earth Engine, Landsat 8/9 Collection 2 Level-2 Tier-1 surface reflectance through the U.S. Geological Survey, MOD09Q1 Collection 6.1 through NASA/LP DAAC, and Copernicus FCOVER V2 RT6 through the Copernicus Land Monitoring Service. Exact source-scene identifiers, GEE asset identifiers, dates, AOIs, and validation records are in `Data/Provenance/00_execution_manifest/source_scenes/active_r2/` and `Data/Collection_metadata/manifests/`.

No credentials, access tokens, personal data, or unpublished field observations are included.

## Reproducibility boundary

`Code/reproduce_results.py` is the recommended independent verification entry point. `Code/src/` and `Code/scripts/` preserve the full active processing and execution implementation. Recreating the upstream cloud extraction requires the relevant public-data accounts and a user-controlled Google Earth Engine project; it is not necessary to reproduce the reported numerical results because the exact derived input table and complete provenance records are included.

The `Data/Legacy_AOI00/` branch is intentionally separate. It supports the legacy AOI-00 DPM consistency check documented in `Data/DPM_stage2/`; it is not a substitute for the frozen four-AOI main-analysis input.

## Additional Sensitivity Analyses

Three reproducible sensitivity pipelines are implemented in
`Code/Additional Sensitivity Analysis/`: non-overlapping temporal composition,
Landsat `SR_QA_AEROSOL` filtering, and NDVI-before-versus-after aggregation
order. All three production runs are complete and isolated under
`Data/Additional Sensitivity Analysis/`; the frozen primary inputs and results
remain unchanged. The hard-gate result is
`Data/Additional Sensitivity Analysis/Combined/MANUSCRIPT_INTEGRATION_READY.md`.

The checkpointed production entry points are:

```bash
PYTHONPATH=Code/src python3 "Code/Additional Sensitivity Analysis/non_overlapping_temporal/run_temporal_sensitivity.py" --run-core-evaluation
PYTHONPATH=Code/src python3 "Code/Additional Sensitivity Analysis/landsat_aerosol_qa/run_aerosol_sensitivity.py" --run-core-evaluation
PYTHONPATH=Code/src python3 "Code/Additional Sensitivity Analysis/finalize_sensitivity_results.py" combined
```

Materialization writes atomic per-sensor/AOI/year checkpoints and resumes only
valid completed checkpoints. Validation reports and final sensitivity tables
are in each sensitivity directory; the five manuscript-integration artefacts
are in `Data/Additional Sensitivity Analysis/Combined/`.

## Citation

Please cite the associated manuscript and this repository version (commit hash or release tag) when using these materials. A formal software/data license has not yet been selected; reuse beyond review and scholarly verification requires the author's permission.
