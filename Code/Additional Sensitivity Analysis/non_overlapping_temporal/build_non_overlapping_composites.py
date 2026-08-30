"""Future composite builder; imports the frozen median reducer through the sensitivity extension."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from additional_sensitivity_analysis.temporal import assign_non_overlapping, temporal_median

__all__ = ["assign_non_overlapping", "temporal_median"]
