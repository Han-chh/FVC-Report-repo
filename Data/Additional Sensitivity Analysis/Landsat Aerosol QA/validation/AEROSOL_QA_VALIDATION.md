# AEROSOL QA VALIDATION

| Check | Status | Detail |
|---|---|---|
| Official product provenance | PASS | Landsat 8/9 Collection 2 Level-2 scenes; surface reflectance remains atmospherically corrected |
| Decoder semantics | PASS | USGS LaSRC: fill bit 0; valid retrieval bit 1; interpolated bit 5; level bits 6–7 |
| Exact-scene association | PASS | queried scene IDs/time stamps and same-image band selection agree |
| Missing aerosol QA | PASS | missing policy is reject; a missing band causes materialization failure, and completed output has zero accepted missing-QA observations |
| Checkpoint and downstream completion | PASS | 80/80 valid checkpoints; modes: primary_no_aerosol_filter, exclude_high_aerosol, valid_retrieval_no_high, strict_aerosol |

Retention counts are canonical paired 300 m identities after the frozen temporal composite and pairing rules; this sensitivity adds aerosol-specific QA screening and does not add atmospheric correction.

OVERALL AEROSOL QA VALIDATION: PASS
