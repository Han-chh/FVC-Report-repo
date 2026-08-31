# Final Repository Audit

## Pre-consolidation state

The checkout began at `2f690bf8917b28e3a11bfb06853092b0830233f4` on `main`, tracking `origin/main`. The recorded pre-change worktree state is in `PRE_REORGANIZATION_GIT_STATE.txt` and the complete 14,620-file inventory is `REPOSITORY_PRECONSOLIDATION_INVENTORY.csv`.

## Final structure

The public tree is organized as `code/`, `data/`, `results/`, `figures/`, `docs/`, and `environment/`.

## Authoritative content

- Canonical data: `data/canonical/paired_observations.csv.gz`.
- Primary results: `results/primary/`.
- Active sensitivity summaries: `results/sensitivities/`.
- Locked result manifest: `results/manuscript_summary/FINAL_RESULTS_MANIFEST.csv`.
- Final scientific audit: `docs/audit/FINAL_SCIENTIFIC_AUDIT.md`.

## Consolidation decisions

Phase 3-deprecated overlapping outputs, former sensitivity outputs, AOI-00 diagnostics, manuscript source artifacts, and development-only scripts were removed from the current tree. Git history retains their provenance. No canonical primary result, active sensitivity summary, or locked audit record was removed.

## Portability, environment, security, and size

Active paths are repository-relative; see `PATH_PORTABILITY_AUDIT.md`. `environment/requirements.txt` provides the verified local reproduction requirements. The repository scan found no credential file or token value. The historical pattern match was field-name-only credential-handling code, not a credential. No tracked file exceeds 100 MB and Git LFS is not required.

## Validation

- Canonical checksum: PASS.
- 72 Multi-AOI OLS rows: PASS.
- 72 Rolling-Origin OLS rows: PASS.
- 48 DPM rows: PASS.
- Zero-support regression tests: PASS (5 tests).

## Scientific preservation and navigation

`SCIENTIFIC_CONTENT_PRESERVATION_AUDIT.md` records the numerical checks. The root README and `REPOSITORY_MANIFEST.md` identify the study, protocol, input, primary code, outputs, sensitivities, 5-km role, and scientific audit.

## Git and remote status

The consolidation commit `893d432be5f8644bf3654e45830d8bad22a58235` was pushed normally to `origin/main` from a non-divergent local branch. No force push, tag, release, DOI, or publication snapshot was created.
