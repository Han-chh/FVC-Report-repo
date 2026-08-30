"""Validate source assignments before a future non-overlapping composite run."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from additional_sensitivity_analysis.temporal import temporal_dry_run_summary

__all__ = ["temporal_dry_run_summary"]
