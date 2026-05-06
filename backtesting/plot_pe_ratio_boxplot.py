"""
Box plot: 按 PE_ratio 分三组，观察 1-year return 分布
"""

import os
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config


def main():
    csv_path = os.path.join(config.DATA_OUTPUT_DIR, "pe_trend_test", "pe_analysis.csv")
    df = pd.read_csv(csv_path)

    valid = df[df["pe_ratio"] != "N/A"].copy()
    valid["pe_ratio"] = valid["pe_ratio"].astype(float)
    valid["price_1yr_return"] = pd.to_numeric(valid["price_1yr_return"], errors="coerce")
    valid = valid.dropna(subset=["price_1yr_return"])

    # Exclude 2026 (no forward data yet)
    valid = valid[valid["year"] != 2026]

    # Split into 3 groups by PE_ratio terciles
    _, bins = pd.qcut(valid["pe_ratio"], q=3, retbins=True)
    group_names = ["Low", "Mid", "High"]
    valid["group"] = pd.cut(valid["pe_ratio"], bins=bins, labels=group_names)

    # Prepare data per group
    groups = []
    for name in group_names:
        grp = valid[valid["group"] == name]["price_1yr_return"].dropna()
        groups.append(grp.values)

    fig, ax = plt.subplots(figsize=(9, 6))
    bp = ax.boxplot(groups, labels=group_names, patch_artist=True,
                    showmeans=True, meanprops={"marker": "D", "markerfacecolor": "red", "markersize": 7},
                    medianprops={"color": "black", "linewidth": 1.5})

    colors = ["#e74c3c", "#2ecc71", "#3498db"]
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)

    ax.set_ylabel("1-Year Price Return (%)", fontsize=12)
    ax.set_xlabel("PE_ratio Group", fontsize=12)
    ax.set_title("1-Year Return by PE_ratio Group", fontsize=13)
    ax.axhline(y=0, color="gray", linewidth=0.8, linestyle="--", alpha=0.5)
    ax.grid(True, alpha=0.2, axis="y")

    # Annotate stats on each box
    for i, (name, grp) in enumerate(valid.groupby("group")):
        vals = grp["price_1yr_return"]
        pe_lo = grp["pe_ratio"].min()
        pe_hi = grp["pe_ratio"].max()
        y_pos = ax.get_ylim()[1] * 0.9
        ax.text(i + 1, y_pos,
                f"n={len(vals)}  mean={vals.mean():.1f}%\n"
                f"med={vals.median():.1f}%  +={(vals > 0).mean():.0%}\n"
                f"PE=[{pe_lo:.3f}, {pe_hi:.3f}]",
                ha="center", fontsize=8, fontweight="bold")

    out_path = os.path.join(config.DATA_OUTPUT_DIR, "pe_trend_test", "pe_ratio_boxplot.png")
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    print(f"Saved: {out_path}")

    # Print summary
    print("\n" + "=" * 60)
    print(f"{'Group':<8} {'n':>3} {'Mean':>8} {'Median':>8} {'Win%':>6} {'PE range':>18}")
    print("-" * 60)
    for name in group_names:
        grp = valid[valid["group"] == name]
        vals = grp["price_1yr_return"]
        pe_lo = grp["pe_ratio"].min()
        pe_hi = grp["pe_ratio"].max()
        print(f"{name:<8} {len(vals):>3} {vals.mean():>7.1f}% {vals.median():>7.1f}% {(vals > 0).mean():>5.0%} [{pe_lo:.3f}, {pe_hi:.3f}]")
    print("=" * 60)


if __name__ == "__main__":
    main()
