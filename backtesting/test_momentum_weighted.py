"""
测试：用前12个月跌幅排序选股，替代PB排序

策略对比:
- 原策略: 四步筛选 + PB最低前5只等权
- 新策略: 四步筛选 + 前12月跌幅最大前3只等权

不做任何核心代码修改，完全独立运行。
"""

import sys
import os
import pickle
import pandas as pd
import numpy as np
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from data_loader import load_stock_pool, load_price_data
from stock_selector import select_stocks
from portfolio import Portfolio
from performance import calculate_performance
from log_util import setup_logger


# ============================================================================
# Config for this test
# ============================================================================
TEST_MAX_POSITIONS_PB = 5     # PB排序保留5只
TEST_MAX_POSITIONS_FINAL = 3  # 涨幅再筛选3只
LOOKBACK_MONTHS = 4           # 回溯窗口（月），用于计算涨幅
REBALANCE_FREQ = "annual"     # 年度调仓
START_DATE = "2015-01-01"
INITIAL_CAPITAL = 1_000_000


def get_lookback_return(code: str, cutoff_date: pd.Timestamp, price_cache: dict, lookback_months: int = 3) -> float | None:
    """
    计算某股票过去 lookback_months 个月的涨幅（后复权价格）。
    """
    if code not in price_cache or price_cache[code].empty:
        return None

    price_df = price_cache[code]
    cutoff_ts = pd.Timestamp(cutoff_date)
    before_date = cutoff_ts - pd.DateOffset(months=lookback_months)

    # 取调仓日当天的收盘价（后复权）
    row_on = price_df[price_df["trade_date"] == cutoff_date]
    if row_on.empty:
        return None
    close_now = row_on["close"].iloc[0]

    # 取 lookback 前最近一天的收盘价
    before_df = price_df[price_df["trade_date"] <= before_date]
    if before_df.empty:
        return None
    close_before = before_df.iloc[-1]["close"]

    if close_before <= 0:
        return None
    return (close_now - close_before) / close_before * 100


def rank_by_price_decline(
    selected: list,
    cutoff_date: pd.Timestamp,
    price_cache: dict,
    max_positions: int,
    lookback_months: int = 3,
) -> list:
    """
    在 PB 已排序的前5只基础上，再按过去 lookback_months 个月跌幅排序，取跌幅最大的前N只。

    两步筛选:
    1. 按 PB 最低取前 5 只（保留PB重排步骤）
    2. 在这 5 只中，按过去N月涨幅升序，取跌幅最大的前 max_positions 只

    Args:
        selected: 通过四步筛选的股票代码列表
        cutoff_date: 截面日
        price_cache: 价格缓存
        max_positions: 最终最多选几只（默认3）
        lookback_months: 回溯窗口月数（默认3）

    Returns:
        按跌幅排序的前 max_positions 只股票代码
    """
    if not selected:
        return []

    pb_selected = selected[:TEST_MAX_POSITIONS_PB]

    if len(pb_selected) <= max_positions:
        return pb_selected

    # Step B: 在 PB 选出的5只中，按过去N月跌幅排序
    returns = []
    no_data = []
    for code in pb_selected:
        ret = get_lookback_return(code, cutoff_date, price_cache, lookback_months)
        if ret is not None:
            returns.append((code, ret))
        else:
            no_data.append(code)

    if not returns:
        # 无法计算涨幅的，回退到 PB 排序的前 max_positions 只
        return pb_selected[:max_positions]

    # 按涨幅降序（涨得最多的排前面）
    returns.sort(key=lambda x: x[1], reverse=True)
    result = [code for code, _ in returns[:max_positions]]

    # 如果涨幅排完不够 max_positions，用 PB 剩余的补上
    if len(result) < max_positions:
        already = set(result)
        for code in pb_selected:
            if code not in already and len(result) < max_positions:
                result.append(code)

    return result


def run_test_backtest():
    """执行完整的测试回测流程"""
    logger = setup_logger("test_momentum_weighted", "test_momentum")
    logger.info("=" * 60)
    logger.info("Test: 跌幅加权选股 vs 原PB选股")
    logger.info(f"  Max positions: {TEST_MAX_POSITIONS_FINAL} (vs original 5)")
    logger.info(f"  Ranking: PB@{TEST_MAX_POSITIONS_PB} → Decline@{TEST_MAX_POSITIONS_FINAL} (vs original PB@5)")
    logger.info("=" * 60)

    # ---------------------------------------------------------------
    # Step 1: Load stock pool & build cutoff dates (annual)
    # ---------------------------------------------------------------
    logger.info("\n[Step 1] Loading stock pool...")
    pool_df = load_stock_pool()
    stock_codes = pool_df["code"].tolist()
    logger.info(f"  Total stocks: {len(stock_codes)}")

    # Load cutoff dates from existing annual backtest intermediate results
    logger.info("\n[Step 2] Loading cutoff dates from existing annual backtest...")
    intermediate_path = os.path.join(config.DATA_OUTPUT_DIR, "intermediate.pkl")
    with open(intermediate_path, "rb") as f:
        old_result = pickle.load(f)

    cutoff_dates = old_result["cutoff_dates"]
    portfolio_states = old_result["portfolio_states"]
    price_cache = old_result["price_cache"]

    logger.info(f"  Cutoff dates ({len(cutoff_dates)}):")
    for c in cutoff_dates:
        logger.info(f"    {c}")

    # Also load existing results for comparison
    old_equity_curve = old_result["equity_curve"]
    old_trades = old_result["trade_records"]
    old_holdings = old_result["holding_snapshots"]

    # Compute original performance
    logger.info("\n>>> Computing original strategy performance...")
    old_perf = calculate_performance(old_equity_curve, cutoff_dates, old_trades)

    # ---------------------------------------------------------------
    # Step 3: Run the new strategy (price-decline ranking, top 3)
    # ---------------------------------------------------------------
    logger.info("\n[Step 3] Running two-stage ranking backtest...")
    logger.info(f"  Stage 1: PB-lowest top {TEST_MAX_POSITIONS_PB}")
    logger.info(f"  Stage 2: {LOOKBACK_MONTHS}-month decline top {TEST_MAX_POSITIONS_FINAL}")

    portfolio = Portfolio(initial_capital=INITIAL_CAPITAL)
    trade_records = []
    holding_snapshots = []

    prev_selected = []
    all_cutoffs = []

    for cutoff in cutoff_dates:
        cutoff_ts = pd.Timestamp(cutoff)

        # Stage 1: 4-step filter + PB ranking (top 5)
        from stock_selector import rank_and_limit
        selected, val_df = select_stocks(stock_codes, cutoff_ts, price_cache=price_cache)
        pb_selected = rank_and_limit(selected, val_df, TEST_MAX_POSITIONS_PB, "pb")

        # Stage 2: Price decline ranking (top 3)
        final_selected = rank_by_price_decline(
            pb_selected, cutoff_ts, price_cache, TEST_MAX_POSITIONS_FINAL
        )

        logger.info(f"\n  {cutoff}: 4step={len(selected)}, PB@5={len(pb_selected)}, decline@3={len(final_selected)}")
        if final_selected:
            for code in final_selected:
                ret = get_lookback_return(code, cutoff_ts, price_cache, LOOKBACK_MONTHS)
                ret_str = f"{ret:+.1f}%" if ret is not None else "N/A"
                logger.info(f"    {code} (12m: {ret_str})")

        prev_selected = final_selected

        # Execution: use cutoff date close as fill price (same as original annual backtest)
        prices = {}
        prev_prices = {}
        for code in stock_codes:
            if code in price_cache:
                df = price_cache[code]
                row = df[df["trade_date"] == cutoff]
                if not row.empty:
                    prices[code] = row["close"].iloc[0]
                before = df[df["trade_date"] < cutoff]
                if not before.empty:
                    prev_prices[code] = before["close"].iloc[-1]

        if not prices:
            continue

        # Calculate total equity and execute trades
        total_equity = portfolio.get_total_equity(prices)
        plan = portfolio.calculate_target_positions(
            final_selected, total_equity, prices, can_buy=True, can_sell=True
        )

        # Sell first
        for code, shares_to_sell in plan["sell_orders"]:
            price = prices.get(code, 0)
            if price <= 0:
                continue
            exec_price = price * (1 - config.SLIPPAGE_RATE)
            trade = portfolio.sell_shares(code, shares_to_sell, exec_price, reason="调仓卖出")
            if trade:
                trade["trade_date"] = cutoff
                trade_records.append(trade)

        # Then buy
        for code, shares_to_buy in plan["buy_orders"]:
            price = prices.get(code, 0)
            if price <= 0:
                continue
            exec_price = price * (1 + config.SLIPPAGE_RATE)
            trade = portfolio.buy_shares(code, shares_to_buy, exec_price, reason="调仓买入")
            if trade:
                trade["trade_date"] = cutoff
                trade_records.append(trade)

        # Record snapshot
        snapshot = portfolio.snapshot_holdings(cutoff, prices)
        holding_snapshots.append(snapshot)
        all_cutoffs.append(cutoff)

    logger.info(f"\n  Total trades: {len(trade_records)}")

    # ---------------------------------------------------------------
    # Step 4: Build equity curve for new strategy
    # ---------------------------------------------------------------
    logger.info("\n[Step 4] Building equity curve for new strategy...")

    # Build price lookup for HFQ close
    stock_close_map = {}
    for code, df in price_cache.items():
        if "close" not in df.columns:
            continue
        stock_close_map[code] = dict(zip(df["trade_date"], df["close"]))

    trading_days = old_result["trading_days"]
    portfolio_states_new = []
    state_idx = 0

    # Rebuild portfolio states from the new backtest
    # We need to recreate the portfolio state at each rebalance
    # Since we didn't save portfolio_states, let's rebuild from snapshots

    # Re-run to get portfolio states
    portfolio2 = Portfolio(initial_capital=INITIAL_CAPITAL)
    portfolio_states_new = []

    prev_selected = []
    for cutoff in cutoff_dates:
        cutoff_ts = pd.Timestamp(cutoff)

        selected, val_df = select_stocks(stock_codes, cutoff_ts, price_cache=price_cache)
        pb_selected = rank_and_limit(selected, val_df, TEST_MAX_POSITIONS_PB, "pb")
        final_selected = rank_by_price_decline(
            pb_selected, cutoff_ts, price_cache, TEST_MAX_POSITIONS_FINAL
        )
        prev_selected = final_selected

        prices = {}
        for code in stock_codes:
            if code in price_cache:
                df = price_cache[code]
                row = df[df["trade_date"] == cutoff]
                if not row.empty:
                    prices[code] = row["close"].iloc[0]

        if not prices:
            continue

        total_equity = portfolio2.get_total_equity(prices)
        plan = portfolio2.calculate_target_positions(
            final_selected, total_equity, prices, can_buy=True, can_sell=True
        )

        for code, shares_to_sell in plan["sell_orders"]:
            price = prices.get(code, 0)
            if price <= 0:
                continue
            exec_price = price * (1 - config.SLIPPAGE_RATE)
            portfolio2.sell_shares(code, shares_to_sell, exec_price, reason="调仓卖出")

        for code, shares_to_buy in plan["buy_orders"]:
            price = prices.get(code, 0)
            if price <= 0:
                continue
            exec_price = price * (1 + config.SLIPPAGE_RATE)
            portfolio2.buy_shares(code, shares_to_buy, exec_price, reason="调仓买入")

        shares_snapshot = {code: pos["shares"] for code, pos in portfolio2.positions.items()}
        portfolio_states_new.append((cutoff_ts, portfolio2.cash, shares_snapshot))

    # Build daily equity curve
    strategy_equity = []
    if portfolio_states_new:
        first_rebalance = portfolio_states_new[0][0]
        state_idx = 0
        current_cash = portfolio_states_new[0][1]
        current_shares = portfolio_states_new[0][2]

        for day in trading_days:
            day_ts = pd.Timestamp(day)

            while state_idx + 1 < len(portfolio_states_new) and portfolio_states_new[state_idx + 1][0] <= day_ts:
                state_idx += 1
                current_cash = portfolio_states_new[state_idx][1]
                current_shares = portfolio_states_new[state_idx][2]

            if day_ts < first_rebalance:
                equity = INITIAL_CAPITAL
            else:
                equity = current_cash
                for code, shares in current_shares.items():
                    if shares > 0 and code in stock_close_map:
                        price = stock_close_map[code].get(day_ts)
                        if price is not None:
                            equity += shares * price
                        else:
                            before_prices = {d: p for d, p in stock_close_map[code].items() if d < day_ts}
                            if before_prices:
                                equity += shares * before_prices[max(before_prices)]

            strategy_equity.append({"date": day_ts, "strategy_equity": equity})

    strategy_df = pd.DataFrame(strategy_equity)

    # Merge with benchmark
    benchmark_df = old_equity_curve[["date", "benchmark_equity"]].copy()
    equity_curve = strategy_df.merge(benchmark_df, on="date", how="left")
    equity_curve["benchmark_equity"] = equity_curve["benchmark_equity"].ffill()
    equity_curve["benchmark_equity"] = equity_curve["benchmark_equity"].fillna(INITIAL_CAPITAL)

    # ---------------------------------------------------------------
    # Step 5: Compute performance
    # ---------------------------------------------------------------
    logger.info("\n[Step 5] Computing performance...")
    new_perf = calculate_performance(equity_curve, all_cutoffs, trade_records)

    # ---------------------------------------------------------------
    # Step 6: Compare results
    # ---------------------------------------------------------------
    logger.info("\n" + "=" * 60)
    logger.info("Performance Comparison")
    logger.info("=" * 60)

    # Use save_performance_summary to get formatted output
    from performance import save_performance_summary
    save_performance_summary(old_perf, os.path.join(config.DATA_OUTPUT_DIR, "momentum_test", "original_perf.csv"))
    save_performance_summary(new_perf, os.path.join(config.DATA_OUTPUT_DIR, "momentum_test", "decline3_perf.csv"))

    # Read back formatted values
    old_df = pd.read_csv(os.path.join(config.DATA_OUTPUT_DIR, "momentum_test", "original_perf.csv"))
    new_df = pd.read_csv(os.path.join(config.DATA_OUTPUT_DIR, "momentum_test", "decline3_perf.csv"))

    perf_map_old = dict(zip(old_df['Metric'], old_df['Value']))
    perf_map_new = dict(zip(new_df['Metric'], new_df['Value']))

    metrics = [
        "Cumulative Return", "Annual Return", "Annual Volatility",
        "Sharpe Ratio", "Max Drawdown", "Win Rate",
        "Profit/Loss Ratio", "Avg Weekly Turnover",
    ]

    logger.info(f"\n{'Metric':<25} {'Original(PB@5)':>15} {'PB@5→Decline@3':>15}")
    logger.info("-" * 58)
    for m in metrics:
        old_val = perf_map_old.get(m, "N/A")
        new_val = perf_map_new.get(m, "N/A")
        logger.info(f"{m:<25} {str(old_val):>15} {str(new_val):>15}")

    # Extra metrics
    logger.info(f"\n{'Final Equity':<25} {perf_map_old.get('Final Equity', 'N/A'):>15} {perf_map_new.get('Final Equity', 'N/A'):>15}")
    logger.info(f"{'Benchmark Return':<25} {perf_map_old.get('Benchmark Cumulative Return', 'N/A'):>15} {perf_map_new.get('Benchmark Cumulative Return', 'N/A'):>15}")
    logger.info(f"{'Excess Return':<25} {perf_map_old.get('Excess Return', 'N/A'):>15} {perf_map_new.get('Excess Return', 'N/A'):>15}")
    logger.info(f"{'Info Ratio':<25} {perf_map_old.get('Information Ratio', 'N/A'):>15} {perf_map_new.get('Information Ratio', 'N/A'):>15}")

    # ---------------------------------------------------------------
    # Step 7: Print annual holdings comparison
    # ---------------------------------------------------------------
    logger.info("\n" + "=" * 60)
    logger.info("Annual Holdings Comparison")
    logger.info("=" * 60)

    # Parse old holdings
    old_holdings_df = pd.concat(old_holdings, ignore_index=True)
    old_holdings_by_year = {}
    for _, row in old_holdings_df.iterrows():
        year = pd.Timestamp(row["rebalance_date"]).year
        if year not in old_holdings_by_year:
            old_holdings_by_year[year] = []
        old_holdings_by_year[year].append(row["stock_code"])

    # Parse new holdings
    new_holdings_df = pd.concat(holding_snapshots, ignore_index=True)
    new_holdings_by_year = {}
    for _, row in new_holdings_df.iterrows():
        year = pd.Timestamp(row["rebalance_date"]).year
        if year not in new_holdings_by_year:
            new_holdings_by_year[year] = []
        new_holdings_by_year[year].append(row["stock_code"])

    all_years = sorted(set(list(old_holdings_by_year.keys()) + list(new_holdings_by_year.keys())))

    for year in all_years:
        old_codes = old_holdings_by_year.get(year, [])
        new_codes = new_holdings_by_year.get(year, [])

        old_str = ", ".join(old_codes) if old_codes else "-"
        new_str = ", ".join(new_codes) if new_codes else "-"

        # Check overlap
        overlap = set(old_codes) & set(new_codes)
        overlap_str = f" (overlap: {len(overlap)})" if overlap else ""

        logger.info(f"\n  {year}:")
        logger.info(f"    Original(PB@5): {old_str}")
        logger.info(f"    PB@5→Decline@3: {new_str}{overlap_str}")

    # ---------------------------------------------------------------
    # Step 8: Save results
    # ---------------------------------------------------------------
    output_dir = os.path.join(config.DATA_OUTPUT_DIR, "momentum_test")
    os.makedirs(output_dir, exist_ok=True)

    equity_curve.to_csv(os.path.join(output_dir, "equity_curve.csv"), index=False)
    if trade_records:
        pd.DataFrame(trade_records).to_csv(os.path.join(output_dir, "trades.csv"), index=False)
    if holding_snapshots:
        pd.concat(holding_snapshots, ignore_index=True).to_csv(
            os.path.join(output_dir, "holdings.csv"), index=False
        )

    # Save performance summary
    perf_rows = []
    for name, perf in [("original", old_perf), ("pb5_decline3", new_perf)]:
        for k, v in perf.items():
            perf_rows.append({"strategy": name, "metric": k, "value": v})
    pd.DataFrame(perf_rows).to_csv(os.path.join(output_dir, "performance.csv"), index=False)

    logger.info(f"\nResults saved to: {output_dir}/")

    logger.info("\n" + "=" * 60)
    logger.info("Test complete!")
    logger.info("=" * 60)

    return old_perf, new_perf


if __name__ == "__main__":
    run_test_backtest()
