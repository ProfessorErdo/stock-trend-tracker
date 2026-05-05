"""
幸存者偏差模拟验证脚本

通过随机剔除股票池中的部分股票，观察策略收益的变化，
估算幸存者偏差可能造成的高估幅度。

运行方式:
    cd backtesting
    python simulate_survivorship.py

参数:
    --iterations N    迭代次数 (默认: 20)
    --drop_ratio R    每次剔除比例 (默认: 0.10)
    --frequency FREQ  调仓频率 (默认: annual)
    --ranking RANK    排名方式 (默认: pb)
"""

import sys
import os
import random
import argparse
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np
from tqdm import tqdm

import config
from data_loader import load_stock_pool, load_price_data, load_financial_data
from trading_calendar import build_trading_calendar, get_annual_cutoff_dates
from stock_selector import (
    select_stocks, get_latest_financial_data, calculate_valuation,
    rank_and_limit, is_new_stock,
)
from backtest_engine import compute_benchmark_equity_curve, check_limit_up_down
from portfolio import Portfolio
from log_util import setup_logger


def compute_metrics(equity_df: pd.DataFrame) -> dict:
    """计算年化收益、最大回撤、夏普比率"""
    df = equity_df.copy()
    initial = df['strategy_equity'].iloc[0]
    final = df['strategy_equity'].iloc[-1]
    trading_days = len(df)
    years = trading_days / 252

    # 年化收益
    ann_return = (final / initial) ** (1 / years) - 1 if years > 0 else 0

    # 最大回撤
    cumulative_peak = df['strategy_equity'].cummax()
    drawdown = (df['strategy_equity'] - cumulative_peak) / cumulative_peak
    max_dd = drawdown.min()

    # 年化波动率 & 夏普
    daily_ret = df['strategy_equity'].pct_change().dropna()
    ann_vol = daily_ret.std() * np.sqrt(252)
    sharpe = (ann_return - config.RISK_FREE_RATE) / ann_vol if ann_vol > 0 else 0

    return {
        'annual_return': ann_return,
        'max_drawdown': max_dd,
        'sharpe_ratio': sharpe,
        'final_equity': final,
    }


def run_single_backtest(
    stock_codes: list,
    trading_days: list,
    cutoffs: list,
    price_cache: dict,
    ranking_method: str = "pb",
) -> dict:
    """对给定的股票子集运行一次完整的回测"""
    # 基准
    benchmark_df = compute_benchmark_equity_curve(
        stock_codes, trading_days, cutoffs, price_cache, config.INITIAL_CAPITAL
    )

    # 选股
    selection_results = {}
    for cutoff, rebalance in cutoffs:
        selected, val_df = select_stocks(stock_codes, cutoff, price_cache=price_cache)
        final_selected = rank_and_limit(selected, val_df, config.MAX_POSITIONS, ranking_method)
        selection_results[(cutoff, rebalance)] = final_selected

    # 调仓
    portfolio = Portfolio(initial_capital=config.INITIAL_CAPITAL)
    trade_records = []
    portfolio_states = []

    for (cutoff, rebalance), selected_codes in selection_results.items():
        execution_date = rebalance if rebalance is not None else cutoff

        prices = {}
        for code in stock_codes:
            if code in price_cache:
                row = price_cache[code][price_cache[code]['trade_date'] == execution_date]
                if not row.empty:
                    prices[code] = row['close'].iloc[0]

        if not prices:
            continue

        can_buy_flags = {}
        can_sell_flags = {}
        for code in set(portfolio.positions.keys()) | set(selected_codes):
            can_buy_flags[code] = True
            can_sell_flags[code] = True

        total_equity = portfolio.get_total_equity(prices)

        plan = portfolio.calculate_target_positions(
            selected_codes, total_equity, prices,
            can_buy=True, can_sell=True
        )

        for code, shares_to_sell in plan['sell_orders']:
            price = prices.get(code, 0)
            if price <= 0:
                continue
            exec_price = price * (1 - config.SLIPPAGE_RATE)
            trade = portfolio.sell_shares(code, shares_to_sell, exec_price, reason="调仓卖出")
            if trade:
                trade['trade_date'] = execution_date
                trade_records.append(trade)

        for code, shares_to_buy in plan['buy_orders']:
            price = prices.get(code, 0)
            if price <= 0:
                continue
            exec_price = price * (1 + config.SLIPPAGE_RATE)
            trade = portfolio.buy_shares(code, shares_to_buy, exec_price, reason="调仓买入")
            if trade:
                trade['trade_date'] = execution_date
                trade_records.append(trade)

        shares_snapshot = {code: pos['shares'] for code, pos in portfolio.positions.items()}
        portfolio_states.append((pd.Timestamp(execution_date), portfolio.cash, shares_snapshot))

    # 每日权益曲线
    stock_close_map = {}
    for code, df in price_cache.items():
        stock_close_map[code] = dict(zip(df['trade_date'], df['close']))

    strategy_equity = []
    if portfolio_states:
        first_rebalance = portfolio_states[0][0]
        state_idx = 0
        current_cash = portfolio_states[0][1]
        current_shares = portfolio_states[0][2]

        for day in trading_days:
            day_ts = pd.Timestamp(day)
            while state_idx + 1 < len(portfolio_states) and portfolio_states[state_idx + 1][0] <= day_ts:
                state_idx += 1
                current_cash = portfolio_states[state_idx][1]
                current_shares = portfolio_states[state_idx][2]

            if day_ts < first_rebalance:
                equity = config.INITIAL_CAPITAL
            else:
                equity = current_cash
                for code, shares in current_shares.items():
                    if shares > 0 and code in stock_close_map:
                        price = stock_close_map[code].get(day_ts)
                        if price is not None:
                            equity += shares * price
                        else:
                            before = {d: p for d, p in stock_close_map[code].items() if d < day_ts}
                            if before:
                                equity += shares * before[max(before)]
            strategy_equity.append({'date': day_ts, 'strategy_equity': equity})
    else:
        for day in trading_days:
            strategy_equity.append({'date': pd.Timestamp(day), 'strategy_equity': config.INITIAL_CAPITAL})

    strategy_df = pd.DataFrame(strategy_equity)

    if len(benchmark_df) > 0:
        equity_curve = strategy_df.merge(
            benchmark_df[['date', 'benchmark_equity']], on='date', how='left'
        )
        equity_curve['benchmark_equity'] = equity_curve['benchmark_equity'].ffill()
        equity_curve['benchmark_equity'] = equity_curve['benchmark_equity'].fillna(config.INITIAL_CAPITAL)
    else:
        equity_curve = strategy_df.copy()
        equity_curve['benchmark_equity'] = config.INITIAL_CAPITAL

    return equity_curve, trade_records


def main():
    parser = argparse.ArgumentParser(description="幸存者偏差模拟验证")
    parser.add_argument("--iterations", type=int, default=20, help="迭代次数 (默认: 20)")
    parser.add_argument("--drop_ratio", type=float, default=0.10, help="每次剔除比例 (默认: 0.10)")
    parser.add_argument("--frequency", type=str, default="annual", help="调仓频率 (默认: annual)")
    parser.add_argument("--ranking", type=str, default="pb", help="排名方式 (默认: pb)")
    parser.add_argument("--seed", type=int, default=42, help="随机种子 (默认: 42)")
    args = parser.parse_args()

    logger = setup_logger("survivorship", "survivorship")
    random.seed(args.seed)
    np.random.seed(args.seed)

    logger.info("=" * 60)
    logger.info("幸存者偏差模拟验证")
    logger.info(f"  迭代次数: {args.iterations}")
    logger.info(f"  每次剔除比例: {args.drop_ratio:.0%}")
    logger.info(f"  调仓频率: {args.frequency}")
    logger.info(f"  排名方式: {args.ranking}")
    logger.info("=" * 60)

    # 加载全局数据（只做一次）
    logger.info("\n[1/4] 加载股票池...")
    pool_df = load_stock_pool()
    all_codes = pool_df['code'].tolist()
    logger.info(f"  总股票数: {len(all_codes)}")

    logger.info(f"\n[2/4] 构建交易日历 ({args.frequency})...")
    trading_days = build_trading_calendar()
    logger.info(f"  交易日: {len(trading_days)}")

    if args.frequency == "annual":
        cutoffs = get_annual_cutoff_dates(trading_days)
    elif args.frequency == "annual_q3":
        from trading_calendar import get_annual_q3_cutoff_dates
        cutoffs = get_annual_q3_cutoff_dates(trading_days)
    else:
        from trading_calendar import get_weekly_cutoff_dates
        cutoffs = get_weekly_cutoff_dates(trading_days)
    logger.info(f"  截面日: {len(cutoffs)}")

    logger.info("\n[3/4] 预加载价格数据（一次加载，多次复用）...")
    price_cache = {}
    for code in tqdm(all_codes, desc="Loading prices"):
        df = load_price_data(code)
        if not df.empty:
            price_cache[code] = df
    logger.info(f"  已缓存 {len(price_cache)} 只股票的价格数据")

    # 完整池的基准回测（用来对比）
    logger.info("\n[4/4] 运行完整池的基准回测...")
    eq_base, trades_base = run_single_backtest(
        all_codes, trading_days, cutoffs, price_cache, args.ranking
    )
    base_metrics = compute_metrics(eq_base)
    logger.info(f"\n  完整池基准结果:")
    logger.info(f"    年化收益:     {base_metrics['annual_return']:.2%}")
    logger.info(f"    最大回撤:     {base_metrics['max_drawdown']:.2%}")
    logger.info(f"    夏普比率:     {base_metrics['sharpe_ratio']:.4f}")
    logger.info(f"    最终权益:     {base_metrics['final_equity']:,.0f}")

    # 随机剔除模拟
    logger.info(f"\n{'=' * 60}")
    logger.info(f"运行 {args.iterations} 次随机剔除 {args.drop_ratio:.0%} 的回测...")
    logger.info(f"{'=' * 60}")

    results = []
    base_n = len(all_codes)
    drop_n = int(base_n * args.drop_ratio)

    for i in tqdm(range(args.iterations), desc="Simulating"):
        # 随机剔除
        dropped = set(random.sample(all_codes, drop_n))
        reduced_codes = [c for c in all_codes if c not in dropped]

        eq, trades = run_single_backtest(
            reduced_codes, trading_days, cutoffs, price_cache, args.ranking
        )

        metrics = compute_metrics(eq)
        metrics['iter'] = i + 1
        metrics['pool_size'] = len(reduced_codes)
        metrics['dropped'] = drop_n
        results.append(metrics)

    # 统计结果
    df_results = pd.DataFrame(results)
    ann_returns = df_results['annual_return']
    max_drawdowns = df_results['max_drawdown']
    sharpes = df_results['sharpe_ratio']

    logger.info(f"\n{'=' * 60}")
    logger.info(f"模拟结果汇总 ({args.iterations} 次 × 剔除 {args.drop_ratio:.0%})")
    logger.info(f"{'=' * 60}")
    logger.info(f"\n  年化收益:")
    logger.info(f"    完整池基准:   {base_metrics['annual_return']:.2%}")
    logger.info(f"    剔除后均值:   {ann_returns.mean():.2%}")
    logger.info(f"    剔除后中位:   {ann_returns.median():.2%}")
    logger.info(f"    剔除后下沿:   {ann_returns.quantile(0.10):.2%}")
    logger.info(f"    剔除后最低:   {ann_returns.min():.2%}")
    logger.info(f"    剔除后最高:   {ann_returns.max():.2%}")
    logger.info(f"    标准差:       {ann_returns.std():.2%}")

    logger.info(f"\n  最大回撤:")
    logger.info(f"    完整池基准:   {base_metrics['max_drawdown']:.2%}")
    logger.info(f"    剔除后均值:   {max_drawdowns.mean():.2%}")
    logger.info(f"    剔除后最差:   {max_drawdowns.min():.2%}")

    logger.info(f"\n  夏普比率:")
    logger.info(f"    完整池基准:   {base_metrics['sharpe_ratio']:.4f}")
    logger.info(f"    剔除后均值:   {sharpes.mean():.4f}")
    logger.info(f"    剔除后最低:   {sharpes.min():.4f}")

    logger.info(f"\n  偏差估计:")
    bias_10 = ann_returns.quantile(0.10) - base_metrics['annual_return']
    bias_mean = ann_returns.mean() - base_metrics['annual_return']
    logger.info(f"    均值偏差:     {bias_mean:+.2%}")
    logger.info(f"    下沿(10%)偏差: {bias_10:+.2%}")

    # 保存结果
    output_path = os.path.join(config.DATA_OUTPUT_DIR, "analysis", "survivorship_simulation.csv")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df_results.to_csv(output_path, index=False)
    logger.info(f"\n详细结果已保存至: {output_path}")


if __name__ == "__main__":
    main()
