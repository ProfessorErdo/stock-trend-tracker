#!/usr/bin/env python3
"""
给 universe_compare 的 summary.csv 补充“首次建仓以来”的年化指标。

回测净值曲线和交易记录都已经落盘，因此不需要重跑回测；直接从
runs/<id>/equity_curve.csv + trades_record.csv 重算即可。

用法::

    cd backtesting
    ../.venv/bin/python enrich_summary_metrics.py \
        --output-root ../data/processed/backtesting/universe_compare_20261107_101219
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from performance import compute_since_first_investment  # noqa: E402


def enrich(output_root: str) -> pd.DataFrame:
    summary_path = os.path.join(output_root, "summary.csv")
    summary = pd.read_csv(summary_path)

    metrics = []
    for run_id in summary["id"]:
        run_dir = os.path.join(output_root, "runs", run_id)
        equity_path = os.path.join(run_dir, "equity_curve.csv")
        trades_path = os.path.join(run_dir, "trades_record.csv")
        if not os.path.exists(equity_path):
            metrics.append({})
            continue
        equity = pd.read_csv(equity_path, parse_dates=["date"])
        trades = (
            pd.read_csv(trades_path).to_dict("records")
            if os.path.exists(trades_path)
            else []
        )
        metrics.append(compute_since_first_investment(equity, trades))

    extra = pd.DataFrame(metrics, index=summary.index)
    for column in extra.columns:
        summary[column] = extra[column]

    summary.to_csv(summary_path, index=False)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    summary = enrich(args.output_root)
    print(f"enriched {len(summary)} rows -> {os.path.join(args.output_root, 'summary.csv')}")
    cols = [
        "id", "annual_return", "annual_return_since_first_investment",
        "first_investment_date", "trading_days_since_first_investment",
    ]
    print(summary[cols].head(5).to_string(index=False))


if __name__ == "__main__":
    main()
