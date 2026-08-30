"""Official-USGS aerosol QA decoder compatibility wrapper."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from additional_sensitivity_analysis.aerosol import aerosol_pass_mask, decode_sr_qa_aerosol

__all__ = ["aerosol_pass_mask", "decode_sr_qa_aerosol"]
