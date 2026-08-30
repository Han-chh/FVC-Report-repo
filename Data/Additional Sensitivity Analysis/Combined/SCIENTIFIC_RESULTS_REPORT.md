# Scientific Sensitivity Results Report

## A — Aggregation Order

Route A reproduced the frozen primary result at 100.00% (13/13), and Route B completed 60/60 checkpoints.
Matched Route A/Route B mean absolute ΔNDVI spans 0.000101477 to 0.00686362; operational ΔRMSE spans -0.00145801 to 0.00049328. Preferred-history changes: 1; rolling-direction changes: 2.

## B — Non-overlapping Temporal

Source assignment retention spans 0.857143 to 1; duplicate source identities are zero. Operational ΔRMSE spans -0.00231886 to 0.0140516; matched-support ΔRMSE spans -0.000899932 to 0.0177631.
Preferred-history changes: 7; rolling-direction changes: 3. The overlapping primary temporal design changes some numerical estimates and preferences but does not materially change the conclusion classifications.

## C — Landsat Aerosol QA

Valid modes were primary_no_aerosol_filter, exclude_high_aerosol, valid_retrieval_no_high, and strict_aerosol.
Canonical paired-identity retention spans 0.355383 to 1; operational ΔRMSE spans -0.00396904 to 0.0270358; matched-support ΔRMSE spans -0.00183726 to 0.0339962.
AOI-specific history exceptions: strict_aerosol/AOI-01; exclude_high_aerosol/AOI-02; strict_aerosol/AOI-02; valid_retrieval_no_high/AOI-02. Rolling-direction exceptions: strict_aerosol/AOI-00; exclude_high_aerosol/AOI-01; strict_aerosol/AOI-01; valid_retrieval_no_high/AOI-01; strict_aerosol/AOI-02; valid_retrieval_no_high/AOI-02; exclude_high_aerosol/AOI-03; strict_aerosol/AOI-03; valid_retrieval_no_high/AOI-03.
Preferred-history changes: 4; rolling-direction changes: 9.

## D — Overall robustness

C1–C5 are robust across all three sensitivities according to the configuration-level numerical evidence in `sensitivity_conclusion_matrix.csv`. Numerical RMSE, coefficients, preferred histories, and some Rolling-Origin directions are quantitatively sensitive; no manuscript-level conclusion is materially revised.
This is an evidence report only; it is not manuscript prose.
