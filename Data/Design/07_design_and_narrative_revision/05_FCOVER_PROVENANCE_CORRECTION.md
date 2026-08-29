# FCOVER provenance correction

## Required distinction

| Category | Fields/meaning | Permitted interpretation |
|---|---|---|
| Product-provided quality information | QFLAG and NOBS | FCOVER screening inputs, with only documented semantics applied. |
| Derived validity domain | `valid_domain_mask`, deterministically derived from source NoData/raster validity | Identifies whether a support cell belongs to the valid FCOVER product domain. |

`valid_domain_mask` is not a source FCOVER band, native QA field, official QA layer, quality grade, quality score, or ground-truth flag. No dedicated source `dataMask` band is assumed.

## Baseline predicate

The baseline reference gate is source FCOVER DN validity, QFLAG validity and `QFLAG < 255`, NOBS validity and `NOBS > 0`, `valid_domain_mask == 1`, and scaled FCOVER in [0, 1]. This retains the former baseline eligibility semantics while correcting its name and provenance.

## Compatibility mapping

Historical artifacts may contain the legacy field name `dataMask`. Where it meant source NoData/raster validity, its explicit mapping is:

`legacy_dataMask -> valid_domain_mask`

Legacy naming is retained only in archived artifacts or change-history references. Publication-facing API, config, documentation, and future asset contracts use `valid_domain_mask`.

