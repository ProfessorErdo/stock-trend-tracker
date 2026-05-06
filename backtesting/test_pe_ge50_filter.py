"""
测试：排除 cutoff 前一年内曾出现过 PE TTM >= 50 的股票
"""

import sys
import os
import pickle
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from data_loader import load_stock_pool, load_financial_data
from stock_selector import rank_and_limit, select_stocks, get_latest_financial_data
from portfolio import Portfolio
from performance import calculate_performance
from log_util import setup_logger


TEST_MAX_POSITIONS = 5
PE_HISTORY_DIR = os.path.join(config.DATA_OUTPUT_DIR, "pe_history")


def load_pe_history(code: str) -> pd.DataFrame | None:
    path = os.path.join(PE_HISTORY_DIR, f"pe_{code}.csv")
    if not os.path.exists(path):
        return None
    return pd.read_csv(path, parse_dates=["trade_date"])


def filter_high_pe_stocks(stock_codes: list, cutoff_date: pd.Timestamp,
                           pe_cache: dict, threshold: float = 50.0) -> list:
    """
    排除 cutoff 前一年内曾出现过 PE TTM >= threshold 的股票。

    只保留过去一年所有交易日 PE 都 < threshold 的股票。
    """
    cutoff_ts = pd.Timestamp(cutoff_date)
    start_date = cutoff_ts - pd.DateOffset(years=1)
    kept = []

    for code in stock_codes:
        if code not in pe_cache:
            continue
        pe_df = pe_cache[code]
        if pe_df.empty:
            continue

        window = pe_df[(pe_df["trade_date"] >= start_date) & (pe_df["trade_date"] <= cutoff_ts)]
        valid_pe = window["pe"].dropna()

        if valid_pe.empty:
            # 没有 PE 数据的也排除
            continue

        if valid_pe.max() >= threshold:
            continue  # 出现过 PE >= 50，排除

        kept.append(code)

    return kept


def execute_rebalance(portfolio, target_codes, rebalance_date, stock_codes, price_cache):
    prices = {}
    for code in stock_codes:
        if code in price_cache:
            df = price_cache[code]
            row = df[df["trade_date"] == rebalance_date]
            if not row.empty:
                prices[code] = row["close"].iloc[0]
    if not prices:
        return [], {}

    total_equity = portfolio.get_total_equity(prices)
    plan = portfolio.calculate_target_positions(
        target_codes, total_equity, prices, can_buy=True, can_sell=True
    )

    trades = []
    for code, shares in plan["sell_orders"]:
        p = prices.get(code, 0)
        if p > 0:
            trade = portfolio.sell_shares(code, shares, p * (1 - config.SLIPPAGE_RATE), reason="调仓卖出")
            if trade:
                trade["trade_date"] = rebalance_date
                trades.append(trade)

    for code, shares in plan["buy_orders"]:
        p = prices.get(code, 0)
        if p > 0:
            trade = portfolio.buy_shares(code, shares, p * (1 + config.SLIPPAGE_RATE), reason="调仓买入")
            if trade:
                trade["trade_date"] = rebalance_date
                trades.append(trade)

    snapshot = portfolio.snapshot_holdings(rebalance_date, prices)
    return trades, snapshot


def run_backtest(stock_codes, cutoffs_with_rebalance, price_cache, trading_days,
                 pe_cache, use_pe_filter: bool, logger=None):
    portfolio = Portfolio(initial_capital=config.INITIAL_CAPITAL)
    all_trades = []
    all_snapshots = []
    actual_cutoffs = []
    portfolio_states = []

    for cutoff, rebalance in cutoffs_with_rebalance:
        cutoff_ts = pd.Timestamp(cutoff)

        if use_pe_filter:
            pool_after_pe = filter_high_pe_stocks(stock_codes, cutoff_ts, pe_cache, threshold=50.0)
            if logger:
                logger.info(f"  {cutoff}: PE filter: {len(stock_codes)} -> {len(pool_after_pe)} (excluded {len(stock_codes) - len(pool_after_pe)})")
        else:
            pool_after_pe = stock_codes

        selected, val_df = select_stocks(pool_after_pe, cutoff_ts, price_cache=price_cache)

        if not selected:
            if logger:
                logger.info(f"  {cutoff}: filtered=0, final=0")
            continue

        final = rank_and_limit(selected, val_df, TEST_MAX_POSITIONS, "pb")

        if logger and final:
            pbs = []
            for code in final:
                row = val_df[val_df["code"] == code]
                if not row.empty:
                    pbs.append(f"    {code} (PB={row.iloc[0]['pb_ttm']:.2f})")
            tag = "PE" if use_pe_filter else "Orig"
            logger.info(f"  {cutoff} [{tag}]: after_filter={len(selected)}, final={len(final)}")
            for p in pbs:
                logger.info(p)

        exec_date = rebalance if rebalance is not None else cutoff
        trades, snapshot = execute_rebalance(portfolio, final, exec_date, stock_codes, price_cache)
        all_trades.extend(trades)
        all_snapshots.append(snapshot)
        actual_cutoffs.append(cutoff)
        shares_snap = {c: pos["shares"] for c, pos in portfolio.positions.items()}
        portfolio_states.append((pd.Timestamp(exec_date), portfolio.cash, shares_snap))

    stock_close_map = {}
    for code, df in price_cache.items():
        if "close" not in df.columns:
            continue
        stock_close_map[code] = dict(zip(df["trade_date"], df["close"]))

    bench_map = {}
    if bench_equity_data is not None and not bench_equity_data.empty:
        bench_map = dict(zip(pd.to_datetime(bench_equity_data["date"]), bench_equity_data["benchmark_equity"]))

    strat_equity = []
    bench_equity_list = []

    if portfolio_states:
        first_rebalance = portfolio_states[0][0]
        state_idx = 0
        cur_cash = portfolio_states[0][1]
        cur_shares = portfolio_states[0][2]

    for day in trading_days:
        day_ts = pd.Timestamp(day)
        if portfolio_states:
            while state_idx + 1 < len(portfolio_states) and portfolio_states[state_idx + 1][0] <= day_ts:
                state_idx += 1
                cur_cash = portfolio_states[state_idx][1]
                cur_shares = portfolio_states[state_idx][2]

        if not portfolio_states or day_ts < first_rebalance:
            strat_eq = config.INITIAL_CAPITAL
        else:
            strat_eq = cur_cash
            for code, shares in cur_shares.items():
                if shares > 0 and code in stock_close_map:
                    price = stock_close_map[code].get(day_ts)
                    if price is None:
                        before = {d: p for d, p in stock_close_map[code].items() if d < day_ts}
                        price = before[max(before)] if before else 0
                    strat_eq += shares * price

        strat_equity.append(strat_eq)
        bench_equity_list.append(bench_map.get(day_ts, config.INITIAL_CAPITAL))

    equity_df = pd.DataFrame({
        "date": pd.to_datetime(trading_days),
        "strategy_equity": strat_equity,
        "benchmark_equity": bench_equity_list,
    })

    perf = calculate_performance(equity_df, actual_cutoffs, all_trades)

    return {
        "equity_curve": equity_df,
        "trade_records": all_trades,
        "holding_snapshots": all_snapshots,
        "cutoff_dates": actual_cutoffs,
        "performance": perf,
    }


bench_equity_data = None


def run_test():
    global bench_equity_data

    logger = setup_logger("test_pe_threshold", "test_pe_threshold")
    logger.info("=" * 60)
    logger.info("Test: Exclude stocks with PE TTM >= 50 in past year")
    logger.info("=" * 60)

    logger.info("\n[1] Loading data...")
    pool_df = load_stock_pool()
    stock_codes = pool_df["code"].tolist()

    with open(os.path.join(config.DATA_OUTPUT_DIR, "intermediate.pkl"), "rb") as f:
        intermediate = pickle.load(f)

    price_cache = intermediate["price_cache"]
    trading_days = intermediate["trading_days"]
    old_cutoffs = intermediate["cutoff_dates"]
    bench_equity_data = intermediate["equity_curve"]

    logger.info(f"  Stocks: {len(stock_codes)}, Trading days: {len(trading_days)}")

    # Load PE history
    logger.info("\n[2] Loading PE history...")
    pe_cache = {}
    for code in stock_codes:
        df = load_pe_history(code)
        if df is not None and not df.empty:
            pe_cache[code] = df
    logger.info(f"  PE history loaded for {len(pe_cache)} stocks")

    # Build cutoff tuples
    all_trading = sorted(set(pd.to_datetime(trading_days)))
    cutoffs_with_rebalance = []
    for c in old_cutoffs:
        c_ts = pd.Timestamp(c)
        next_days = [d for d in all_trading if d > c_ts]
        rebalance = next_days[0] if next_days else None
        cutoffs_with_rebalance.append((c_ts, rebalance))

    # Original
    logger.info("\n[3] Running original strategy...")
    result_orig = run_backtest(stock_codes, cutoffs_with_rebalance, price_cache, trading_days,
                               pe_cache, use_pe_filter=False, logger=logger)

    # New filter
    logger.info("\n[4] Running PE>=50 exclusion filter...")
    result_new = run_backtest(stock_codes, cutoffs_with_rebalance, price_cache, trading_days,
                              pe_cache, use_pe_filter=True, logger=logger)

    # Performance comparison
    logger.info("\n" + "=" * 60)
    logger.info("Performance Comparison")
    logger.info("=" * 60)

    from performance import save_performance_summary

    strategies = [
        ("Original", result_orig["performance"]),
        ("PE>=50_excl", result_new["performance"]),
    ]

    output_dir = os.path.join(config.DATA_OUTPUT_DIR, "pe_trend_test")
    os.makedirs(output_dir, exist_ok=True)

    for name, perf in strategies:
        save_performance_summary(perf, os.path.join(output_dir, f"{name}_perf.csv"))

    perf_maps = {}
    for name, _ in strategies:
        df = pd.read_csv(os.path.join(output_dir, f"{name}_perf.csv"))
        perf_maps[name] = dict(zip(df["Metric"], df["Value"]))

    w0 = 25
    w = 22
    header = f"{'Metric':<{w0}}"
    for name, _ in strategies:
        header += f"{name:<{w}}"
    logger.info(header)
    logger.info("-" * (w0 + w * 2))

    metrics = [
        "Cumulative Return", "Annual Return", "Annual Volatility",
        "Sharpe Ratio", "Max Drawdown", "Win Rate", "Profit/Loss Ratio",
    ]
    for m in metrics:
        row = f"{m:<{w0}}"
        for name, _ in strategies:
            val = str(perf_maps[name].get(m, "N/A"))
            row += f"{val:<{w}}"
        logger.info(row)

    logger.info("")
    for m in ["Final Equity", "Benchmark Cumulative Return", "Excess Return", "Information Ratio"]:
        row = f"{m:<{w0}}"
        for name, _ in strategies:
            val = str(perf_maps[name].get(m, "N/A"))
            row += f"{val:<{w}}"
        logger.info(row)

    # Save results
    logger.info("\n[5] Saving results...")
    for name, result in [("original", result_orig), ("pe_ge50_excl", result_new)]:
        if result["equity_curve"] is not None and not result["equity_curve"].empty:
            result["equity_curve"].to_csv(os.path.join(output_dir, f"{name}_equity.csv"), index=False)
        if result["trade_records"]:
            pd.DataFrame(result["trade_records"]).to_csv(os.path.join(output_dir, f"{name}_trades.csv"), index=False)
        if result["holding_snapshots"]:
            valid = [h for h in result["holding_snapshots"] if h is not None]
            if valid:
                pd.concat(valid, ignore_index=True).to_csv(os.path.join(output_dir, f"{name}_holdings.csv"), index=False)

    logger.info(f"\nResults saved to: {output_dir}/")
    logger.info("\n" + "=" * 60)
    logger.info("Test complete!")
    logger.info("=" * 60)

    return result_orig["performance"], result_new["performance"]


if __name__ == "__main__":
    run_test()
