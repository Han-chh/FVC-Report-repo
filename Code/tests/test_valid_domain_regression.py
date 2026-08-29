import numpy as np

from data_prep.fcover import fcover_value_valid_mask


def test_rmse_nodata_does_not_invalidate_a_valid_fcover_domain_cell():
    fcover = np.array([112], dtype="uint8")
    rmse = np.array([255], dtype="uint8")
    qflag = np.array([96], dtype="uint8")
    nobs = np.array([1], dtype="uint8")
    assert fcover_value_valid_mask(fcover, nodata=255).item()
    assert rmse.item() == 255 and qflag.item() != 255 and nobs.item() != 255


def test_fcover_nodata_invalidates_domain_even_when_auxiliary_fields_exist():
    assert not fcover_value_valid_mask(np.array([255], dtype="uint8"), nodata=255).item()
