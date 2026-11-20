#!/usr/bin/env python3
"""
构建以 M3b 为主口径的年度配置数据集。

数据源：
- 2015-start 回测（M3/M3b、逐年收益、净值曲线）
- 标准回测（M1/M2，用于辅助列）

输出：m3b_20261120/m3b_annual.csv
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
sys.path.insert(0, BASE_DIR)

ROOTS = {
    "1052": {
        "std": os.path.join(PROJECT_DIR, "data", "processed", "backtesting", "universe_compare_20261107_101219"),
        "y15": os.path.join(PROJECT_DIR, "data", "processed", "backtesting", "universe_compare_2015start_20261120"),
        "pool": "union",
    },
    "932": {
        "std": os.path.join(PROJECT_DIR, "data", "processed", "backtesting", "universe_compare_legacy932_20261107"),
        "y15": os.path.join(PROJECT_DIR, "data", "processed", "backtesting", "universe_compare_legacy932_2015start_20261120"),
        "pool": "legacy",
    },
}

ANNUAL_PHASES = {"core", "trim", "positions", "threshold", "refine", "special"}


def metrics_from_equity(equity: pd.DataFrame, start: pd.Timestamp) -> dict:
    sub = equity[equity["date"] >= start].sort_values("date").reset_index(drop=True)
    if len(sub) < 2:
        return {}
    the = sub["strategy_equity"].to_numpy()
    daily = sub["strategy_equity"].pct_change().dropna()
    cumulative = the[-1] / the[0] - 1
    annual = (1 + cumulative) ** (252 / len(sub)) - 1
    vol = float(daily.std() * np.sqrt(252))
    sharpe = (annual - 0.02) / vol if vol else np.nan
    mdd = float((the / np.maximum.accumulate(the) - 1).min())
    return {"M3b_days": len(sub), "M3b": annual, "M3b_vol": vol,
            "M3b_sharpe": sharpe, "M3b_mdd": mdd}


def first_buy_date(run_dir: str, equity: pd.DataFrame) -> pd.Timestamp:
    path = os.path.join(run_dir, "trades_record.csv")
    if os.path.exists(path):
        trades = pd.read_csv(path)
        if "direction" in trades.columns:
            buys = trades[trades["direction"] == "买入"]
            if not buys.empty:
                return pd.to_datetime(buys["trade_date"]).min()
    return equity["date"].min()


def build_pool(pool: str, roots: dict) -> pd.DataFrame:
    y15 = pd.read_csv(os.path.join(roots["y15"], "summary.csv"))
    y15 = y15[(y15["pool"] == roots["pool"]) & (y15["phase"].isin(ANNUAL_PHASES))].copy()

    std = pd.read_csv(os.path.join(roots["std"], "summary.csv"))
    std = std[(std["pool"] == roots["pool"]) & (~std["phase"].astype(str).str.startswith("val"))].copy()
    std = std[["id", "annual_return", "annual_return_since_first_investment", "sharpe_ratio", "max_drawdown"]]
    std = std.rename(columns={
        "id": "std_id", "annual_return": "M1",
        "annual_return_since_first_investment": "M2",
        "sharpe_ratio": "M1_sharpe", "max_drawdown": "M1_mdd",
    })

    rows = []
    for _, row in y15.iterrows():
        run_dir = os.path.join(roots["y15"], "runs", row["id"])
        equity_path = os.path.join(run_dir, "equity_curve.csv")
        if not os.path.exists(equity_path):
            continue
        equity = pd.read_csv(equity_path, parse_dates=["date"])
        first = first_buy_date(run_dir, equity)
        m = metrics_from_equity(equity, first)
        if not m:
            continue
        ar_path = os.path.join(run_dir, "annual_returns.csv")
        y2015 = y2016 = np.nan
        if os.path.exists(ar_path):
            ar = pd.read_csv(ar_path).set_index("year")["strategy_return"]
            y2015 = float(ar.get(2015, np.nan))
            y2016 = float(ar.get(2016, np.nan))
        key = row["id"].replace("_2015start", "")
        rows.append({
            "pool": pool, "key": key, "std_id": key, "phase": row["phase"],
            "sig": "|".join(str(row[k]) for k in (
                "filters", "ranking", "trim", "max_positions",
                "pe_thr", "pb_thr", "pr_thr", "roe_thr",
            )),
            "filters": row["filters"], "ranking": row["ranking"],
            "trim": str(row["trim"]), "max_positions": row["max_positions"],
            "pe_thr": row["pe_thr"], "pb_thr": row["pb_thr"],
            "pr_thr": row["pr_thr"], "roe_thr": row["roe_thr"],
            "M3": row["annual_return"],
            "M3b": row["annual_return_since_first_investment"],
            "M3_sharpe": row["sharpe_ratio"], "M3_mdd": row["max_drawdown"],
            "M3_2015_return": y2015, "M3_2016_return": y2016,
            "first_investment_date": first.strftime("%Y-%m-%d"),
            "y15_id": row["id"],
            **m,
        })
    out = pd.DataFrame(rows)
    return out.merge(std, on="std_id", how="left")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--std-1052", default=ROOTS["1052"]["std"])
    parser.add_argument("--y15-1052", default=ROOTS["1052"]["y15"])
    parser.add_argument("--std-932", default=ROOTS["932"]["std"])
    parser.add_argument("--y15-932", default=ROOTS["932"]["y15"])
    parser.add_argument("--out-dir", default="data/processed/backtesting/m3b_20261120")
    args = parser.parse_args()

    roots = {
        "1052": {"std": args.std_1052, "y15": args.y15_1052, "pool": "union"},
        "932": {"std": args.std_932, "y15": args.y15_932, "pool": "legacy"},
    }
    data = pd.concat([build_pool("1052", roots), build_pool("932", roots)], ignore_index=True)
    data = data[data["first_investment_date"] == "2015-05-04"].copy()
    data = data.sort_values(["pool", "M3b"], ascending=[True, False]).reset_index(drop=True)

    out_dir = os.path.join(PROJECT_DIR, args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    data.to_csv(os.path.join(out_dir, "m3b_annual.csv"), index=False)

    print(f"rows: {len(data)}")
    print(data.groupby("pool").size().to_dict())
    for pool in ["1052", "932"]:
        sub = data[data["pool"] == pool].sort_values("M3b", ascending=False).head(5)
        print(f"\n{pool} top 5 by M3b:")
        print(sub[["key", "M3b", "M1", "M3", "M3b_sharpe", "M3b_mdd"]].to_string(index=False))


if __name__ == "__main__":
    main()
