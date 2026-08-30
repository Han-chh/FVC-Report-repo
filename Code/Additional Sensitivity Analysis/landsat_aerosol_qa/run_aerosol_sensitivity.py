"""Dry-run interface for the additional Landsat aerosol QA branch."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from additional_sensitivity_analysis.aerosol import gee_retrieval_band_spec
from additional_sensitivity_analysis.config import load_yaml
from additional_sensitivity_analysis.production import assert_output_root, evaluate_pairs, materialize
import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.yaml"))
    parser.add_argument("--variant")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--run-core-evaluation", action="store_true")
    parser.add_argument("--materialize-only", action="store_true")
    parser.add_argument("--evaluate-only", action="store_true")
    arguments = parser.parse_args(); config = load_yaml(arguments.config)
    variant = arguments.variant or config["aerosol_mode"]
    if arguments.dry_run:
        print(json.dumps({"status": "DRY_RUN_ONLY", "sensitivity": config["sensitivity_name"],
                      "variant": variant, "required_same_scene_bands": gee_retrieval_band_spec(),
                      "source_data_status": config["source_data_status"],
                      "will_run_core_evaluation": bool(arguments.run_core_evaluation)}, indent=2)); return
    if arguments.materialize_only and arguments.evaluate_only: raise ValueError("AEROSOL_STAGE_ARGUMENT_CONFLICT")
    root = assert_output_root(Path(config["output_root"])); final = root / "final"; final.mkdir(parents=True, exist_ok=True)
    modes = [variant] if arguments.variant else list(config["modes"])
    for mode in modes:
        path = final / f"paired_ndvi_fcover_{mode}.csv"
        if not arguments.evaluate_only: materialize("landsat", sensitivity=config["sensitivity_name"], variant=mode, output_csv=path, aerosol_mode=mode)
        if arguments.materialize_only: continue
        if not path.is_file(): raise FileNotFoundError(f"AEROSOL_CANONICAL_PAIRS_MISSING:{mode}")
        pairs = pd.read_csv(path)
        if arguments.run_core_evaluation: evaluate_pairs(pairs, final / mode, sensitivity=config["sensitivity_name"], variant=mode)


if __name__ == "__main__":
    main()
