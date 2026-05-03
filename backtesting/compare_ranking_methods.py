"""
排名方式对比回测：在四步选股基础上，测试 4 种 Top-10 排名方式
1. ROE 最高前 10
2. PE 最低前 10
3. PB 最低前 10
4. PR 最低前 10
"""

import sys
import logging
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger("compare_ranking")

import pandas as pd
import numpy as np
from tqdm import tqdm

import config
from data_loader import load_stock_pool, load_price_data
from trading_calendar import build_trading_calendar, get_quarterly_cutoff_dates
from stock_selector import (
    select_stocks, get_latest_financial_data, calculate_valuation,
    winsorize, is_new_stock, rank_and_limit
)
from backtest_engine import compute_benchmark_equity_curve


RANKING_METHODS = {
    "roe_high": {"label": "ROE 最高 Top-10", "method": "roe"},
    "pe_low":   {"label": "PE 最低 Top-10", "method": "pe"},
    "pb_low":   {"label": "PB 最低 Top-10", "method": "pb"},
    "pr_low":   {"label": "PR 最低 Top-10", "method": "pr"},
}

MAX_POSITIONS = 10


def run_ranking_backtest(
    stock_codes: list,
    trading_days: list,
    cutoffs: list,
    price_cache: dict,
    ranking_method: str,
    initial_capital: float = config.INITIAL_CAPITAL,
) -> dict:
    """
    Run a full backtest for a single ranking method.

    Returns:
        {
            'equity_curve': DataFrame with date/strategy_equity,
            'trade_records': list,
            'holding_snapshots': list,
            'cutoff_dates': list,
            'selection_counts': list of (cutoff, raw_count, final_count),
        }
    """
    # --- Step 1: compute benchmark ---
    benchmark_df = compute_benchmark_equity_curve(
        stock_codes, trading_days, cutoffs, price_cache, initial_capital
    )

    # --- Step 2: selection for each cutoff ---
    selection_results = {}  # {(cutoff, rebalance): selected_codes}
    selection_counts = []

    for cutoff, rebalance in tqdm(cutoffs, desc=f"  {ranking_method}"):
        selected, val_df = select_stocks(stock_codes, cutoff, price_cache=price_cache)
        raw_count = len(selected)

        # Apply ranking + limit
        final_selected = rank_and_limit(selected, val_df, MAX_POSITIONS, ranking_method)

        if rebalance is not None:
            selection_results[(cutoff, rebalance)] = final_selected

        selection_counts.append((cutoff, raw_count, len(final_selected)))

    # --- Step 3: portfolio simulation ---
    from portfolio import Portfolio

    portfolio = Portfolio(initial_capital=initial_capital)
    trade_records = []
    holding_snapshots = []
    cutoff_dates = []

    for (cutoff, rebalance), selected_codes in tqdm(
        selection_results.items(), desc=f"  {ranking_method} trades"
    ):
        prices = {}
        prev_prices = {}

        for code in stock_codes:
            if code in price_cache:
                df = price_cache[code]
                row = df[df["trade_date"] == rebalance]
                if not row.empty:
                    prices[code] = row["close"].iloc[0]
                before = df[df["trade_date"] < rebalance]
                if not before.empty:
                    prev_prices[code] = before["close"].iloc[-1]

        if not prices:
            continue

        # Limit up/down check
        from backtest_engine import check_limit_up_down

        all_relevant = set(portfolio.positions.keys()) | set(selected_codes)
        can_buy_flags = {}
        can_sell_flags = {}

        for code in all_relevant:
            if code in price_cache and code in prev_prices:
                df = price_cache[code]
                result = check_limit_up_down(code, rebalance, df, prev_prices[code])
                can_buy_flags[code] = result["can_buy"]
                can_sell_flags[code] = result["can_sell"]
            else:
                can_buy_flags[code] = True
                can_sell_flags[code] = True

        total_equity = portfolio.get_total_equity(prices)
        plan = portfolio.calculate_target_positions(
            selected_codes, total_equity, prices,
            can_buy=True, can_sell=True
        )

        for code, shares_to_sell in plan["sell_orders"]:
            price = prices.get(code, 0)
            if price <= 0 or not can_sell_flags.get(code, True):
                continue
            trade = portfolio.sell_shares(code, shares_to_sell, price, reason="调仓卖出")
            if trade:
                trade["trade_date"] = rebalance
                trade_records.append(trade)

        for code, shares_to_buy in plan["buy_orders"]:
            price = prices.get(code, 0)
            if price <= 0 or not can_buy_flags.get(code, True):
                continue
            if code in price_cache and is_new_stock(code, price_cache[code], rebalance, config.NEW_STOCK_EXCLUDE_DAYS):
                continue
            trade = portfolio.buy_shares(code, shares_to_buy, price, reason="调仓买入")
            if trade:
                trade["trade_date"] = rebalance
                trade_records.append(trade)

        snapshot = portfolio.snapshot_holdings(rebalance, prices)
        holding_snapshots.append(snapshot)
        cutoff_dates.append(cutoff)

    # --- Step 4: daily equity curve ---
    strategy_equity = []
    for day in trading_days:
        day_ts = pd.Timestamp(day)
        day_prices = {}
        for code in price_cache:
            df = price_cache[code]
            row = df[df["trade_date"] == day_ts]
            if not row.empty:
                day_prices[code] = row["close"].iloc[0]
        equity = portfolio.get_total_equity(day_prices)
        strategy_equity.append({"date": day_ts, "strategy_equity": equity})

    strategy_df = pd.DataFrame(strategy_equity)

    if len(benchmark_df) > 0:
        equity_curve = strategy_df.merge(
            benchmark_df[["date", "benchmark_equity"]], on="date", how="left"
        )
        equity_curve["benchmark_equity"] = equity_curve["benchmark_equity"].ffill()
        equity_curve["benchmark_equity"] = equity_curve["benchmark_equity"].fillna(initial_capital)
    else:
        equity_curve = strategy_df.copy()
        equity_curve["benchmark_equity"] = initial_capital

    return {
        "equity_curve": equity_curve,
        "trade_records": trade_records,
        "holding_snapshots": holding_snapshots,
        "cutoff_dates": cutoff_dates,
        "selection_counts": selection_counts,
    }


def compute_performance(equity_curve: pd.DataFrame) -> dict:
    """Calculate key performance metrics."""
    initial = config.INITIAL_CAPITAL
    final = equity_curve["strategy_equity"].iloc[-1]
    cum_return = (final - initial) / initial

    bench_final = equity_curve["benchmark_equity"].iloc[-1]

    daily_returns = equity_curve["strategy_equity"].pct_change().dropna()
    trading_days = len(equity_curve)
    years = trading_days / 252

    ann_return = (equity_curve["strategy_equity"].iloc[-1] / initial) ** (1 / years) - 1
    bench_annual_return = (bench_final / initial) ** (1 / years) - 1
    ann_vol = daily_returns.std() * np.sqrt(252)
    sharpe = ann_return / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    equity_vals = equity_curve["strategy_equity"].values
    running_max = np.maximum.accumulate(equity_vals)
    drawdowns = (equity_vals - running_max) / running_max
    max_dd = drawdowns.min()

    bench_cum_return = (bench_final - initial) / initial
    excess_return = cum_return - bench_cum_return

    return {
        "cumulative_return": cum_return,
        "benchmark_return": (bench_final - initial) / initial,
        "benchmark_annual_return": bench_annual_return,
        "excess_return": excess_return,
        "annual_return": ann_return,
        "annual_volatility": ann_vol,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_dd,
    }


def compute_annual_returns(equity_curve: pd.DataFrame) -> dict:
    """Calculate annual returns for each year."""
    ec = equity_curve.copy()
    ec["year"] = ec["date"].dt.year

    results = {}
    for year, group in ec.groupby("year"):
        first_val = group["strategy_equity"].iloc[0]
        last_val = group["strategy_equity"].iloc[-1]
        first_bench = group["benchmark_equity"].iloc[0]
        last_bench = group["benchmark_equity"].iloc[-1]
        results[year] = {
            "strategy": (last_val - first_val) / first_val,
            "benchmark": (last_bench - first_bench) / first_bench,
        }
    return results


def main():
    logger.info("=" * 80)
    logger.info("  Ranking Method Comparison - Top-10 Selection After 4-Step Filter")
    logger.info("=" * 80)
    logger.info(f"  Max positions: {MAX_POSITIONS}")
    logger.info(f"  Methods: ROE-highest, PE-lowest, PB-lowest, PR-lowest")
    logger.info("=" * 80)

    # Load data
    logger.info("\n[1/5] Loading stock pool...")
    pool_df = load_stock_pool()
    stock_codes = pool_df["code"].tolist()
    logger.info(f"  {len(stock_codes)} stocks")

    logger.info("\n[2/5] Building trading calendar...")
    trading_days = build_trading_calendar()
    cutoffs = get_quarterly_cutoff_dates(trading_days)
    logger.info(f"  {len(cutoffs)} quarterly cutoffs")

    logger.info("\n[3/5] Loading price data...")
    price_cache = {}
    for code in tqdm(stock_codes, desc="Loading"):
        try:
            df = load_price_data(code)
            if not df.empty:
                price_cache[code] = df
        except:
            continue
    logger.info(f"  {len(price_cache)} stocks loaded")

    # Run backtests for each method
    logger.info("\n[4/5] Running backtests for each ranking method...")
    results = {}
    for key, spec in RANKING_METHODS.items():
        logger.info(f"\n  Running: {spec['label']}")
        results[key] = run_ranking_backtest(
            stock_codes, trading_days, cutoffs, price_cache,
            ranking_method=spec["method"]
        )

    # Compute performance and compare
    logger.info("\n[5/5] Computing performance...")

    # --- Summary table ---
    logger.info("\n" + "=" * 80)
    logger.info(f"  Performance Comparison (2015-01-01 to present)")
    logger.info("=" * 80)
    header = f"{'指标':<20}"
    for key, spec in RANKING_METHODS.items():
        header += f"  {spec['label']:>18}"
    logger.info(header)
    logger.info("-" * 80)

    perf_data = {}
    for key in RANKING_METHODS:
        perf = compute_performance(results[key]["equity_curve"])
        perf_data[key] = perf

    metrics = [
        ("累计收益", lambda p: f"{p['cumulative_return']:.2%}"),
        ("年化收益", lambda p: f"{p['annual_return']:.2%}"),
        ("年化波动", lambda p: f"{p['annual_volatility']:.2%}"),
        ("夏普比率", lambda p: f"{p['sharpe_ratio']:.4f}"),
        ("最大回撤", lambda p: f"{p['max_drawdown']:.2%}"),
        ("基准收益", lambda p: f"{p['benchmark_return']:.2%}"),
        ("超额收益", lambda p: f"{p['excess_return']:.2%}"),
    ]

    for name, fmt in metrics:
        row = f"{name:<20}"
        for key in RANKING_METHODS:
            row += f"  {fmt(perf_data[key]):>18}"
        logger.info(row)

    # --- Trade counts ---
    logger.info("-" * 80)
    trade_row = f"{'交易次数':<20}"
    for key in RANKING_METHODS:
        trade_row += f"  {len(results[key]['trade_records']):>18}"
    logger.info(trade_row)

    # --- Annual returns ---
    logger.info("\n" + "=" * 80)
    logger.info(f"  Annual Returns by Method")
    logger.info("=" * 80)

    all_years = set()
    annual_data = {}
    for key in RANKING_METHODS:
        annual_data[key] = compute_annual_returns(results[key]["equity_curve"])
        all_years.update(annual_data[key].keys())

    header2 = f"{'年份':>6}"
    for key, spec in RANKING_METHODS.items():
        header2 += f"  {spec['label'][:12]:>14}"
    header2 += f"  {'基准':>10}"
    logger.info(header2)
    logger.info("-" * 80)

    for year in sorted(all_years):
        row = f"{year:>6}"
        bench_vals = []
        for key in RANKING_METHODS:
            if year in annual_data[key]:
                row += f"  {annual_data[key][year]['strategy']:>13.2%}"
                bench_vals.append(annual_data[key][year]["benchmark"])
            else:
                row += f"  {'N/A':>14}"
        # Average benchmark
        if bench_vals:
            avg_bench = np.mean(bench_vals)
            row += f"  {avg_bench:>9.2%}"
        else:
            row += f"  {'N/A':>10}"
        logger.info(row)

    # --- Selection count comparison ---
    logger.info("\n" + "=" * 80)
    logger.info(f"  Selection Counts per Cutoff Date")
    logger.info("=" * 80)
    header3 = f"{'截面日期':>12}"
    for key, spec in RANKING_METHODS.items():
        header3 += f"  {spec['label'][:8]:>10}"
    logger.info(header3)
    logger.info("-" * 80)

    for i in range(len(cutoffs)):
        cutoff = cutoffs[i][0]
        row = f"{cutoff.strftime('%Y-%m-%d'):>12}"
        for key in RANKING_METHODS:
            if i < len(results[key]["selection_counts"]):
                _, raw, final = results[key]["selection_counts"][i]
                row += f"  {raw:>4}/{final:>4}"
            else:
                row += f"  {'N/A':>10}"
        logger.info(row)

    # --- Summary: best method ---
    logger.info("\n" + "=" * 80)
    logger.info("  Conclusion")
    logger.info("=" * 80)

    best_sharpe = max(RANKING_METHODS, key=lambda k: perf_data[k]["sharpe_ratio"])
    best_cum = max(RANKING_METHODS, key=lambda k: perf_data[k]["cumulative_return"])
    best_dd = max(RANKING_METHODS, key=lambda k: perf_data[k]["max_drawdown"])

    logger.info(f"  Best Sharpe Ratio:  {RANKING_METHODS[best_sharpe]['label']} ({perf_data[best_sharpe]['sharpe_ratio']:.4f})")
    logger.info(f"  Best Cum Return:    {RANKING_METHODS[best_cum]['label']} ({perf_data[best_cum]['cumulative_return']:.2%})")
    logger.info(f"  Smallest Drawdown:  {RANKING_METHODS[best_dd]['label']} ({perf_data[best_dd]['max_drawdown']:.2%})")
    logger.info("=" * 80)


logging.basicConfig(level=logging.INFO, format="%(message)s")

if __name__ == "__main__":
    main()
