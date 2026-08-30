# Production integration audit

Status at the start of Stage A: **NOT READY**.

| Sensitivity | Transformation | Source loader | Materialization | Schema adapter | Core evaluation | Full-run entry | Ready |
|---|---|---|---|---|---|---|---|
| Non-overlapping temporal | YES (array assignment) | NO | NO | partial | NO | NO | NO |
| Landsat aerosol QA | YES (decoder) | partial (band selector only) | NO | partial | NO | NO | NO |
| Aggregation order | YES (array reducer) | NO | NO | partial | NO | NO | NO |

The implementation-only runners contain hard-coded guards in their `main()`
functions.  The shared `additional_sensitivity_analysis` package currently
contains transformations and a narrow OLS scoring adapter, but no source scene
loader, FCOVER-grid materializer, checkpointed canonical pair writer, or
full historical / rolling integration. Stage A replaces these omissions; it
does not bypass the guards.
