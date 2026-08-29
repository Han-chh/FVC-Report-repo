# Active pipeline change report

## Active registry

`report/publication/code/configs/active_experiments.yaml` contains only `multi_aoi` and `rolling_origin`. The active runnable entry points are scripts 20 and 21, both still phase-gated.

## Terminology and contract changes

- `data_prep.fcover.valid_reference_mask` replaces the old dual-profile mask API.
- `valid_domain_mask` replaces the publication-facing `dataMask` name.
- Source ingestion reads FCOVER, QFLAG, and NOBS, then derives the validity domain from source NoData/raster-validity semantics.
- Future GEE asset contracts use `valid_domain_mask`; pair cubes use `valid_domain_mask_*` and `valid_reference_*` instead of `datamask_*`, `normal_*`, and `strict_*`.
- The former strict runner, profiles, tests, and code live under `report/publication/code/_deprecated/`.

## Historical compatibility

Existing manifests and audit records that describe already-created legacy assets are not rewritten as if they were new data. They are historical evidence and must be read using the mapping `legacy_dataMask -> valid_domain_mask`. No GEE asset was changed, re-ingested, deleted, or exported in this task.

