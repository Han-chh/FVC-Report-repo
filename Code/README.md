# Code guide

`src/`, `configs/`, `scripts/`, and `tests/` are the active publication implementation. Deprecated FCOVER quality-sensitivity code is deliberately excluded because it was not part of the frozen active design.

## Recommended reviewer command

From the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r Code/requirements-reproduction.txt
python Code/reproduce_results.py
```

The runner has no network or credential requirement. It reads `Data/Inputs/paired_observations.csv.gz`, recomputes the formal Multi-AOI and Rolling-Origin OLS metrics and the DPM endpoint candidates, and compares them with the committed results. It checks 72 + 72 + 48 result rows at an absolute tolerance of `1e-10` for floating-point quantities.

## Full processing implementation

The scripts implement the frozen preprocessing contract, source inventory checks, exact 5 km block rules, seed-42 SHA-256 reserve partition, GroupKFold, leave-one-year-out diagnostic, rolling-origin analysis, Holm correction, final result packaging, and coefficient diagnostics.

The cloud-extraction scripts require a user-controlled Google Earth Engine environment and public-source access configured outside this repository. They must not be run with credentials committed to source control. The exact already-extracted input and all source manifests are included under `Data/`, so cloud access is not needed for numerical result reproduction.

## Legacy AOI-00 code

`legacy/` contains the historical report-side scripts used by the AOI-00 DPM consistency check. Set `FVC_REPORT_DATA` to `Data/Legacy_AOI00/data_final` and choose a writable `FVC_REPORT_OUTPUT` directory before using those scripts. The current manuscript's main reproducibility path is the portable `reproduce_results.py` runner, not the legacy script family.
