"""
估值指标组合对比回测

测试不同估值指标组合对策略收益的影响：
1. PE + PB + ROE（去掉 PR）
2. PB + ROE（只看 PB 和 ROE）
3. PE + ROE（只看 PE 和 ROE）

运行方式:
    cd backtesting
    python test_filter_combos.py
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
    get_latest_financial_data, calculate_valuation, is_new_stock,
    winsorize, rank_and_limit,
)
from backtest_engine import compute_benchmark_equity_curve
from portfolio import Portfolio
from log_util import setup_logger


def select_stocks_custom(
    stock_codes: list,
    trade_date: pd.Timestamp,
    price_cache: dict = None,
    use_pe: bool = True,
    use_pb: bool = True,
    use_pr: bool = True,
    use_roe: bool = True,
) -> tuple:
    """
    自定义指标组合的四步选股。

    Args:
        stock_codes: 候选股票代码列表
        trade_date: 截面日
        price_cache: 价格数据缓存
        use_pe: 是否使用 PE 作为过滤条件
        use_pb: 是否使用 PB 作为过滤条件
        use_pr: 是否使用 PR 作为过滤条件
        use_roe: 是否使用 ROE 作为过滤条件

    Returns:
        (selected_codes, all_valuations_df)
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

        all_valuations.append({
            "code": code,
            **valuation
        })

    if not all_valuations:
        return [], pd.DataFrame()

    val_df = pd.DataFrame(all_valuations)

    # Step 2 - Valuation filter (winsorize enabled by default)
    use_winsor = config.WINSORIZE_ENABLED
    conditions = []

    if use_pe:
        if use_winsor:
            val_df["pe_w"] = winsorize(val_df["pe_ttm"])
            pe_cut = val_df["pe_w"].quantile(config.PE_THRESHOLD)
        else:
            pe_cut = val_df["pe_ttm"].quantile(config.PE_THRESHOLD)
        conditions.append(val_df["pe_ttm"] <= pe_cut)

    if use_pb:
        if use_winsor:
            val_df["pb_w"] = winsorize(val_df["pb_ttm"])
            pb_cut = val_df["pb_w"].quantile(config.PB_THRESHOLD)
        else:
            pb_cut = val_df["pb_ttm"].quantile(config.PB_THRESHOLD)
        conditions.append(val_df["pb_ttm"] <= pb_cut)

    if use_pr:
        if use_winsor:
            val_df["pr_w"] = winsorize(val_df["pr_ttm"])
            pr_cut = val_df["pr_w"].quantile(config.PR_THRESHOLD)
        else:
            pr_cut = val_df["pr_ttm"].quantile(config.PR_THRESHOLD)
        conditions.append(val_df["pr_ttm"] <= pr_cut)

    step2_df = val_df
    if conditions:
        combined = conditions[0]
        for c in conditions[1:]:
            combined = combined & c
        step2_df = val_df[combined]

    if step2_df.empty:
        return [], val_df

    # Step 3 - ROE filter
    if use_roe:
        roe_cut = val_df["roe_ttm"].quantile(config.ROE_THRESHOLD)
        step3_df = step2_df[step2_df["roe_ttm"] >= roe_cut]
    else:
        step3_df = step2_df

    if step3_df.empty:
        return [], val_df

    # Step 4 - New stock exclude
    selected = []
    for _, row in step3_df.iterrows():
        code = row["code"]
        p_df = price_cache.get(code)
        if p_df is not None and not is_new_stock(code, p_df, trade_date, config.NEW_STOCK_EXCLUDE_DAYS):
            selected.append(code)

    return selected, val_df


def compute_metrics(equity_df: pd.DataFrame) -> dict:
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
        'annual_volatility': ann_vol,
    }


def compute_annual_returns(equity_df: pd.DataFrame) -> dict:
    ec = equity_df.copy()
    ec['year'] = pd.to_datetime(ec['date']).dt.year
    results = {}
    for year, group in ec.groupby('year'):
        first = group['strategy_equity'].iloc[0]
        last = group['strategy_equity'].iloc[-1]
        results[year] = (last - first) / first
    return results


def run_backtest(stock_codes, trading_days, cutoffs, price_cache,
                 use_pe=True, use_pb=True, use_pr=True, use_roe=True,
                 ranking_method="pb"):
    """执行单次回测"""
    benchmark_df = compute_benchmark_equity_curve(
        stock_codes, trading_days, cutoffs, price_cache, config.INITIAL_CAPITAL
    )

    selection_results = {}
    for cutoff, rebalance in cutoffs:
        selected, val_df = select_stocks_custom(
            stock_codes, cutoff, price_cache,
            use_pe=use_pe, use_pb=use_pb, use_pr=use_pr, use_roe=use_roe,
        )
        final_selected = rank_and_limit(selected, val_df, config.MAX_POSITIONS, ranking_method)
        selection_results[(cutoff, rebalance)] = final_selected

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
    logger = setup_logger("filter_combos", "filter_combos")

    combos = [
        # 筛选: PE+ROE, 排名: PE/PB/PR
        {"label": "筛选PE+ROE + 排名PE", "pe": True, "pb": False, "pr": False, "roe": True, "rank": "pe"},
        {"label": "筛选PE+ROE + 排名PB", "pe": True, "pb": False, "pr": False, "roe": True, "rank": "pb"},
        {"label": "筛选PE+ROE + 排名PR", "pe": True, "pb": False, "pr": False, "roe": True, "rank": "pr"},
        # 筛选: PB+ROE, 排名: PE/PB/PR
        {"label": "筛选PB+ROE + 排名PE", "pe": False, "pb": True, "pr": False, "roe": True, "rank": "pe"},
        {"label": "筛选PB+ROE + 排名PB", "pe": False, "pb": True, "pr": False, "roe": True, "rank": "pb"},
        {"label": "筛选PB+ROE + 排名PR", "pe": False, "pb": True, "pr": False, "roe": True, "rank": "pr"},
        # 筛选: PR+ROE, 排名: PE/PB/PR
        {"label": "筛选PR+ROE + 排名PE", "pe": False, "pb": False, "pr": True, "roe": True, "rank": "pe"},
        {"label": "筛选PR+ROE + 排名PB", "pe": False, "pb": False, "pr": True, "roe": True, "rank": "pb"},
        {"label": "筛选PR+ROE + 排名PR", "pe": False, "pb": False, "pr": True, "roe": True, "rank": "pr"},
    ]

    logger.info("=" * 60)
    logger.info("估值指标组合对比回测")
    logger.info(f"  调仓频率: annual, 排名方式: pb, no_winsorize")
    logger.info(f"  对比基准: PE+PB+PR+ROE (原策略) = 11.37%")
    logger.info("=" * 60)

    # 关闭 winsorization（用户的习惯配置）
    config.WINSORIZE_ENABLED = False

    # Load data
    pool_df = load_stock_pool()
    all_codes = pool_df['code'].tolist()
    logger.info(f"  股票池: {len(all_codes)} 只")

    trading_days = build_trading_calendar()
    logger.info(f"  交易日: {len(trading_days)}")

    cutoffs = get_annual_cutoff_dates(trading_days)
    logger.info(f"  截面日: {len(cutoffs)}")

    logger.info("  加载价格数据...")
    price_cache = {}
    for code in tqdm(all_codes, desc="Loading"):
        df = load_price_data(code)
        if not df.empty:
            price_cache[code] = df
    logger.info(f"  已缓存 {len(price_cache)} 只股票")

    # Run all combos
    results = {}
    for combo in combos:
        label = combo["label"]
        logger.info(f"\n>>> 测试: {label}")
        eq, trades = run_backtest(
            all_codes, trading_days, cutoffs, price_cache,
            use_pe=combo["pe"], use_pb=combo["pb"],
            use_pr=combo["pr"], use_roe=combo["roe"],
            ranking_method=combo["rank"],
        )
        metrics = compute_metrics(eq)
        annual = compute_annual_returns(eq)
        results[label] = {"metrics": metrics, "annual": annual, "trades": len(trades)}

    # Print summary table
    logger.info(f"\n{'=' * 80}")
    logger.info(f"对比汇总")
    logger.info(f"{'=' * 80}")
    logger.info(f"  {'指标组合':<30}  {'年化收益':>10}  {'最大回撤':>10}  {'夏普':>8}  {'年化波动':>10}")
    logger.info("  " + "-" * 70)

    # Original baseline
    logger.info(f"  {'PE+PB+PR+ROE (原策略)':<30}  {0.1137:>9.2%}  {-0.4034:>9.2%}  {0.5025:>7.4f}  {0.1865:>9.2%}")

    for combo in combos:
        label = combo["label"]
        m = results[label]["metrics"]
        logger.info(f"  {label:<30}  {m['annual_return']:>9.2%}  {m['max_drawdown']:>9.2%}  {m['sharpe_ratio']:>7.4f}  {m['annual_volatility']:>9.2%}")

    # Annual returns detail
    logger.info(f"\n{'=' * 80}")
    logger.info(f"年度收益明细")
    logger.info(f"{'=' * 80}")

    all_labels = ["PE+PB+PR+ROE (原策略)"] + [c["label"] for c in combos]
    original_annual = {
        2015: 0.00, 2016: 0.093, 2017: 0.230, 2018: -0.327,
        2019: 0.477, 2020: -0.006, 2021: 0.209, 2022: -0.075,
        2023: 0.196, 2024: 0.426, 2025: 0.266, 2026: -0.026,
    }
    all_years = sorted(original_annual.keys())

    header = f"  {'年份':>6}"
    for label in all_labels:
        header += f"  {label[:16]:>16}"
    logger.info(header)
    logger.info("  " + "-" * (8 + 18 * len(all_labels)))

    for year in all_years:
        row = f"  {year:>6}"
        row += f"  {original_annual[year]:>15.2%}"
        for combo in combos:
            label = combo["label"]
            val = results[label]["annual"].get(year)
            if val is not None:
                row += f"  {val:>15.2%}"
            else:
                row += f"  {'N/A':>16}"
        logger.info(row)

    # Trade counts
    logger.info(f"\n交易次数:")
    logger.info(f"  PE+PB+PR+ROE (原策略):  N/A (未记录)")
    for combo in combos:
        label = combo["label"]
        logger.info(f"  {label}:  {results[label]['trades']}")


if __name__ == "__main__":
    main()
