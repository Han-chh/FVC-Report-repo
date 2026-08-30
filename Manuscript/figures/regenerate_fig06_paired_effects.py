#!/usr/bin/env python3
"""Regenerate Figure 4/6 from the existing paired-test output without rerunning analysis."""

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D


HERE = Path(__file__).resolve().parent
TESTS = HERE.parent / "repo" / "Data" / "Results" / "03_rolling_origin_results" / "ROLLING_ORIGIN_PAIRED_TESTS.csv"
OUTPUT = HERE / "fig06_paired_effects.pdf"
SENSORS = ("sentinel2", "landsat", "modis")
SENSOR_SHORT = {"sentinel2": "Sentinel-2", "landsat": "Landsat", "modis": "MODIS"}
AOIS = ("AOI-00", "AOI-01", "AOI-02", "AOI-03")

mpl.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 8.0,
        "axes.titlesize": 8.8,
        "axes.labelsize": 8.2,
        "xtick.labelsize": 7.2,
        "ytick.labelsize": 7.2,
        "legend.fontsize": 7.0,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)


def main() -> None:
    tests = pd.read_csv(TESTS)
    contrast_order = ("1y_vs_2y", "1y_vs_3y", "2y_vs_3y")
    label_map = {"1y_vs_2y": "H1-H2", "1y_vs_3y": "H1-H3", "2y_vs_3y": "H2-H3"}
    order = [(aoi, target, contrast) for aoi in AOIS for target in (2024, 2025) for contrast in contrast_order]
    labels = [f"{aoi[-2:]}/{str(target)[-2:]} {label_map[contrast]}" for aoi, target, contrast in order]
    y = np.arange(len(order))
    max_abs = float(np.abs(tests.mean_difference_RMSE).max()) * 1.08

    fig, axes = plt.subplots(1, 3, figsize=(7.25, 6.25), sharex=True)
    for ax, sensor in zip(axes, SENSORS):
        subset = tests[tests.sensor == sensor].set_index(["AOI", "target_year", "contrast"]).loc[order]
        supported = subset.significant.astype(bool).to_numpy()
        values = subset.mean_difference_RMSE.to_numpy()
        colors = np.where(values >= 0, "#0072B2", "#D55E00")
        ax.axvline(0, color="#334155", lw=0.8)
        ax.scatter(values[~supported], y[~supported], s=23, facecolor="white", edgecolor=colors[~supported], linewidth=0.9)
        ax.scatter(values[supported], y[supported], s=25, facecolor=colors[supported], edgecolor=colors[supported], linewidth=0.8)
        ax.set_title(SENSOR_SHORT[sensor], weight="bold")
        ax.set_xlim(-max_abs, max_abs)
        ax.grid(axis="x", color="#CBD5E1", lw=0.45)
        ax.set_xlabel("Paired mean $\\Delta$RMSE\n(left - right)")
        ax.set_yticks(y, labels if ax is axes[0] else [])
        ax.invert_yaxis()

    handles = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#0072B2", markeredgecolor="#0072B2", label="Holm-supported, longer-window lower error"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#D55E00", markeredgecolor="#D55E00", label="Holm-supported, longer-window higher error"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="white", markeredgecolor="#64748B", label="Not Holm-supported"),
    ]
    fig.legend(handles=handles, frameon=False, ncol=1, loc="upper center", bbox_to_anchor=(0.5, 1.01))
    fig.tight_layout(rect=(0, 0, 1, 0.88), pad=0.25, w_pad=0.55)
    fig.savefig(OUTPUT, bbox_inches="tight", pad_inches=0.03)
    plt.close(fig)


if __name__ == "__main__":
    main()
