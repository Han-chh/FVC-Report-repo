# Multi-Sensor NDVI–FCOVER Agreement on a Common 300-m Grid

This repository is the final reproducibility package for a study of agreement between NDVI-based fractional vegetation cover retrievals and Copernicus FCOVER V2 RT6. It covers Sentinel-2, Landsat 8/9, and MODIS across four Qinghai Plateau areas of interest (AOIs) during 2021–2025, using the native 300-m FCOVER target grid.

The canonical temporal protocol assigns every eligible source observation within an inclusive ±15-day support window to its nearest nominal date (20 July, 31 July, or 10 August), breaks exact ties toward the earlier date, and permits no source reuse across nominal dates.

## Repository structure

- `code/` contains the portable verification runner, scientific implementations, configurations, and tests.
- `data/` contains the canonical paired input and metadata required to interpret and reproduce the analysis.
- `results/` contains authoritative primary, sensitivity, and manuscript-summary outputs.
- `figures/` contains final manuscript figures.
- `docs/` contains methodology, reproducibility guidance, and audit records.
- `environment/` contains the verified local dependency specification.

## Primary analysis

The locked primary analysis includes 72 Multi-AOI OLS runs, 72 Rolling-Origin OLS runs, 48 descriptive DPM endpoint configurations, and 72 predefined paired 5-km block contrasts. Fixed-origin 5-km blocks are the sole prespecified inferential aggregation scale; they reduce local pseudo-replication but do not establish spatial independence or an optimal block size.

## Sensitivity analyses

The active processing sensitivities are aggregation order and Landsat aerosol QA. Non-overlapping temporal assignment is the primary protocol, not a sensitivity analysis.

## Reproducing the numerical results

The local verification run does not require satellite-data downloads or cloud credentials.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r environment/requirements.txt
python code/reproduce_results.py
```

It verifies the canonical paired-input checksum and recomputes the 72 Multi-AOI OLS, 72 Rolling-Origin OLS, and 48 DPM rows against the committed final tables. See [the repository manifest](docs/reproducibility/REPOSITORY_MANIFEST.md) for entry points and output locations.

## Data availability

`data/canonical/paired_observations.csv.gz` is the exact derived 681,545-row input used by the primary numerical checks. Source products are accessed from their public providers; scene identifiers, AOI definitions, and processing metadata are retained under `data/metadata/`.

Agreement with FCOVER is not field-level validation, and a shared target grid does not imply identical post-QA effective support across sensors.

## Final scientific audit

The locked design, result provenance, and validation evidence are documented in [Final Scientific Audit](docs/audit/FINAL_SCIENTIFIC_AUDIT.md).

## Citation

Please cite the associated manuscript and this repository commit. No DOI or release has been created.
