"""Dry-run interface for the matched aggregation-order sensitivity."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from additional_sensitivity_analysis.config import load_yaml
from additional_sensitivity_analysis.production import assert_output_root, evaluate_pairs, materialize
import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.yaml"))
    parser.add_argument("--route", choices=("primary_ndvi_first", "reflectance_first"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--run-core-evaluation", action="store_true")
    parser.add_argument("--materialize-only", action="store_true")
    parser.add_argument("--evaluate-only", action="store_true")
    arguments = parser.parse_args(); config = load_yaml(arguments.config)
    if arguments.dry_run:
        print(json.dumps({"status": "DRY_RUN_ONLY", "sensitivity": config["sensitivity_name"],
                      "route": arguments.route or config["aggregation_route"],
                      "target_grid": config["target_grid"],
                      "matched_native_support": True,
                      "will_run_core_evaluation": bool(arguments.run_core_evaluation)}, indent=2)); return
    if arguments.materialize_only and arguments.evaluate_only: raise ValueError("AGGREGATION_STAGE_ARGUMENT_CONFLICT")
    root = assert_output_root(Path(config["output_root"])); final = root / "final"; final.mkdir(parents=True, exist_ok=True)
    route = arguments.route or config["aggregation_route"]
    paths = [final / f"paired_ndvi_fcover_{route}_{sensor}.csv" for sensor in ("sentinel2", "landsat", "modis")]
    if not arguments.evaluate_only:
        for sensor, path in zip(("sentinel2", "landsat", "modis"), paths):
            materialize(sensor, sensitivity=config["sensitivity_name"], variant=route, output_csv=path, aggregation_route=route)
    if arguments.materialize_only: return
    if not all(path.is_file() for path in paths): raise FileNotFoundError("AGGREGATION_CANONICAL_PAIRS_MISSING")
    pairs = pd.concat([pd.read_csv(path) for path in paths], ignore_index=True); pairs.to_csv(final / f"paired_ndvi_fcover_{route}.csv", index=False)
    if arguments.run_core_evaluation: evaluate_pairs(pairs, final / route, sensitivity=config["sensitivity_name"], variant=route)


if __name__ == "__main__":
    main()
