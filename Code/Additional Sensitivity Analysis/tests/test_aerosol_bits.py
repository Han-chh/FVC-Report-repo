from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from additional_sensitivity_analysis.aerosol import aerosol_pass_mask, decode_sr_qa_aerosol


def test_official_aerosol_fields_decode_and_high_is_rejected() -> None:
    # bit 1 valid retrieval; bit 5 interpolated; bits 6--7 aerosol level.
    qa = np.array([2 | (2 << 6), 2 | (3 << 6), 2 | 32 | (1 << 6)], dtype=np.uint16)
    decoded = decode_sr_qa_aerosol(qa)
    assert decoded["valid_retrieval"].tolist() == [True, True, True]
    assert decoded["interpolated"].tolist() == [False, False, True]
    assert decoded["aerosol_level_code"].tolist() == [2, 3, 1]
    assert aerosol_pass_mask(qa, mode="exclude_high_aerosol").tolist() == [True, False, True]
    assert aerosol_pass_mask(qa, mode="valid_retrieval_no_high").tolist() == [True, False, False]
    assert aerosol_pass_mask(qa, mode="strict_aerosol").tolist() == [False, False, False]


def test_missing_qa_fails_loudly_and_primary_mode_adds_no_filter() -> None:
    with pytest.raises(ValueError, match="AEROSOL_QA_MISSING"):
        aerosol_pass_mask(None, mode="exclude_high_aerosol")
    assert aerosol_pass_mask(np.array([0, 1, 255]), mode="primary_no_aerosol_filter").tolist() == [True, True, True]
