#!/usr/bin/env python3
"""Generate the reporting-only historical spatial-reserve diagnostic.

This evaluator reads the frozen 300 m historical samples and reproduces the
existing deterministic 5 km block split.  For each sensor and prescribed
historical window it fits OLS only on diagnostic Development blocks and
evaluates once on the historical spatial reserve.  It does not rewrite formal
models, 2025 applications, GroupKFold/LOYO artifacts, endpoint results, or Holm
tests.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
from pyproj import Transformer
from sklearn.linear_model import LinearRegression

import generate_validation_artifacts as base


REPORT = Path(__file__).resolve().parents[1]
OUT = REPORT / "reports"
PUBLICATION = REPORT / "publication"
SUPP_TABLES = PUBLICATION / "supplementary" / "supplementary_tables"
SUPP_FIGURES = PUBLICATION / "supplementary" / "supplementary_figures"

SENSOR_NAMES = {"sentinel2": "Sentinel-2", "landsat": "Landsat 8/9", "modis": "MODIS"}
WINDOWS = tuple(base.WINDOWS)

FORMAL_ARTIFACTS = (
    OUT / "final_21_metrics.csv",
    OUT / "groupkfold_summary.csv",
    OUT / "loyo_summary_by_window.csv",
    OUT / "endpoint_sensitivity_metrics.csv",
    OUT / "pairwise_ttest_sentinel2.csv",
    OUT / "pairwise_ttest_landsat.csv",
    OUT / "pairwise_ttest_modis.csv",
)


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["status"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _metric_columns(y: np.ndarray, prediction: np.ndarray, prefix: str = "") -> dict:
    values = base.metric(y, prediction)
    return {f"{prefix}{key}": value for key, value in values.items()}


def evaluate() -> tuple[list[dict], list[dict], list[dict], dict]:
    formal_before = {str(path.relative_to(REPORT)): base.sha(path) for path in FORMAL_ARTIFACTS}
    group = pd.read_csv(OUT / "groupkfold_summary.csv").set_index(["sensor", "window"])
    formal_models = pd.read_csv(REPORT / "data_final" / "reports" / "model_parameters.csv")
    formal_models = formal_models[formal_models.strategy.isin(WINDOWS)].set_index(["sensor", "strategy"])

    summary_rows: list[dict] = []
    block_rows: list[dict] = []
    assignment_rows: list[dict] = []
    split_records: list[dict] = []
    all_checks: list[dict] = []

    for sensor in base.SENSORS:
        cache = base.sample_frame(sensor, (2022, 2023, 2024))
        for window, years in base.WINDOWS.items():
            full = cache.loc[cache.year.isin(years)].copy()
            assigned, info = base.blocks(full)
            block_ids = sorted(assigned.block_id.unique())
            reserve_ids = set(base.select_final_blocks(block_ids))
            development_ids = set(block_ids) - reserve_ids
            development = assigned.loc[assigned.block_id.isin(development_ids)].copy()
            reserve = assigned.loc[assigned.block_id.isin(reserve_ids)].copy()

            overlap = development_ids & reserve_ids
            support_role_count = assigned.assign(
                role=np.where(assigned.block_id.isin(reserve_ids), "historical_spatial_reserve", "diagnostic_development")
            ).groupby("support_id").role.nunique()

            model = LinearRegression(fit_intercept=True).fit(development[["NDVI"]], development.FCOVER)
            reserve_raw = model.predict(reserve[["NDVI"]])
            reserve_clipped = np.clip(reserve_raw, 0.0, 1.0)
            clipped_metrics = _metric_columns(reserve.FCOVER.to_numpy(), reserve_clipped)
            raw_metrics = _metric_columns(reserve.FCOVER.to_numpy(), reserve_raw, "raw_")

            window_blocks: list[dict] = []
            for block_id, block in reserve.assign(prediction=reserve_clipped, raw_prediction=reserve_raw).groupby("block_id", sort=True):
                values = _metric_columns(block.FCOVER.to_numpy(), block.prediction.to_numpy())
                raw_values = _metric_columns(block.FCOVER.to_numpy(), block.raw_prediction.to_numpy(), "raw_")
                record = {
                    "sensor": sensor,
                    "window": window,
                    "block_id": block_id,
                    "n_observations": int(len(block)),
                    **values,
                    **raw_values,
                }
                block_rows.append(record)
                window_blocks.append(record)

            block_rmse = np.asarray([row["RMSE"] for row in window_blocks], dtype=float)
            q25, q75 = np.percentile(block_rmse, [25, 75])
            gkf_rmse = float(group.loc[(sensor, window), "RMSE_mean"])
            partition_hash = base.stable({**info, "block_ids": block_ids})
            formal_n = int(formal_models.loc[(sensor, window), "total_training_samples"])
            raw_clip_rate = float(((reserve_raw < 0) | (reserve_raw > 1)).mean())

            row = {
                "sensor": sensor,
                "window": window,
                "development_blocks": len(development_ids),
                "reserve_blocks": len(reserve_ids),
                "total_blocks": len(block_ids),
                "reserve_block_fraction": len(reserve_ids) / len(block_ids),
                "development_samples": int(len(development)),
                "reserve_samples": int(len(reserve)),
                "full_history_samples": int(len(assigned)),
                "reserve_sample_fraction": len(reserve) / len(assigned),
                "slope_a_development_only": float(model.coef_[0]),
                "intercept_b_development_only": float(model.intercept_),
                "prediction_clip_rate": raw_clip_rate,
                **clipped_metrics,
                **raw_metrics,
                "block_RMSE_mean": float(block_rmse.mean()),
                "block_RMSE_SD": float(block_rmse.std(ddof=1)),
                "block_RMSE_median": float(np.median(block_rmse)),
                "block_RMSE_IQR": float(q75 - q25),
                "development_GroupKFold_RMSE_mean": gkf_rmse,
                "delta_RMSE_reserve_minus_GroupKFold": float(clipped_metrics["RMSE"] - gkf_rmse),
                "partition_hash": partition_hash,
                "reserve_block_ids": ";".join(sorted(reserve_ids)),
                "development_block_ids": ";".join(sorted(development_ids)),
                "sample_unit": "FCOVER footprint x nominal date x year",
                "metric_prediction": "OLS prediction clipped to [0,1]",
                "diagnostic_role": "pre-refit held-out historical spatial diagnostic; reporting only",
            }
            summary_rows.append(row)

            for block_id in block_ids:
                role = "historical_spatial_reserve" if block_id in reserve_ids else "diagnostic_development"
                assignment_rows.append({
                    "sensor": sensor,
                    "window": window,
                    "block_id": block_id,
                    "role": role,
                    "n_observations": int((assigned.block_id == block_id).sum()),
                    "partition_hash": partition_hash,
                })

            split_records.append({
                "sensor": sensor,
                "window": window,
                "crs": info["crs"],
                "block_size_m": info["block_size_m"],
                "grid_origin_x_m": info["grid_origin_x_m"],
                "grid_origin_y_m": info["grid_origin_y_m"],
                "random_seed": info["random_seed"],
                "configured_reserve_fraction": 0.2,
                "development_block_ids": sorted(development_ids),
                "historical_spatial_reserve_block_ids": sorted(reserve_ids),
                "partition_hash": partition_hash,
            })
            all_checks.append({
                "sensor": sensor,
                "window": window,
                "development_reserve_block_intersection_empty": not overlap,
                "each_footprint_has_one_spatial_role": bool((support_role_count == 1).all()),
                "reserve_not_in_model_training": not bool(set(development.block_id) & reserve_ids),
                "reserve_evaluation_contains_only_reserve_blocks": set(reserve.block_id) == reserve_ids,
                "development_plus_reserve_equals_full_history": len(development) + len(reserve) == len(assigned),
                "formal_full_history_refit_sample_count_matches": formal_n == len(assigned),
                "historical_evaluator_contains_no_2025": int(assigned.year.max()) <= 2024,
            })

    formal_after = {str(path.relative_to(REPORT)): base.sha(path) for path in FORMAL_ARTIFACTS}
    integrity = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluator": str(Path(__file__).relative_to(REPORT)),
        "evaluator_sha256": base.sha(Path(__file__)),
        "formal_artifacts_unchanged_during_evaluation": formal_before == formal_after,
        "formal_artifact_sha256": formal_after,
        "all_partition_and_leakage_checks_pass": all(all(value for key, value in row.items() if key not in {"sensor", "window"}) for row in all_checks),
        "checks_by_sensor_window": all_checks,
        "split_records": split_records,
        "reserve_used_for_tuning": False,
        "pairwise_tests_added": False,
        "full_history_refit_changed": False,
        "2025_outputs_changed": False,
    }
    return summary_rows, block_rows, assignment_rows, integrity


def _number(value: float, digits: int = 4) -> str:
    return f"{float(value):.{digits}f}"


def write_latex_table(rows: list[dict], language: str) -> None:
    labels = {
        "en": {
            "caption": "Historical spatial-reserve held-out diagnostics for all sensor--window combinations. OLS was fitted only on diagnostic Development blocks and evaluated once on the reserve; predictions were clipped to [0,1]. Block SD uses $n-1$, IQR is P75--P25, and $\\Delta$ is reserve RMSE minus the existing development-stage GroupKFold mean RMSE. No inferential tests were performed.",
            "source": "Source", "window": "Window", "dev": "Dev. blocks", "reserve": "Reserve blocks",
            "ntrain": "$n_{\\mathrm{Dev}}$", "nreserve": "$n_{\\mathrm{res}}$", "rmse": "RMSE", "mae": "MAE",
            "bias": "Bias", "r2": "$R^2$", "r": "$r$", "bmean": "Block mean", "bsd": "Block SD",
            "bmedian": "Block median", "biqr": "Block IQR", "delta": "$\\Delta$RMSE",
            "label": "tab:s-reserve-en",
        },
        "cn": {
            "caption": "全部传感器与历史窗口的历史空间预留块留出诊断。OLS 仅使用诊断开发块拟合，并在预留块上一次性评价；预测裁剪至 [0,1]。空间块 SD 采用 $n-1$，IQR 为 P75--P25，$\\Delta$ 为预留块 RMSE 减现有开发阶段 GroupKFold 平均 RMSE；未执行推断检验。",
            "source": "数据源", "window": "窗口", "dev": "开发块", "reserve": "预留块",
            "ntrain": "$n_{\\mathrm{Dev}}$", "nreserve": "$n_{\\mathrm{res}}$", "rmse": "RMSE", "mae": "MAE",
            "bias": "Bias", "r2": "$R^2$", "r": "$r$", "bmean": "块均值", "bsd": "块 SD",
            "bmedian": "块中位数", "biqr": "块 IQR", "delta": "$\\Delta$RMSE",
            "label": "tab:s-reserve-cn",
        },
    }[language]
    output = [
        "\\begin{landscape}",
        "\\begin{table}[p]\\centering\\scriptsize",
        f"\\caption{{{labels['caption']}}}\\label{{{labels['label']}}}",
        "\\setlength{\\tabcolsep}{2.5pt}",
        "\\resizebox{\\linewidth}{!}{%",
        "\\begin{tabular}{llrrrrrrrrrrrrrr}\\toprule",
        f"{labels['source']} & {labels['window']} & {labels['dev']} & {labels['reserve']} & {labels['ntrain']} & {labels['nreserve']} & {labels['rmse']} & {labels['mae']} & {labels['bias']} & {labels['r2']} & {labels['r']} & {labels['bmean']} & {labels['bsd']} & {labels['bmedian']} & {labels['biqr']} & {labels['delta']} \\\\ \\midrule",
    ]
    previous = None
    for row in rows:
        if previous is not None and row["sensor"] != previous:
            output.append("\\midrule")
        output.append(
            f"{SENSOR_NAMES[row['sensor']]} & {row['window']} & {row['development_blocks']} & {row['reserve_blocks']} & "
            f"{row['development_samples']:,} & {row['reserve_samples']:,} & {_number(row['RMSE'])} & {_number(row['MAE'])} & "
            f"{_number(row['Bias'])} & {_number(row['R2'])} & {_number(row['Pearson_r'], 3)} & "
            f"{_number(row['block_RMSE_mean'])} & {_number(row['block_RMSE_SD'])} & {_number(row['block_RMSE_median'])} & "
            f"{_number(row['block_RMSE_IQR'])} & {_number(row['delta_RMSE_reserve_minus_GroupKFold'])} \\\\"
        )
        previous = row["sensor"]
    output.extend(["\\bottomrule\\end{tabular}%", "}", "\\end{table}", "\\end{landscape}"])
    path = SUPP_TABLES / f"historical_spatial_reserve_metrics_{language}.tex"
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def write_figure(rows: list[dict], language: str) -> None:
    reserve = pd.DataFrame(rows).set_index(["sensor", "window"])
    group = pd.read_csv(OUT / "groupkfold_summary.csv").set_index(["sensor", "window"])
    final = pd.read_csv(OUT / "final_21_metrics.csv")
    final = final[final.strategy.isin(WINDOWS)].set_index(["sensor", "strategy"])
    mpl.rcParams.update({
        "font.family": "Arial Unicode MS" if language == "cn" else "DejaVu Sans",
        "font.size": 8.0, "axes.titlesize": 9.0, "axes.labelsize": 8.2,
        "xtick.labelsize": 7.2, "ytick.labelsize": 7.2, "legend.fontsize": 7.5,
        "pdf.fonttype": 42, "ps.fonttype": 42,
    })
    labels = {
        "en": ("GroupKFold mean ± SD", "Historical spatial reserve", "Independent 2025", "RMSE"),
        "cn": ("GroupKFold 平均值 ± SD", "历史空间预留块", "独立 2025", "RMSE"),
    }[language]
    fig, axes = plt.subplots(1, 3, figsize=(7.25, 2.95), sharex=True)
    x = np.arange(len(WINDOWS))
    display_windows = [item.replace("-", "–") for item in WINDOWS]
    for ax, sensor in zip(axes, base.SENSORS):
        spatial = group.loc[[(sensor, window) for window in WINDOWS]]
        reserve_values = reserve.loc[[(sensor, window) for window in WINDOWS]]
        fixed = final.loc[[(sensor, window) for window in WINDOWS]]
        ax.errorbar(x - 0.12, spatial.RMSE_mean, yerr=spatial.RMSE_sd, fmt="o", ms=3.6,
                    lw=0.9, capsize=2.0, color="#0072B2", label=labels[0])
        ax.plot(x, reserve_values.RMSE, linestyle="none", marker="D", ms=3.8,
                color="#009E73", label=labels[1])
        ax.plot(x + 0.12, fixed.rmse, linestyle="none", marker="s", ms=4.0,
                markerfacecolor="white", markeredgewidth=0.9, markeredgecolor="#D55E00", label=labels[2])
        ax.set_title(SENSOR_NAMES[sensor], weight="bold")
        ax.set_xticks(x, display_windows, rotation=42, ha="right")
        ax.set_ylabel(labels[3])
        ax.grid(axis="y", color="0.82", lw=0.45, alpha=0.65)
        ax.set_axisbelow(True)
    handles = [
        Line2D([], [], color="#0072B2", marker="o", linestyle="none", markersize=4.0, label=labels[0]),
        Line2D([], [], color="#009E73", marker="D", linestyle="none", markersize=4.0, label=labels[1]),
        Line2D([], [], color="#D55E00", marker="s", markerfacecolor="white", linestyle="none",
               markersize=4.2, label=labels[2]),
    ]
    fig.legend(handles, [item.get_label() for item in handles], loc="upper center",
               bbox_to_anchor=(0.5, 1.01), ncol=3, frameon=False)
    fig.tight_layout(rect=(0, 0, 1, 0.90), pad=0.45, w_pad=0.75)
    for suffix in ("pdf", "png"):
        fig.savefig(SUPP_FIGURES / f"historical_spatial_reserve_comparison_{language}.{suffix}",
                    bbox_inches="tight", pad_inches=0.025, dpi=300)
    plt.close(fig)


def write_partition_figure(language: str) -> None:
    """Redraw the frozen partition without the legacy ``final test`` label."""
    data = pd.read_csv(OUT / "spatial_partition_all_sensors.csv")
    mpl.rcParams["font.family"] = "Arial Unicode MS" if language == "cn" else "DejaVu Sans"
    text = {
        "en": ("Diagnostic Development blocks", "Historical spatial reserve", "No valid samples",
               "Longitude", "Latitude (EPSG:4326)"),
        "cn": ("诊断开发块", "历史空间预留块", "无有效样本", "经度", "纬度（EPSG:4326）"),
    }[language]
    colors = {"development_blocks": "#72B7B2", "spatial_final_test_blocks": "#E45756",
              "no_valid_samples": "#D9D9D9"}
    transformer = Transformer.from_crs("EPSG:32647", "EPSG:4326", always_xy=True)
    fig, axes = plt.subplots(1, 3, figsize=(7.25, 2.55), sharex=True, sharey=True)
    for ax, sensor in zip(axes, base.SENSORS):
        subset = data[data.sensor == sensor]
        for row in subset.itertuples(index=False):
            x0 = row.grid_origin_x_m + row.block_column * row.block_size_m
            y0 = row.grid_origin_y_m + row.block_row * row.block_size_m
            xs = [x0, x0 + row.block_size_m, x0 + row.block_size_m, x0, x0]
            ys = [y0, y0, y0 + row.block_size_m, y0 + row.block_size_m, y0]
            lon, lat = transformer.transform(xs, ys)
            ax.fill(lon, lat, color=colors[row.spatial_role], edgecolor="white", lw=0.30, alpha=0.88)
        counts = subset.spatial_role.value_counts()
        ax.set_title(SENSOR_NAMES[sensor], weight="bold")
        ax.set_xlabel(text[3])
        ax.grid(color="0.84", lw=0.35, alpha=0.45)
        short = ("Dev", "Reserve") if language == "en" else ("开发块", "预留块")
        ax.text(0.5, 0.02,
                f"{short[0]} {counts.get('development_blocks', 0)}  |  {short[1]} {counts.get('spatial_final_test_blocks', 0)}",
                transform=ax.transAxes, ha="center", va="bottom", fontsize=5.8,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.86, "pad": 1.4})
    axes[0].set_ylabel(text[4])
    handles = [Patch(facecolor=colors["development_blocks"], label=text[0]),
               Patch(facecolor=colors["spatial_final_test_blocks"], label=text[1]),
               Patch(facecolor=colors["no_valid_samples"], label=text[2])]
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, 1.01), ncol=3, frameon=False, fontsize=7.2)
    fig.tight_layout(rect=(0, 0, 1, 0.88), pad=0.35, w_pad=0.45)
    for suffix in ("pdf", "png"):
        fig.savefig(SUPP_FIGURES / f"spatial_partition_all_sensors_{language}.{suffix}",
                    bbox_inches="tight", pad_inches=0.025, dpi=300)
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    SUPP_TABLES.mkdir(parents=True, exist_ok=True)
    SUPP_FIGURES.mkdir(parents=True, exist_ok=True)
    summary, blocks, assignments, integrity = evaluate()
    summary_path = OUT / "historical_spatial_reserve_metrics.csv"
    block_path = OUT / "historical_spatial_reserve_block_metrics.csv"
    assignment_path = OUT / "historical_spatial_reserve_block_assignments.csv"
    write_csv(summary_path, summary)
    write_csv(block_path, blocks)
    write_csv(assignment_path, assignments)
    integrity["output_sha256"] = {
        str(path.relative_to(REPORT)): base.sha(path)
        for path in (summary_path, block_path, assignment_path)
    }
    (OUT / "historical_spatial_reserve_manifest.json").write_text(
        json.dumps(integrity, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_latex_table(summary, "en")
    write_latex_table(summary, "cn")
    write_figure(summary, "en")
    write_figure(summary, "cn")
    write_partition_figure("en")
    write_partition_figure("cn")
    print(f"Wrote {len(summary)} sensor-window reserve diagnostics; integrity={integrity['all_partition_and_leakage_checks_pass']}")


if __name__ == "__main__":
    main()
