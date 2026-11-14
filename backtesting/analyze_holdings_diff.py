#!/usr/bin/env python3
"""
对比 2026 年调仓后两套持仓的走势（932 池，等权持有）：
  A：原始阈值 -> 成都/杭州/人保/太保/东航物流
  B：裁尾 1%  -> 成都/杭州/人保/太保/常熟银行

直接用回测引擎已经算好的净值曲线（含买入成本），从 2026-05-06 归一到 1。
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
sys.path.insert(0, BASE_DIR)

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RUNS = {
    "A: raw thresholds (holds Eastern Air)": (
        "trim_legacy_annual_pe+pb+pr_pb_raw_N5_pe0.25-pb0.25-pr0.25-roe0.75"
    ),
    "B: 1% trim (holds Changshu Bank)": (
        "core_legacy_annual_pe_pb_trim1pct_N5_pe0.25-pb0.25-pr0.25-roe0.75"
    ),
}

STOCKS = {
    "601156": "601156 Eastern Air Logistics",
    "601838": "601838 Bank of Chengdu",
    "601319": "601319 PICC",
    "600926": "600926 Bank of Hangzhou",
    "601128": "601128 Changshu Bank",
    "601601": "601601 CPIC",
}

START = pd.Timestamp("2026-05-06")
END = pd.Timestamp("2026-11-06")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-root",
        default=os.path.join(
            PROJECT_DIR,
            "data",
            "processed",
            "backtesting",
            "universe_compare_legacy932_20261107",
        ),
    )
    parser.add_argument(
        "--out-dir",
        default=os.path.join(PROJECT_DIR, "docs", "img", "universe-backtest-932-2026-11"),
    )
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    # 1) 净值曲线
    curves = {}
    for label, run_id in RUNS.items():
        eq = pd.read_csv(
            os.path.join(args.run_root, "runs", run_id, "equity_curve.csv"),
            parse_dates=["date"],
        )
        seg = eq[eq["date"] >= START].copy().reset_index(drop=True)
        seg["norm"] = seg["strategy_equity"] / seg["strategy_equity"].iloc[0]
        curves[label] = seg

    daily = pd.DataFrame({"date": curves[list(curves)[0]]["date"]})
    for label, seg in curves.items():
        daily[label] = seg["norm"].to_numpy()
    daily.to_csv(os.path.join(args.out_dir, "holdings_compare_since_20260506.csv"), index=False)

    fig, axes = plt.subplots(
        2, 1, figsize=(10, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1.2]}
    )
    for (label, seg), color in zip(curves.items(), ["#C44E52", "#4C72B0"]):
        total = (seg["norm"].iloc[-1] - 1) * 100
        axes[0].plot(
            seg["date"], seg["norm"], lw=1.8, color=color,
            label=f"{label}  ({total:+.2f}%)",
        )
        dd = seg["norm"] / seg["norm"].cummax() - 1
        axes[1].plot(
            seg["date"], dd * 100, lw=1.2, color=color,
            label=f"{label.split(':')[0]} (min {dd.min()*100:.1f}%)",
        )
    axes[0].axhline(1, color="grey", lw=0.8, ls=":")
    axes[0].set_ylabel("Net value (2026-05-06 = 1.0)")
    axes[0].set_title("Post-rebalance: 932 pool, equal weight, 2026-05-06 to 2026-11-06")
    axes[0].grid(alpha=0.3)
    axes[0].legend(fontsize=9, loc="upper left")
    axes[1].axhline(0, color="grey", lw=0.8, ls=":")
    axes[1].set_ylabel("Drawdown (%)")
    axes[1].grid(alpha=0.3)
    axes[1].legend(fontsize=8, loc="lower left")
    fig.tight_layout()
    fig.savefig(os.path.join(args.out_dir, "holdings_compare_since_20260506.png"), dpi=160)
    plt.close(fig)

    # 2) 个股收益
    rows = []
    for code, name in STOCKS.items():
        price = pd.read_csv(
            os.path.join(
                PROJECT_DIR, "data", "input", "backtesting", "price", f"price_{code}.csv"
            ),
            parse_dates=["trade_date"],
        )
        first = price[price["trade_date"] == START].iloc[0]
        last = price[price["trade_date"] == END].iloc[0]
        rows.append({"code": code, "name": name, "hfq_return": last["close"] / first["close"] - 1})
    returns = pd.DataFrame(rows).sort_values("hfq_return")
    returns.to_csv(os.path.join(args.out_dir, "holdings_stock_returns_since_20260506.csv"), index=False)

    colors = [
        "#C44E52" if c == "601156" else "#4C72B0" if c == "601128" else "#9e9e9e"
        for c in returns["code"]
    ]
    fig, ax = plt.subplots(figsize=(8.5, 4.2))
    bars = ax.barh(returns["name"], returns["hfq_return"] * 100, color=colors)
    for bar, value in zip(bars, returns["hfq_return"] * 100):
        ax.text(
            value + (0.6 if value >= 0 else -0.6),
            bar.get_y() + bar.get_height() / 2,
            f"{value:+.1f}%",
            va="center",
            ha="left" if value >= 0 else "right",
            fontsize=9,
        )
    ax.axvline(0, color="black", lw=0.8)
    ax.set_xlim(returns["hfq_return"].min() * 100 - 5, returns["hfq_return"].max() * 100 + 5)
    ax.set_xlabel("Return since 2026-05-06 (%, HFQ)")
    ax.set_title("Holdings since rebalance: Eastern Air (red) vs Changshu (blue)")
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(args.out_dir, "holdings_stock_returns_since_20260506.png"), dpi=160)
    plt.close(fig)

    for label, seg in curves.items():
        dd = seg["norm"] / seg["norm"].cummax() - 1
        print(
            f"{label}: return={(seg['norm'].iloc[-1]-1)*100:+.2f}% "
            f"mdd={dd.min()*100:.2f}% days={len(seg)}"
        )
    print(returns.to_string(index=False))


if __name__ == "__main__":
    main()
