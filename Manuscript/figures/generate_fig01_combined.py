"""Regenerate Figure 1 from its archived layout with terminology calibrated for submission.

This presentation-only source neither reads nor changes experimental results.
"""
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch


OUT = Path(__file__).with_name("fig01_combined.pdf")
mpl.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8.0, "pdf.fonttype": 42})


def box(ax, x, y, w, h, label, color):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.01,rounding_size=0.012",
                                facecolor=color, edgecolor="#475569", linewidth=0.8))
    ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", fontsize=7.0, linespacing=1.08)


def main():
    centers = {
        "AOI-00": (99.51, 38.04), "AOI-01": (93.50, 36.50),
        "AOI-02": (95.60, 32.90), "AOI-03": (97.20, 35.70),
    }
    fig = plt.figure(figsize=(7.25, 3.25))
    grid = fig.add_gridspec(1, 2, width_ratios=(0.82, 1.58), wspace=0.15)
    map_ax, flow_ax = fig.add_subplot(grid[0, 0]), fig.add_subplot(grid[0, 1])
    map_ax.set_facecolor("#F7FAFC")
    for aoi, (lon, lat) in centers.items():
        map_ax.scatter(lon, lat, s=43, color="#246A73", edgecolor="white", linewidth=0.8, zorder=3)
        offset = (4, 4) if aoi != "AOI-02" else (4, -12)
        map_ax.annotate(aoi, (lon, lat), xytext=offset, textcoords="offset points", fontsize=6.5)
    map_ax.set(xlim=(92.4, 100.8), ylim=(31.9, 39.0), xlabel="Longitude (degrees E)", ylabel="Latitude (degrees N)")
    map_ax.grid(color="#CBD5E1", linewidth=0.45, alpha=0.8)
    map_ax.set_title("A  Selected AOIs", loc="left", weight="bold")

    flow_ax.set(xlim=(0, 1), ylim=(0, 1)); flow_ax.axis("off")
    upper = [
        (0.01, 0.68, 0.16, 0.15, "Native SR\n+ QA", "#E8F1F8"),
        (0.21, 0.68, 0.15, 0.15, "Native-grid\nNDVI", "#E8F1F8"),
        (0.40, 0.68, 0.22, 0.15, "Mask-aware mean\nto FCOVER grid", "#E6F4EA"),
        (0.66, 0.68, 0.17, 0.15, "$\\pm$15 d\nmedian", "#E6F4EA"),
        (0.87, 0.68, 0.12, 0.15, "300 m\npairs", "#E6F4EA"),
    ]
    for node in upper: box(flow_ax, *node)
    arrow = {"arrowstyle": "-|>", "lw": 0.8, "color": "#475569", "shrinkA": 2, "shrinkB": 2}
    for left, right in zip(upper[:-1], upper[1:]):
        flow_ax.annotate("", xy=(right[0], right[1] + right[3] / 2), xytext=(left[0] + left[2], left[1] + left[3] / 2), arrowprops=arrow)
    lower = [
        (0.01, 0.22, 0.22, 0.20, "NDVI-based DPM\ncomparator", "#FFF2CC"),
        (0.265, 0.22, 0.22, 0.20, "Spatial/LOYO\ndiagnostics", "#FFF2CC"),
        (0.52, 0.22, 0.22, 0.20, "Multi-AOI\n2025 target", "#FDE2E2"),
        (0.775, 0.22, 0.22, 0.20, "Rolling-Origin\n2024/2025", "#FDE2E2"),
    ]
    for node in lower:
        box(flow_ax, *node)
        flow_ax.annotate("", xy=(node[0] + node[2] / 2, node[1] + node[3]), xytext=(0.93, 0.68), arrowprops=arrow)
    flow_ax.set_title("B  Common-target-grid design", loc="left", weight="bold")
    flow_ax.text(0.5, 0.06, "5 km blocks; consistent analysis configuration; OLS refitted by history",
                 ha="center", fontsize=6.8, color="#7C2D12")
    fig.subplots_adjust(left=0.07, right=0.995, top=0.91, bottom=0.18)
    fig.savefig(OUT, bbox_inches="tight", pad_inches=0.03)


if __name__ == "__main__":
    main()
