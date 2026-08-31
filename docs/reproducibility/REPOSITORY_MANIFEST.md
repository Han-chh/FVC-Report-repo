# Repository Manifest

## Canonical data

- `data/canonical/paired_observations.csv.gz` — exact 681,545-row canonical paired input.
- `data/metadata/` — AOI definitions, source-scene records, design specifications, and execution provenance.

## Analysis and validation

- `code/reproduce_results.py` — local checksum and numerical verification.
- `code/primary_analysis/build_canonical_nonoverlap_outputs.py` — canonical primary-output builder.
- `code/sensitivities/build_processing_sensitivities.py` — aggregation-order and aerosol-QA materialization entry point.
- `code/validation/test_zero_support_pairs.py` — zero-support regression tests.

## Outputs

- `results/primary/` — Multi-AOI, Rolling-Origin, DPM, and block-inference tables.
- `results/sensitivities/aggregation_order/` — aggregation-order summaries.
- `results/sensitivities/landsat_aerosol/` — Landsat aerosol-QA summaries.
- `results/manuscript_summary/` — final result manifest and manuscript-facing records.
- `figures/manuscript/primary_block_contrasts.pdf` — final block-contrast figure.

## Scientific documentation

- `docs/methodology/FINAL_SCIENTIFIC_SCOPE.md`
- `docs/methodology/FINAL_SCIENTIFIC_DESIGN_LOCK.md`
- `docs/audit/FINAL_SCIENTIFIC_AUDIT.md`
