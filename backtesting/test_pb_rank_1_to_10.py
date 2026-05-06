"""
测试：PB排名取前N只（N=1到10）

筛选逻辑不变（PB<25% → ROE>75%），只改变排名取前几只。
单只股票最大仓位 = 1/N（满仓时）。N<5时每只占20%，总仓位=N*20%。
"""

import sys
import os
import pickle
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from data_loader import load_stock_pool
from stock_selector import select_stocks, rank_and_limit
from portfolio import Portfolio
from performance import calculate_performance
from log_util import setup_logger


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
                 max_positions: int, logger=None):
    portfolio = Portfolio(initial_capital=config.INITIAL_CAPITAL)
    all_trades = []
    all_snapshots = []
    actual_cutoffs = []
    portfolio_states = []

    for cutoff, rebalance in cutoffs_with_rebalance:
        cutoff_ts = pd.Timestamp(cutoff)

        selected, val_df = select_stocks(stock_codes, cutoff_ts, price_cache=price_cache)

        if not selected:
            if logger:
                logger.info(f"  {cutoff}: filtered=0, final=0")
            continue

        final = rank_and_limit(selected, val_df, max_positions, "pb")

        if logger and final and max_positions <= 5:
            for code in final:
                row = val_df[val_df["code"] == code]
                if not row.empty:
                    logger.info(f"    {code} (PB={row.iloc[0]['pb_ttm']:.2f})")
            logger.info(f"  {cutoff}: filtered={len(selected)}, final={len(final)}")

        exec_date = rebalance if rebalance is not None else cutoff
        trades, snapshot = execute_rebalance(portfolio, final, exec_date, stock_codes, price_cache)
        all_trades.extend(trades)
        all_snapshots.append(snapshot)
        actual_cutoffs.append(cutoff)
        shares_snap = {c: pos["shares"] for c, pos in portfolio.positions.items()}
        portfolio_states.append((pd.Timestamp(exec_date), portfolio.cash, shares_snap))

    # Build daily equity curve
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

    logger = setup_logger("test_pb_rank_1_10", "test_pb_rank_1_10")
    logger.info("=" * 60)
    logger.info("Test: PB Ranking N=1 to 10")
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

    # Build cutoff tuples
    all_trading = sorted(set(pd.to_datetime(trading_days)))
    cutoffs_with_rebalance = []
    for c in old_cutoffs:
        c_ts = pd.Timestamp(c)
        next_days = [d for d in all_trading if d > c_ts]
        rebalance = next_days[0] if next_days else None
        cutoffs_with_rebalance.append((c_ts, rebalance))

    # Run N=1 to 10
    results = {}
    for n in range(1, 11):
        logger.info(f"\n[Running] Max Positions = {n}...")
        result = run_backtest(stock_codes, cutoffs_with_rebalance, price_cache, trading_days,
                              max_positions=n, logger=None)  # suppress per-stock logs for brevity
        results[n] = result
        logger.info(f"  Trades: {len(result['trade_records'])}")

    # Performance comparison table
    logger.info("\n" + "=" * 60)
    logger.info("Performance Comparison (N=1 to 10)")
    logger.info("=" * 60)

    from performance import save_performance_summary

    output_dir = os.path.join(config.DATA_OUTPUT_DIR, "pb_rank_1_10")
    os.makedirs(output_dir, exist_ok=True)

    # Save performance summaries first
    for n in range(1, 11):
        save_performance_summary(results[n]["performance"], os.path.join(output_dir, f"n{n}_perf.csv"))

    # Read back from CSVs to get formatted strings
    perf_maps = {}
    for n in range(1, 11):
        df = pd.read_csv(os.path.join(output_dir, f"n{n}_perf.csv"))
        perf_maps[n] = dict(zip(df["Metric"], df["Value"]))

    w0 = 8
    w = 14
    header = f"{'N':<{w0}}"
    for n in range(1, 11):
        header += f"N={n:<{w-2}}"
    logger.info(header)
    logger.info("-" * (w0 + w * 10))

    metrics = [
        "Annual Return", "Cumulative Return", "Sharpe Ratio",
        "Max Drawdown", "Win Rate", "Profit/Loss Ratio",
        "Annual Volatility", "Information Ratio", "Final Equity",
    ]

    for m_name in metrics:
        row = f"{m_name:<{w0}}"
        for n in range(1, 11):
            val = perf_maps[n].get(m_name, "N/A")
            row += f"{str(val):<{w}}"
        logger.info(row)

    # Save individual results
    logger.info("\n[3] Saving results...")
    for n in range(1, 11):
        result = results[n]
        if result["equity_curve"] is not None and not result["equity_curve"].empty:
            result["equity_curve"].to_csv(os.path.join(output_dir, f"n{n}_equity.csv"), index=False)
        if result["trade_records"]:
            pd.DataFrame(result["trade_records"]).to_csv(os.path.join(output_dir, f"n{n}_trades.csv"), index=False)
        if result["holding_snapshots"]:
            valid = [h for h in result["holding_snapshots"] if h is not None]
            if valid:
                pd.concat(valid, ignore_index=True).to_csv(os.path.join(output_dir, f"n{n}_holdings.csv"), index=False)

    logger.info(f"\nResults saved to: {output_dir}/")
    logger.info("\n" + "=" * 60)
    logger.info("Test complete!")
    logger.info("=" * 60)

    return results


if __name__ == "__main__":
    run_test()
