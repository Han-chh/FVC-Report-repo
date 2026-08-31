from __future__ import annotations

import numpy as np


def fcover_value_valid_mask(fcover_dn, *, nodata=255):
    """Derived FCOVER support domain, independent of QA/auxiliary fields.

    FCOVER source raster validity is the sole domain predicate.  QFLAG/NOBS
    availability and their frozen acceptance rules are evaluated separately by
    ``valid_reference_mask``; RMSE/LBEFORE/LAFTER remain provenance fields.
    """
    values = np.asarray(fcover_dn)
    valid = np.isfinite(values)
    if nodata is not None:
        valid &= values != nodata
    return valid


def valid_reference_mask(fcover_dn, qflag, nobs, valid_domain_mask, *, nodata=65535, scale=0.004):
    """Return the baseline FCOVER reference mask.

    ``valid_domain_mask`` is deterministically derived from source NoData and
    raster-validity semantics.  It is not a Copernicus source QA band and does
    not express an additional quality tier.
    """
    values = fcover_dn.astype("float32") * scale
    return (
        (fcover_dn != nodata) & (qflag != nodata) & (nobs != nodata) &
        (valid_domain_mask > 0) & (qflag < 255) & (nobs > 0) &
        np.isfinite(values) & (values >= 0) & (values <= 1)
    )


def scaled_values(fcover_dn, valid, *, scale=0.004):
    return np.where(valid, fcover_dn.astype("float32") * scale, np.nan)
