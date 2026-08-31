# Phase 3 Final Scientific Audit

## Status

**PHASE 3 — FINAL SCIENTIFIC DESIGN LOCK: PASS**

The scientific design is locked and ready for Phase 4 clean reproduction and publication freeze.

## Validation gates

| Gate | Result | Evidence |
|---|---|---|
| 1 Primary protocol lock | PASS | Non-overlap is the sole primary protocol. |
| 2 Run-count consistency | PASS | 72 Multi-AOI, 72 Rolling-Origin, 48 DPM. |
| 3 Numeric manifest | PASS | 1,094 machine-readable source-linked records. |
| 4-6 Lineage and aerosol comparability | PASS | Canonical primary and final Phase 1 summaries; zero-support and NOT_COMPARABLE retained. |
| 7-9 5-km rationale and boundaries | PASS | Pragmatic inferential scale; no independence, optimality, or multiscale claim. |
| 10-12 Tables, figures, abstract | PASS | Table/Figure audit and candidate source audit. |
| 13-17 Methods, results, discussion, limitations, conclusion | PASS | Code-to-text matrix and claim matrix. |
| 18 Cover letter | PASS | Independent consistency audit. |
| 19 Supplement dependency | PASS | No reviewer-facing supplementary dependency. |
| 20 Data/code truth | PASS | Availability wording qualified to current pre-freeze state. |
| 21 Page limit | PASS | Candidate compiled; six pages; Conclusion starts on page 3 and ends on page 4. |

## Methods code-to-text parity

Products, scaling, QA, masks, common target grid, FCOVER validity, NDVI, aggregation order, nearest-nominal assignment, tie rule, two-contribution reducer, history windows, complete-block rule, OLS, clipping, DPM endpoints, retrospective selection, Rolling-Origin, 5-km blocks, paired tests, Holm correction, and active sensitivity semantics were cross-referenced to `Code/configs/canonical_nonoverlap_primary.yaml`, `Code/src/additional_sensitivity_analysis/production.py`, `temporal.py`, `finalize.py`, `Code/src/execution/science.py`, and `Code/src/metrics/`. Result: PASS.

## Candidate corrections

One wording-only correction was made: the availability statement no longer implies that a formal immutable repository release already exists. No scientific result, table value, figure, or experiment changed.

## Locked design and authoritative numbers

- Temporal protocol: inclusive +/-15-day support, nearest nominal-date assignment, earlier-date ties, and no source reuse.
- Data and design: Sentinel-2, Landsat 8/9, MODIS, and Copernicus FCOVER V2 RT6; four Qinghai Plateau AOIs; 2021-2025; native 300-m FCOVER target grid.
- Formal models: 72 Multi-AOI OLS + 72 Rolling-Origin OLS = 144 formal OLS runs; 48 DPM configurations.
- Primary totals: 681,545 paired observations; mean 2025 Multi-AOI RMSE of 0.045182 (Sentinel-2), 0.037984 (Landsat), and 0.034141 (MODIS).
- Inference: 72 5-km paired contrasts; 36 Holm-supported (28 longer-history lower-error; 8 higher-error).
- Sensitivities: aggregation-order retention 1.0 with 1/12 preferred-history and 2/12 unit-level RO changes; aerosol QA has 60 support records, 2 zero-support groups, 12/12 operational and 12/12 matched Multi-AOI comparisons estimable, and 14 direction changes among 21 comparable RO comparisons (3 NOT_COMPARABLE).

## Boundaries and exclusions

The 5-km scale is pragmatic and inferential, not optimality or spatial-independence evidence; its limitation remains concise. The candidate claims FCOVER-reference agreement and configuration-specific heterogeneity, not field accuracy, causal history effects, universal sensor superiority, or cross-scale robustness. Deprecated manuscript sources are overlapping-primary outputs, old non-overlap sensitivity framing, overlapping-baseline aggregation/aerosol outputs, partial aerosol outputs, and obsolete drafts.

## Provenance, contamination, and submission artifacts

- Provenance: 1,105/1,105 manuscript-facing numeric or configuration-level records trace successfully to source rows (**100%**).
- Legacy contamination: old overlapping results **NO**; old sensitivity results **NO**; partial aerosol outputs **NO**.
- Cover letter: **PASS**. Supplement dependency: **NONE**. Page check: six total manuscript pages; Conclusion page 3-4.
- Phase 3 outputs: `FINAL_SCIENTIFIC_SCOPE.md`, `FINAL_SCIENTIFIC_DESIGN_LOCK.md`, `FINAL_RESULTS_MANIFEST.csv`, `FINAL_RESULTS_MANIFEST.md`, `MANUSCRIPT_RESULT_PROVENANCE.csv`, `FINAL_CLAIM_MATRIX.md`, `TABLE_FIGURE_AUDIT.md`, `LEGACY_CONTAMINATION_AUDIT.md`, `SCIENTIFIC_OUTPUT_CLASSIFICATION.csv`, `DATA_CODE_AVAILABILITY_TRUTH_AUDIT.md`, `COVER_LETTER_CONSISTENCY_AUDIT.md`, and this report.

## Compile and visual audit

The candidate manuscript and cover letter compiled with Tectonic. The manuscript is six A4 pages and the cover letter is one A4 page. All six manuscript pages and the one cover-letter page were rendered and visually inspected: no clipping, overlap, missing figure, broken table, citation failure, or special-character defect was observed. Underfull-box warnings are retained layout diagnostics only.
