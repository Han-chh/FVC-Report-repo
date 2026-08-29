#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "src"))
from aoi_expansion.select_final_aois import select
from aoi_expansion.mapping import candidate_map

exp = ROOT.parent / "new_experiments/01_multi_aoi"
df, log = select(exp / "environmental_features.csv", exp / "candidate_aoi_registry.geojson", ROOT / "configs/aoi_candidates.yaml", exp)
boundary = ROOT.parent / "new_experiments/data/aoi/qinghai_adm1.geojson"
candidate_map(boundary, exp / "candidate_aoi_registry.geojson", exp / "candidate_aoi_registry.csv", exp / "candidate_aoi_map.png")
print(df[["aoi_id", "selection_status", "final_aoi_id", "eligibility", "exclusion_reason"]].to_string(index=False))

