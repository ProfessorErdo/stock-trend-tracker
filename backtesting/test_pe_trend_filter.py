"""
测试：PE 趋势预筛选 + PB/ROE 筛选 + PB 排序

三步筛选:
1. 新增: 排除 PE_ratio 最低 10%（排除"从亏损恢复"的假性低PE）
   PE_ratio = 截面日 PE / 前一年 PE 均值
   负PE → 赋 1000（大值）
2. 原 Step 2: PB < 25% AND ROE > 75%
3. 原 Step 3: PB 排序取前 5

PE history 从 data/processed/backtesting/pe_history/*.csv 读取

对比:
- 原策略: PB+ROE筛选 → PB排序前5
- 新策略: PE趋势预筛 → PB+ROE筛选 → PB排序前5
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


# ============================================================================
# Config
# ============================================================================
TEST_MAX_POSITIONS = 5
PE_TREND_EXCLUDE_PCT = 0.10   # 排除最高/最低各 10%
PE_NEG_VALUE = 1000           # 负PE赋的大值
PE_HISTORY_DIR = os.path.join(config.DATA_OUTPUT_DIR, "pe_history")


def load_pe_history(code: str) -> pd.DataFrame | None:
    """读取单只股票的 PE history CSV."""
    path = os.path.join(PE_HISTORY_DIR, f"pe_{code}.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path, parse_dates=["trade_date"])
    return df


def compute_pe_ratios_for_cutoff(cutoff_date: pd.Timestamp, stock_codes: list,
                                  pe_cache: dict, lookback_years: int = 3) -> dict:
    """
    对截面日，计算每只股票的 PE_ratio = current_PE / avg_PE.

    Args:
        cutoff_date: 截面日
        stock_codes: 股票池
        pe_cache: {code: DataFrame(trade_date, pe)}
        lookback_years: 回溯年数（默认3）

    Returns:
        {code: pe_ratio}
    """
    cutoff_ts = pd.Timestamp(cutoff_date)
    start_date = cutoff_ts - pd.DateOffset(years=lookback_years)
    results = {}

    for code in stock_codes:
        if code not in pe_cache:
            continue
        pe_df = pe_cache[code]
        if pe_df.empty:
            continue

        # 截面日 PE（当天或之前最近一天）
        on_day = pe_df[pe_df["trade_date"] == cutoff_ts]
        if not on_day.empty:
            current_pe = on_day.iloc[0]["pe"]
        else:
            before = pe_df[pe_df["trade_date"] <= cutoff_ts]
            if before.empty:
                continue
            current_pe = before.iloc[-1]["pe"]

        # 前1年 PE 均值
        window = pe_df[(pe_df["trade_date"] >= start_date) & (pe_df["trade_date"] <= cutoff_ts)]
        valid_pe = window["pe"].dropna()

        if valid_pe.empty or valid_pe.mean() <= 0:
            # 没有有效历史PE，给中性值
            results[code] = 1.0
            continue

        avg_pe = valid_pe.mean()

        # 当前PE为负 → 大值
        if pd.isna(current_pe) or current_pe <= 0:
            results[code] = PE_NEG_VALUE
        else:
            results[code] = current_pe / avg_pe

    return results


def filter_pe_trend(stock_codes: list, pe_ratios: dict, exclude_pct: float = 0.10) -> list:
    """
    按 PE_ratio 排除最低 exclude_pct，保留其余（包含高PE_ratio）.
    """
    if len(pe_ratios) < 10:
        return stock_codes

    sorted_ratios = sorted(pe_ratios.items(), key=lambda x: x[1])
    n = len(sorted_ratios)
    exclude_count = max(1, int(n * exclude_pct))

    kept = sorted_ratios[exclude_count:]
    return [code for code, _ in kept]


def execute_rebalance(portfolio, target_codes, rebalance_date, stock_codes,
                      price_cache, weights=None):
    """在 rebalance 日执行调仓，使用 rebalance 日的价格.

    weights: {code: weight} 归一化权重（sum=1）.
             若为 None 则走原逻辑（等权或20%上限）.
             若提供则: 每只股票目标仓位 = total_equity * N * 0.2 * weight.
    """
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
        target_codes, total_equity, prices, can_buy=True, can_sell=True,
        weights=weights
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


def compute_weights(method: str, final: list, val_df: pd.DataFrame,
                     logger=None, cutoff=None) -> dict | None:
    """
    计算权重.

    method: "equal" | "softmax" | "temp_0.2" | "temp_0.3" | "rank" | "reciprocal_rank" | "percentile"
    """
    if method == "equal":
        return None

    # Collect PB values for all candidates in val_df (full candidate pool)
    all_candidate_pbs = {}
    for _, row in val_df.iterrows():
        if row["pb_ttm"] > 0:
            all_candidate_pbs[row["code"]] = row["pb_ttm"]

    # Collect PB values for final stocks
    pb_vals = {}
    for code in final:
        row = val_df[val_df["code"] == code]
        if not row.empty and row.iloc[0]["pb_ttm"] > 0:
            pb_vals[code] = row.iloc[0]["pb_ttm"]
    if not pb_vals or len(pb_vals) != len(final):
        return None

    inv_pb = {code: 1.0 / pb for code, pb in pb_vals.items()}

    if method == "softmax":
        exp_vals = {code: np.exp(v) for code, v in inv_pb.items()}
        total = sum(exp_vals.values())
        return {code: v / total for code, v in exp_vals.items()}

    elif method.startswith("temp_"):
        T = float(method.split("_")[1])
        exp_vals = {code: np.exp(v / T) for code, v in inv_pb.items()}
        total = sum(exp_vals.values())
        return {code: v / total for code, v in exp_vals.items()}

    elif method == "rank":
        sorted_codes = sorted(pb_vals.keys(), key=lambda c: pb_vals[c])
        n = len(sorted_codes)
        rank_weights = {code: (n - i) / (n * (n + 1) / 2) for i, code in enumerate(sorted_codes)}
        return rank_weights

    elif method == "reciprocal_rank":
        sorted_codes = sorted(pb_vals.keys(), key=lambda c: pb_vals[c])
        n = len(sorted_codes)
        rr = {code: 1.0 / (i + 1) for i, code in enumerate(sorted_codes)}
        total = sum(rr.values())
        return {code: v / total for code, v in rr.items()}

    elif method == "percentile":
        if not all_candidate_pbs:
            return None
        all_pbs_sorted = sorted(all_candidate_pbs.values())
        n_all = len(all_pbs_sorted)
        weights = {}
        for code in final:
            pb = pb_vals[code]
            pct = sum(1 for p in all_pbs_sorted if p <= pb) / n_all
            weights[code] = 1.0 - pct
        total = sum(weights.values())
        if total <= 0:
            return None
        return {code: v / total for code, v in weights.items()}

    return None


def run_backtest(stock_codes, cutoffs_with_rebalance, price_cache, trading_days,
                 pe_cache, use_pe_trend=False, logger=None, lookback_years: int = 3,
                 weighting_method: str = "equal"):
    """
    运行完整回测.

    use_pe_trend: True=三步筛选(PE预筛→PB+ROE→PB排序), False=原两步(PB+ROE→PB排序)
    lookback_years: PE_ratio 分母的回溯年数
    weighting_method: "equal" | "softmax" | "temp_0.2" | "temp_0.3" | "rank" | "reciprocal_rank" | "percentile"
    注意：cutoff 日做筛选，rebalance 日执行交易.
    """
    portfolio = Portfolio(initial_capital=config.INITIAL_CAPITAL)
    all_trades = []
    all_snapshots = []
    actual_cutoffs = []
    portfolio_states = []

    for cutoff, rebalance in cutoffs_with_rebalance:
        cutoff_ts = pd.Timestamp(cutoff)

        if use_pe_trend:
            pe_ratios = compute_pe_ratios_for_cutoff(cutoff_ts, stock_codes, pe_cache, lookback_years)
            pool_after_pe = filter_pe_trend(stock_codes, pe_ratios, PE_TREND_EXCLUDE_PCT)
            if logger:
                logger.info(f"  {cutoff}: PE_ratio computed={len(pe_ratios)}, excluded={len(stock_codes) - len(pool_after_pe)}, kept={len(pool_after_pe)}")
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
            if use_pe_trend:
                logger.info(f"  {cutoff}: after_PE={len(pool_after_pe)}, after_filter={len(selected)}, final={len(final)}")
            else:
                logger.info(f"  {cutoff}: filtered={len(selected)}, final={len(final)}")
            for p in pbs:
                logger.info(p)

        # Compute weights based on method
        weights = compute_weights(weighting_method, final, val_df, logger, cutoff)

        # 在 rebalance 日执行交易；若无下一个交易日，用 cutoff 日价格
        exec_date = rebalance if rebalance is not None else cutoff
        trades, snapshot = execute_rebalance(portfolio, final, exec_date, stock_codes, price_cache, weights)
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

    # 基准数据
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


# 全局变量：基准数据
bench_equity_data = None


def run_test():
    global bench_equity_data

    logger = setup_logger("test_pb_weight", "test_pb_weight")
    logger.info("=" * 60)
    logger.info("Test: Weighting Strategy Comparison")
    logger.info("  Strategies: equal, softmax, temp_0.2, temp_0.3, rank, reciprocal_rank, percentile")
    logger.info("=" * 60)

    # Load data
    logger.info("\n[1] Loading stock pool & intermediate data...")
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
    logger.info("\n[2] Loading PE history from CSVs...")
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

    # Define strategies
    strategies = [
        ("equal", "Equal Weight"),
        ("softmax", "Softmax(1/PB)"),
        ("temp_0.2", "Temp-Scaled T=0.2"),
        ("temp_0.3", "Temp-Scaled T=0.3"),
        ("rank", "Rank-Based"),
        ("reciprocal_rank", "Reciprocal Rank"),
        ("percentile", "PB Percentile"),
    ]

    # Run backtests
    results = {}
    for method, label in strategies:
        logger.info(f"\n[{label}] Running backtest...")
        result = run_backtest(stock_codes, cutoffs_with_rebalance, price_cache, trading_days,
                              pe_cache, use_pe_trend=False, logger=logger, weighting_method=method)
        results[method] = result
        logger.info(f"  Trades: {len(result['trade_records'])}")

    # Performance comparison
    logger.info("\n" + "=" * 60)
    logger.info("Performance Comparison")
    logger.info("=" * 60)

    from performance import save_performance_summary

    output_dir = os.path.join(config.DATA_OUTPUT_DIR, "pb_weight_test")
    os.makedirs(output_dir, exist_ok=True)

    strat_list = [(method, label, results[method]["performance"]) for method, label in strategies]

    for method, label, perf in strat_list:
        save_performance_summary(perf, os.path.join(output_dir, f"{method}_perf.csv"))

    perf_maps = {}
    for method, label, _ in strat_list:
        df = pd.read_csv(os.path.join(output_dir, f"{method}_perf.csv"))
        perf_maps[method] = dict(zip(df["Metric"], df["Value"]))

    w0 = 22
    w = 18
    col_labels = [label for _, label, _ in strat_list]
    header = f"{'Metric':<{w0}}"
    for label in col_labels:
        header += f"{label:<{w}}"
    logger.info(header)
    logger.info("-" * (w0 + w * len(col_labels)))

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

    # Save results
    logger.info("\n[4] Saving results...")
    for method, label, _ in strat_list:
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


if __name__ == "__main__":
    run_test()
