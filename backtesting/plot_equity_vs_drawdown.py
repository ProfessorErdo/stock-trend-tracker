"""
画出净值曲线 + 回撤曲线，左右对比
"""

import os
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config


def main():
    output_dir = os.path.join(config.DATA_OUTPUT_DIR, "pe_trend_test")
    path = os.path.join(output_dir, "original_equity.csv")
    df = pd.read_csv(path)
    dates = pd.to_datetime(df["date"])
    equity = df["strategy_equity"].values
    bench = df["benchmark_equity"].values

    running_max = np.maximum.accumulate(equity)
    drawdown = (equity - running_max) / running_max * 100

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)

    # Top: equity curve
    ax1 = axes[0]
    ax1.plot(dates, equity / 1e4, label="Strategy", color="#1f77b4", linewidth=1.2)
    ax1.plot(dates, bench / 1e4, label="Benchmark", color="#d62728", linewidth=1.0, alpha=0.6)
    ax1.set_ylabel("Equity (万元)", fontsize=11)
    ax1.set_title("净值曲线 vs 基准（原始策略）", fontsize=12)
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.2)

    # Mark rebalance dates (roughly April each year)
    for year in range(2016, 2027):
        ax1.axvline(pd.Timestamp(year, 5, 1), color="gray", linestyle=":", alpha=0.3, linewidth=0.5)

    # Bottom: drawdown
    ax2 = axes[1]
    ax2.plot(dates, drawdown, color="#1f77b4", linewidth=1.0)
    ax2.fill_between(dates, drawdown, 0, color="red", alpha=0.1)
    ax2.axhline(y=0, color="black", linewidth=0.5)
    ax2.set_ylabel("Drawdown (%)", fontsize=11)
    ax2.set_xlabel("Date", fontsize=11)
    ax2.set_title("回撤曲线（距离历史最高点）", fontsize=12)
    ax2.grid(True, alpha=0.2)
    ax2.set_ylim(bottom=min(drawdown.min(), -45))

    plt.tight_layout()
    out_path = os.path.join(output_dir, "equity_vs_drawdown.png")
    plt.savefig(out_path, dpi=150)
    print(f"Saved: {out_path}")

    # Print explanation
    total_days = len(dates)
    above_zero_days = (drawdown == 0).sum()
    print(f"\n总交易日: {total_days}")
    print(f"处于历史最高点（回撤=0）的天数: {above_zero_days} ({above_zero_days/total_days:.1%})")
    print(f"净值从 {equity[0]:,.0f} → {equity[-1]:,.0f}，累计收益 {(equity[-1]/equity[0]-1)*100:.1f}%")


if __name__ == "__main__":
    main()
