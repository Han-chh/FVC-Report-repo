# Code

`reproduce_results.py` is the local, read-only numerical verification entry point. Run it from the repository root after installing `environment/requirements.txt`.

The `src/` packages implement preprocessing helpers, OLS/DPM modelling, 5-km block evaluation, and validation. Final-build entry points are:

- `primary_analysis/build_canonical_nonoverlap_outputs.py`
- `sensitivities/build_processing_sensitivities.py`

The build entry points require an explicit, empty output directory outside the repository; they never overwrite tracked authoritative results. The primary builder uses the committed canonical pair table and can be run locally with `PYTHONPATH=code/src python code/primary_analysis/build_canonical_nonoverlap_outputs.py --output /absolute/path/to/reconstruction`. The sensitivity builder additionally requires documented public upstream access and Earth Engine credentials.

The public manuscript workflow starts at `data/canonical/paired_observations.csv.gz`. The AOI-expansion and execution-readiness modules under `src/` are retained preparation/provenance utilities, not supported raw-satellite-to-paper entry points; some retain historical workspace references as audit provenance. They are not invoked by the local numerical verification or the canonical primary builder.
