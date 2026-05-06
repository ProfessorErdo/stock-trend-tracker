"""
对比四种策略的回撤曲线
"""

import os
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config


def calc_drawdown(equity_df):
    equity = equity_df["strategy_equity"].values
    running_max = np.maximum.accumulate(equity)
    drawdown = (equity - running_max) / running_max * 100
    return pd.to_datetime(equity_df["date"]), drawdown


def main():
    output_dir = os.path.join(config.DATA_OUTPUT_DIR, "pe_trend_test")

    files = {
        "Original (11.37%)": "original_equity.csv",
        "PE_3yr (8.94%)": "pe_trend_3yr_equity.csv",
        "PE_2yr (10.06%)": "pe_trend_2yr_equity.csv",
        "PE_1yr (9.26%)": "pe_trend_1yr_equity.csv",
    }

    dd_results = {}
    for name, fname in files.items():
        path = os.path.join(output_dir, fname)
        if not os.path.exists(path):
            print(f"  Missing: {fname}")
            continue
        df = pd.read_csv(path)
        dates, dd = calc_drawdown(df)
        dd_results[name] = (dates, dd)

    fig, ax = plt.subplots(figsize=(12, 5))
    colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]

    max_dd_info = {}
    for i, (name, (dates, dd)) in enumerate(dd_results.items()):
        c = colors[i]
        ax.plot(dates, dd, label=name, color=c, linewidth=1.2)
        max_dd = dd.min()
        max_dd_info[name] = max_dd

    ax.axhline(y=0, color="black", linewidth=0.5)
    ax.set_ylabel("Drawdown (%)", fontsize=12)
    ax.set_xlabel("Date", fontsize=12)
    ax.set_title("Drawdown Comparison: Four PE_ratio Configurations", fontsize=13)
    ax.legend(fontsize=9, loc="lower left")
    ax.grid(True, alpha=0.2)

    # Zero line shading
    y_min = ax.get_ylim()[0]
    ax.axhspan(y_min, 0, color="red", alpha=0.03, zorder=0)

    out_path = os.path.join(output_dir, "drawdown_comparison.png")
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    print(f"Saved: {out_path}")

    # Print summary table
    print(f"\n{'Strategy':<22} {'Max DD':>10} {'Days < -10%':>14} {'Days < -20%':>14}")
    print("-" * 62)
    for name, (dates, dd) in dd_results.items():
        max_dd = dd.min()
        dd10 = int((dd < -10).sum())
        dd20 = int((dd < -20).sum())
        print(f"{name:<22} {max_dd:>9.1f}%   {dd10:>10}   {dd20:>10}")

    # Recovery time: how long from peak to recovery after max DD
    print(f"\n{'Strategy':<22} {'Max DD Date':>14} {'Recovery Date':>16} {'Recovery Days':>16}")
    print("-" * 70)
    for name, (dates, dd) in dd_results.items():
        max_dd_idx = dd.argmin()
        max_dd_date = dates.values[max_dd_idx]
        after_dd = dd[max_dd_idx:]
        recovered = (after_dd >= 0)
        if recovered.any():
            rec_offset = np.where(recovered)[0][0]
            rec_date = dates.values[max_dd_idx + rec_offset]
            days = (pd.Timestamp(rec_date) - pd.Timestamp(max_dd_date)).days
            print(f"{name:<22} {pd.Timestamp(max_dd_date).strftime('%Y-%m-%d'):>14} {pd.Timestamp(rec_date).strftime('%Y-%m-%d'):>16} {days:>12}")
        else:
            print(f"{name:<22} {pd.Timestamp(max_dd_date).strftime('%Y-%m-%d'):>14} {'(not recovered)':>16} {'—':>12}")


if __name__ == "__main__":
    main()
