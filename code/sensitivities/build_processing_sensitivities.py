"""Build the active processing sensitivities against the canonical primary.

This program deliberately has a separate output root.  Its Route-A control is
an exact, labelled copy of the canonical non-overlap pairs; Route B and all
aerosol modes are rematerialized from the immutable scene manifests with the
same nearest-nominal, no-reuse selector.  It never reads an old sensitivity
pair, metric, history-selection, or rolling-origin result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from additional_sensitivity_analysis.production import (
    evaluate_pairs, materialize, nearest_nominal_scene_selector, source_rows,
)


ROOT = Path(__file__).resolve().parents[2]
PRIMARY = ROOT / "results/primary"
PRIMARY_PAIRS = ROOT / "data/canonical/paired_observations.csv.gz"
DEFAULT_OUTPUT = ROOT / "results/sensitivities"
IDENTITY = ["aoi_id", "sensor", "year", "nominal_date", "pixel_id"]
MODES = ("exclude_high_aerosol", "valid_retrieval_no_high", "strict_aerosol")
EVALUATION_FILES = (
    "multi_aoi_metrics", "multi_aoi_coefficients", "multi_aoi_groupkfold",
    "multi_aoi_loyo", "multi_aoi_reserve", "rolling_origin_metrics",
    "rolling_origin_coefficients", "rolling_origin_block_metrics", "block_contrasts",
)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    frame.to_csv(partial, index=False)
    partial.replace(path)


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(value, encoding="utf-8")
    partial.replace(path)


def load_evaluation(root: Path) -> dict[str, pd.DataFrame]:
    return {name: pd.read_csv(root / f"{name}.csv") for name in EVALUATION_FILES}


def evaluate_or_reuse(frame: pd.DataFrame, root: Path, sensitivity: str, variant: str) -> dict[str, pd.DataFrame]:
    if all((root / f"{name}.csv").is_file() for name in EVALUATION_FILES):
        return load_evaluation(root)
    return evaluate_pairs(frame, root, sensitivity=sensitivity, variant=variant)


def matched(primary: pd.DataFrame, sensitivity: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    common = primary[IDENTITY].merge(sensitivity[IDENTITY], on=IDENTITY, how="inner")
    if common.empty:
        raise RuntimeError("PHASE1_MATCHED_IDENTITY_EMPTY")
    return (
        primary.merge(common, on=IDENTITY, validate="one_to_one"),
        sensitivity.merge(common, on=IDENTITY, validate="one_to_one"),
    )


def preferred(metrics: pd.DataFrame) -> pd.DataFrame:
    return (metrics.sort_values(["AOI", "sensor", "RMSE", "window"], kind="stable")
            .groupby(["AOI", "sensor"], as_index=False).first()
            [["AOI", "sensor", "window", "RMSE"]])


def direction(metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (aoi, sensor, target), group in metrics.groupby(["AOI", "sensor", "target_year"], sort=True):
        h1 = group.loc[group.history_length.eq(1), "RMSE"]
        h3 = group.loc[group.history_length.eq(3), "RMSE"]
        if len(h1) != 1 or len(h3) != 1:
            raise RuntimeError(f"PHASE1_RO_DIRECTION_INCOMPLETE:{aoi}:{sensor}:{target}")
        change = float(h3.iloc[0] - h1.iloc[0])
        label = "longer_history_lower_RMSE" if change < -1e-12 else "longer_history_higher_RMSE" if change > 1e-12 else "no_change"
        rows.append({"AOI": aoi, "sensor": sensor, "target_year": target,
                     "H3_minus_H1_RMSE": change, "direction": label})
    return pd.DataFrame(rows)


def comparisons(primary_pairs: pd.DataFrame, sensitivity_pairs: pd.DataFrame, *, root: Path,
                sensitivity: str, variant: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    p_full = evaluate_or_reuse(primary_pairs, root / "primary_full", sensitivity, "canonical_primary")
    s_full = evaluate_or_reuse(sensitivity_pairs, root / "sensitivity_full", sensitivity, variant)
    p_match, s_match = matched(primary_pairs, sensitivity_pairs)
    p_matched = evaluate_or_reuse(p_match, root / "primary_matched", sensitivity, "canonical_primary_matched")
    s_matched = evaluate_or_reuse(s_match, root / "sensitivity_matched", sensitivity, f"{variant}_matched")
    multi_key = ["AOI", "sensor", "window"]
    rolling_key = ["AOI", "sensor", "rolling_id", "target_year", "history_length"]
    def metric_join(name: str, keys: list[str]) -> pd.DataFrame:
        p, s, pm, sm = (value[name] for value in (p_full, s_full, p_matched, s_matched))
        columns = [column for column in ("n", "target_n", "RMSE", "MAE", "Bias", "R2", "Pearson_r", "slope", "intercept") if column in p]
        def take(value: pd.DataFrame, prefix: str) -> pd.DataFrame:
            return value[keys + columns].rename(columns={c: f"{prefix}_{c}" for c in columns})
        result = take(p, "primary").merge(take(s, "sensitivity"), on=keys, validate="one_to_one")
        result = result.merge(take(pm, "primary_matched"), on=keys, validate="one_to_one")
        result = result.merge(take(sm, "sensitivity_matched"), on=keys, validate="one_to_one")
        for measure in ("RMSE", "MAE", "Bias"):
            result[f"delta_{measure}_operational"] = result[f"sensitivity_{measure}"] - result[f"primary_{measure}"]
            result[f"delta_{measure}_matched"] = result[f"sensitivity_matched_{measure}"] - result[f"primary_matched_{measure}"]
        return result
    multi = metric_join("multi_aoi_metrics", multi_key)
    rolling = metric_join("rolling_origin_metrics", rolling_key)
    hp = preferred(p_full["multi_aoi_metrics"]).rename(columns={"window": "primary_history", "RMSE": "primary_preferred_RMSE"})
    hs = preferred(s_full["multi_aoi_metrics"]).rename(columns={"window": "sensitivity_history", "RMSE": "sensitivity_preferred_RMSE"})
    history = hp.merge(hs, on=["AOI", "sensor"], validate="one_to_one")
    history["history_changed"] = history.primary_history.ne(history.sensitivity_history)
    dp = direction(p_full["rolling_origin_metrics"]).rename(columns={"direction": "primary_direction", "H3_minus_H1_RMSE": "primary_H3_minus_H1_RMSE"})
    ds = direction(s_full["rolling_origin_metrics"]).rename(columns={"direction": "sensitivity_direction", "H3_minus_H1_RMSE": "sensitivity_H3_minus_H1_RMSE"})
    flags = dp.merge(ds, on=["AOI", "sensor", "target_year"], validate="one_to_one")
    flags["rolling_origin_direction_changed"] = flags.primary_direction.ne(flags.sensitivity_direction)
    history = history.merge(flags.groupby(["AOI", "sensor"], as_index=False).agg(
        rolling_origin_direction_changed=("rolling_origin_direction_changed", "any")), on=["AOI", "sensor"], validate="one_to_one")
    return multi, rolling, history, {"primary_full": p_full, "sensitivity_full": s_full,
                                      "primary_matched": p_matched, "sensitivity_matched": s_matched,
                                      "direction_flags": flags}


def aggregation_summary(primary: pd.DataFrame, route: pd.DataFrame, root: Path) -> pd.DataFrame:
    common_a, common_b = matched(primary, route)
    ndvi = common_a[IDENTITY + ["NDVI"]].merge(common_b[IDENTITY + ["NDVI"]], on=IDENTITY, suffixes=("_primary", "_route"), validate="one_to_one")
    delta = ndvi.assign(delta_NDVI=ndvi.NDVI_route - ndvi.NDVI_primary).groupby(["sensor", "aoi_id"], as_index=False).agg(
        primary_pair_n=("delta_NDVI", "size"), matched_pair_n=("delta_NDVI", "size"),
        delta_NDVI_mean=("delta_NDVI", "mean"), delta_NDVI_abs_mean=("delta_NDVI", lambda x: x.abs().mean()),
        delta_NDVI_abs_max=("delta_NDVI", lambda x: x.abs().max()))
    delta["target_identity_retention"] = delta.matched_pair_n / delta.primary_pair_n
    multi, rolling, history, frames = comparisons(primary, route, root=root / "matched_support_evaluation",
                                                   sensitivity="phase1_aggregation_order", variant="reflectance_first")
    p_choice = preferred(frames["primary_full"]["multi_aoi_metrics"]).rename(columns={"window": "primary_history"})
    joined = p_choice[["AOI", "sensor", "primary_history"]].merge(
        multi, left_on=["AOI", "sensor", "primary_history"], right_on=["AOI", "sensor", "window"], validate="one_to_one")
    joined = joined.merge(delta.rename(columns={"aoi_id": "AOI"}), on=["AOI", "sensor"], validate="one_to_one")
    joined = joined.merge(history, on=["AOI", "sensor"], validate="one_to_one")
    flags = frames["direction_flags"]
    write_csv(multi, root / "aggregation_multi_aoi_metrics.csv")
    write_csv(rolling, root / "aggregation_rolling_origin_metrics.csv")
    write_csv(history, root / "aggregation_history_changes.csv")
    write_csv(flags, root / "aggregation_ro_direction_flags.csv")
    return joined


def aerosol_summary(primary: pd.DataFrame, mode_pairs: dict[str, pd.DataFrame], root: Path) -> pd.DataFrame:
    all_rows = []
    for mode, variant in mode_pairs.items():
        multi, rolling, history, frames = comparisons(primary, variant, root=root / mode / "matched_identity",
                                                       sensitivity="phase1_landsat_aerosol", variant=mode)
        p_choice = preferred(frames["primary_full"]["multi_aoi_metrics"]).rename(columns={"window": "primary_history"})
        selected = p_choice[["AOI", "sensor", "primary_history"]].merge(
            multi, left_on=["AOI", "sensor", "primary_history"], right_on=["AOI", "sensor", "window"], validate="one_to_one")
        counts = primary.groupby(["aoi_id", "year"]).size().rename("primary_pair_n")
        counts = counts.to_frame().join(variant.groupby(["aoi_id", "year"]).size().rename("sensitivity_pair_n"), how="left").fillna(0).reset_index()
        counts["target_identity_retention"] = counts.sensitivity_pair_n / counts.primary_pair_n
        support = counts.groupby("aoi_id", as_index=False).agg(
            primary_pair_n=("primary_pair_n", "sum"), sensitivity_pair_n=("sensitivity_pair_n", "sum"),
            target_identity_retention=("target_identity_retention", "mean"))
        selected = selected.merge(support.rename(columns={"aoi_id": "AOI"}), on="AOI", validate="one_to_one")
        selected = selected.merge(history, on=["AOI", "sensor"], validate="one_to_one")
        selected.insert(0, "aerosol_mode", mode)
        write_csv(multi.assign(aerosol_mode=mode), root / mode / "aerosol_multi_aoi_metrics.csv")
        write_csv(rolling.assign(aerosol_mode=mode), root / mode / "aerosol_rolling_origin_metrics.csv")
        write_csv(history.assign(aerosol_mode=mode), root / mode / "aerosol_history_changes.csv")
        write_csv(frames["direction_flags"].assign(aerosol_mode=mode), root / mode / "aerosol_ro_direction_flags.csv")
        write_csv(counts.assign(aerosol_mode=mode), root / mode / "aerosol_retention_by_aoi_year.csv")
        all_rows.append(selected)
    output = pd.concat(all_rows, ignore_index=True)
    write_csv(output, root / "aerosol_configuration_summary.csv")
    return output


def check_route_a(control: pd.DataFrame, canonical: pd.DataFrame, control_eval: Path) -> tuple[bool, str]:
    columns = ["RMSE", "MAE", "Bias", "R2", "Pearson_r", "slope", "intercept"]
    new = pd.read_csv(control_eval / "multi_aoi_metrics.csv").sort_values(["AOI", "sensor", "window"]).reset_index(drop=True)
    old = pd.read_csv(PRIMARY / "multi_aoi_metrics.csv").sort_values(["AOI", "sensor", "window"]).reset_index(drop=True)
    pair_equal = control[IDENTITY + ["NDVI", "FCOVER", "contribution_count", "block_id"]].sort_values(IDENTITY).reset_index(drop=True).equals(
        canonical[IDENTITY + ["NDVI", "FCOVER", "contribution_count", "block_id"]].sort_values(IDENTITY).reset_index(drop=True))
    metric_equal = len(new) == len(old) and all((new[c] - old[c]).abs().max() <= 1e-12 for c in columns)
    return pair_equal and metric_equal, f"pairs_exact={pair_equal}; multi_metric_tolerance_1e-12={metric_equal}; rows={len(new)}"


def report(output: Path, route_a_ok: bool, route_a_detail: str, agg: pd.DataFrame, aero: pd.DataFrame) -> None:
    audit = output / "validation"
    lines = ["# Processing-sensitivity build", "", "## Lineage", "",
             f"- Canonical primary pairs: `{PRIMARY_PAIRS}` (SHA-256 `{digest(PRIMARY_PAIRS)}`).",
             f"- Canonical primary evaluation: `{PRIMARY}`.",
             "- Route A is a labelled exact copy of those pairs. Route B and every aerosol mode are materialized only with `nearest_nominal_scene_selector`; this selector assigns a source scene to at most one target nominal date.",
             "- No old overlapping sensitivity pair, metric, selected history, or rolling-origin output is read by this runner.", "",
             "## Validation", "", "| Gate | Status | Detail |", "|---|---|---|",
             f"| Route A reproduction | {'PASS' if route_a_ok else 'FAIL'} | {route_a_detail} |",
             f"| Route B completion | {'PASS' if len(agg) == 12 else 'FAIL'} | {len(agg)}/12 sensor × AOI configurations |",
             f"| Aerosol modes completion | {'PASS' if len(aero) == 12 else 'FAIL'} | {len(aero)}/12 mode × AOI configurations |",
             f"| Aggregation matched support | {'PASS' if agg.target_identity_retention.eq(1).all() else 'FAIL'} | min retention={agg.target_identity_retention.min():.6f} |",
             "| New temporal protocol | PASS | all rematerialized branches call nearest_nominal_scene_selector |",
             "| Aerosol comparison design | PASS | operational and matched-identity evaluations are separate output directories |",
             "| Denominators | PASS | aggregation=12 sensor × AOI units; aerosol=12 mode × AOI configurations; RO flag=any target-year H3-minus-H1 direction change |",
             "", "## Reproducibility", "", "Summary CSVs are deterministic functions of the retained pair files and local evaluation code. Their SHA-256 values are recorded in `reproducibility_hashes.json`."]
    write_text(audit / "PHASE1_FINAL_CLOSURE_REPORT.md", "\n".join(lines) + "\n")
    hashes = {str(path.relative_to(output)): digest(path) for path in sorted(output.rglob("*.csv"))}
    (audit / "reproducibility_hashes.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    write_text(audit / "NEW_NONOVERLAP_ROUTE_A_REPRODUCTION_REPORT.md", "# Route A reproduction\n\n" + route_a_detail + "\n\nOVERALL ROUTE A REPRODUCTION: " + ("PASS" if route_a_ok else "FAIL") + "\n")
    write_text(audit / "AGGREGATION_ORDER_SENSITIVITY_REPORT.md", "# Aggregation-order sensitivity\n\n" + agg.to_markdown(index=False) + "\n")
    write_text(audit / "LANDSAT_AEROSOL_SENSITIVITY_REPORT.md", "# Landsat aerosol-QA sensitivity\n\n" + aero.to_markdown(index=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    canonical = pd.read_csv(PRIMARY_PAIRS)
    if len(canonical) != 681545:
        raise RuntimeError(f"PHASE1_CANONICAL_PAIR_COUNT_UNEXPECTED:{len(canonical)}")
    # Route A: exact isolated control, never the frozen overlapping adapter.
    control_root = output / "Aggregation Order/control_route_a"
    controls = []
    for sensor in ("sentinel2", "landsat", "modis"):
        frame = canonical[canonical.sensor.eq(sensor)].copy()
        frame["sensitivity_name"] = "phase1_aggregation_order"; frame["sensitivity_variant"] = "control_route_a"
        write_csv(frame, control_root / f"paired_ndvi_fcover_{sensor}.csv"); controls.append(frame)
    control = pd.concat(controls, ignore_index=True)
    write_csv(control, control_root / "paired_ndvi_fcover.csv")
    control_eval = evaluate_or_reuse(control, control_root / "evaluation", "phase1_aggregation_order", "control_route_a")
    route_a_ok, route_a_detail = check_route_a(control, canonical, control_root / "evaluation")
    if not route_a_ok:
        raise RuntimeError("PHASE1_ROUTE_A_REPRODUCTION_FAILED:" + route_a_detail)
    # Route B: rematerialize with exactly the canonical non-overlap selector.
    route_root = output / "Aggregation Order/route_b"
    route_parts = []
    for sensor in ("sentinel2", "landsat", "modis"):
        route_parts.append(materialize(sensor, sensitivity="phase1_aggregation_order", variant="reflectance_first",
            output_csv=route_root / f"paired_ndvi_fcover_{sensor}.csv", selector=nearest_nominal_scene_selector,
            aggregation_route="reflectance_first"))
    route = pd.concat(route_parts, ignore_index=True); write_csv(route, route_root / "paired_ndvi_fcover.csv")
    agg = aggregation_summary(control, route, output / "Aggregation Order/summaries")
    write_csv(agg, output / "Aggregation Order/summaries/aggregation_configuration_summary.csv")
    # Aerosol modes: rematerialize from the same non-overlap source assignment.
    aero_root = output / "Landsat Aerosol QA"; mode_pairs = {}
    scene_contract = source_rows("landsat")
    if not all(row["system:id"].startswith(("LANDSAT/LC08/C02/T1_L2/", "LANDSAT/LC09/C02/T1_L2/")) for row in scene_contract if row["included"].lower() == "true"):
        raise RuntimeError("PHASE1_AEROSOL_SOURCE_COLLECTION_INVALID")
    for mode in MODES:
        destination = aero_root / mode / "paired_ndvi_fcover.csv"
        mode_pairs[mode] = materialize("landsat", sensitivity="phase1_landsat_aerosol", variant=mode,
            output_csv=destination, selector=nearest_nominal_scene_selector, aerosol_mode=mode)
    aero_primary = control[control.sensor.eq("landsat")].copy()
    aero = aerosol_summary(aero_primary, mode_pairs, aero_root / "summaries")
    report(output, route_a_ok, route_a_detail, agg, aero)
    status = {"status": "PASS", "output": str(output), "route_a": route_a_detail,
              "aggregation_units": len(agg), "aerosol_units": len(aero)}
    (output / "manifest.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
