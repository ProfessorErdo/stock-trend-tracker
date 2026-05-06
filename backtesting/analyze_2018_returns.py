"""
分析2018调仓日到2019调仓日的个股收益分布
"""

import os
import sys
import pickle
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from data_loader import load_stock_pool, load_financial_data

CUTOFF_2018 = "2018-04-27"
CUTOFF_2019 = "2019-04-30"


def main():
    with open(os.path.join(config.DATA_OUTPUT_DIR, "intermediate.pkl"), "rb") as f:
        intermediate = pickle.load(f)

    pool_df = load_stock_pool()
    stock_codes = pool_df["code"].tolist()
    price_cache = intermediate["price_cache"]

    cutoff_2018 = pd.Timestamp(CUTOFF_2018)
    cutoff_2019 = pd.Timestamp(CUTOFF_2019)

    rows = []
    for code in stock_codes:
        if code not in price_cache:
            continue
        df = price_cache[code]
        if df.empty:
            continue

        # Price at 2018 cutoff (or latest before)
        row_2018 = df[df["trade_date"] == cutoff_2018]
        if row_2018.empty:
            before = df[df["trade_date"] <= cutoff_2018]
            if before.empty:
                continue
            row_2018 = before.iloc[[-1]]

        # Price at 2019 cutoff (or latest before)
        row_2019 = df[df["trade_date"] == cutoff_2019]
        if row_2019.empty:
            before = df[df["trade_date"] <= cutoff_2019]
            if before.empty:
                continue
            row_2019 = before.iloc[[-1]]

        price_start = row_2018["close"].iloc[0]
        price_end = row_2019["close"].iloc[0]

        if price_start <= 0:
            continue

        ret = (price_end - price_start) / price_start * 100

        # PB at 2018 cutoff: price / bps_ttm (latest available report)
        fin_df = load_financial_data(code)
        pb = None
        if fin_df is not None and not fin_df.empty and "bps_ttm" in fin_df.columns:
            fin_df = fin_df.sort_values("report_date")
            available = fin_df[fin_df["ann_available_date"] <= cutoff_2018]
            if not available.empty:
                latest = available.iloc[-1]
                bps = latest.get("bps_ttm", np.nan)
                if pd.notna(bps) and bps > 0:
                    pb = price_start / bps

        rows.append({
            "code": code,
            "price_2018cutoff": round(price_start, 2),
            "price_2019cutoff": round(price_end, 2),
            "return_1yr": round(ret, 2),
            "pb_2018cutoff": round(pb, 2) if pb is not None else None,
        })

    result = pd.DataFrame(rows)
    print(f"Total stocks with price data: {len(result)}")

    # Sort by return descending
    result = result.dropna(subset=["return_1yr"])
    result = result.sort_values("return_1yr", ascending=False).reset_index(drop=True)

    # Save
    out_dir = os.path.join(config.DATA_OUTPUT_DIR, "pe_trend_test")
    out_csv = os.path.join(out_dir, "2018_2019_returns.csv")
    os.makedirs(out_dir, exist_ok=True)
    result.to_csv(out_csv, index=False)
    print(f"\nSaved CSV: {out_csv}")

    # Print top 20
    print(f"\n{'#':>3}  {'Code':>8}  {'Return':>10}  {'PB@2018':>10}")
    print("=" * 36)
    for i in range(min(20, len(result))):
        row = result.iloc[i]
        pb_str = f"{row['pb_2018cutoff']:.2f}" if pd.notna(row["pb_2018cutoff"]) else "N/A"
        print(f"{i+1:>3}  {row['code']:>8}  {row['return_1yr']:>+9.2f}%  {pb_str:>10}")

    print(f"\n... (total {len(result)} stocks) ...\n")

    print(f"{'#':>3}  {'Code':>8}  {'Return':>10}  {'PB@2018':>10}")
    print("=" * 36)
    for i in range(max(0, len(result)-20), len(result)):
        row = result.iloc[i]
        pb_str = f"{row['pb_2018cutoff']:.2f}" if pd.notna(row["pb_2018cutoff"]) else "N/A"
        print(f"{i+1:>3}  {row['code']:>8}  {row['return_1yr']:>+9.2f}%  {pb_str:>10}")

    # Scatter plot: PB vs 1yr return (use log scale on PB, cap extremes)
    fig, axes = plt.subplots(1, 2, figsize=(16, 5))

    for ax_idx, ax in enumerate(axes):
        valid = result[result["pb_2018cutoff"].notna()].copy()

        # Cap PB for display
        if ax_idx == 0:
            display = valid[valid["pb_2018cutoff"] <= 50].copy()
            title_suffix = " (PB<=50)"
        else:
            display = valid[valid["pb_2018cutoff"] <= 5].copy()
            title_suffix = " (PB<=5)"

        orig_holdings = {"000625", "601009", "000338", "600208", "600758"}
        is_orig = display["code"].isin(orig_holdings)
        orig = display[is_orig]
        other = display[~is_orig]

        ax.scatter(other["pb_2018cutoff"], other["return_1yr"],
                   s=15, alpha=0.4, color="steelblue")
        ax.scatter(orig["pb_2018cutoff"], orig["return_1yr"],
                   s=50, edgecolors="red", facecolors="none", linewidth=2)

        for _, row in orig.iterrows():
            ax.annotate(row["code"], (row["pb_2018cutoff"], row["return_1yr"]),
                        textcoords="offset points", xytext=(4, 3), fontsize=8, fontweight="bold", color="red")

        ax.axhline(y=0, color="gray", linewidth=0.8, linestyle="--", alpha=0.5)

        if ax_idx == 0:
            ax.set_xscale("log")

        r = np.corrcoef(display["pb_2018cutoff"], display["return_1yr"])[0, 1]
        ax.annotate(f"r={r:.3f}", xy=(0.98, 0.95), xycoords="axes fraction",
                    ha="right", va="top", fontsize=9, bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))

        ax.set_xlabel("PB @ 2018 Cutoff", fontsize=11)
        ax.set_ylabel("1-Year Return (%)", fontsize=11)
        ax.set_title(f"2018→2019 Return vs PB ({len(display)} stocks{title_suffix})", fontsize=12)
        ax.grid(True, alpha=0.2)

    # Legend for first subplot
    from matplotlib.patches import Patch, Circle
    handles = [
        Patch(color="steelblue", alpha=0.4, label="Other stocks"),
        Circle((0,0), 5, edgecolor="red", facecolor="none", linewidth=2, label="Original holdings"),
    ]
    axes[0].legend(handles=handles, fontsize=9, loc="lower right")

    out_path = os.path.join(out_dir, "2018_2019_return_vs_pb.png")
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    print(f"\nSaved plot: {out_path}")

    # Also save PB<=5 version as separate file
    fig2, ax2 = plt.subplots(figsize=(10, 6))
    valid5 = result[result["pb_2018cutoff"].notna() & (result["pb_2018cutoff"] <= 5)].copy()
    orig_holdings_set = {"000625", "601009", "000338", "600208", "600758"}
    is_orig5 = valid5["code"].isin(orig_holdings_set)
    orig5 = valid5[is_orig5]
    other5 = valid5[~is_orig5]

    ax2.scatter(other5["pb_2018cutoff"], other5["return_1yr"], s=15, alpha=0.5, color="steelblue")
    ax2.scatter(orig5["pb_2018cutoff"], orig5["return_1yr"],
                s=50, edgecolors="red", facecolors="none", linewidth=2)
    for _, row in orig5.iterrows():
        ax2.annotate(row["code"], (row["pb_2018cutoff"], row["return_1yr"]),
                     textcoords="offset points", xytext=(6, 4), fontsize=9, fontweight="bold", color="red")
    ax2.axhline(y=0, color="gray", linewidth=0.8, linestyle="--", alpha=0.5)
    r5 = np.corrcoef(valid5["pb_2018cutoff"], valid5["return_1yr"])[0, 1]
    ax2.annotate(f"Correlation: r={r5:.3f}", xy=(0.98, 0.95), xycoords="axes fraction",
                 ha="right", va="top", fontsize=10, bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))
    ax2.set_xlabel("PB @ 2018 Cutoff", fontsize=12)
    ax2.set_ylabel("1-Year Return (%)", fontsize=12)
    ax2.set_title(f"2018→2019 Return vs PB ({len(valid5)} stocks, PB<=5)", fontsize=13)
    ax2.grid(True, alpha=0.2)

    out_path2 = os.path.join(out_dir, "2018_2019_return_vs_pb_zoom.png")
    plt.tight_layout()
    plt.savefig(out_path2, dpi=150)
    print(f"Saved zoom plot: {out_path2}")

    # Return stats
    print(f"\nReturn distribution ({len(result)} stocks):")
    print(f"  Mean:   {result['return_1yr'].mean():.1f}%")
    print(f"  Median: {result['return_1yr'].median():.1f}%")
    print(f"  Min:    {result['return_1yr'].min():.1f}%")
    print(f"  Max:    {result['return_1yr'].max():.1f}%")
    print(f"  Positive: {(result['return_1yr'] > 0).sum()} ({(result['return_1yr'] > 0).mean():.0%})")


if __name__ == "__main__":
    main()
