#!/usr/bin/env python3
"""
比较同一批参数在三个起点口径下的年化排名：

M1  full_2015 : 标准回测（2015-01 起，含 2015 空仓） annual_return
M2  since_2016: 标准回测中从首次建仓（2016-05）起算 annual_return_since_first_investment
M3  start_2015: 2015 首个截面跳过新股过滤后的回测 annual_return（2015-01 起）

用法::

    cd backtesting
    ../.venv/bin/python compare_three_metrics.py \
        --standard-root ../data/processed/backtesting/universe_compare_20261107_101219 \
        --start2015-root ../data/processed/backtesting/universe_compare_2015start_20261120
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)


def load(path: str) -> pd.DataFrame:
    frame = pd.read_csv(os.path.join(path, "summary.csv"))
    frame = frame[~frame["phase"].astype(str).str.startswith("val")].copy()
    return frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--standard-root", required=True)
    parser.add_argument("--start2015-root", required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    std = load(args.standard_root)
    y15 = load(args.start2015_root)

    std["key"] = std["id"]
    y15["key"] = y15["id"].str.replace(r"_2015start$", "", regex=True)

    merged = std.merge(
        y15[
            [
                "key", "annual_return", "annual_return_since_first_investment",
                "first_investment_date", "sharpe_ratio", "max_drawdown",
                "cagr_2021_2026",
            ]
        ],
        on="key",
        suffixes=("_std", "_2015"),
        how="inner",
    )
    merged = merged.rename(
        columns={
            "annual_return_std": "M1_full_2015",
            "annual_return_since_first_investment_std": "M2_since_2016",
            "annual_return_2015": "M3_start_2015",
            "annual_return_since_first_investment_2015": "M3b_since_2015",
            "sharpe_ratio_std": "sharpe_M1",
            "sharpe_ratio_2015": "sharpe_M3",
            "max_drawdown_std": "mdd_M1",
            "max_drawdown_2015": "mdd_M3",
        }
    )

    for metric in ["M1_full_2015", "M2_since_2016", "M3_start_2015"]:
        merged[f"rank_{metric}"] = merged[metric].rank(ascending=False)

    corr_12 = merged[["M1_full_2015", "M2_since_2016"]].corr(method="spearman").iloc[0, 1]
    corr_13 = merged[["M1_full_2015", "M3_start_2015"]].corr(method="spearman").iloc[0, 1]

    print(f"matched configs: {len(merged)}")
    print(f"Spearman M1 vs M2: {corr_12:.4f}")
    print(f"Spearman M1 vs M3: {corr_13:.4f}")

    cols = [
        "key", "filters", "ranking", "trim", "max_positions",
        "M1_full_2015", "M2_since_2016", "M3_start_2015", "M3b_since_2015",
    ]
    for metric in ["M1_full_2015", "M2_since_2016", "M3_start_2015"]:
        print(f"\n=== Top 8 by {metric} ===")
        print(
            merged.sort_values(metric, ascending=False)[cols]
            .head(8)
            .to_string(index=False)
        )

    if args.out:
        merged.to_csv(args.out, index=False)
        print(f"\nsaved -> {args.out}")


if __name__ == "__main__":
    main()
