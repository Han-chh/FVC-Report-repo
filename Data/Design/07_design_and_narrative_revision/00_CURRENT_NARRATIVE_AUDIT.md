# Current narrative audit

Audit date: 2026-08-10. Scope: the nine-page English manuscript PDF, English LaTeX source and supplement, active publication code/configuration, and active new-experiment documentation. No model, metric, inference, or export was run.

| Location before revision | Previous wording/role | Accurate? | Required correction and scientific meaning | Existing-result impact |
|---|---|---|---|---|
| English Table 1 | `QFLAG, NOBS, and dataMask` under “Native QA used” | No | QFLAG and NOBS are product-provided quality fields; source NoData/raster validity defines a derived support-domain mask. | Terminology/provenance only. |
| English Methods 2.1 | QA and NoData were referenced collectively, without their provenance distinction. | Incomplete | State that the validity domain is derived, is not a source band, and does not measure an additional quality tier. | Terminology/provenance only. |
| Supplement S2/S3 | FCOVER, QFLAG, NOBS and local `dataMask` described as a four-band local file. | Potentially misleading | Describe the three source fields separately from `valid_domain_mask`, derived from source NoData/raster validity. | Terminology/provenance only; the retained predicates are unchanged. |
| Workflow figure/caption | No `dataMask` label occurs in the figure or caption. | Accurate | No figure redraw required. | None. |
| Abstract, Results, Discussion, Conclusion | Report only original-AOI historical/2025 results; no Normal/Strict result is claimed. | Accurate | Preserve all result values and restrict any extension language to planned blocks. | None. |
| Introduction/RQs | Current RQs are matched to completed single-AOI evidence but do not distinguish the planned cross-environment/rolling extension. | Partly complete | Clarify the current-evidence boundary; prepare replacement RQs for use only after new experiments. | No result claim added. |
| Active experiment README/code | Multi-AOI, rolling-origin, and FCOVER quality sensitivity were all presented as active. | No | The active registry must contain only Multi-AOI and rolling-origin; retain baseline QA. | Design/code-entry correction only. |
| Active code/data contract | `dataMask` was presented as a required source fourth band; Normal/Strict profiles created an unnecessary active four-band/dual-profile contract. | No | Use `valid_domain_mask` for the derived domain; remove strict sensitivity from active paths. Legacy artifacts remain archived. | No execution and no scientific behavior change to baseline predicates. |

The current manuscript is a **current-evidence manuscript**. Its existing Abstract, Results, Discussion, and Conclusion must not be rewritten as if four AOIs or rolling-origin results already existed. Planned post-results text is kept in `planned_manuscript_blocks/`.

