"""
打分制选股策略回测

使用多因子打分替代 PB 单一排名，选股逻辑：
1. Step 1-4 不变（硬阈值 AND 过滤：PE<25% + PB<25% + PR<25% + ROE>75% + 新股排除）
2. 在幸存者中对 PE/PB/PR/ROE 计算百分位排名
3. 综合得分 = PE_rank + PB_rank + PR_rank + (1 - ROE_rank)
4. 取得分最低的 5 只（而非仅按 PB 取前 5）

运行方式:
    cd backtesting
    python test_scoring.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np
from tqdm import tqdm

import config
from data_loader import load_stock_pool, load_price_data
from trading_calendar import build_trading_calendar, get_annual_cutoff_dates
from stock_selector import (
    select_stocks, rank_and_limit,
)
from backtest_engine import compute_benchmark_equity_curve
from portfolio import Portfolio
from log_util import setup_logger


def rank_and_limit_by_score(selected: list, val_df: pd.DataFrame, max_positions: int = 5) -> list:
    """
    在通过硬阈值筛选的股票中，按综合得分排序取前 N 只。

    得分公式: score = PE_pct + PB_pct + PR_pct + (1 - ROE_pct)
    分数越低越好。

    Args:
        selected: 通过四步筛选的股票代码列表
        val_df: 所有候选股票的估值 DataFrame
        max_positions: 最大持仓数量

    Returns:
        排序后的股票代码列表（不超过 max_positions）
    """
    if len(selected) <= max_positions:
        return selected

    subset = val_df[val_df['code'].isin(selected)].copy()
    if subset.empty:
        return selected[:max_positions]

    subset['pe_rank'] = subset['pe_ttm'].rank(pct=True, ascending=True)
    subset['pb_rank'] = subset['pb_ttm'].rank(pct=True, ascending=True)
    subset['pr_rank'] = subset['pr_ttm'].rank(pct=True, ascending=True)
    subset['roe_rank'] = subset['roe_ttm'].rank(pct=True, ascending=False)

    subset['score'] = (
        subset['pe_rank'] +
        subset['pb_rank'] +
        subset['pr_rank'] +
        subset['roe_rank']
    )

    subset = subset.sort_values('score')
    return subset['code'].head(max_positions).tolist()
    val_df = val_df.sort_values("score").head(max_positions * 2)  # 多取一些应对新股排除

    # 新股排除
    selected = []
    for _, row in val_df.iterrows():
        code = row["code"]
        price_df = price_cache.get(code)
        if price_df is not None and not is_new_stock(code, price_df, trade_date, config.NEW_STOCK_EXCLUDE_DAYS):
            selected.append(code)
        if len(selected) >= max_positions:
            break

    return selected


def compute_metrics(equity_df: pd.DataFrame) -> dict:
    """计算年化收益、最大回撤、夏普比率"""
    df = equity_df.copy()
    initial = df['strategy_equity'].iloc[0]
    final = df['strategy_equity'].iloc[-1]
    trading_days = len(df)
    years = trading_days / 252
    ann_return = (final / initial) ** (1 / years) - 1 if years > 0 else 0
    peak = df['strategy_equity'].cummax()
    drawdown = (df['strategy_equity'] - peak) / peak
    max_dd = drawdown.min()
    daily_ret = df['strategy_equity'].pct_change().dropna()
    ann_vol = daily_ret.std() * np.sqrt(252)
    sharpe = (ann_return - config.RISK_FREE_RATE) / ann_vol if ann_vol > 0 else 0
    return {
        'annual_return': ann_return,
        'max_drawdown': max_dd,
        'sharpe_ratio': sharpe,
        'final_equity': final,
    }


def run_backtest(stock_codes, trading_days, cutoffs, price_cache):
    """执行完整回测"""
    benchmark_df = compute_benchmark_equity_curve(
        stock_codes, trading_days, cutoffs, price_cache, config.INITIAL_CAPITAL
    )

    # 选股：硬阈值AND过滤 + 打分排名
    selection_results = {}
    for cutoff, rebalance in cutoffs:
        selected, val_df = select_stocks(stock_codes, cutoff, price_cache=price_cache)
        final_selected = rank_and_limit_by_score(selected, val_df, config.MAX_POSITIONS)
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

        total_equity = portfolio.get_total_equity(prices)
        plan = portfolio.calculate_target_positions(
            selected_codes, total_equity, prices, can_buy=True, can_sell=True
        )

        for code, shares_to_sell in plan['sell_orders']:
            price = prices.get(code, 0)
            if price <= 0:
                continue
            trade = portfolio.sell_shares(code, shares_to_sell, price * (1 - config.SLIPPAGE_RATE), reason="调仓卖出")
            if trade:
                trade['trade_date'] = execution_date
                trade_records.append(trade)

        for code, shares_to_buy in plan['buy_orders']:
            price = prices.get(code, 0)
            if price <= 0:
                continue
            trade = portfolio.buy_shares(code, shares_to_buy, price * (1 + config.SLIPPAGE_RATE), reason="调仓买入")
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
    logger = setup_logger("test_scoring", "test_scoring")

    logger.info("=" * 60)
    logger.info("混合策略回测：硬阈值AND过滤 + 打分排名")
    logger.info("  Step 1-4: PE<25% AND PB<25% AND PR<25% AND ROE>75%（同原策略）")
    logger.info("  排名方式: score = PE_pct + PB_pct + PR_pct + (1-ROE_pct)，取最低5只")
    logger.info("  对比原策略: 同步骤1-4，但原策略仅按PB排名")
    logger.info("  调仓频率: annual, 无止损, 无 winsorization")
    logger.info("=" * 60)

    # 加载数据
    pool_df = load_stock_pool()
    all_codes = pool_df['code'].tolist()
    logger.info(f"  股票池: {len(all_codes)} 只")

    trading_days = build_trading_calendar()
    logger.info(f"  交易日: {len(trading_days)}")

    cutoffs = get_annual_cutoff_dates(trading_days)
    logger.info(f"  截面日: {len(cutoffs)}")

    logger.info("  加载价格数据...")
    price_cache = {}
    for code in tqdm(all_codes, desc="Loading prices"):
        df = load_price_data(code)
        if not df.empty:
            price_cache[code] = df
    logger.info(f"  已缓存 {len(price_cache)} 只股票")

    # 运行打分制回测
    logger.info("\n运行打分制选股回测...")
    eq_score, trades_score = run_backtest(all_codes, trading_days, cutoffs, price_cache)
    metrics_score = compute_metrics(eq_score)

    # 计算年度收益
    eq_score['year'] = pd.to_datetime(eq_score['date']).dt.year
    annual_returns = []
    for year, group in eq_score.groupby('year'):
        strat_ret = group['strategy_equity'].iloc[-1] / group['strategy_equity'].iloc[0] - 1
        bench_ret = group['benchmark_equity'].iloc[-1] / group['benchmark_equity'].iloc[0] - 1
        annual_returns.append({'year': year, 'strategy': strat_ret, 'benchmark': bench_ret})

    logger.info(f"\n{'=' * 60}")
    logger.info("混合策略结果")
    logger.info(f"{'=' * 60}")
    logger.info(f"  年化收益:     {metrics_score['annual_return']:.2%}")
    logger.info(f"  最大回撤:     {metrics_score['max_drawdown']:.2%}")
    logger.info(f"  夏普比率:     {metrics_score['sharpe_ratio']:.4f}")
    logger.info(f"  最终权益:     {metrics_score['final_equity']:,.0f}")
    logger.info(f"  交易次数:     {len(trades_score)}")

    logger.info(f"\n{'=' * 60}")
    logger.info("年度对比（混合策略 vs 原策略PB排名）")
    logger.info(f"{'=' * 60}")
    logger.info(f"  {'年份':>6}  {'打分制':>10}  {'原策略':>10}  {'基准':>10}")
    logger.info("  " + "-" * 40)

    # 原策略年度收益（从已知数据填入）
    original_annual = {
        2015: 0.00, 2016: 0.093, 2017: 0.230, 2018: -0.327,
        2019: 0.477, 2020: -0.006, 2021: 0.209, 2022: -0.075,
        2023: 0.196, 2024: 0.426, 2025: 0.266, 2026: -0.026,
    }

    for ar in sorted(annual_returns, key=lambda x: x['year']):
        orig = original_annual.get(ar['year'], None)
        orig_str = f"{orig:.2%}" if orig is not None else "N/A"
        logger.info(f"  {ar['year']:>6}  {ar['strategy']:>10.2%}  {orig_str:>10}  {ar['benchmark']:>10.2%}")

    logger.info(f"\n{'=' * 60}")
    logger.info("对比总结")
    logger.info(f"{'=' * 60}")
    logger.info(f"  {'指标':<20}  {'混合策略':>12}  {'原策略(PB排名)':>16}")
    logger.info(f"  {'年化收益':<20}  {metrics_score['annual_return']:>11.2%}  {0.1137:>15.2%}")
    logger.info(f"  {'最大回撤':<20}  {metrics_score['max_drawdown']:>11.2%}  {-0.4034:>15.2%}")
    logger.info(f"  {'夏普比率':<20}  {metrics_score['sharpe_ratio']:>11.4f}  {0.5025:>15.4f}")
    logger.info(f"  {'最终权益':<20}  {metrics_score['final_equity']:>11,.0f}  {3241201:>15,.0f}")


if __name__ == "__main__":
    main()
