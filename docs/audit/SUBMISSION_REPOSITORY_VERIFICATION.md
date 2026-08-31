# Phase 5 — Submission Repository Verification

**Status: PASS**

Audit date: 2026-08-31  
Verified remote: `git@github.com:Han-chh/FVC-Report-repo.git`  
Verified branch: `main`  
Verified content commit: `fe2ea5778441b32e94a24131630580ec8831158a`

## Verification matrix

| Check | Status | Evidence |
|---|---|---|
| Remote clean clone | PASS | Fresh depth-1 clone completed cleanly at the verified commit. |
| Repository structure | PASS | See `REPOSITORY_STRUCTURE_AUDIT.md`. |
| README navigation | PASS | Study, AOIs, years, products, target grid, protocol, data boundary, commands, sensitivities, inference boundary, and audit location are stated. |
| Canonical data completeness | PASS | 681,545-row paired table, schema, AOI/grid/block metadata, and scene provenance present. |
| Primary code completeness | PASS | Public local verifier and explicit-output primary builder present and exercised. |
| Primary results completeness | PASS | 72 Multi-AOI; 72 Rolling-Origin; 48 DPM; 72 block contrasts. |
| Aggregation-order sensitivity | PASS | 12 configuration rows, Route-A/matched-support outputs, Route-B summary, 1.0 identity retention. |
| Aerosol-QA sensitivity | PASS | 60 support rows, zero-support state, estimability/matched/history/RO/final-summary assets. |
| 5-km inference assets | PASS | Block manifest and 72 paired contrasts present. |
| Environment documentation | PASS | Python >=3.11, minimal verification requirements, full editable environment, geospatial and Earth Engine boundary documented. |
| Path portability | PASS | Public entry points use `Path`/repository-relative inputs and explicit external outputs; no active absolute local paths. |
| File references | PASS | All 1,094 final-manifest and 1,105 provenance source/generator references resolve. |
| Table/figure traceability | PASS | See `MANUSCRIPT_ARTIFACT_TRACEABILITY.csv`. |
| Lightweight reconstruction | PASS | See `CLEAN_CLONE_RECONSTRUCTION_AUDIT.md`. |
| Regression tests | PASS | 5/5 tests passed; no failures. |
| Security quick check | PASS | No live credential artifacts or key-like contents found in the current tree. |
| Remote submission commit | PASS | Remote clean clone matched the intended branch and commit. |

## Reproduction boundary

**PUBLICATION_REPRODUCTION_STARTING_POINT:** `data/canonical/paired_observations.csv.gz`. It is the readable 681,545-row canonical non-overlap pair table with AOI, sensor, year, nominal-date, target identity, NDVI, FCOVER, contribution count, and 5-km block fields. It supports the local manuscript-level reproduction command without remote data access. Upstream acquisitions are intentionally not bundled; products, scene identities, QA, temporal protocol, target grid, and export lineage are documented under `code/configs/` and `data/metadata/`.

## Documentation and storage

README, data/code/results/environment READMEs, methodology, reproducibility manifest, and final scientific audit are all discoverable and clear. The historical preparation utilities have been explicitly separated from the supported canonical-data workflow in `code/README.md`.

## Issues

- Critical: none.
- Major: none.
- Minor: the complete primary builder emits warnings for singleton/constant supporting partitions while generating non-manuscript supporting metrics. Its principal and auxiliary authoritative CSVs match exactly; no scientific result changed.

## Repairs made before this verification

1. Repaired public reconstruction output handling: builders now require an explicit empty external directory and cannot write into the repository.
2. Repaired canonical/manifest/provenance paths so every active source and generator reference resolves in a clean clone.
3. Clarified AOIs/products, environment split, upstream boundary, and the retained historical-utility boundary.

No tag, GitHub release, Zenodo DOI, or immutable release artifact was created.
