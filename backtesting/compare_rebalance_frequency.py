"""
调仓频率对比回测：PB最低 Top-10 策略
测试两种调仓频率：
1. Annual:      一年1次，年报后（每年4月底截止，5月初调仓）
2. Semi-annual: 一年2次，年报+半年报后（4月底 + 8月底截止，次月初调仓）

运行方式:
    cd backtesting
    python compare_rebalance_frequency.py

日志将保存到: backtesting/logs/frequency_comparison_YYYYMMDD_HHMMSS.log
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np
from tqdm import tqdm
import logging
from datetime import datetime

import config
from data_loader import load_stock_pool, load_price_data
from trading_calendar import build_trading_calendar, get_annual_cutoff_dates, get_semi_annual_cutoff_dates
from stock_selector import select_stocks, is_new_stock, rank_and_limit
from backtest_engine import compute_benchmark_equity_curve, check_limit_up_down
from portfolio import Portfolio

# --- Logging setup ---
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)


def setup_logger(log_file: str) -> logging.Logger:
    """Setup logger: DEBUG to file, INFO to console."""
    logger = logging.getLogger("frequency_comparison")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    # File handler: DEBUG level (everything)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh.setFormatter(fh_fmt)
    logger.addHandler(fh)

    # Console handler: INFO level
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch_fmt = logging.Formatter("%(message)s")
    ch.setFormatter(ch_fmt)
    logger.addHandler(ch)

    return logger


FREQ_METHODS = {
    "annual":       {"label": "一年1次（年报后）",   "cutoff_fn": get_annual_cutoff_dates},
    "semi_annual":  {"label": "一年2次（年报+半年报）", "cutoff_fn": get_semi_annual_cutoff_dates},
}

MAX_POSITIONS = 10
RANKING_METHOD = "pb"


def run_frequency_backtest(
    stock_codes: list,
    trading_days: list,
    cutoffs: list,
    price_cache: dict,
    frequency_label: str,
    logger: logging.Logger,
    initial_capital: float = config.INITIAL_CAPITAL,
) -> dict:
    """Run a full backtest for a single rebalance frequency."""
    logger.info(f"\n{'=' * 60}")
    logger.info(f"  开始回测: {frequency_label}")
    logger.info(f"  截面日期数量: {len(cutoffs)}")
    logger.info(f"{'=' * 60}")

    # --- Step 1: compute benchmark ---
    logger.info("[1/4] 计算基准曲线...")
    benchmark_df = compute_benchmark_equity_curve(
        stock_codes, trading_days, cutoffs, price_cache, initial_capital
    )

    # --- Step 2: stock selection ---
    logger.info("[2/4] 执行选股筛选...")
    selection_results = {}
    selection_counts = []

    for cutoff, rebalance in tqdm(cutoffs, desc=f"  选股 [{frequency_label}]"):
        selected, val_df = select_stocks(stock_codes, cutoff, price_cache=price_cache)
        raw_count = len(selected)
        final_selected = rank_and_limit(selected, val_df, MAX_POSITIONS, RANKING_METHOD)

        if rebalance is not None:
            selection_results[(cutoff, rebalance)] = final_selected

        selection_counts.append((cutoff, raw_count, len(final_selected)))
        logger.debug(f"  截面 {cutoff.strftime('%Y-%m-%d')}: 原始={raw_count}, 最终={len(final_selected)}")
        logger.info(f"  [{cutoff.strftime('%Y-%m-%d')}] 候选 {raw_count} 只 -> 选中 {len(final_selected)} 只")

    # --- Step 3: portfolio simulation ---
    logger.info(f"[3/4] 模拟投资组合 (初始资金 {initial_capital:,.0f})...")
    portfolio = Portfolio(initial_capital=initial_capital)
    trade_records = []
    holding_snapshots = []
    cutoff_dates = []

    for i, ((cutoff, rebalance), selected_codes) in enumerate(
        tqdm(selection_results.items(), desc=f"  交易 [{frequency_label}]")
    ):
        logger.info(f"\n--- 第 {i + 1}/{len(selection_results)} 次调仓 ---")
        logger.info(f"  截面日: {cutoff.strftime('%Y-%m-%d')}, 调仓日: {rebalance.strftime('%Y-%m-%d')}")
        logger.info(f"  目标股票: {selected_codes}")

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
            logger.warning(f"  跳过：无价格数据")
            continue

        # Limit up/down check
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
        logger.info(f"  调仓前总资产: {total_equity:,.0f}")

        plan = portfolio.calculate_target_positions(
            selected_codes, total_equity, prices,
            can_buy=True, can_sell=True
        )

        sell_count = 0
        buy_count = 0
        for code, shares_to_sell in plan["sell_orders"]:
            price = prices.get(code, 0)
            if price <= 0 or not can_sell_flags.get(code, True):
                logger.debug(f"    跳过卖出 {code}: 价格={price:.2f}, 可卖={can_sell_flags.get(code, True)}")
                continue
            trade = portfolio.sell_shares(code, shares_to_sell, price, reason="调仓卖出")
            if trade:
                trade["trade_date"] = rebalance
                trade_records.append(trade)
                sell_count += 1
                logger.debug(f"    卖出 {code}: {shares_to_sell}股 @ {price:.2f}")

        for code, shares_to_buy in plan["buy_orders"]:
            price = prices.get(code, 0)
            if price <= 0 or not can_buy_flags.get(code, True):
                logger.debug(f"    跳过买入 {code}: 价格={price:.2f}, 可买={can_buy_flags.get(code, True)}")
                continue
            if code in price_cache and is_new_stock(code, price_cache[code], rebalance, config.NEW_STOCK_EXCLUDE_DAYS):
                logger.debug(f"    跳过买入 {code}: 新股")
                continue
            trade = portfolio.buy_shares(code, shares_to_buy, price, reason="调仓买入")
            if trade:
                trade["trade_date"] = rebalance
                trade_records.append(trade)
                buy_count += 1
                logger.debug(f"    买入 {code}: {shares_to_buy}股 @ {price:.2f}")

        logger.info(f"  执行: 卖出 {sell_count} 笔, 买入 {buy_count} 笔")

        snapshot = portfolio.snapshot_holdings(rebalance, prices)
        holding_snapshots.append(snapshot)
        cutoff_dates.append(cutoff)

        after_equity = portfolio.get_total_equity(prices)
        logger.info(f"  调仓后总资产: {after_equity:,.0f}")

    # --- Step 4: daily equity curve ---
    logger.info("[4/4] 计算每日净值曲线...")
    strategy_equity = []
    for day in tqdm(trading_days, desc=f"  净值 [{frequency_label}]"):
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

    logger.info(f"\n回测完成: {frequency_label}")
    logger.info(f"  交易次数: {len(trade_records)}")
    logger.info(f"  截面次数: {len(cutoff_dates)}")
    logger.info(f"  起始净值: {equity_curve['strategy_equity'].iloc[0]:,.0f}")
    logger.info(f"  最终净值: {equity_curve['strategy_equity'].iloc[-1]:,.0f}")

    return {
        "equity_curve": equity_curve,
        "trade_records": trade_records,
        "holding_snapshots": holding_snapshots,
        "cutoff_dates": cutoff_dates,
        "selection_counts": selection_counts,
    }


def compute_performance(equity_curve: pd.DataFrame) -> dict:
    """Calculate key performance metrics using CAGR."""
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

    equity_vals = equity_curve["strategy_equity"].values
    running_max = np.maximum.accumulate(equity_vals)
    drawdowns = (equity_vals - running_max) / running_max
    max_dd = drawdowns.min()

    bench_cum_return = (bench_final - initial) / initial
    excess_return = cum_return - bench_cum_return

    return {
        "cumulative_return": cum_return,
        "benchmark_return": bench_cum_return,
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


def print_selection_summary(results: dict, logger: logging.Logger):
    """Print selection count summary for each frequency (dates differ, so show separately)."""
    logger.info(f"\n{'=' * 80}")
    logger.info(f"  截面选股数量统计")
    logger.info(f"{'=' * 80}")

    for key, spec in FREQ_METHODS.items():
        counts = results[key]["selection_counts"]
        if not counts:
            continue

        raw_counts = [c[1] for c in counts]
        final_counts = [c[2] for c in counts]
        final_series = pd.Series(final_counts)

        logger.info(f"\n  {spec['label']} ({len(counts)} 个截面日):")
        logger.info(f"    原始候选: mean={np.mean(raw_counts):.1f}, median={np.median(raw_counts):.0f}, "
                     f"min={np.min(raw_counts):.0f}, max={np.max(raw_counts):.0f}")
        logger.info(f"    最终选中: mean={np.mean(final_counts):.1f}, median={np.median(final_counts):.0f}, "
                     f"min={np.min(final_counts):.0f}, max={np.max(final_counts):.0f}")

        # Print per-date detail
        logger.info(f"    逐截面明细:")
        for cutoff, raw, final in counts:
            logger.info(f"      {cutoff.strftime('%Y-%m-%d')}: 候选={raw:>3}, 选中={final:>3}")


def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(LOG_DIR, f"frequency_comparison_{timestamp}.log")
    logger = setup_logger(log_file)

    logger.info("=" * 60)
    logger.info("  PB最低 Top-10 策略 - 调仓频率对比回测")
    logger.info("=" * 60)
    logger.info(f"  日志文件: {log_file}")
    logger.info(f"  回测区间: {config.START_DATE} 至今")
    logger.info(f"  最大持仓: {MAX_POSITIONS} 只")
    logger.info(f"  排名方式: PB最低")
    logger.info(f"  测试频率: 一年1次（年报后） vs 一年2次（年报+半年报）")
    logger.info("=" * 60)
    logger.info(f"  日志将同时写入: {log_file}")
    logger.info("=" * 60)

    # Load stock pool
    logger.info("\n[1/5] 加载股票池...")
    pool_df = load_stock_pool()
    stock_codes = pool_df["code"].tolist()
    logger.info(f"  股票池: {len(stock_codes)} 只")

    # Build calendar
    logger.info("\n[2/5] 构建交易日历...")
    trading_days = build_trading_calendar()
    logger.info(f"  交易日: {len(trading_days)} 天")

    # Load price data
    logger.info("\n[3/5] 加载价格数据...")
    price_cache = {}
    for code in tqdm(stock_codes, desc="  加载"):
        try:
            df = load_price_data(code)
            if not df.empty:
                price_cache[code] = df
        except Exception:
            continue
    logger.info(f"  已加载: {len(price_cache)} 只")

    # Run backtests
    logger.info("\n[4/5] 执行回测...")
    results = {}
    for key, spec in FREQ_METHODS.items():
        cutoffs = spec["cutoff_fn"](trading_days)
        logger.info(f"\n>>> 频率: {spec['label']} ({len(cutoffs)} 个截面日)")
        results[key] = run_frequency_backtest(
            stock_codes, trading_days, cutoffs, price_cache,
            frequency_label=spec["label"],
            logger=logger,
        )

    # Compute and compare
    logger.info("\n[5/5] 计算并对比性能...")

    # Summary table
    logger.info(f"\n{'=' * 80}")
    logger.info(f"  性能对比表")
    logger.info(f"{'=' * 80}")
    header = f"{'指标':<20}"
    for key, spec in FREQ_METHODS.items():
        header += f"  {spec['label']:>22}"
    logger.info(header)
    logger.info("-" * 80)

    perf_data = {}
    for key in FREQ_METHODS:
        perf_data[key] = compute_performance(results[key]["equity_curve"])

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
        for key in FREQ_METHODS:
            row += f"  {fmt(perf_data[key]):>22}"
        logger.info(row)

    # Trade counts
    logger.info("-" * 80)
    trade_row = f"{'交易次数':<20}"
    for key in FREQ_METHODS:
        trade_row += f"  {len(results[key]['trade_records']):>22}"
    logger.info(trade_row)
    logger.info("-" * 80)

    # Annual returns
    logger.info(f"\n{'=' * 80}")
    logger.info(f"  年度收益对比")
    logger.info(f"{'=' * 80}")

    all_years = set()
    annual_data = {}
    for key in FREQ_METHODS:
        annual_data[key] = compute_annual_returns(results[key]["equity_curve"])
        all_years.update(annual_data[key].keys())

    header2 = f"{'年份':>6}"
    for key, spec in FREQ_METHODS.items():
        header2 += f"  {spec['label'][:14]:>16}"
    header2 += f"  {'基准':>10}"
    logger.info(header2)
    logger.info("-" * 80)

    for year in sorted(all_years):
        row = f"{year:>6}"
        bench_vals = []
        for key in FREQ_METHODS:
            if year in annual_data[key]:
                row += f"  {annual_data[key][year]['strategy']:>15.2%}"
                bench_vals.append(annual_data[key][year]["benchmark"])
            else:
                row += f"  {'N/A':>16}"
        if bench_vals:
            avg_bench = np.mean(bench_vals)
            row += f"  {avg_bench:>9.2%}"
        else:
            row += f"  {'N/A':>10}"
        logger.info(row)

    # Selection count summary (per frequency, since dates differ)
    print_selection_summary(results, logger)

    # Conclusion
    logger.info(f"\n{'=' * 80}")
    logger.info("  结论")
    logger.info(f"{'=' * 80}")

    best_sharpe = max(FREQ_METHODS, key=lambda k: perf_data[k]["sharpe_ratio"])
    best_cum = max(FREQ_METHODS, key=lambda k: perf_data[k]["cumulative_return"])
    best_dd = max(FREQ_METHODS, key=lambda k: perf_data[k]["max_drawdown"])

    logger.info(f"  最佳夏普比率:  {FREQ_METHODS[best_sharpe]['label']} ({perf_data[best_sharpe]['sharpe_ratio']:.4f})")
    logger.info(f"  最佳累计收益: {FREQ_METHODS[best_cum]['label']} ({perf_data[best_cum]['cumulative_return']:.2%})")
    logger.info(f"  最小回撤:     {FREQ_METHODS[best_dd]['label']} ({perf_data[best_dd]['max_drawdown']:.2%})")
    logger.info(f"{'=' * 80}")
    logger.info(f"\n完整日志已保存至: {log_file}")


if __name__ == "__main__":
    main()
