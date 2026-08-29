# FCOVER Normal/Strict sensitivity removal

## Former design

The former third extension repeated the pipeline under a baseline “Normal” mask and a more restrictive QFLAG-method subset (“Strict”), then proposed comparisons of retention, model coefficients, FCOVER-reference agreement, rolling-origin ordering, and inference.

## Current decision

The Normal/Strict sensitivity experiment is removed from the active study design because the publication is being focused on two primary transferability questions: environmental/geographic replication and chronological forward transfer. This is a scope-consolidation decision, not a claim that FCOVER QA is unimportant or that the experiment is technically difficult.

## What remains in baseline preprocessing

- QFLAG and NOBS remain product-provided screening fields.
- `valid_domain_mask` remains a deterministic derived indicator of the source-valid FCOVER support domain.
- FCOVER values must remain finite and scaled values must remain in the stated valid range.
- No derived validity indicator is interpreted as an independent quality class or product flag.

## Record and future handling

Historical design files, retention records, scripts, and configuration are preserved in `_deprecated/fcover_quality_sensitivity_removed/` and `report/publication/code/_deprecated/`. They are not active runners, configurations, or research questions. If reviewers later require this robustness analysis, it may be designed and authorized as a revision-stage analysis; it is not a required result of the present paper.

FCOVER reference uncertainty is handled in the main narrative by positioning FCOVER as an operational product reference/comparator, never as field ground truth, and by retaining clear quality and validity-domain provenance.

