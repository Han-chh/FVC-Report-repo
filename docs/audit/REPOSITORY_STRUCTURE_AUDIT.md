# Repository Structure Audit

## Verdict: PASS

The clean clone separates the canonical paired input (`data/canonical/`), AOI/design/provenance metadata (`data/metadata/`), authoritative primary results (`results/primary/`), final sensitivities (`results/sensitivities/`), manuscript summaries (`results/manuscript_summary/`), code, figures, documentation, and environment specifications. No LFS pointers were detected. Three large tracked files are substantive repository assets: the 11.1 MB canonical paired table, 6.2 MB block manifest, and 3.6 MB pre-consolidation inventory.

## Development-stage language

No development-stage filenames were found in the public scientific data/result tree. Occurrences of terms such as `phase`, `repair`, or pre-consolidation paths are contained in audit/provenance materials. The three retained preparation modules are explicitly documented in `code/README.md` as historical utilities outside the supported public manuscript workflow.

## Storage clarity

| Category | Rating | Evidence |
|---|---|---|
| Input data | PASS | `data/canonical/` and `data/metadata/` are distinct. |
| Derived data | PASS | Derived paired input is labelled canonical. |
| Primary results | PASS | `results/primary/` has analysis-specific subdirectories. |
| Sensitivities | PASS | Aggregation and aerosol summaries are distinct. |
| Figures | PASS | `figures/manuscript/` is unambiguous. |
| Code | PASS | Public entry points are described in `code/README.md`. |
| Documentation/audits | PASS | `docs/{methodology,reproducibility,audit}/` is discoverable. |
