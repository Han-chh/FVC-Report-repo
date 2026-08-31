# Clean-Clone Reconstruction Audit

Verified from a clean remote clone at `fe2ea5778441b32e94a24131630580ec8831158a`.

- `python code/reproduce_results.py`: PASS; checksum plus exactly 72 Multi-AOI, 72 Rolling-Origin, and 48 DPM rows.
- `PYTHONPATH=code/src python code/primary_analysis/build_canonical_nonoverlap_outputs.py --output <external empty directory>`: PASS.
- Rebuilt `multi_aoi_metrics` (72), `rolling_origin_metrics` (72), `block_contrasts` (72), `dpm_endpoint_sensitivity` (48), `dpm_vs_ols_selected` (12), and `aoi01_baseline_clipping` (12) exactly for categorical fields and within absolute tolerance `1e-12` for numeric fields.
- Aggregation-order summary: 12 configurations; primary matched identity retention exactly 1.0.
- Aerosol QA summary: 60 support records (3 modes × 4 AOIs × 5 years), 2 explicit zero-support groups, 12/12 operational and 12/12 matched comparisons estimable, and 3 Rolling-Origin `NOT_COMPARABLE` states.
- The full primary builder emits expected NumPy/scikit-learn warnings for singleton/constant supporting partitions; its authoritative outputs remain exactly matched. This is logged as a minor usability issue, not a numerical discrepancy.

Upstream acquisition and full sensitivity rematerialization were documented but not executed because they require external Earth Engine/public-data access and user-local credentials.
