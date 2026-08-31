# Code

`reproduce_results.py` is the local, read-only numerical verification entry point. Run it from the repository root after installing `../environment/requirements.txt`.

The `src/` packages implement preprocessing helpers, OLS/DPM modelling, 5-km block evaluation, and validation. Final-build entry points are:

- `primary_analysis/build_canonical_nonoverlap_outputs.py`
- `sensitivities/build_processing_sensitivities.py`

The build entry points can require externally configured public-data access; use an explicit temporary output directory when regenerating material and do not overwrite tracked authoritative results.
