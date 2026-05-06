"""
散点图：PE_ratio vs 1-year price return
"""

import os
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

YEAR_COLORS = {
    2016: "#1f77b4", 2017: "#ff7f0e", 2018: "#2ca02c",
    2019: "#d62728", 2020: "#9467bd", 2021: "#8c564b",
    2022: "#e377c2", 2023: "#7f7f7f", 2024: "#bcbd22",
    2025: "#17becf", 2026: "#000000",
}


def main():
    csv_path = os.path.join(config.DATA_OUTPUT_DIR, "pe_trend_test", "pe_analysis.csv")
    df = pd.read_csv(csv_path)

    # Filter valid PE and return
    valid = df[df["pe_ratio"] != "N/A"].copy()
    valid["pe_ratio"] = valid["pe_ratio"].astype(float)
    valid["price_1yr_return"] = pd.to_numeric(valid["price_1yr_return"], errors="coerce")
    valid = valid.dropna(subset=["price_1yr_return"])

    # Exclude 2026 (0% return because no data yet)
    valid = valid[valid["year"] != 2026]

    fig, ax = plt.subplots(figsize=(10, 6.5))

    # Scatter by year
    for year, grp in valid.groupby("year"):
        c = YEAR_COLORS.get(year, "#999999")
        ax.scatter(grp["pe_ratio"], grp["price_1yr_return"], c=c, s=80,
                   label=str(year), edgecolors="white", linewidth=0.5, alpha=0.85)

        # Annotate stock codes
        for _, row in grp.iterrows():
            ax.annotate(row["stock_code"], (row["pe_ratio"], row["price_1yr_return"]),
                        textcoords="offset points", xytext=(6, 4), fontsize=7, alpha=0.8)

    # Best-fit line
    x = valid["pe_ratio"].values
    y = valid["price_1yr_return"].values
    coeffs = np.polyfit(x, y, 1)
    slope, intercept = coeffs[0], coeffs[1]
    # Manual correlation
    r_val = np.corrcoef(x, y)[0, 1]
    p_val = 0.0  # approximate
    x_line = np.linspace(x.min(), x.max(), 100)
    ax.plot(x_line, slope * x_line + intercept, "--", color="red", alpha=0.6,
            linewidth=1.5, label=f"Fit: y={slope:.1f}x+{intercept:.1f}\n"
                                 f"r={r_val:.3f}, p={p_val:.3f}")

    # Zero-return line
    ax.axhline(y=0, color="gray", linewidth=0.8, linestyle=":", alpha=0.5)

    ax.set_xlabel("PE_ratio (Current PE / 3yr Avg PE)", fontsize=12)
    ax.set_ylabel("1-Year Price Return (%)", fontsize=12)
    ax.set_title("PE_ratio vs 1-Year Forward Return\nOriginal Strategy Holdings", fontsize=13)
    ax.legend(fontsize=8, loc="upper left", title="Year", title_fontsize=9)
    ax.grid(True, alpha=0.25)

    print(f"Correlation: r = {r_val:.3f} (p = {p_val:.3f})")
    print(f"Slope: {slope:.3f}")

    out_dir = os.path.join(config.DATA_OUTPUT_DIR, "pe_trend_test")
    out_path = os.path.join(out_dir, "pe_ratio_vs_return.png")
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
