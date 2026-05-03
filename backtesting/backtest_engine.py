"""
回测引擎模块 - 核心回测执行器
整合所有模块，执行完整的回测流程：
加载数据、构建交易日历、每周选股、调仓执行、生成结果
"""

import pandas as pd
import numpy as np
import os
import sys
import logging
from datetime import datetime
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from data_loader import load_price_data, load_stock_pool
from trading_calendar import (
    build_trading_calendar, get_weekly_cutoff_dates, get_monthly_cutoff_dates,
    get_quarterly_cutoff_dates, get_annual_cutoff_dates, get_annual_q3_cutoff_dates,
)
from stock_selector import select_stocks, is_new_stock, rank_and_limit
from portfolio import Portfolio

logger = logging.getLogger("backtest_engine")


def check_limit_up_down(
    code: str,
    trade_date: pd.Timestamp,
    price_df: pd.DataFrame,
    prev_close: float
) -> dict:
    """
    判断股票是否涨停（无法买入）或跌停（无法卖出）

    涨停：open >= prev_close * (1 + limit_ratio - tolerance)
          AND low >= same threshold（全天封板）
    跌停：open <= prev_close * (1 - limit_ratio + tolerance)
          AND high <= same threshold（全天封板）

    Args:
        code: 股票代码
        trade_date: 交易日期
        price_df: 价格数据 DataFrame（含 trade_date, open, high, low, close）
        prev_close: 前一日收盘价

    Returns:
        {'can_buy': bool, 'can_sell': bool}
        如果 trade_date 无数据（停牌），返回 can_buy=False, can_sell=False
    """
    result = {'can_buy': True, 'can_sell': True}

    # 获取该日数据
    row = price_df[price_df['trade_date'] == trade_date]
    if row.empty:
        # 无数据视为停牌
        return {'can_buy': False, 'can_sell': False}

    date_str = trade_date.strftime('%Y-%m-%d')
    limit_ratio = config.get_limit_ratio(code, date_str)
    tolerance = config.LIMIT_TOLERANCE

    open_price = row['open'].iloc[0]
    high_price = row['high'].iloc[0]
    low_price = row['low'].iloc[0]

    # 涨停阈值
    limit_up_threshold = prev_close * (1 + limit_ratio - tolerance)
    # 跌停阈值
    limit_down_threshold = prev_close * (1 - limit_ratio + tolerance)

    # 涨停判断：开盘价和最低价都在涨停阈值之上（全天封板）
    if open_price >= limit_up_threshold and low_price >= limit_up_threshold:
        result['can_buy'] = False

    # 跌停判断：开盘价和最高价都在跌停阈值之下（全天封板）
    if open_price <= limit_down_threshold and high_price <= limit_down_threshold:
        result['can_sell'] = False

    return result


def compute_benchmark_equity_curve(
    stock_codes: list,
    trading_days: list,
    weekly_cutoffs: list,
    price_cache: dict,
    initial_capital: float
) -> pd.DataFrame:
    """
    计算基准等权组合的每日权益曲线

    策略：起始日等权买入所有股票，每周第一个交易日再平衡

    Args:
        stock_codes: 股票池代码列表
        trading_days: 交易日历
        weekly_cutoffs: 周截面日列表 [(cutoff, rebalance), ...]
        price_cache: 价格数据缓存
        initial_capital: 初始资金

    Returns:
        DataFrame with ['date', 'benchmark_equity']
    """
    # 确定每周第一个交易日（即 rebalance 日）
    rebalance_dates = set()
    for cutoff, rebalance in weekly_cutoffs:
        if rebalance is not None:
            rebalance_dates.add(pd.Timestamp(rebalance))

    # 构建每只股票的价格映射: {code: {date: close}}
    stock_price_map = {}
    for code in stock_codes:
        if code in price_cache and not price_cache[code].empty:
            df = price_cache[code]
            stock_price_map[code] = dict(zip(df['trade_date'], df['close']))

    if not stock_price_map:
        return pd.DataFrame(columns=['date', 'benchmark_equity'])

    # 第一天的权重：等权
    N = len(stock_codes)
    weight_per_stock = 1.0 / N if N > 0 else 0

    # 跟踪每个股票的持仓份额
    shares = {}
    # 第一天：用收盘价买入
    first_day = pd.Timestamp(trading_days[0])
    first_prices = {}
    for code in stock_codes:
        if code in stock_price_map and first_day in stock_price_map[code]:
            first_prices[code] = stock_price_map[code][first_day]

    # 计算等权买入份额
    alloc_per_stock = initial_capital * weight_per_stock
    for code in stock_codes:
        if code in first_prices and first_prices[code] > 0:
            s = int(alloc_per_stock / first_prices[code])
            s = (s // config.LOT_SIZE) * config.LOT_SIZE
            if s > 0:
                shares[code] = s

    # 计算实际使用的资金
    actual_invested = sum(shares.get(c, 0) * first_prices.get(c, 0) for c in stock_codes)
    cash = initial_capital - actual_invested

    # 逐日计算基准权益
    benchmark_equity = []
    for day in trading_days:
        day_ts = pd.Timestamp(day)

        # 如果当天是再平衡日，重新等权分配
        if day_ts in rebalance_dates and day_ts != first_day:
            # 先计算当前总资产
            total_val = cash
            for code, s in shares.items():
                if code in stock_price_map and day_ts in stock_price_map[code]:
                    total_val += s * stock_price_map[code][day_ts]

            # 重新等权分配
            new_shares = {}
            alloc = total_val * weight_per_stock
            day_prices = {}
            for code in stock_codes:
                if code in stock_price_map and day_ts in stock_price_map[code]:
                    day_prices[code] = stock_price_map[code][day_ts]

            for code in stock_codes:
                if code in day_prices and day_prices[code] > 0:
                    s = int(alloc / day_prices[code])
                    s = (s // config.LOT_SIZE) * config.LOT_SIZE
                    if s > 0:
                        new_shares[code] = s

            # 卖出不再持有的（简化：不计算成本，直接按市值转换）
            shares = new_shares
            # 重新计算现金
            invested = sum(shares.get(c, 0) * day_prices.get(c, 0) for c in stock_codes)
            cash = total_val - invested

        # 计算当日权益
        day_equity = cash
        for code, s in shares.items():
            if code in stock_price_map and day_ts in stock_price_map[code]:
                day_equity += s * stock_price_map[code][day_ts]

        benchmark_equity.append({
            'date': day_ts,
            'benchmark_equity': day_equity
        })

    return pd.DataFrame(benchmark_equity)


def run_backtest(
    start_date: str = config.START_DATE,
    end_date: str = None,
    incremental_from: str = None,
    frequency: str = None,
    ranking_method: str = "pb",
) -> dict:
    """
    Execute full backtest workflow

    Args:
        start_date: backtest start date
        end_date: backtest end date
        incremental_from: path to previous intermediate pickle (incremental mode)
        frequency: rebalance frequency — "weekly", "monthly", "quarterly", "annual", "annual_q3"
        ranking_method: ranking when filtered stocks > 10 — "pe", "pb", "pr", "roe", "pure_pb"

    Returns:
        {
            'portfolio': Portfolio,
            'equity_curve': DataFrame ['date', 'strategy_equity', 'benchmark_equity'],
            'trade_records': list,
            'holding_snapshots': list,
            'cutoff_dates': list
        }
    """
    if frequency is None:
        frequency = config.REBALANCE_FREQUENCY

    freq_labels = {
        "weekly": "Weekly", "monthly": "Monthly", "quarterly": "Quarterly",
        "annual": "Annual", "annual_q3": "Annual+Q3",
    }
    freq_label = freq_labels.get(frequency, frequency)
    rank_labels = {
        "pe": "PE-lowest", "pb": "PB-lowest", "pr": "PR-lowest",
        "roe": "ROE-highest", "pure_pb": "Pure-PB-lowest",
    }
    rank_label = rank_labels.get(ranking_method, ranking_method)

    logger.info("=" * 60)
    logger.info("Starting backtest...")
    logger.info(f"Start date: {start_date}, End date: {end_date or 'latest'}")
    logger.info(f"Rebalance frequency: {freq_label}")
    logger.info(f"Ranking method: {rank_label}")
    if incremental_from:
        logger.info(f"Incremental mode, loading from: {incremental_from}")
    logger.info("=" * 60)

    # Step 1: 加载股票池
    logger.info("\n[Step 1] Loading stock pool...")
    pool_df = load_stock_pool()
    stock_codes = pool_df['code'].tolist()
    logger.info(f"  Total stocks in pool: {len(stock_codes)}")

    # Step 2: 构建交易日历
    logger.info("\n[Step 2] Building trading calendar...")
    trading_days = build_trading_calendar(start_date=start_date, end_date=end_date)
    if not trading_days:
        logger.info("  ERROR: No trading days found. Ensure price data exists.")
        return None
    logger.info(f"  Total trading days: {len(trading_days)}")

    if frequency == "monthly":
        cutoffs = get_monthly_cutoff_dates(trading_days)
        logger.info(f"  Monthly cutoff/rebalance pairs: {len(cutoffs)}")
    elif frequency == "quarterly":
        cutoffs = get_quarterly_cutoff_dates(trading_days)
        logger.info(f"  Quarterly cutoff/rebalance pairs: {len(cutoffs)}")
    elif frequency == "annual":
        cutoffs = get_annual_cutoff_dates(trading_days)
        logger.info(f"  Annual cutoff/rebalance pairs: {len(cutoffs)}")
    elif frequency == "annual_q3":
        cutoffs = get_annual_q3_cutoff_dates(trading_days)
        logger.info(f"  Annual+Q3 cutoff/rebalance pairs: {len(cutoffs)}")
    else:
        cutoffs = get_weekly_cutoff_dates(trading_days)
        logger.info(f"  Weekly cutoff/rebalance pairs: {len(cutoffs)}")

    # Step 3: 预加载所有价格数据到缓存
    logger.info("\n[Step 3] Pre-loading price data...")
    price_cache = {}
    for code in tqdm(stock_codes, desc="Loading prices"):
        try:
            df = load_price_data(code)
            if not df.empty:
                price_cache[code] = df
        except Exception as e:
            logger.info(f"\n  Warning: failed to load price data for {code}: {e}")
            continue
    logger.info(f"  Cached price data for {len(price_cache)} stocks.")

    # --- 增量模式：加载历史状态 ---
    old_result = None
    last_cutoff = None
    if incremental_from:
        try:
            import pickle
            with open(incremental_from, "rb") as f:
                old_result = pickle.load(f)
            # 找到上次最后一个截面日
            last_cutoff = old_result['cutoff_dates'][-1]
            logger.info(f"\n  *** Incremental mode: last cutoff was {last_cutoff} ***")
            # 只保留新增的截面日
            cutoffs = [(c, r) for c, r in cutoffs if c > last_cutoff]
            logger.info(f"  New cutoff/rebalance pairs to process: {len(cutoffs)}")
        except Exception as e:
            logger.info(f"\n  Warning: failed to load incremental data: {e}")
            old_result = None
            last_cutoff = None

    # Step 4: 计算基准权益曲线（等权组合，每周再平衡）
    logger.info("\n[Step 4] Computing benchmark equity curve...")
    benchmark_df = compute_benchmark_equity_curve(
        stock_codes, trading_days, cutoffs, price_cache,
        config.INITIAL_CAPITAL
    )
    logger.info(f"  Benchmark computed for {len(benchmark_df)} days.")

    # Step 5: 选股 - 对每个截面日执行选股
    logger.info("\n[Step 5] Running stock selection for each cutoff date...")
    logger.info(f"  Ranking method: {rank_label}")
    selection_results = {}  # {(cutoff_date, rebalance_date): selected_codes}
    for cutoff, rebalance in tqdm(cutoffs, desc="Selecting stocks"):
        try:
            if ranking_method == "pure_pb":
                # Pure PB: basic filter only (Step 1), then rank by PB lowest 10
                from stock_selector import get_latest_financial_data, calculate_valuation
                all_valuations = []
                for code in stock_codes:
                    price_df = price_cache.get(code)
                    if price_df is None or price_df.empty:
                        continue
                    if cutoff not in price_df["trade_date"].values:
                        continue
                    fin_data = get_latest_financial_data(code, cutoff)
                    if fin_data is None:
                        continue
                    valuation = calculate_valuation(price_df, cutoff, fin_data)
                    if valuation is None:
                        continue
                    if (valuation["pe_ttm"] <= 0 or valuation["pb_ttm"] <= 0 or
                            valuation["pr_ttm"] <= 0 or valuation["roe_ttm"] <= 0):
                        continue
                    all_valuations.append({"code": code, **valuation})
                if all_valuations:
                    val_df = pd.DataFrame(all_valuations)
                    val_df = val_df.sort_values("pb_ttm").head(config.MAX_POSITIONS)
                    final_selected = val_df["code"].tolist()
                else:
                    final_selected = []
            else:
                selected, val_df = select_stocks(stock_codes, cutoff, price_cache=price_cache)
                final_selected = rank_and_limit(selected, val_df, config.MAX_POSITIONS, ranking_method)

            # Always include the pair — when rebalance is None, use cutoff date close as fill price
            selection_results[(cutoff, rebalance)] = final_selected
        except Exception as e:
            logger.info(f"\n  Warning: stock selection failed for cutoff {cutoff}: {e}")
            continue

    valid_pairs = list(selection_results.keys())
    logger.info(f"  Valid cutoff/rebalance pairs with selections: {len(valid_pairs)}")

    # Step 6: 调仓执行 + 跟踪每日权益
    logger.info("\n[Step 6] Executing rebalances...")

    if old_result is not None:
        # 增量模式：从上次状态恢复
        portfolio = old_result['portfolio']
        trade_records = list(old_result['trade_records'])
        holding_snapshots = list(old_result['holding_snapshots'])
        all_cutoffs = list(old_result['cutoff_dates'])
        logger.info(f"  Restored portfolio: cash={portfolio.cash:,.0f}, positions={len(portfolio.positions)}")
    else:
        portfolio = Portfolio(initial_capital=config.INITIAL_CAPITAL)
        trade_records = []
        holding_snapshots = []
        all_cutoffs = []

    # Track strategy equity at each rebalance date
    strategy_equity_points = []  # [(date_ts, equity), ...]

    for (cutoff, rebalance), selected_codes in tqdm(
        selection_results.items(), desc="Rebalancing"
    ):
        try:
            # When rebalance is None (latest cutoff, no future trading day yet),
            # use cutoff date's close as fill price. This represents the realistic
            # scenario where we select stocks based on available data and execute
            # at the known closing price.
            execution_date = rebalance if rebalance is not None else cutoff

            # 获取执行日的价格
            prices = {}
            prev_prices = {}  # 用于涨跌停判断的 prev_close

            for code in stock_codes:
                if code in price_cache:
                    df = price_cache[code]
                    # 执行日价格
                    row = df[df['trade_date'] == execution_date]
                    if not row.empty:
                        prices[code] = row['close'].iloc[0]
                    # 找执行日之前的最近一天收盘价作为 prev_close
                    before = df[df['trade_date'] < execution_date]
                    if not before.empty:
                        prev_prices[code] = before['close'].iloc[-1]

            if not prices:
                continue

            # 涨跌停检查：仅适用于有实际执行日的情况
            # 当 rebalance is None 时，跳过涨跌停检查（无法预知次日开盘情况）
            can_buy_flags = {}
            can_sell_flags = {}

            if rebalance is not None:
                all_relevant = set(portfolio.positions.keys()) | set(selected_codes)
                for code in all_relevant:
                    if code in price_cache and code in prev_prices:
                        df = price_cache[code]
                        result = check_limit_up_down(
                            code, execution_date, df, prev_prices[code]
                        )
                        can_buy_flags[code] = result['can_buy']
                        can_sell_flags[code] = result['can_sell']
                    else:
                        can_buy_flags[code] = True
                        can_sell_flags[code] = True
            else:
                # No limit check for latest cutoff — use cutoff close as fill
                for code in set(portfolio.positions.keys()) | set(selected_codes):
                    can_buy_flags[code] = True
                    can_sell_flags[code] = True

            # 计算当前总资产
            total_equity = portfolio.get_total_equity(prices)

            # 生成目标仓位
            plan = portfolio.calculate_target_positions(
                selected_codes, total_equity, prices,
                can_buy=True, can_sell=True
            )

            # 先执行卖出
            for code, shares_to_sell in plan['sell_orders']:
                price = prices.get(code, 0)
                if price <= 0:
                    continue
                if not can_sell_flags.get(code, True):
                    continue

                trade = portfolio.sell_shares(
                    code, shares_to_sell, price, reason="调仓卖出"
                )
                if trade:
                    trade['trade_date'] = execution_date
                    trade_records.append(trade)

            # 再执行买入
            for code, shares_to_buy in plan['buy_orders']:
                price = prices.get(code, 0)
                if price <= 0:
                    continue
                if not can_buy_flags.get(code, True):
                    continue

                # 新股检查
                if code in price_cache:
                    if is_new_stock(code, price_cache[code], execution_date, config.NEW_STOCK_EXCLUDE_DAYS):
                        continue

                trade = portfolio.buy_shares(
                    code, shares_to_buy, price, reason="调仓买入"
                )
                if trade:
                    trade['trade_date'] = execution_date
                    trade_records.append(trade)

            # 记录调仓后的组合价值
            post_rebalance_equity = portfolio.get_total_equity(prices)
            equity_date = pd.Timestamp(execution_date)
            strategy_equity_points.append((equity_date, post_rebalance_equity))

            # 记录持仓快照
            snapshot = portfolio.snapshot_holdings(execution_date, prices)
            holding_snapshots.append(snapshot)
            all_cutoffs.append(cutoff)

        except Exception as e:
            logger.info(f"\n  Warning: rebalance failed for {cutoff} -> {rebalance}: {e}")
            continue

    logger.info(f"  Total trades executed: {len(trade_records)}")
    logger.info(f"  Holding snapshots: {len(holding_snapshots)}")

    # Step 7: 构建每日权益曲线
    logger.info("\n[Step 7] Computing daily equity curve...")
    strategy_equity = []

    if strategy_equity_points:
        first_rebalance = strategy_equity_points[0][0]
        rebalance_set = {d for d, _ in strategy_equity_points}
        equity_map = {d: e for d, e in strategy_equity_points}

        for day in trading_days:
            day_ts = pd.Timestamp(day)
            if day_ts < first_rebalance:
                # 首次调仓前：全部现金
                equity = config.INITIAL_CAPITAL
            elif day_ts in rebalance_set:
                # 调仓日：使用记录的准确价值
                equity = equity_map[day_ts]
            else:
                # 非调仓日：前值填充（调仓之间的持仓不变）
                equity = strategy_equity[-1]['strategy_equity'] if strategy_equity else config.INITIAL_CAPITAL

            strategy_equity.append({
                'date': day_ts,
                'strategy_equity': equity
            })
    else:
        # 没有调仓：全部现金
        for day in trading_days:
            strategy_equity.append({
                'date': pd.Timestamp(day),
                'strategy_equity': config.INITIAL_CAPITAL
            })

    strategy_df = pd.DataFrame(strategy_equity)

    # 合并策略和基准权益曲线
    if len(benchmark_df) > 0:
        equity_curve = strategy_df.merge(
            benchmark_df[['date', 'benchmark_equity']],
            on='date',
            how='left'
        )
        equity_curve['benchmark_equity'] = equity_curve['benchmark_equity'].ffill()
        equity_curve['benchmark_equity'] = equity_curve['benchmark_equity'].fillna(config.INITIAL_CAPITAL)
    else:
        equity_curve = strategy_df.copy()
        equity_curve['benchmark_equity'] = config.INITIAL_CAPITAL

    # 收集截面日列表
    cutoff_dates = [cutoff for cutoff, _ in cutoffs]

    logger.info(f"\nBacktest complete.")
    logger.info(f"  Final strategy equity: {strategy_equity[-1]['strategy_equity']:.2f}" if strategy_equity else "  No equity data.")
    if len(benchmark_df) > 0 and len(equity_curve) > 0:
        last_bench = equity_curve['benchmark_equity'].iloc[-1]
        logger.info(f"  Final benchmark equity: {last_bench:.2f}")

    return {
        'portfolio': portfolio,
        'equity_curve': equity_curve,
        'trade_records': trade_records,
        'holding_snapshots': holding_snapshots,
        'cutoff_dates': cutoff_dates,
    }


def save_results(result: dict):
    """
    保存回测结果到 CSV 文件

    Args:
        result: run_backtest 返回的字典
    """
    logger.info("\n" + "=" * 60)
    logger.info("Saving results...")
    logger.info("=" * 60)

    config.ensure_dirs()

    # 1. 保存持仓汇总 (holdings_summary.csv)
    holdings_path = os.path.join(config.HOLDINGS_DIR, "holdings_summary.csv")
    if result['holding_snapshots']:
        all_holdings = pd.concat(result['holding_snapshots'], ignore_index=True)
        all_holdings.to_csv(holdings_path, index=False)
        logger.info(f"  Saved holdings summary: {holdings_path} ({len(all_holdings)} rows)")
    else:
        pd.DataFrame(columns=[
            'rebalance_date', 'stock_code', 'shares', 'cost_price',
            'current_price', 'market_value', 'weight'
        ]).to_csv(holdings_path, index=False)
        logger.info(f"  Saved empty holdings summary: {holdings_path}")

    # 2. 保存交易记录 (trades_record.csv)
    trades_path = os.path.join(config.TRADES_DIR, "trades_record.csv")
    if result['trade_records']:
        trades_df = pd.DataFrame(result['trade_records'])
        trades_df.to_csv(trades_path, index=False)
        logger.info(f"  Saved trades record: {trades_path} ({len(trades_df)} rows)")
    else:
        pd.DataFrame(columns=[
            'trade_date', 'stock_code', 'direction', 'shares',
            'price', 'amount', 'commission', 'stamp_tax', 'reason'
        ]).to_csv(trades_path, index=False)
        logger.info(f"  Saved empty trades record: {trades_path}")

    # 3. 保存权益曲线 (equity_curve.csv)
    equity_path = os.path.join(config.PERFORMANCE_DIR, "equity_curve.csv")
    if result['equity_curve'] is not None and not result['equity_curve'].empty:
        result['equity_curve'].to_csv(equity_path, index=False)
        logger.info(f"  Saved equity curve: {equity_path} ({len(result['equity_curve'])} rows)")
    else:
        pd.DataFrame(columns=['date', 'strategy_equity', 'benchmark_equity']).to_csv(
            equity_path, index=False
        )
        logger.info(f"  Saved empty equity curve: {equity_path}")

    logger.info("Results saved successfully.")


def main():
    """CLI 入口点"""
    import argparse

    parser = argparse.ArgumentParser(description="A股低估值高ROE策略回测引擎")
    parser.add_argument(
        '--start-date',
        type=str,
        default=config.START_DATE,
        help=f'回测起始日期 (默认: {config.START_DATE})'
    )
    parser.add_argument(
        '--end-date',
        type=str,
        default=None,
        help='回测结束日期 (默认: 最新交易日)'
    )
    parser.add_argument(
        '--no-save',
        action='store_true',
        help='不保存结果文件'
    )

    args = parser.parse_args()

    # 确保目录存在
    config.ensure_dirs()

    # 执行回测
    result = run_backtest(
        start_date=args.start_date,
        end_date=args.end_date
    )

    if result is None:
        logger.info("Backtest failed. No results to save.")
        return

    # 保存结果
    if not args.no_save:
        save_results(result)

    # 打印简要绩效
    logger.info("\n" + "=" * 60)
    logger.info("Backtest Summary")
    logger.info("=" * 60)

    equity_curve = result['equity_curve']
    if equity_curve is not None and not equity_curve.empty:
        initial = config.INITIAL_CAPITAL
        final_strategy = equity_curve['strategy_equity'].iloc[-1]
        final_benchmark = equity_curve['benchmark_equity'].iloc[-1]

        strategy_return = (final_strategy - initial) / initial
        benchmark_return = (final_benchmark - initial) / initial

        logger.info(f"  Initial capital:     {initial:,.2f}")
        logger.info(f"  Final strategy:      {final_strategy:,.2f}")
        logger.info(f"  Final benchmark:     {final_benchmark:,.2f}")
        logger.info(f"  Strategy return:     {strategy_return:.2%}")
        logger.info(f"  Benchmark return:    {benchmark_return:.2%}")
        logger.info(f"  Excess return:       {strategy_return - benchmark_return:.2%}")
        logger.info(f"  Total trades:        {len(result['trade_records'])}")
        logger.info(f"  Rebalance times:     {len(result['cutoff_dates'])}")

    logger.info("=" * 60)


if __name__ == '__main__':
    main()
