from __future__ import annotations

import yaml
from pathlib import Path

REQUIRED_ORDER = ["reflectance_scaling", "native_qa", "source_pixel_ndvi", "average_to_native_fcover_grid", "temporal_nanmedian_on_fcover_grid"]


def validate(path: Path):
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert config["processing_order"] == REQUIRED_ORDER
    assert config["minimum_finite_contributions"] == 2
    assert config["target_support"]["resample_fcover"] is False
    assert config["target_support"]["extra_coverage_threshold"] is None
    assert config["spatial_blocks"]["size_m"] == 5000
    assert config["historical_partition"]["seed"] == 42
    assert config["model"]["family"] == "OLS"
    assert config["model"]["intercept"] is True
    return config

