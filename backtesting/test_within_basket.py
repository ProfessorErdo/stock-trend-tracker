#!/usr/bin/env python3
"""
固定年度篮子内的再平衡实验。

与 universe_compare.py 的区别：
- universe_compare 在每个调仓日都重新选股（选股频率 = 调仓频率）。
- 本脚本只在每年 4 月底选一次股，篮子固定一年；
  年内按周/月/季/半年/年度把权重恢复为目标权重（可选等权或不等权）。

用法::

    cd backtesting
    ../.venv/bin/python test_within_basket.py
    ../.venv/bin/python test_within_basket.py --configs best1052,classic1052 \
        --frequencies weekly,monthly,quarterly,semiannual,annual \
        --weightings equal,inv_pb,pb_rank,roe_tilt

输出：data/processed/backtesting/within_basket_<时间戳>/
  - results.csv            每个（配置 × 频率 × 权重）一行
  - runs/<id>.csv          净值曲线
  - charts/*.png           频率对比、权重对比
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
sys.path.insert(0, BASE_DIR)

import config  # noqa: E402
import data_loader  # noqa: E402
import stock_selector as ss  # noqa: E402
import universe_compare as uc  # noqa: E402
from performance import calculate_performance  # noqa: E402
from portfolio import Portfolio  # noqa: E402
from trading_calendar import build_trading_calendar, get_annual_cutoff_dates  # noqa: E402

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

PRESETS = {
    "best1052": {
        "pool": "union",
        "filters": ["pb"],
        "pe_thr": 0.25,
        "pb_thr": 0.15,
        "pr_thr": 0.25,
        "roe_thr": 0.70,
        "ranking": "pe",
        "trim": 0.01,
        "max_positions": 5,
    },
    "classic1052": {
        "pool": "union",
        "filters": ["pe", "pb", "pr"],
        "pe_thr": 0.25,
        "pb_thr": 0.25,
        "pr_thr": 0.25,
        "roe_thr": 0.75,
        "ranking": "pb",
        "trim": 0.02,
        "max_positions": 5,
    },
    "best932": {
        "pool": "legacy",
        "filters": ["pe"],
        "pe_thr": 0.25,
        "pb_thr": 0.25,
        "pr_thr": 0.25,
        "roe_thr": 0.75,
        "ranking": "pb",
        "trim": 0.01,
        "max_positions": 5,
    },
}

FREQUENCIES = ["weekly", "monthly", "quarterly", "semiannual", "annual"]
WEIGHTINGS = ["equal", "inv_pb", "inv_pb_cap40", "pb_rank", "roe_tilt"]


# ---------------------------------------------------------------------------
# 权重方案（在年度选股时确定，年内作为目标权重）
# ---------------------------------------------------------------------------
def weights_for(weighting: str, picks: list[str], meta: dict) -> dict[str, float]:
    n = len(picks)
    if n == 0:
        return {}
    if weighting == "equal":
        return {c: 1.0 / n for c in picks}

    if weighting in ("inv_pb", "inv_pb_cap40"):
        raw = {c: 1.0 / max(meta[c]["pb"], 1e-6) for c in picks}
        total = sum(raw.values())
        w = {c: raw[c] / total for c in picks}
        if weighting == "inv_pb_cap40":
            cap = 0.40
            fixed = {}
            remaining = list(picks)
            remaining_sum = 1.0
            while remaining:
                over = [c for c in remaining if w[c] > cap + 1e-12]
                if not over:
                    break
                for c in over:
                    fixed[c] = cap
                    remaining.remove(c)
                    remaining_sum -= cap
                raw_sum = sum(raw[c] for c in remaining)
                if raw_sum <= 0:
                    break
                for c in remaining:
                    w[c] = remaining_sum * raw[c] / raw_sum
            for c in fixed:
                w[c] = fixed[c]
            total = sum(w.values())
            w = {c: w[c] / total for c in picks}
        return w

    if weighting == "pb_rank":
        ordered = sorted(picks, key=lambda c: meta[c]["pb"])  # cheapest first
        scores = {c: n - i for i, c in enumerate(ordered)}
        total = sum(scores.values())
        return {c: scores[c] / total for c in picks}

    if weighting == "roe_tilt":
        raw = {c: max(meta[c]["roe"], 0.0) for c in picks}
        total = sum(raw.values())
        if total <= 0:
            return {c: 1.0 / n for c in picks}
        return {c: raw[c] / total for c in picks}

    raise ValueError(f"unknown weighting: {weighting}")


# ---------------------------------------------------------------------------
# 频率日期
# ---------------------------------------------------------------------------
def frequency_dates(trading_days: list, start: pd.Timestamp, end: pd.Timestamp,
                    frequency: str) -> list[pd.Timestamp]:
    if frequency == "annual":
        return []
    days = [d for d in trading_days if start < d < end]
    if not days:
        return []
    frame = pd.DataFrame({"date": days})
    if frequency == "weekly":
        iso = frame["date"].dt.isocalendar()
        frame["key"] = iso["year"].astype(str) + "-" + iso["week"].astype(str)
    elif frequency == "monthly":
        frame["key"] = frame["date"].dt.strftime("%Y-%m")
    elif frequency == "quarterly":
        frame["quarter"] = frame["date"].dt.quarter
        frame = frame[frame["quarter"].isin([1, 2, 3, 4])]
        frame["key"] = frame["date"].dt.strftime("%Y") + "-Q" + frame["quarter"].astype(str)
    elif frequency == "semiannual":
        frame["month"] = frame["date"].dt.month
        frame = frame[frame["month"].isin([6, 12])]
        frame["key"] = frame["date"].dt.strftime("%Y") + "-" + frame["month"].astype(str)
    else:
        raise ValueError(f"unknown frequency: {frequency}")
    return frame.groupby("key")["date"].max().sort_values().tolist()


# ---------------------------------------------------------------------------
# 选择年度篮子
# ---------------------------------------------------------------------------
def select_cycles(preset: dict, trading_days: list, price_cache: dict,
                  codes: list[str]) -> list[dict]:
    config.FILTER_INDICATORS = list(preset["filters"])
    config.PE_THRESHOLD = preset["pe_thr"]
    config.PB_THRESHOLD = preset["pb_thr"]
    config.PR_THRESHOLD = preset["pr_thr"]
    config.ROE_THRESHOLD = preset["roe_thr"]
    config.MAX_POSITIONS = preset["max_positions"]
    config.WINSORIZE_ENABLED = preset["trim"] is not None
    config.THRESHOLD_TRIM_RATIO = preset["trim"] if preset["trim"] is not None else 0.01

    pairs = get_annual_cutoff_dates(trading_days)
    cycles = []
    for i, (cutoff, rebalance) in enumerate(pairs):
        start = rebalance if rebalance is not None else cutoff
        end = (
            (pairs[i + 1][1] if pairs[i + 1][1] is not None else pairs[i + 1][0])
            if i + 1 < len(pairs)
            else pd.Timestamp(trading_days[-1])
        )
        if start >= end:
            continue
        selected, valuations = ss.select_stocks(
            codes, cutoff, price_cache=price_cache,
            filter_indicators=preset["filters"],
        )
        picks = ss.rank_and_limit(
            selected, valuations, preset["max_positions"], preset["ranking"]
        )
        meta = {}
        if picks and not valuations.empty:
            val = valuations.set_index("code")
            for code in picks:
                row = val.loc[code]
                meta[code] = {
                    "pb": float(row["pb_ttm"]),
                    "pe": float(row["pe_ttm"]),
                    "roe": float(row["roe_ttm"]),
                }
        cycles.append(
            {
                "cutoff": cutoff,
                "start": start,
                "end": end,
                "picks": picks,
                "meta": meta,
                "weights": {},
            }
        )
    return cycles


# ---------------------------------------------------------------------------
# 交易执行
# ---------------------------------------------------------------------------
def _exec_price(close: float, side: str) -> float:
    if side == "sell":
        return close * (1 - config.SLIPPAGE_RATE)
    return close * (1 + config.SLIPPAGE_RATE)


def _rebalance(portfolio: Portfolio, picks: list[str], weights: dict[str, float],
               trade_prices: dict[str, float], valuation_prices: dict[str, float],
               day: pd.Timestamp, reason: str, trade_records: list) -> None:
    if not picks:
        for code in list(portfolio.positions):
            close = trade_prices.get(code)
            if close is None:
                continue
            trade = portfolio.sell_shares(
                code, portfolio.positions[code]["shares"],
                _exec_price(close, "sell"), reason=reason,
            )
            if trade:
                trade["trade_date"] = day
                trade_records.append(trade)
        return

    n = len(picks)
    total_alloc = min(n, config.MIN_FULL_POSITION_STOCKS) * config.MAX_SINGLE_POSITION
    equity = portfolio.get_total_equity(valuation_prices)

    target_shares = {}
    for code in picks:
        close = trade_prices.get(code)
        if close is None or close <= 0:
            continue
        target_value = equity * total_alloc * weights[code]
        target_shares[code] = (int(target_value / close) // config.LOT_SIZE) * config.LOT_SIZE

    # 卖出超配（不在目标里的旧持仓也卖）
    for code, pos in list(portfolio.positions.items()):
        close = trade_prices.get(code)
        if close is None or close <= 0:
            continue
        target = target_shares.get(code, 0)
        diff = pos["shares"] - target
        if diff >= config.LOT_SIZE:
            trade = portfolio.sell_shares(
                code, diff, _exec_price(close, "sell"), reason=reason,
            )
            if trade:
                trade["trade_date"] = day
                trade_records.append(trade)

    # 买入低配
    for code in picks:
        close = trade_prices.get(code)
        if close is None or close <= 0 or code not in target_shares:
            continue
        held = portfolio.positions.get(code, {}).get("shares", 0)
        diff = target_shares[code] - held
        if diff >= config.LOT_SIZE:
            trade = portfolio.buy_shares(
                code, diff, _exec_price(close, "buy"), reason=reason,
            )
            if trade:
                trade["trade_date"] = day
                trade_records.append(trade)


# ---------------------------------------------------------------------------
# 模拟
# ---------------------------------------------------------------------------
def simulate(preset: dict, frequency: str, weighting: str, cycles: list[dict],
             trading_days: list, price_cache: dict) -> dict:
    close_map = {
        code: dict(zip(df["trade_date"], df["close"]))
        for code, df in price_cache.items()
        if "close" in df.columns
    }
    last_price = {}
    portfolio = Portfolio(config.INITIAL_CAPITAL)
    trade_records = []
    equity_rows = []

    # 事件表：(日期, 类型, cycle_index)
    events = []
    for i, cycle in enumerate(cycles):
        if not cycle["picks"]:
            continue
        cycle["weights"] = weights_for(weighting, cycle["picks"], cycle["meta"])
        events.append((cycle["start"], "turnover", i))
        for d in frequency_dates(trading_days, cycle["start"], cycle["end"], frequency):
            events.append((d, "rebalance", i))
    events.sort(key=lambda x: (x[0], 0 if x[1] == "turnover" else 1))

    relevant = set()
    for cycle in cycles:
        relevant |= set(cycle["picks"])

    event_idx = 0
    for day in trading_days:
        day_ts = pd.Timestamp(day)
        trade_prices = {}
        for code in relevant:
            price = close_map.get(code, {}).get(day_ts)
            if price is not None:
                trade_prices[code] = price
                last_price[code] = price
        valuation_prices = dict(last_price)

        while event_idx < len(events) and events[event_idx][0] == day_ts:
            _, kind, cycle_index = events[event_idx]
            cycle = cycles[cycle_index]
            reason = "年度换仓" if kind == "turnover" else f"{frequency}再平衡"
            _rebalance(
                portfolio, cycle["picks"], cycle["weights"],
                trade_prices, valuation_prices, day_ts, reason, trade_records,
            )
            equity_rows.append((day_ts, portfolio.get_total_equity(valuation_prices)))
            event_idx += 1

        # 非事件日也记录每日净值
        if not equity_rows or equity_rows[-1][0] != day_ts:
            equity_rows.append((day_ts, portfolio.get_total_equity(valuation_prices)))

    equity = pd.DataFrame(equity_rows, columns=["date", "strategy_equity"]).drop_duplicates("date")
    equity = equity.sort_values("date").reset_index(drop=True)
    equity["benchmark_equity"] = config.INITIAL_CAPITAL
    return {
        "equity": equity,
        "trades": trade_records,
        "cutoffs": [c["cutoff"] for c in cycles if c["picks"]],
    }


def metrics(preset_name: str, frequency: str, weighting: str, result: dict) -> dict:
    perf = calculate_performance(
        result["equity"], result["cutoffs"], result["trades"]
    )
    eq = result["equity"]
    returns = eq["strategy_equity"].pct_change().dropna()
    annual = perf["annual_returns"]
    return {
        "config": preset_name,
        "frequency": frequency,
        "weighting": weighting,
        "annual_return": perf["annual_return"],
        "cumulative_return": perf["cumulative_return"],
        "annual_volatility": perf["annual_volatility"],
        "sharpe_ratio": perf["sharpe_ratio"],
        "max_drawdown": perf["max_drawdown"],
        "calmar": perf["annual_return"] / abs(perf["max_drawdown"])
        if perf["max_drawdown"] else np.nan,
        "final_equity": perf["final_equity"],
        "n_trades": len(result["trades"]),
        "annual_turnover": float(
            sum(t["amount"] for t in result["trades"])
            / result["equity"]["strategy_equity"].mean()
            / (len(result["equity"]) / 252)
        ),
        "cagr_2016_2020": _period_cagr(eq, "2016-01-01", "2020-12-31"),
        "cagr_2021_2026": _period_cagr(eq, "2021-01-01", "2099-12-31"),
        "worst_year": float(annual["strategy_return"].min()) if len(annual) else np.nan,
        "best_year": float(annual["strategy_return"].max()) if len(annual) else np.nan,
        "positive_years": int((annual["strategy_return"] > 0).sum()),
        "n_years": int(len(annual)),
    }


def _period_cagr(equity: pd.DataFrame, start: str, end: str):
    sub = equity[(equity["date"] >= pd.Timestamp(start)) & (equity["date"] <= pd.Timestamp(end))]
    if len(sub) < 2:
        return np.nan
    cumulative = sub["strategy_equity"].iloc[-1] / sub["strategy_equity"].iloc[0] - 1
    return float((1 + cumulative) ** (252 / len(sub)) - 1)


# ---------------------------------------------------------------------------
# 图表
# ---------------------------------------------------------------------------
def plot_frequency(results: pd.DataFrame, curves: dict, charts_dir: str) -> None:
    subset = results[(results["config"] == results["config"].iloc[0])
                     & (results["weighting"] == "equal")]
    standard = ["weekly", "monthly", "quarterly", "semiannual", "annual"]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    for freq in standard:
        row = subset[subset["frequency"] == freq]
        if row.empty:
            continue
        key = (row.iloc[0]["config"], freq, "equal")
        eq = curves.get(key)
        if eq is None:
            continue
        ax.plot(eq["date"], eq["strategy_equity"] / eq["strategy_equity"].iloc[0],
                lw=1.5, label=f"{freq} ({row.iloc[0]['annual_return']*100:.2f}%)")
    ax.set_yscale("log")
    ax.set_ylabel("Net value (log scale)")
    ax.set_title("Fixed annual basket: rebalance frequency (equal weight)")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(charts_dir, "frequency_equal.png"), dpi=160)
    plt.close(fig)


def plot_weighting(results: pd.DataFrame, curves: dict, charts_dir: str) -> None:
    config_name = results["config"].iloc[0]
    freq = "quarterly" if (results["frequency"] == "quarterly").any() else results["frequency"].iloc[0]
    subset = results[(results["config"] == config_name) & (results["frequency"] == freq)]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    for _, row in subset.iterrows():
        eq = curves.get((config_name, freq, row["weighting"]))
        if eq is None:
            continue
        ax.plot(eq["date"], eq["strategy_equity"] / eq["strategy_equity"].iloc[0],
                lw=1.5, label=f"{row['weighting']} ({row['annual_return']*100:.2f}%)")
    ax.set_yscale("log")
    ax.set_ylabel("Net value (log scale)")
    ax.set_title(f"Fixed annual basket: weighting schemes ({freq} rebalance)")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(charts_dir, "weighting.png"), dpi=160)
    plt.close(fig)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end-date", default="2026-11-06")
    parser.add_argument("--configs", default="best1052,classic1052")
    parser.add_argument("--frequencies", default=",".join(FREQUENCIES))
    parser.add_argument("--weightings", default=",".join(WEIGHTINGS))
    parser.add_argument("--output-root", default=None)
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_root = args.output_root or os.path.join(
        config.DATA_OUTPUT_DIR, f"within_basket_{timestamp}"
    )
    charts_dir = os.path.join(out_root, "charts")
    os.makedirs(charts_dir, exist_ok=True)

    config_names = [x.strip() for x in args.configs.split(",") if x.strip()]
    frequencies = [x.strip() for x in args.frequencies.split(",") if x.strip()]
    weightings = [x.strip() for x in args.weightings.split(",") if x.strip()]

    # 数据缓存
    cache = {}
    for name in config_names:
        preset = PRESETS[name]
        uc.set_pool(preset["pool"])
        codes = data_loader.load_stock_pool()["code"].tolist()
        price_cache = {c: data_loader.load_price_data(c) for c in codes}
        cache[name] = (codes, price_cache)
    uc.set_pool("union")

    trading_days = build_trading_calendar("2015-01-01", args.end_date)
    print(f"Trading days: {len(trading_days)}  end={args.end_date}")

    rows = []
    curves = {}
    for name in config_names:
        codes, price_cache = cache[name]
        cycles = select_cycles(PRESETS[name], trading_days, price_cache, codes)
        invested = [c for c in cycles if c["picks"]]
        print(f"\n{name}: {len(cycles)} annual cycles, {len(invested)} with picks")
        for cycle in cycles[:3]:
            print(f"  {cycle['cutoff'].date()} -> {cycle['start'].date()}: {cycle['picks']}")
        for freq in frequencies:
            for weighting in weightings:
                result = simulate(
                    PRESETS[name], freq, weighting, cycles, trading_days, price_cache
                )
                row = metrics(name, freq, weighting, result)
                rows.append(row)
                curves[(name, freq, weighting)] = result["equity"]
                run_id = f"{name}_{freq}_{weighting}"
                result["equity"].to_csv(
                    os.path.join(out_root, f"runs_{run_id}.csv"), index=False
                )
                print(
                    f"  {freq:10s} {weighting:14s} annual={row['annual_return']*100:6.2f}% "
                    f"sharpe={row['sharpe_ratio']:5.3f} mdd={row['max_drawdown']*100:6.2f}% "
                    f"trades={row['n_trades']}"
                )

    results = pd.DataFrame(rows).sort_values(
        ["config", "frequency", "weighting"]
    )
    results.to_csv(os.path.join(out_root, "results.csv"), index=False)
    plot_frequency(results, curves, charts_dir)
    plot_weighting(results, curves, charts_dir)
    print(f"\nSaved: {out_root}")


if __name__ == "__main__":
    main()
