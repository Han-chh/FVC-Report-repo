# Data layout and status semantics

All report experiment rasters are stored and processed in GEE under `projects/qinghai-internship-fvc-models/assets/fvc_report_data`. This local directory contains only small registries, status tables, logs, and manifests; it contains no active local or removable-drive raster cache.

`data_preparation_status.csv` has 220 AOI×year×product rows. Every row is READY and points to a verified GEE asset. Status semantics remain:

- READY: source, QA, grid, temporal-count, lineage, integrity, and manifest contracts passed;
- PARTIAL: some required preparation contract is incomplete;
- FAILED: preparation was attempted and failed, with the log retained;
- NOT_AVAILABLE: no compatible product record exists.

The authoritative image inventory is `manifests/gee_cloud_asset_manifest.json`; the consolidated execution inventory is `manifests/gee_cloud_preparation_manifest.json`. No year/product substitution, QA relaxation, window expansion, or n-threshold change is allowed.
