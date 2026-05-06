"""
测试：前4月涨幅选股 + 一年三次调仓

调仓时间:
1. 4月底（年报/一季报后）
2. 8月底（中报后）
3. 10月底（三季报后）

策略:
- PB@5 -> 4月涨幅@3（涨最多的入选）
- 一年调三次

对比:
1. 原策略: 年度调仓, PB@5
2. 3x年度 PB-only: 同样3次调仓, 但用PB排序
3. 3x年度 涨幅: 同样3次调仓, 用涨幅排序
"""

import sys
import os
import pickle
import pandas as pd
import numpy as np
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from data_loader import load_stock_pool
from stock_selector import select_stocks, rank_and_limit
from portfolio import Portfolio
from performance import calculate_performance
from log_util import setup_logger


# ============================================================================
# Config
# ============================================================================
TEST_MAX_POSITIONS_PB = 5
TEST_MAX_POSITIONS_FINAL = 3
LOOKBACK_MONTHS = 4           # 前4个月涨幅
REBALANCE_MONTHS = [4, 8, 10] # 4月/8月/10月调仓
INITIAL_CAPITAL = 1_000_000


def generate_3x_cutoff_dates(trading_days: list) -> list:
    """生成每年3次的调仓日: 4月/8月/10月最后一个交易日."""
    sorted_days = sorted(set(pd.to_datetime(trading_days)))
    years = sorted(set(d.year for d in sorted_days))
    results = []
    for year in years:
        for month in REBALANCE_MONTHS:
            month_start = pd.Timestamp(year, month, 1)
            if month == 12:
                month_end = pd.Timestamp(year + 1, 1, 1) - pd.Timedelta(days=1)
            else:
                month_end = pd.Timestamp(year, month + 1, 1) - pd.Timedelta(days=1)
            month_trades = [d for d in sorted_days if month_start <= d <= month_end]
            if not month_trades:
                continue
            cutoff = month_trades[-1]
            next_start = pd.Timestamp(year, month + 1, 1)
            next_trades = [d for d in sorted_days if d >= next_start]
            rebalance = next_trades[0] if next_trades else None
            results.append((cutoff, rebalance))
    results.sort(key=lambda x: x[0])
    return results


def get_lookback_return(code, cutoff_date, price_cache, lookback_months=4):
    """计算某股票过去 lookback_months 个月的涨幅（后复权价格）。"""
    if code not in price_cache or price_cache[code].empty:
        return None
    price_df = price_cache[code]
    cutoff_ts = pd.Timestamp(cutoff_date)
    before_date = cutoff_ts - pd.DateOffset(months=lookback_months)
    row_on = price_df[price_df["trade_date"] == cutoff_date]
    if row_on.empty:
        return None
    close_now = row_on["close"].iloc[0]
    before_df = price_df[price_df["trade_date"] <= before_date]
    if before_df.empty:
        return None
    close_before = before_df.iloc[-1]["close"]
    if close_before <= 0:
        return None
    return (close_now - close_before) / close_before * 100


def rank_by_momentum(selected, cutoff_date, price_cache, max_positions, lookback_months=4):
    """在 PB@5 基础上，按过去 lookback_months 月涨幅排序，取涨最多的前N只."""
    if not selected:
        return []
    pb_selected = selected[:TEST_MAX_POSITIONS_PB]
    if len(pb_selected) <= max_positions:
        return pb_selected

    returns = []
    for code in pb_selected:
        ret = get_lookback_return(code, cutoff_date, price_cache, lookback_months)
        if ret is not None:
            returns.append((code, ret))
        else:
            returns.append((code, -999))

    # 按涨幅降序（涨最多的排前面）
    returns.sort(key=lambda x: x[1], reverse=True)
    return [code for code, _ in returns[:max_positions]]


def get_stock_prices(stock_codes, cutoff, price_cache):
    """获取某日各股票的后复权收盘价."""
    prices = {}
    for code in stock_codes:
        if code in price_cache:
            df = price_cache[code]
            row = df[df["trade_date"] == cutoff]
            if not row.empty:
                prices[code] = row["close"].iloc[0]
    return prices


def run_single_backtest(stock_codes, cutoffs, price_cache, trading_days, bench_map,
                        ranking_method="pb", logger=None):
    """运行一个完整的回测."""
    portfolio = Portfolio(initial_capital=INITIAL_CAPITAL)
    all_trades = []
    all_snapshots = []
    actual_cutoffs = []
    portfolio_states = []

    for cutoff, _rebalance in cutoffs:
        cutoff_ts = pd.Timestamp(cutoff)
        selected, val_df = select_stocks(stock_codes, cutoff_ts, price_cache=price_cache)

        if ranking_method == "pb":
            pb_sel = rank_and_limit(selected, val_df, TEST_MAX_POSITIONS_PB, "pb")
            final = pb_sel[:TEST_MAX_POSITIONS_FINAL] if len(pb_sel) > TEST_MAX_POSITIONS_FINAL else pb_sel
        elif ranking_method == "momentum":
            pb_sel = rank_and_limit(selected, val_df, TEST_MAX_POSITIONS_PB, "pb")
            final = rank_by_momentum(pb_sel, cutoff, price_cache, TEST_MAX_POSITIONS_FINAL, LOOKBACK_MONTHS)
        else:
            final = []

        if logger and final:
            rets = []
            for code in final:
                r = get_lookback_return(code, cutoff, price_cache, LOOKBACK_MONTHS)
                rets.append(f"  {code} (4m: {r:+.1f}%)" if r is not None else f"  {code} (N/A)")
            logger.info(f"  {cutoff}: filtered={len(selected)}, final={len(final)}")
            for r in rets:
                logger.info(r)

        prices = get_stock_prices(stock_codes, cutoff, price_cache)
        if not prices:
            continue

        total_equity = portfolio.get_total_equity(prices)
        plan = portfolio.calculate_target_positions(
            final, total_equity, prices, can_buy=True, can_sell=True
        )

        for code, shares in plan["sell_orders"]:
            p = prices.get(code, 0)
            if p > 0:
                trade = portfolio.sell_shares(code, shares, p * (1 - config.SLIPPAGE_RATE), reason="调仓卖出")
                if trade:
                    trade["trade_date"] = cutoff
                    all_trades.append(trade)

        for code, shares in plan["buy_orders"]:
            p = prices.get(code, 0)
            if p > 0:
                trade = portfolio.buy_shares(code, shares, p * (1 + config.SLIPPAGE_RATE), reason="调仓买入")
                if trade:
                    trade["trade_date"] = cutoff
                    all_trades.append(trade)

        snapshot = portfolio.snapshot_holdings(cutoff, prices)
        all_snapshots.append(snapshot)
        actual_cutoffs.append(cutoff)
        shares_snap = {c: pos["shares"] for c, pos in portfolio.positions.items()}
        portfolio_states.append((pd.Timestamp(cutoff), portfolio.cash, shares_snap))

    # 构建日度净值曲线（策略+基准）
    stock_close_map = {}
    for code, df in price_cache.items():
        if "close" not in df.columns:
            continue
        stock_close_map[code] = dict(zip(df["trade_date"], df["close"]))

    # 基准：等权全部股票
    n_stocks = len(stock_codes)
    strat_equity = []
    bench_equity = []

    if portfolio_states:
        first_rebalance = portfolio_states[0][0]
        state_idx = 0
        cur_cash = portfolio_states[0][1]
        cur_shares = portfolio_states[0][2]

    for day in trading_days:
        day_ts = pd.Timestamp(day)

        # Update portfolio state
        if portfolio_states:
            while state_idx + 1 < len(portfolio_states) and portfolio_states[state_idx + 1][0] <= day_ts:
                state_idx += 1
                cur_cash = portfolio_states[state_idx][1]
                cur_shares = portfolio_states[state_idx][2]

        # Strategy equity
        if not portfolio_states or day_ts < first_rebalance:
            strat_eq = INITIAL_CAPITAL
        else:
            strat_eq = cur_cash
            for code, shares in cur_shares.items():
                if shares > 0 and code in stock_close_map:
                    price = stock_close_map[code].get(day_ts)
                    if price is None:
                        before = {d: p for d, p in stock_close_map[code].items() if d < day_ts}
                        price = before[max(before)] if before else 0
                    strat_eq += shares * price

        # Benchmark equity: loaded from intermediate (same benchmark for all)
        bench_eq = bench_map.get(day_ts, INITIAL_CAPITAL)

        strat_equity.append(strat_eq)
        bench_equity.append(bench_eq if bench_eq > 0 else INITIAL_CAPITAL)

    equity_df = pd.DataFrame({
        "date": pd.to_datetime(trading_days),
        "strategy_equity": strat_equity,
        "benchmark_equity": bench_equity,
    })

    perf = calculate_performance(equity_df, actual_cutoffs, all_trades)

    return {
        "equity_curve": equity_df,
        "trade_records": all_trades,
        "holding_snapshots": all_snapshots,
        "cutoff_dates": actual_cutoffs,
        "performance": perf,
    }


def run_test():
    logger = setup_logger("test_momentum_3x", "test_momentum_3x")
    logger.info("=" * 60)
    logger.info("Test: 3x/Year Rebalance with 4-Month Momentum")
    logger.info(f"  Cutoff months: {REBALANCE_MONTHS}")
    logger.info(f"  Lookback: {LOOKBACK_MONTHS} months (highest gainers)")
    logger.info(f"  Positions: PB@{TEST_MAX_POSITIONS_PB} -> Momentum@{TEST_MAX_POSITIONS_FINAL}")
    logger.info("=" * 60)

    # Load data
    logger.info("\n[1] Loading stock pool & intermediate data...")
    pool_df = load_stock_pool()
    stock_codes = pool_df["code"].tolist()

    with open(os.path.join(config.DATA_OUTPUT_DIR, "intermediate.pkl"), "rb") as f:
        intermediate = pickle.load(f)

    price_cache = intermediate["price_cache"]
    trading_days = intermediate["trading_days"]

    logger.info(f"  Stocks: {len(stock_codes)}, Trading days: {len(trading_days)}")

    # Generate 3x/year cutoff dates
    cutoffs_3x = generate_3x_cutoff_dates(trading_days)
    logger.info(f"\n[2] Generated {len(cutoffs_3x)} cutoff dates (3x/year):")
    for c, r in cutoffs_3x[:9]:
        logger.info(f"    {c.strftime('%Y-%m-%d')} -> rebalance {r.strftime('%Y-%m-%d') if r else 'N/A'}")
    logger.info(f"    ... ({len(cutoffs_3x)} total)")

    # Load original annual results
    logger.info("\n[3] Loading original annual results...")
    old_cutoffs = intermediate["cutoff_dates"]
    old_trades = intermediate["trade_records"]
    old_holdings = intermediate["holding_snapshots"]
    old_equity = intermediate["equity_curve"]
    old_perf = calculate_performance(old_equity, old_cutoffs, old_trades)

    # Build benchmark map from intermediate equity curve
    bench_map = dict(zip(pd.to_datetime(old_equity["date"]), old_equity["benchmark_equity"]))

    # Run 3x/year PB-only strategy
    logger.info("\n[4] Running 3x/year PB-only strategy...")
    result_3x_pb = run_single_backtest(stock_codes, cutoffs_3x, price_cache, trading_days, bench_map,
                                        ranking_method="pb", logger=logger)
    logger.info(f"  Trades: {len(result_3x_pb['trade_records'])}")

    # Run 3x/year Momentum strategy
    logger.info("\n[5] Running 3x/year Momentum strategy...")
    result_3x_mom = run_single_backtest(stock_codes, cutoffs_3x, price_cache, trading_days, bench_map,
                                         ranking_method="momentum", logger=logger)
    logger.info(f"  Trades: {len(result_3x_mom['trade_records'])}")

    # Performance comparison
    logger.info("\n" + "=" * 60)
    logger.info("Performance Comparison")
    logger.info("=" * 60)

    from performance import save_performance_summary

    strategies = [
        ("Original(Annual PB@5)", old_perf),
        ("3x/yr PB-only", result_3x_pb["performance"]),
        ("3x/yr Momentum@3", result_3x_mom["performance"]),
    ]

    output_dir = os.path.join(config.DATA_OUTPUT_DIR, "momentum_3x_yearly")
    os.makedirs(output_dir, exist_ok=True)

    for name, perf in strategies:
        save_performance_summary(perf, os.path.join(output_dir, f"{name.replace(' ', '_').replace('/', '')}_perf.csv"))

    # Read formatted values
    perf_maps = {}
    for name, _ in strategies:
        fname = name.replace(" ", "_").replace("/", "")
        df = pd.read_csv(os.path.join(output_dir, f"{fname}_perf.csv"))
        perf_maps[name] = dict(zip(df["Metric"], df["Value"]))

    w0 = 25
    w = 22
    header = f"{'Metric':<{w0}}"
    for name, _ in strategies:
        header += f"{name:<{w}}"
    logger.info(header)
    logger.info("-" * (w0 + w * 3))

    metrics = [
        "Cumulative Return", "Annual Return", "Annual Volatility",
        "Sharpe Ratio", "Max Drawdown", "Win Rate",
        "Profit/Loss Ratio", "Avg Weekly Turnover",
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

    # Annual holdings for momentum strategy
    logger.info("\n" + "=" * 60)
    logger.info("Annual Holdings (3x/year Momentum)")
    logger.info("=" * 60)

    mom_holdings = result_3x_mom["holding_snapshots"]
    if mom_holdings:
        mom_df = pd.concat([h for h in mom_holdings if h is not None], ignore_index=True)
        if not mom_df.empty:
            mom_df["year"] = pd.to_datetime(mom_df["rebalance_date"]).dt.year
            for year in sorted(mom_df["year"].unique()):
                codes = mom_df[mom_df["year"] == year]["stock_code"].tolist()
                dates = mom_df[mom_df["year"] == year]["rebalance_date"].unique()
                logger.info(f"\n  {year} ({len(dates)} rebalances):")
                for d in sorted(dates):
                    subset = mom_df[mom_df["rebalance_date"] == d]["stock_code"].tolist()
                    logger.info(f"    {d}: {', '.join(subset)}")

    # Save results
    logger.info("\n[6] Saving results...")
    for name, result in [("3x_pb", result_3x_pb), ("3x_momentum", result_3x_mom)]:
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

    return old_perf, result_3x_pb["performance"], result_3x_mom["performance"]


if __name__ == "__main__":
    run_test()
