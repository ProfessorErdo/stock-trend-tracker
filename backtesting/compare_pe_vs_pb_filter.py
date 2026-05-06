"""
对比：PE+ROE 筛选 vs PB+ROE 筛选（都用 PB 排名取前5）

两种策略结构相同，只有 Step2 过滤指标不同：
- PE+ROE: Step2 只保留 PE < 25% 的股票 → Step3 ROE > 75% → 按 PB 排序取前5
- PB+ROE: Step2 只保留 PB < 25% 的股票 → Step3 ROE > 75% → 按 PB 排序取前5

注意：原策略是 PE/PB/PR 三者 AND 都<25%，这里拆成单一指标。
"""

import sys
import os
import pickle
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from data_loader import load_stock_pool, load_financial_data
from stock_selector import get_latest_financial_data, calculate_valuation, winsorize, is_new_stock, rank_and_limit
from portfolio import Portfolio
from performance import calculate_performance
from log_util import setup_logger

TEST_MAX_POSITIONS = 5


def select_stocks_pe_or_pb(stock_codes, trade_date, price_cache, filter_metric: str):
    """
    选股：Step1(基础) → Step2(单一指标<25%) → Step3(ROE>75%) → Step4(新股排除)

    filter_metric: "pe" or "pb"
    Returns: (selected_codes, val_df)
    """
    all_valuations = []

    for code in stock_codes:
        if price_cache is not None and code in price_cache:
            price_df = price_cache[code]
        else:
            continue  # no price data

        if trade_date not in price_df["trade_date"].values:
            continue

        fin_data = get_latest_financial_data(code, trade_date)
        if fin_data is None:
            continue

        valuation = calculate_valuation(price_df, trade_date, fin_data)
        if valuation is None:
            continue

        if valuation["pe_ttm"] <= 0 or valuation["pb_ttm"] <= 0 or \
           valuation["pr_ttm"] <= 0 or valuation["roe_ttm"] <= 0:
            continue

        all_valuations.append({"code": code, **valuation})

    if not all_valuations:
        return [], pd.DataFrame()

    val_df = pd.DataFrame(all_valuations)

    # Winsorize
    if config.WINSORIZE_ENABLED:
        val_df["pe_w"] = winsorize(val_df["pe_ttm"], config.WINSORIZE_LOWER, config.WINSORIZE_UPPER)
        val_df["pb_w"] = winsorize(val_df["pb_ttm"], config.WINSORIZE_LOWER, config.WINSORIZE_UPPER)
        val_df["pr_w"] = winsorize(val_df["pr_ttm"], config.WINSORIZE_LOWER, config.WINSORIZE_UPPER)

        if filter_metric == "pe":
            cut = val_df["pe_w"].quantile(config.PE_THRESHOLD)
            step2 = val_df[val_df["pe_ttm"] <= cut]
        else:  # pb
            cut = val_df["pb_w"].quantile(config.PB_THRESHOLD)
            step2 = val_df[val_df["pb_ttm"] <= cut]
    else:
        if filter_metric == "pe":
            cut = val_df["pe_ttm"].quantile(config.PE_THRESHOLD)
            step2 = val_df[val_df["pe_ttm"] <= cut]
        else:
            cut = val_df["pb_ttm"].quantile(config.PB_THRESHOLD)
            step2 = val_df[val_df["pb_ttm"] <= cut]

    if step2.empty:
        return [], val_df.drop(columns=["pe_w", "pb_w", "pr_w"], errors="ignore")

    # Step 3 - ROE filter on full candidate pool
    roe_cut = val_df["roe_ttm"].quantile(config.ROE_THRESHOLD)
    step3 = step2[step2["roe_ttm"] >= roe_cut]

    if step3.empty:
        return [], val_df.drop(columns=["pe_w", "pb_w", "pr_w"], errors="ignore")

    # Step 4 - 新股排除
    selected = []
    for _, row in step3.iterrows():
        code = row["code"]
        p_df = price_cache.get(code) if price_cache else load_price_data_for_code(code)
        if not is_new_stock(code, p_df, trade_date, config.NEW_STOCK_EXCLUDE_DAYS):
            selected.append(code)

    clean_df = val_df.drop(columns=["pe_w", "pb_w", "pr_w"], errors="ignore")
    return selected, clean_df


def load_price_data_for_code(code):
    from data_loader import load_price_data
    return load_price_data(code)


def execute_rebalance(portfolio, target_codes, rebalance_date, stock_codes,
                      price_cache, ranking_metric: str):
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
                 filter_metric: str, ranking_metric: str, logger=None):
    """
    filter_metric: "pe" or "pb" — Step2用什么指标过滤
    ranking_metric: "pe" or "pb" — 排序取前5用什么指标
    """
    portfolio = Portfolio(initial_capital=config.INITIAL_CAPITAL)
    all_trades = []
    all_snapshots = []
    actual_cutoffs = []
    portfolio_states = []

    for cutoff, rebalance in cutoffs_with_rebalance:
        cutoff_ts = pd.Timestamp(cutoff)

        selected, val_df = select_stocks_pe_or_pb(stock_codes, cutoff_ts, price_cache, filter_metric)

        if not selected:
            if logger:
                logger.info(f"  {cutoff}: filtered=0, final=0")
            continue

        final = rank_and_limit(selected, val_df, TEST_MAX_POSITIONS, ranking_metric)

        if logger and final:
            for code in final:
                row = val_df[val_df["code"] == code]
                if not row.empty:
                    r = row.iloc[0]
                    logger.info(f"    {code} (PB={r['pb_ttm']:.2f}, PE={r['pe_ttm']:.2f}, ROE={r['roe_ttm']:.2%})")
            logger.info(f"  {cutoff}: filtered={len(selected)}, final={len(final)}")

        exec_date = rebalance if rebalance is not None else cutoff
        trades, snapshot = execute_rebalance(portfolio, final, exec_date, stock_codes, price_cache, ranking_metric)
        all_trades.extend(trades)
        all_snapshots.append(snapshot)
        actual_cutoffs.append(cutoff)
        shares_snap = {c: pos["shares"] for c, pos in portfolio.positions.items()}
        portfolio_states.append((pd.Timestamp(exec_date), portfolio.cash, shares_snap))

    # 构建日度净值曲线
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

    logger = setup_logger("compare_pe_pb", "compare_pe_pb")
    logger.info("=" * 60)
    logger.info("Comparison: PE+ROE filter → PE rank  vs  PB+ROE filter → PB rank")
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

    # Run both strategies — both use PB ranking, only filter differs
    strategies = [
        ("pe_pb", "PE+ROE → PB rank"),
        ("pb_pb", "PB+ROE → PB rank"),
    ]

    results = {}
    for method, label in strategies:
        filter_m = method.split("_")[0]
        rank_m = method.split("_")[1]  # always "pb"
        logger.info(f"\n[Running] {label}...")
        result = run_backtest(stock_codes, cutoffs_with_rebalance, price_cache, trading_days,
                              filter_m, rank_m, logger)
        results[method] = result
        logger.info(f"  Trades: {len(result['trade_records'])}")

    # Performance comparison
    logger.info("\n" + "=" * 60)
    logger.info("Performance Comparison")
    logger.info("=" * 60)

    from performance import save_performance_summary

    output_dir = os.path.join(config.DATA_OUTPUT_DIR, "pe_vs_pb_test")
    os.makedirs(output_dir, exist_ok=True)

    strat_list = [(method, label, results[method]["performance"]) for method, label in strategies]

    for method, label, perf in strat_list:
        save_performance_summary(perf, os.path.join(output_dir, f"{method}_perf.csv"))

    perf_maps = {}
    for method, _, _ in strat_list:
        df = pd.read_csv(os.path.join(output_dir, f"{method}_perf.csv"))
        perf_maps[method] = dict(zip(df["Metric"], df["Value"]))

    w0 = 25
    w = 25
    header = f"{'Metric':<{w0}}"
    for _, label, _ in strat_list:
        header += f"{label:<{w}}"
    logger.info(header)
    logger.info("-" * (w0 + w * len(strat_list)))

    metrics = [
        "Cumulative Return", "Annual Return", "Annual Volatility",
        "Sharpe Ratio", "Max Drawdown", "Win Rate",
        "Profit/Loss Ratio",
    ]
    for m in metrics:
        row = f"{m:<{w0}}"
        for method, _, _ in strat_list:
            val = str(perf_maps[method].get(m, "N/A"))
            row += f"{val:<{w}}"
        logger.info(row)

    logger.info("")
    for m in ["Final Equity", "Benchmark Cumulative Return", "Excess Return", "Information Ratio"]:
        row = f"{m:<{w0}}"
        for method, _, _ in strat_list:
            val = str(perf_maps[method].get(m, "N/A"))
            row += f"{val:<{w}}"
        logger.info(row)

    # Year-by-year holdings comparison
    logger.info("\n" + "=" * 60)
    logger.info("Annual Holdings Comparison")
    logger.info("=" * 60)

    for method, label, _ in strat_list:
        result = results[method]
        logger.info(f"\n--- {label} ---")
        snapshots = result["holding_snapshots"]
        cutoffs = result["cutoff_dates"]
        for i, cutoff in enumerate(cutoffs):
            if i < len(snapshots) and snapshots[i] is not None:
                snap = snapshots[i]
                if not snap.empty:
                    logger.info(f"  {str(cutoff)[:10]}: ({len(snap)} stocks)")
                    for _, row in snap.iterrows():
                        logger.info(f"    {row['stock_code']} (weight={row['weight']:.1%})")

    # Save results
    logger.info("\n[5] Saving results...")
    for method, _, _ in strat_list:
        result = results[method]
        if result["equity_curve"] is not None and not result["equity_curve"].empty:
            result["equity_curve"].to_csv(os.path.join(output_dir, f"{method}_equity.csv"), index=False)
        if result["trade_records"]:
            pd.DataFrame(result["trade_records"]).to_csv(os.path.join(output_dir, f"{method}_trades.csv"), index=False)
        if result["holding_snapshots"]:
            valid = [h for h in result["holding_snapshots"] if h is not None]
            if valid:
                pd.concat(valid, ignore_index=True).to_csv(os.path.join(output_dir, f"{method}_holdings.csv"), index=False)

    logger.info(f"\nResults saved to: {output_dir}/")
    logger.info("\n" + "=" * 60)
    logger.info("Test complete!")
    logger.info("=" * 60)

    return {method: perf for method, _, perf in strat_list}


def filter_metric_for_method(method: str) -> str:
    return method.split("_")[0]


if __name__ == "__main__":
    run_test()
