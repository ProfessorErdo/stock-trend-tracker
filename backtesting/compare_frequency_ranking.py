"""
调仓频率 × 排名方式 全面对比回测

测试维度:
  频率 (2种):
    - annual:      年报后（4月底截止，5月初调仓）
    - annual_q3:   年报+三季报后（4月底 + 10月底截止，次月初调仓）
  排名条件 (5种):
    - pe:   PE最低 Top-10（四步选股后再排名）
    - pb:   PB最低 Top-10（四步选股后再排名）
    - pr:   PR最低 Top-10（四步选股后再排名）
    - roe:  ROE最高 Top-10（四步选股后再排名）
    - pure_pb: 纯PB最低 Top-10（仅Step 1基础过滤后直接按PB取最低10只）

共计 2 × 5 = 10 种组合

运行方式:
    cd backtesting
    python compare_frequency_ranking.py

日志将保存到: backtesting/logs/freq_ranking_YYYYMMDD_HHMMSS.log
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
from trading_calendar import (
    build_trading_calendar,
    get_annual_cutoff_dates,
    get_annual_q3_cutoff_dates,
)
from stock_selector import (
    get_latest_financial_data, calculate_valuation, is_new_stock,
    select_stocks, rank_and_limit,
)
from backtest_engine import compute_benchmark_equity_curve, check_limit_up_down
from portfolio import Portfolio
from log_util import setup_logger


# --- Configuration ---
FREQ_METHODS = {
    "annual":     {"label": "年报后",       "cutoff_fn": get_annual_cutoff_dates},
    "annual_q3":  {"label": "年报+三季报",   "cutoff_fn": get_annual_q3_cutoff_dates},
}

RANKING_METHODS = {
    "pe":      {"label": "PE最低 Top-10",     "method": "pe",     "uses_select": True},
    "pb":      {"label": "PB最低 Top-10",     "method": "pb",     "uses_select": True},
    "pr":      {"label": "PR最低 Top-10",     "method": "pr",     "uses_select": True},
    "roe":     {"label": "ROE最高 Top-10",    "method": "roe",    "uses_select": True},
    "pure_pb": {"label": "纯PB最低 Top-10",   "method": "pb",     "uses_select": False},
}

MAX_POSITIONS = 10


def _select_pure_pb(stock_codes: list, trade_date: pd.Timestamp,
                    price_cache: dict) -> tuple:
    """
    纯PB排名选股：仅做Step 1基础过滤（停牌、无财务数据、负估值），
    然后直接按PB最低取前10只。

    Returns:
        (selected_codes, val_df)
    """
    all_valuations = []

    for code in stock_codes:
        price_df = price_cache.get(code)
        if price_df is None or price_df.empty:
            continue

        if trade_date not in price_df["trade_date"].values:
            continue

        fin_data = get_latest_financial_data(code, trade_date)
        if fin_data is None:
            continue

        valuation = calculate_valuation(price_df, trade_date, fin_data)
        if valuation is None:
            continue

        if (valuation["pe_ttm"] <= 0 or valuation["pb_ttm"] <= 0 or
                valuation["pr_ttm"] <= 0 or valuation["roe_ttm"] <= 0):
            continue

        all_valuations.append({"code": code, **valuation})

    if not all_valuations:
        return [], pd.DataFrame()

    val_df = pd.DataFrame(all_valuations)
    val_df = val_df.sort_values("pb_ttm").head(MAX_POSITIONS)
    return val_df["code"].tolist(), val_df


def _portfolio_key(freq_key: str, rank_key: str) -> str:
    return f"{freq_key}_{rank_key}"


def run_single_backtest(
    stock_codes: list,
    trading_days: list,
    cutoffs: list,
    price_cache: dict,
    ranking_spec: dict,
    label: str,
    logger: logging.Logger,
    initial_capital: float = config.INITIAL_CAPITAL,
) -> dict:
    """
    Run a full backtest for a single (frequency, ranking) combination.
    """
    uses_select = ranking_spec["uses_select"]
    ranking_method = ranking_spec["method"]

    logger.info(f"\n{'=' * 60}")
    logger.info(f"  回测: {label}")
    logger.info(f"  截面日期数量: {len(cutoffs)}")
    if uses_select:
        logger.info(f"  选股方式: 四步选股 → {ranking_method} 排名 Top-{MAX_POSITIONS}")
    else:
        logger.info(f"  选股方式: 基础过滤 → {ranking_method} 排名 Top-{MAX_POSITIONS}")
    logger.info(f"{'=' * 60}")

    # --- Step 1: benchmark ---
    logger.info("[1/4] 计算基准曲线...")
    benchmark_df = compute_benchmark_equity_curve(
        stock_codes, trading_days, cutoffs, price_cache, initial_capital
    )

    # --- Step 2: stock selection ---
    logger.info("[2/4] 执行选股筛选...")
    selection_results = {}
    selection_counts = []

    for cutoff, rebalance in tqdm(cutoffs, desc=f"  选股 [{label}]"):
        if uses_select:
            selected, val_df = select_stocks(stock_codes, cutoff, price_cache=price_cache)
            final_selected = rank_and_limit(
                selected, val_df, MAX_POSITIONS, ranking_method
            )
        else:
            final_selected, val_df = _select_pure_pb(
                stock_codes, cutoff, price_cache
            )

        raw_count = len(val_df) if not val_df.empty else 0
        if rebalance is not None:
            selection_results[(cutoff, rebalance)] = final_selected

        selection_counts.append((cutoff, raw_count, len(final_selected)))
        logger.debug(
            f"  截面 {cutoff.strftime('%Y-%m-%d')}: "
            f"候选={raw_count}, 最终={len(final_selected)}"
        )
        logger.info(
            f"  [{cutoff.strftime('%Y-%m-%d')}] "
            f"候选 {raw_count} 只 -> 选中 {len(final_selected)} 只"
        )

    # --- Step 3: portfolio simulation ---
    logger.info(f"[3/4] 模拟投资组合 (初始资金 {initial_capital:,.0f})...")
    portfolio = Portfolio(initial_capital=initial_capital)
    trade_records = []
    holding_snapshots = []
    cutoff_dates = []

    for i, ((cutoff, rebalance), selected_codes) in enumerate(
        tqdm(selection_results.items(), desc=f"  交易 [{label}]")
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
            logger.warning("  跳过：无价格数据")
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
                logger.debug(f"    跳过卖出 {code}: 价格={price:.2f}")
                continue
            trade = portfolio.sell_shares(code, shares_to_sell, price, reason="调仓卖出")
            if trade:
                trade["trade_date"] = rebalance
                trade_records.append(trade)
                sell_count += 1

        for code, shares_to_buy in plan["buy_orders"]:
            price = prices.get(code, 0)
            if price <= 0 or not can_buy_flags.get(code, True):
                logger.debug(f"    跳过买入 {code}: 价格={price:.2f}")
                continue
            if code in price_cache and is_new_stock(
                code, price_cache[code], rebalance, config.NEW_STOCK_EXCLUDE_DAYS
            ):
                logger.debug(f"    跳过买入 {code}: 新股")
                continue
            trade = portfolio.buy_shares(code, shares_to_buy, price, reason="调仓买入")
            if trade:
                trade["trade_date"] = rebalance
                trade_records.append(trade)
                buy_count += 1

        logger.info(f"  执行: 卖出 {sell_count} 笔, 买入 {buy_count} 笔")

        snapshot = portfolio.snapshot_holdings(rebalance, prices)
        holding_snapshots.append(snapshot)
        cutoff_dates.append(cutoff)

        after_equity = portfolio.get_total_equity(prices)
        logger.info(f"  调仓后总资产: {after_equity:,.0f}")

    # --- Step 4: daily equity curve ---
    logger.info("[4/4] 计算每日净值曲线...")
    strategy_equity = []
    for day in tqdm(trading_days, desc=f"  净值 [{label}]"):
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

    logger.info(f"\n回测完成: {label}")
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


def main():
    logger = setup_logger("freq_ranking", "freq_ranking")

    logger.info("=" * 60)
    logger.info("  调仓频率 × 排名方式 全面对比回测")
    logger.info("=" * 60)
    logger.info(f"  回测区间: {config.START_DATE} 至今")
    logger.info(f"  最大持仓: {MAX_POSITIONS} 只")
    logger.info(f"  频率 (2种): 年报后 / 年报+三季报")
    logger.info(f"  排名 (5种): PE最低 / PB最低 / PR最低 / ROE最高 / 纯PB最低")
    logger.info(f"  组合总数: {len(FREQ_METHODS) * len(RANKING_METHODS)} 种")
    logger.info("=" * 60)

    # --- Load data ---
    logger.info("\n[1/4] 加载股票池...")
    pool_df = load_stock_pool()
    stock_codes = pool_df["code"].tolist()
    logger.info(f"  股票池: {len(stock_codes)} 只")

    logger.info("\n[2/4] 构建交易日历...")
    trading_days = build_trading_calendar()
    logger.info(f"  交易日: {len(trading_days)} 天")

    logger.info("\n[3/4] 加载价格数据...")
    price_cache = {}
    for code in tqdm(stock_codes, desc="  加载"):
        try:
            df = load_price_data(code)
            if not df.empty:
                price_cache[code] = df
        except Exception:
            continue
    logger.info(f"  已加载: {len(price_cache)} 只")

    # --- Run all 10 combinations ---
    logger.info("\n[4/4] 执行回测 (10 种组合)...")
    results = {}

    for freq_key, freq_spec in FREQ_METHODS.items():
        cutoffs = freq_spec["cutoff_fn"](trading_days)
        logger.info(f"\n{'=' * 60}")
        logger.info(f"  频率: {freq_spec['label']} ({len(cutoffs)} 个截面日)")
        logger.info(f"{'=' * 60}")

        for rank_key, rank_spec in RANKING_METHODS.items():
            label = f"{freq_spec['label']} × {rank_spec['label']}"
            combo_key = _portfolio_key(freq_key, rank_key)

            logger.info(f"\n>>> [{combo_key}] {label}")
            results[combo_key] = run_single_backtest(
                stock_codes, trading_days, cutoffs, price_cache,
                ranking_spec=rank_spec,
                label=label,
                logger=logger,
            )

    # --- Performance computation ---
    perf_data = {}
    annual_data = {}
    for combo_key in results:
        perf_data[combo_key] = compute_performance(results[combo_key]["equity_curve"])
        annual_data[combo_key] = compute_annual_returns(results[combo_key]["equity_curve"])

    # ===== SUMMARY TABLES =====

    # Table 1: Overall performance comparison
    logger.info(f"\n{'=' * 120}")
    logger.info(f"  性能对比总表")
    logger.info(f"{'=' * 120}")
    col_width = 24
    header = f"{'指标':<18}"
    combo_keys = list(results.keys())
    for k in combo_keys:
        header += f"  {k:>22}"
    logger.info(header)
    logger.info("-" * 120)

    metrics = [
        ("累计收益", lambda p: f"{p['cumulative_return']:.2%}"),
        ("年化收益", lambda p: f"{p['annual_return']:.2%}"),
        ("年化波动", lambda p: f"{p['annual_volatility']:.2%}"),
        ("夏普比率", lambda p: f"{p['sharpe_ratio']:.4f}"),
        ("最大回撤", lambda p: f"{p['max_drawdown']:.2%}"),
        ("基准收益", lambda p: f"{p['benchmark_return']:.2%}"),
        ("超额收益", lambda p: f"{p['excess_return']:.2%}"),
        ("交易次数", lambda p, k: f"{len(results[k]['trade_records']):>22}"),
    ]

    for name, fmt in metrics:
        row = f"{name:<18}"
        for k in combo_keys:
            try:
                row += f"  {fmt(perf_data[k], k):>22}"
            except TypeError:
                row += f"  {fmt(perf_data[k]):>22}"
        logger.info(row)

    # Table 2: Per-frequency performance comparison (group by ranking method)
    logger.info(f"\n{'=' * 120}")
    logger.info(f"  按频率分组对比")
    logger.info(f"{'=' * 120}")

    for freq_key, freq_spec in FREQ_METHODS.items():
        logger.info(f"\n  --- {freq_spec['label']} ---")
        row_header = f"{'指标':<18}"
        row_header += "".join(
            f"  {RANKING_METHODS[rk]['label']:>22}"
            for rk in RANKING_METHODS
        )
        logger.info(row_header)
        logger.info("-" * 120)

        for metric_name, metric_fn in metrics[:-1]:  # exclude trade count
            row = f"{metric_name:<18}"
            for rk in RANKING_METHODS:
                k = _portfolio_key(freq_key, rk)
                val = metric_fn(perf_data[k])
                row += f"  {val:>22}"
            logger.info(row)

        # Trade count
        row = f"{'交易次数':<18}"
        for rk in RANKING_METHODS:
            k = _portfolio_key(freq_key, rk)
            row += f"  {len(results[k]['trade_records']):>22}"
        logger.info(row)

    # Table 3: Annual returns
    logger.info(f"\n{'=' * 120}")
    logger.info(f"  年度收益对比")
    logger.info(f"{'=' * 120}")

    all_years = set()
    for k in combo_keys:
        all_years.update(annual_data[k].keys())

    header3 = f"{'年份':>6}"
    for k in combo_keys:
        header3 += f"  {k:>16}"
    header3 += f"  {'基准(均值)':>12}"
    logger.info(header3)
    logger.info("-" * 120)

    for year in sorted(all_years):
        row = f"{year:>6}"
        bench_vals = []
        for k in combo_keys:
            if year in annual_data[k]:
                row += f"  {annual_data[k][year]['strategy']:>15.2%}"
                bench_vals.append(annual_data[k][year]["benchmark"])
            else:
                row += f"  {'N/A':>16}"
        if bench_vals:
            row += f"  {np.mean(bench_vals):>11.2%}"
        else:
            row += f"  {'N/A':>12}"
        logger.info(row)

    # Table 4: Selection count summary
    logger.info(f"\n{'=' * 120}")
    logger.info(f"  截面选股数量统计")
    logger.info(f"{'=' * 120}")

    for freq_key, freq_spec in FREQ_METHODS.items():
        logger.info(f"\n  --- {freq_spec['label']} ---")
        detail_header = f"{'截面日期':>12}"
        for rk in RANKING_METHODS:
            detail_header += f"  {RANKING_METHODS[rk]['label'][:8]:>10}"
        logger.info(detail_header)
        logger.info("-" * 80)

        max_cutoffs = max(
            len(results[_portfolio_key(freq_key, rk)]["selection_counts"])
            for rk in RANKING_METHODS
        )
        for i in range(max_cutoffs):
            row = ""
            for rk in RANKING_METHODS:
                k = _portfolio_key(freq_key, rk)
                counts = results[k]["selection_counts"]
                if i < len(counts):
                    cutoff, raw, final = counts[i]
                    if rk == list(RANKING_METHODS.keys())[0]:
                        row = f"{cutoff.strftime('%Y-%m-%d'):>12}"
                    row += f"  {raw:>4}/{final:>4}"
                else:
                    row += f"  {'N/A':>10}"
            logger.info(row)

        # Summary stats
        logger.info(f"  统计汇总:")
        for rk in RANKING_METHODS:
            k = _portfolio_key(freq_key, rk)
            counts = results[k]["selection_counts"]
            if not counts:
                continue
            raw_vals = [c[1] for c in counts]
            final_vals = [c[2] for c in counts]
            logger.info(f"    {RANKING_METHODS[rk]['label']:>14}: "
                        f"候选 mean={np.mean(raw_vals):.1f} median={np.median(raw_vals):.0f} "
                        f"[{np.min(raw_vals)}-{np.max(raw_vals)}], "
                        f"选中 mean={np.mean(final_vals):.1f} median={np.median(final_vals):.0f} "
                        f"[{np.min(final_vals)}-{np.max(final_vals)}]")

    # ===== CONCLUSION =====
    logger.info(f"\n{'=' * 120}")
    logger.info("  结论")
    logger.info(f"{'=' * 120}")

    # Best overall
    best_sharpe = max(combo_keys, key=lambda k: perf_data[k]["sharpe_ratio"])
    best_cum = max(combo_keys, key=lambda k: perf_data[k]["cumulative_return"])
    best_dd = max(combo_keys, key=lambda k: perf_data[k]["max_drawdown"])

    logger.info(f"  最佳夏普比率:  {best_sharpe} ({perf_data[best_sharpe]['sharpe_ratio']:.4f})")
    logger.info(f"  最佳累计收益: {best_cum} ({perf_data[best_cum]['cumulative_return']:.2%})")
    logger.info(f"  最小回撤:     {best_dd} ({perf_data[best_dd]['max_drawdown']:.2%})")

    # Per frequency best
    for freq_key, freq_spec in FREQ_METHODS.items():
        freq_keys = [_portfolio_key(freq_key, rk) for rk in RANKING_METHODS]
        freq_best_sharpe = max(freq_keys, key=lambda k: perf_data[k]["sharpe_ratio"])
        freq_best_cum = max(freq_keys, key=lambda k: perf_data[k]["cumulative_return"])
        logger.info(f"\n  [{freq_spec['label']}] 最佳夏普: {freq_best_sharpe} "
                    f"({perf_data[freq_best_sharpe]['sharpe_ratio']:.4f}), "
                    f"最佳累计: {freq_best_cum} "
                    f"({perf_data[freq_best_cum]['cumulative_return']:.2%})")

    logger.info(f"\n{'=' * 120}")
    logger.info(f"完整日志已保存至: {log_file}")


if __name__ == "__main__":
    main()
