#!/usr/bin/env python3
"""
合并 1052 / 932 两个股票池、标准 / 2015-start 两套回测，输出统一的
M1 / M2 / M3 / M3b 横向对比表。

M1  = 标准回测 annual_return（2015-01 起，含 2015 空仓）
M2  = 标准回测 annual_return_since_first_investment（2016-05 起）
M3  = 2015-start 回测 annual_return（2015-01 起，2015-05 建仓）
M3b = 2015-start 回测 annual_return_since_first_investment（2015-05 起）

用法::

    cd backtesting
    ../.venv/bin/python build_consolidated_metrics.py
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
sys.path.insert(0, BASE_DIR)

DEFAULT_ROOTS = {
    "1052_std": "data/processed/backtesting/universe_compare_20261107_101219",
    "1052_2015": "data/processed/backtesting/universe_compare_2015start_20261120",
    "932_std": "data/processed/backtesting/universe_compare_legacy932_20261107",
    "932_2015": "data/processed/backtesting/universe_compare_legacy932_2015start_20261120",
}


def load_summary(root: str, pool: str) -> pd.DataFrame:
    frame = pd.read_csv(os.path.join(PROJECT_DIR, root, "summary.csv"))
    frame = frame[frame["pool"] == pool].copy()
    frame = frame[~frame["phase"].astype(str).str.startswith("val")].copy()
    return frame


def load_annual(root: str, run_id: str) -> pd.DataFrame | None:
    path = os.path.join(PROJECT_DIR, root, "runs", run_id, "annual_returns.csv")
    if not os.path.exists(path):
        return None
    return pd.read_csv(path)


def build_pair(std: pd.DataFrame, y15: pd.DataFrame, pool_name: str, std_root: str, y15_root: str) -> pd.DataFrame:
    std = std.copy()
    y15 = y15.copy()
    std["key"] = std["id"]
    y15["key"] = y15["id"].str.replace(r"_2015start$", "", regex=True)

    merged = std.merge(
        y15[
            [
                "key", "annual_return", "annual_return_since_first_investment",
                "sharpe_ratio", "max_drawdown", "id",
            ]
        ],
        on="key",
        suffixes=("_std", "_2015"),
        how="inner",
    )
    merged["pool"] = pool_name

    rows = []
    for _, row in merged.iterrows():
        std_id = row["id_std"]
        y15_id = row["id_2015"]
        std_ar = load_annual(std_root, std_id)
        y15_ar = load_annual(y15_root, y15_id)
        y2015 = y2016 = None
        if y15_ar is not None:
            s = y15_ar.set_index("year")["strategy_return"]
            y2015 = float(s.get(2015)) if 2015 in s.index else None
            y2016 = float(s.get(2016)) if 2016 in s.index else None
        rows.append(
            {
                "pool": pool_name,
                "key": row["key"],
                "phase": row["phase"],
                "filters": row["filters"],
                "ranking": row["ranking"],
                "trim": str(row["trim"]),
                "max_positions": row["max_positions"],
                "pe_thr": row["pe_thr"],
                "pb_thr": row["pb_thr"],
                "pr_thr": row["pr_thr"],
                "roe_thr": row["roe_thr"],
                "M1": row["annual_return_std"],
                "M2": row["annual_return_since_first_investment_std"],
                "M3": row["annual_return_2015"],
                "M3b": row["annual_return_since_first_investment_2015"],
                "M1_sharpe": row["sharpe_ratio_std"],
                "M3_sharpe": row["sharpe_ratio_2015"],
                "M1_mdd": row["max_drawdown_std"],
                "M3_mdd": row["max_drawdown_2015"],
                "M3_2015_return": y2015,
                "M3_2016_return": y2016,
                "std_id": std_id,
                "y15_id": y15_id,
            }
        )
    return pd.DataFrame(rows)


def key_configs(consolidated: pd.DataFrame) -> pd.DataFrame:
    wanted = [
        ("1052 最佳：PB15/ROE70/PE/1%/N5", "1052", "pb", "pe", "0.01", 5, 0.15, 0.70),
        ("932 最佳：PE25/ROE75/PB/1%/N5", "932", "pe", "pb", "0.01", 5, 0.25, 0.75),
        ("经典 1%：PE+PB+PR/PB/1%/N5", "both", "pe+pb+pr", "pb", "0.01", 5, 0.25, 0.75),
        ("经典 2%：PE+PB+PR/PB/2%/N5", "both", "pe+pb+pr", "pb", "0.02", 5, 0.25, 0.75),
        ("经典 raw：PE+PB+PR/PB/raw/N5", "both", "pe+pb+pr", "pb", "raw", 5, 0.25, 0.75),
    ]
    rows = []
    for label, pool_filter, filters, ranking, trim, n, pb_thr, roe in wanted:
        subset = consolidated[
            (consolidated["filters"] == filters)
            & (consolidated["ranking"] == ranking)
            & (consolidated["trim"] == trim)
            & (consolidated["max_positions"] == n)
            & (consolidated["pb_thr"] == pb_thr)
            & (consolidated["roe_thr"] == roe)
        ]
        subset = subset.drop_duplicates(subset=["pool"])
        for _, row in subset.iterrows():
            rows.append(
                {
                    "配置": label,
                    "池子": row["pool"],
                    "M1": row["M1"],
                    "M2": row["M2"],
                    "M3": row["M3"],
                    "M3b": row["M3b"],
                    "M1 夏普": row["M1_sharpe"],
                    "M3 夏普": row["M3_sharpe"],
                    "M1 回撤": row["M1_mdd"],
                    "M3 回撤": row["M3_mdd"],
                    "2015(M3)": row["M3_2015_return"],
                    "2016(M3)": row["M3_2016_return"],
                }
            )
    return pd.DataFrame(rows)


ANNUAL_PHASES = {"core", "trim", "positions", "threshold", "refine"}


def best_by_metric(consolidated: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for metric in ["M1", "M2", "M3", "M3b"]:
        for pool in ["1052", "932"]:
            sub = consolidated[
                (consolidated["pool"] == pool)
                & (consolidated["phase"].isin(ANNUAL_PHASES))
            ].dropna(subset=[metric])
            if sub.empty:
                continue
            row = sub.loc[sub[metric].idxmax()]
            rows.append(
                {
                    "指标": metric,
                    "池子": pool,
                    "配置": row["key"],
                    "数值": row[metric],
                    "M1": row["M1"],
                    "M3": row["M3"],
                }
            )
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default="data/processed/backtesting/consolidated_20261120")
    args = parser.parse_args()
    out_dir = os.path.join(PROJECT_DIR, args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    pairs = []
    for pool_name, pool_key in [("1052", "union"), ("932", "legacy")]:
        std_root = DEFAULT_ROOTS[f"{pool_name}_std"]
        y15_root = DEFAULT_ROOTS[f"{pool_name}_2015"]
        std = load_summary(std_root, pool_key)
        y15 = load_summary(y15_root, pool_key)
        pair = build_pair(std, y15, pool_name, std_root, y15_root)
        print(f"{pool_name}: std {len(std)} + 2015start {len(y15)} -> matched {len(pair)}")
        pairs.append(pair)

    consolidated = pd.concat(pairs, ignore_index=True)
    consolidated = consolidated.drop_duplicates(subset=["pool", "key"]).reset_index(drop=True)
    consolidated.to_csv(os.path.join(out_dir, "consolidated.csv"), index=False)

    keys = key_configs(consolidated)
    keys.to_csv(os.path.join(out_dir, "key_configs.csv"), index=False)

    best = best_by_metric(consolidated)
    best.to_csv(os.path.join(out_dir, "best_by_metric.csv"), index=False)

    print("\n=== best by metric ===")
    print(best.to_string(index=False))
    print("\n=== key configs ===")
    print(keys.to_string(index=False))

    # top 10 by M1 / M3 per pool
    for metric in ["M1", "M3"]:
        for pool in ["1052", "932"]:
            sub = consolidated[consolidated["pool"] == pool]
            sub = sub.drop_duplicates(subset=[metric]).sort_values(metric, ascending=False).head(10)
            print(f"\n=== {pool} top 10 by {metric} ===")
            print(sub[["key", "M1", "M2", "M3", "M3b"]].to_string(index=False))


if __name__ == "__main__":
    main()
