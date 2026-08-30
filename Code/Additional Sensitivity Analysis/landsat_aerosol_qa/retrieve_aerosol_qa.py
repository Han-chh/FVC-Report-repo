"""Same-scene GEE retrieval contract for Collection 2 Level-2 aerosol QA."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from additional_sensitivity_analysis.aerosol import gee_retrieval_band_spec


def select_same_scene_bands(image):
    """Return required C2 L2 bands from *one* source image; no cross-scene join."""
    return image.select(list(gee_retrieval_band_spec())).copyProperties(
        image, ["system:id", "system:index", "system:time_start", "SPACECRAFT_ID"]
    )
