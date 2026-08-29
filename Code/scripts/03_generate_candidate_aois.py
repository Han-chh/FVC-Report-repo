#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "src"))
from aoi_expansion.candidate_generation import generate

workspace = ROOT.parents[2]
output = ROOT.parent / "new_experiments/01_multi_aoi/candidate_aoi_registry.geojson"
generate(ROOT / "configs/aoi_candidates.yaml", workspace / "report/data_final/aoi.geojson", output)
print(output)
