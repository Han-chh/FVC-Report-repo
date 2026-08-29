# Post-revision consistency audit

Audit completed: 2026-08-10. This audit used source inspection, static terminology scans, Python compilation, the active code test suite, English manuscript/supplement compilation, text extraction, and visual inspection of the revised Table 1, Methods provenance paragraph, workflow page, and Supplement S3.

| Check | Status | Evidence |
|---|---|---|
| A. Abstract makes no unrun extension claim | Pass | Abstract was retained as current evidence only. |
| B. Introduction does not promise absent results | Pass | It marks cross-environment/multi-target work as post-execution extension design. |
| C. Current RQs remain answerable by current evidence | Pass | RQ1 is explicitly restricted to the original study area; final RQs are planned separately. |
| D. Methods distinguish plan from execution | Pass | Current methods only correct provenance; future methods are in planned blocks. |
| E. Results retain only executed results | Pass | No result source was edited. |
| F. Discussion has no unrun interpretation | Pass | Existing discussion was retained. |
| G. Conclusion does not overclaim multi-AOI/two-target evidence | Pass | Existing current-evidence conclusion was retained. |
| H. Source-band `dataMask` misstatement removed from current English manuscript/supplement | Pass | Table 1 and S2/S3 use QFLAG/NOBS plus derived `valid_domain_mask`. |
| I. FCOVER quality sensitivity removed from active design | Pass | Only `multi_aoi` and `rolling_origin` occur in the active registry; sensitivity artifacts are archived. |
| J. Baseline QFLAG/NOBS/validity handling retained | Pass | Active config and `valid_reference_mask` preserve the baseline reference gate under correct provenance terminology. |
| Active code test suite | Pass | `26 passed` via `model/.venv/bin/python -m pytest -q report/publication/code/tests`. |
| Code syntax | Pass | `compileall` completed for active source and scripts. |
| Narrative PDF layout | Pass | English manuscript compiled to nine pages; visual inspection found no clipping, overlap, or table break. |
| Supplement layout | Pass | English supplement compiled to 13 pages; visual inspection found the corrected S3 text and equation readable. |
| Chinese-source compilation | Pass | The synchronized Chinese manuscript and supplement compiled successfully to temporary 8-page and 12-page checks; existing Chinese PDFs were not overwritten. |

The checked output is `report/publication/english/FVC_publication_en_narrative_revision.pdf`, accompanied by `report/publication/supplementary/Supplementary_Methods_EN_narrative_revision.pdf`. Neither file is a final post-experiment publication version.
