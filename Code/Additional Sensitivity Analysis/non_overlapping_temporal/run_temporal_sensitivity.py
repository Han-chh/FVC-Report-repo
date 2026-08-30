"""Plan, but never implicitly launch, a temporal sensitivity production run."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from additional_sensitivity_analysis.config import load_yaml
from additional_sensitivity_analysis.production import (assert_output_root, evaluate_pairs, materialize,
                                                        nearest_nominal_scene_selector)
import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.yaml"))
    parser.add_argument("--dry-run", action="store_true", help="Print the future run contract; performs no data access.")
    parser.add_argument("--run-core-evaluation", action="store_true")
    parser.add_argument("--materialize-only", action="store_true")
    parser.add_argument("--evaluate-only", action="store_true")
    parser.add_argument("--sensor", choices=("sentinel2", "landsat", "modis"),
                        help="Resume one independent sensor materialization; evaluation still requires all sensors.")
    arguments = parser.parse_args()
    config = load_yaml(arguments.config)
    if arguments.dry_run:
        print(json.dumps({"status": "DRY_RUN_ONLY", "sensitivity": config["sensitivity_name"],
                      "variant": config["temporal_mode"], "output_root": config["output_root"],
                      "will_run_core_evaluation": bool(arguments.run_core_evaluation),
                      "validation": ["one_assignment_per_source_identity", "original_union_only",
                                     "nominal_labels_fixed", "no_target_or_later_year_leakage",
                                     "downstream_pair_schema"]}, indent=2)); return
    if arguments.materialize_only and arguments.evaluate_only: raise ValueError("TEMPORAL_STAGE_ARGUMENT_CONFLICT")
    root = assert_output_root(Path(config["output_root"])); final = root / "final"; final.mkdir(parents=True, exist_ok=True)
    sensors = (arguments.sensor,) if arguments.sensor else ("sentinel2", "landsat", "modis")
    paths = {sensor: final / f"paired_ndvi_fcover_{sensor}.csv" for sensor in sensors}
    if not arguments.evaluate_only:
        for sensor, path in paths.items():
            materialize(sensor, sensitivity=config["sensitivity_name"], variant=config["temporal_mode"], output_csv=path,
                        selector=nearest_nominal_scene_selector)
    if arguments.materialize_only: return
    all_paths = [final / f"paired_ndvi_fcover_{sensor}.csv" for sensor in ("sentinel2", "landsat", "modis")]
    if not all(path.is_file() for path in all_paths): raise FileNotFoundError("TEMPORAL_CANONICAL_PAIRS_MISSING")
    pairs = pd.concat([pd.read_csv(path) for path in all_paths], ignore_index=True); pairs.to_csv(final / "paired_ndvi_fcover.csv", index=False)
    if arguments.run_core_evaluation: evaluate_pairs(pairs, final, sensitivity=config["sensitivity_name"], variant=config["temporal_mode"])


if __name__ == "__main__":
    main()
