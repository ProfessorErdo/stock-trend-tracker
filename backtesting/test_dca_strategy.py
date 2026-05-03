"""
月度定投 + 回撤触发加仓策略模拟

规则：
- 从 2015-01 起，每月累积 30,000 元
- 每年 5 月调仓（复用 annual 频率回测）
- 当年度回撤超过阈值时，将已累积现金等权买入当前持仓
- 加仓后累积归零，继续每月累积，当年可多次触发
"""

import sys
import os
import logging

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from data_loader import load_stock_pool, query_price_data
from trading_calendar import build_trading_calendar, get_annual_cutoff_dates
from backtest_engine import run_backtest
from performance import calculate_performance, save_performance_summary
from log_util import setup_logger

MONTHLY_DEPOSIT = 30000
DEPOSIT_START = "2015-01-01"
DRAWDOWN_THRESHOLD = 0.10

logger = logging.getLogger("dca")


def _xirr(cash_flows: list) -> float:
    """计算 XIRR（扩展内部收益率）— 年化资金权重收益率 (MWR)"""
    dates = [pd.Timestamp(d) for d, _ in cash_flows]
    amounts = [float(a) for _, a in cash_flows]
    t0 = dates[0]
    days = [(d - t0).days for d in dates]

    def npv(rate):
        return sum(cf / (1 + rate) ** (d / 365) for cf, d in zip(amounts, days))

    def npv_deriv(rate):
        return sum(
            -cf * (d / 365) / (1 + rate) ** (d / 365 + 1)
            for cf, d in zip(amounts, days)
        )

    # Newton-Raphson
    rate = 0.1
    for _ in range(100):
        val = npv(rate)
        if abs(val) < 1e-8:
            return rate
        deriv = npv_deriv(rate)
        if deriv == 0:
            break
        rate -= val / deriv
        if rate < -0.99:
            rate = -0.99

    # Fallback: bisection
    lo, hi = -0.99, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2
        val = npv(mid)
        if abs(val) < 1e-8:
            return mid
        if npv(lo) * val < 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def simulate_dca_add_deposit(result: dict, monthly_deposit: float = MONTHLY_DEPOSIT,
                              drawdown_threshold: float = DRAWDOWN_THRESHOLD) -> dict:
    equity_curve = result['equity_curve'].copy()
    portfolio_states = result['portfolio_states']
    price_cache = result['price_cache']
    trading_days = result['trading_days']

    stock_close_map = {}
    for code, df in price_cache.items():
        if 'close' not in df.columns:
            continue
        stock_close_map[code] = dict(zip(df['trade_date'], df['close']))

    first_rebalance = portfolio_states[0][0]

    # 收集每年调仓日（用于强制投入累积资金）
    annual_rebalances = [
        pd.Timestamp(r) for _, r in get_annual_cutoff_dates(trading_days) if r
    ]

    deposit_shares = {}
    accumulated = 0.0
    deposit_start_ts = pd.Timestamp(DEPOSIT_START)

    dca_equity = []
    deposit_log = []
    daily_deposits = []

    state_idx = 0
    current_cash = portfolio_states[0][1]
    current_shares = portfolio_states[0][2]

    # 回撤峰值：仅跟踪已投入的市值（base_equity + deposit_value），不含累积现金
    invested_yearly_peak = 0.0
    current_year = None
    deposited_today = False

    for day in trading_days:
        day_ts = pd.Timestamp(day)

        while state_idx + 1 < len(portfolio_states) and portfolio_states[state_idx + 1][0] <= day_ts:
            state_idx += 1
            current_cash = portfolio_states[state_idx][1]
            current_shares = portfolio_states[state_idx][2]

        if day_ts < first_rebalance:
            base_equity = config.INITIAL_CAPITAL
        else:
            base_equity = current_cash
            for code, shares in current_shares.items():
                if shares > 0 and code in stock_close_map:
                    price = stock_close_map[code].get(day_ts)
                    if price is None:
                        before = {d: p for d, p in stock_close_map[code].items() if d < day_ts}
                        price = before[max(before)] if before else 0
                    base_equity += shares * price

        bench_row = equity_curve[equity_curve['date'] == day_ts]
        bench_equity = config.INITIAL_CAPITAL
        if not bench_row.empty:
            bench_equity = bench_row.iloc[0].get('benchmark_equity', config.INITIAL_CAPITAL)

        deposit_value = 0.0
        for code, shares in deposit_shares.items():
            if shares > 0 and code in stock_close_map:
                price = stock_close_map[code].get(day_ts)
                if price is None:
                    before = {d: p for d, p in stock_close_map[code].items() if d < day_ts}
                    price = before[max(before)] if before else 0
                deposit_value += shares * price

        invested_value = base_equity + deposit_value
        dca_eq = invested_value + accumulated

        months = (day_ts.year - deposit_start_ts.year) * 12 + (day_ts.month - deposit_start_ts.month)
        expected = months * monthly_deposit
        if expected > accumulated:
            accumulated = expected

        if current_year != day_ts.year:
            current_year = day_ts.year
            invested_yearly_peak = 0.0
            deposited_today = False

        # 峰值仅跟踪已投入市值
        if not deposited_today:
            if invested_value > invested_yearly_peak:
                invested_yearly_peak = invested_value

        # 强制投入触发条件：每年调仓日 或 年度回撤超过阈值
        is_rebalance_day = day_ts in annual_rebalances
        triggered = False
        trigger_reason = ""

        if len(current_shares) > 0 and not deposited_today and accumulated > 0:
            if is_rebalance_day:
                triggered = True
                trigger_reason = "年度调仓"

            if not triggered and invested_yearly_peak > 0:
                drawdown = (invested_value - invested_yearly_peak) / invested_yearly_peak
                if drawdown < -drawdown_threshold:
                    triggered = True
                    trigger_reason = f"回撤 {drawdown:.1%}"

        if triggered:
            deposit_amount = accumulated
            n = len(current_shares)
            per_stock = deposit_amount / n

            shares_bought = {}
            for code in current_shares:
                price = stock_close_map.get(code, {}).get(day_ts, 0)
                if price > 0:
                    lots = int(per_stock / price) // config.LOT_SIZE * config.LOT_SIZE
                    shares_bought[code] = lots
                    deposit_shares[code] = deposit_shares.get(code, 0) + lots

            actual_invested = sum(
                shares_bought[c] * stock_close_map.get(c, {}).get(day_ts, 0)
                for c in shares_bought
            )

            drawdown_at_trigger = drawdown if 'drawdown' in dir() else 0.0

            deposit_log.append({
                'date': day_ts,
                'deposit_amount': deposit_amount,
                'actual_invested': actual_invested,
                'n_positions': n,
                'yearly_peak': invested_yearly_peak,
                'drawdown': drawdown_at_trigger,
                'reason': trigger_reason,
                'shares_bought': shares_bought,
            })

            daily_deposits.append({'date': day_ts, 'amount': deposit_amount})

            accumulated = 0.0
            deposit_start_ts = day_ts
            deposited_today = True

            logger.info(
                f"  [#{len(deposit_log):2d}] {day_ts.strftime('%Y-%m-%d')} "
                f"deposit {deposit_amount:>10,.0f} into {n} positions "
                f"[{trigger_reason}]"
            )

            # Recalculate DCA equity after deposit
            deposit_value = 0.0
            for code, shares in deposit_shares.items():
                if shares > 0 and code in stock_close_map:
                    price = stock_close_map[code].get(day_ts, 0)
                    if price is None:
                        before = {d: p for d, p in stock_close_map[code].items() if d < day_ts}
                        price = before[max(before)] if before else 0
                    deposit_value += shares * price
            dca_eq = base_equity + deposit_value + accumulated

        dca_equity.append({
            'date': day_ts,
            'strategy_equity': base_equity,
            'dca_equity': dca_eq,
            'benchmark_equity': bench_equity,
        })

    return {
        'equity_curve': pd.DataFrame(dca_equity),
        'deposit_log': deposit_log,
        'daily_deposits': daily_deposits,
    }


def calculate_dca_performance(dca_df: pd.DataFrame, daily_deposits: list,
                               cutoffs: list, benchmark_df: pd.DataFrame) -> dict:
    """
    计算 DCA 策略的绩效指标，分别输出 MWR 和 TWR。

    MWR = XIRR（资金权重，投资者体验）
    TWR = 每日 Modified Dietz 连乘（时间权重，策略能力）
    """
    df = dca_df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)

    deposit_map = {d['date']: d['amount'] for d in daily_deposits}

    eq = df['dca_equity'].values
    dates = df['date'].values
    n = len(df)

    t_start = pd.Timestamp(dates[0])
    t_end = pd.Timestamp(dates[-1])
    t_days = (t_end - t_start).days

    # =====================================================================
    # MWR — XIRR: "我赚了多少钱"
    # =====================================================================
    cash_flows = []
    cash_flows.append((t_start, -config.INITIAL_CAPITAL))
    for d in daily_deposits:
        cash_flows.append((pd.Timestamp(d['date']), -d['amount']))
    cash_flows.append((t_end, eq[-1]))
    cash_flows.sort(key=lambda x: pd.Timestamp(x[0]))

    mwr_annual = _xirr(cash_flows)

    # =====================================================================
    # TWR — "策略本身赚了多少"（剥离资金进出）
    #
    # Modified Dietz daily return:
    #   r_i = (V_i - V_{i-1} - CF_i) / (V_{i-1} + sum(CF_before_i))
    # CF_before_i = 当日充值（发生在盘后时不影响分母）
    # 简化：假设充值发生在盘后，即 r_i = (V_i - V_{i-1} - CF_i) / V_{i-1}
    # =====================================================================
    daily_returns = np.zeros(n)
    twr_cum = 1.0
    for i in range(1, n):
        cf = deposit_map.get(pd.Timestamp(dates[i]), 0.0)
        prev = eq[i - 1]
        if prev > 0:
            ret = (eq[i] - cf) / prev - 1
            daily_returns[i] = ret
            twr_cum *= (1 + ret)
        else:
            daily_returns[i] = 0.0
    twr = twr_cum - 1
    twr_annual = (1 + twr) ** (252 / t_days) - 1 if t_days > 0 else 0.0

    df['daily_return'] = daily_returns

    # =====================================================================
    # 累计本金 & 利润
    # =====================================================================
    cumulative_deposits = np.cumsum([deposit_map.get(pd.Timestamp(d), 0.0) for d in dates])
    df['capital'] = config.INITIAL_CAPITAL + cumulative_deposits

    total_deposits = cumulative_deposits[-1]
    final_capital = config.INITIAL_CAPITAL + total_deposits
    final_equity = eq[-1]
    total_profit = final_equity - final_capital

    # =====================================================================
    # 波动率 / 夏普（用 TWR 的每日收益率，MWR 年化收益做分子）
    # =====================================================================
    annual_volatility = df['daily_return'].std() * np.sqrt(252)
    sharpe_ratio = (mwr_annual - config.RISK_FREE_RATE) / annual_volatility if annual_volatility != 0 else 0

    # =====================================================================
    # 最大回撤
    # =====================================================================
    df['cumulative_peak'] = df['dca_equity'].cummax()
    df['drawdown'] = (df['dca_equity'] - df['cumulative_peak']) / df['cumulative_peak']

    max_drawdown = df['drawdown'].min()
    trough_idx = df['drawdown'].idxmin()
    peak_idx = df.loc[:trough_idx, 'dca_equity'].idxmax()
    max_drawdown_duration_days = (df.loc[trough_idx, 'date'] - df.loc[peak_idx, 'date']).days

    peak_equity = df.loc[peak_idx, 'dca_equity']
    recovery_series = df.loc[trough_idx:, 'dca_equity']
    recovered = recovery_series[recovery_series >= peak_equity]
    recovery_days = (df.loc[recovered.index[0], 'date'] - df.loc[trough_idx, 'date']).days if len(recovered) > 0 else None

    # =====================================================================
    # 胜率（Modified Dietz 口径）
    # =====================================================================
    win_rate, profit_loss_ratio = _dca_win_rate(df, cutoffs, deposit_map)

    # =====================================================================
    # 基准
    # =====================================================================
    bench_initial = df['benchmark_equity'].iloc[0]
    bench_final = df['benchmark_equity'].iloc[-1]
    benchmark_cumulative_return = bench_final / bench_initial - 1
    benchmark_annual_return = (1 + benchmark_cumulative_return) ** (252 / t_days) - 1 if t_days > 0 else 0

    df['benchmark_daily_return'] = df['benchmark_equity'].pct_change()
    df['excess_daily_return'] = df['daily_return'] - df['benchmark_daily_return']
    tracking_error = df['excess_daily_return'].std() * np.sqrt(252)
    excess_annual = mwr_annual - benchmark_annual_return
    information_ratio = excess_annual / tracking_error if tracking_error != 0 else 0

    annual_returns = _dca_annual_returns(df, deposit_map)

    return {
        'mwr_annual': mwr_annual,
        'twr_cumulative': twr,
        'twr_annual': twr_annual,
        'annual_volatility': annual_volatility,
        'sharpe_ratio': sharpe_ratio,
        'max_drawdown': max_drawdown,
        'max_drawdown_duration_days': max_drawdown_duration_days,
        'recovery_days': recovery_days,
        'win_rate': win_rate,
        'profit_loss_ratio': profit_loss_ratio,
        'benchmark_cumulative_return': benchmark_cumulative_return,
        'benchmark_annual_return': benchmark_annual_return,
        'excess_return': excess_annual,
        'tracking_error': tracking_error,
        'information_ratio': information_ratio,
        'annual_returns': annual_returns,
        'trading_days': n,
        'initial_capital': config.INITIAL_CAPITAL,
        'total_deposits': total_deposits,
        'final_capital': final_capital,
        'final_equity': final_equity,
        'total_profit': total_profit,
    }


def _dca_win_rate(df: pd.DataFrame, cutoffs: list, deposit_map: dict) -> tuple:
    cutoffs_dt = [pd.to_datetime(c) for c in cutoffs]
    returns = []
    for i in range(1, len(cutoffs_dt)):
        start_date = cutoffs_dt[i - 1]
        end_date = cutoffs_dt[i]
        start_rows = df[df['date'] >= start_date]
        end_rows = df[df['date'] >= end_date]
        if len(start_rows) == 0 or len(end_rows) == 0:
            continue
        start_equity = start_rows.iloc[0]['dca_equity']
        end_equity = end_rows.iloc[0]['dca_equity']
        period_deposits = sum(
            amt for d, amt in deposit_map.items()
            if start_date <= d < end_date
        )
        period_return = (end_equity - start_equity - period_deposits) / start_equity
        returns.append(period_return)

    if not returns:
        return None, None
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    win_rate = len(wins) / len(returns)
    avg_win = np.mean(wins) if wins else 0
    avg_loss = abs(np.mean(losses)) if losses else 0
    return win_rate, avg_win / avg_loss if avg_loss != 0 else float('inf')


def _dca_annual_returns(df: pd.DataFrame, deposit_map: dict) -> pd.DataFrame:
    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df['year'] = df['date'].dt.year
    records = []
    for year, group in df.groupby('year'):
        group = group.sort_values('date')
        start_equity = group['dca_equity'].iloc[0]
        end_equity = group['dca_equity'].iloc[-1]
        year_deposits = sum(
            amt for d, amt in deposit_map.items()
            if pd.Timestamp(d).year == year
        )
        strat_ret = (end_equity - start_equity - year_deposits) / start_equity
        bench_ret = group['benchmark_equity'].iloc[-1] / group['benchmark_equity'].iloc[0] - 1
        records.append({
            'year': year,
            'strategy_return': strat_ret,
            'benchmark_return': bench_ret,
            'excess_return': strat_ret - bench_ret,
        })
    return pd.DataFrame(records)


def main():
    # 调整初始资金
    config.INITIAL_CAPITAL = 300_000

    logger.info("=" * 60)
    logger.info("  Monthly DCA + Drawdown-Triggered Deposit Simulation")
    logger.info("=" * 60)
    logger.info(f"  Monthly deposit: {MONTHLY_DEPOSIT:,.0f} RMB")
    logger.info(f"  Drawdown trigger: {DRAWDOWN_THRESHOLD:.0%}")
    logger.info(f"  Rebalance frequency: Annual (May)")
    logger.info(f"  Initial capital: {config.INITIAL_CAPITAL:,.0f} RMB")
    logger.info("=" * 60)

    logger.info("\n>>> Running base backtest (annual, PB-lowest)...")
    result = run_backtest(
        config.START_DATE, None,
        incremental_from=None,
        frequency="annual",
        ranking_method="pb",
    )

    if result is None:
        logger.error("Backtest failed.")
        return

    logger.info("\n>>> Computing base performance...")
    base_perf = calculate_performance(
        result['equity_curve'],
        result['cutoff_dates'],
        result['trade_records'],
    )

    logger.info("\n>>> Simulating DCA + drawdown-triggered deposits...")
    logger.info("-" * 60)
    dca_result = simulate_dca_add_deposit(result)
    logger.info("-" * 60)

    dca_df = dca_result['equity_curve']
    deposit_log = dca_result['deposit_log']
    daily_deposits = dca_result['daily_deposits']

    logger.info("\n>>> Computing DCA performance (MWR + TWR)...")
    dca_perf = calculate_dca_performance(
        dca_df, daily_deposits, result['cutoff_dates'], result['equity_curve']
    )

    total_deposits = dca_perf['total_deposits']
    final_capital = dca_perf['final_capital']
    final_equity = dca_perf['final_equity']
    total_profit = dca_perf['total_profit']

    logger.info(f"\n  Capital Summary:")
    logger.info(f"    Initial capital:     {config.INITIAL_CAPITAL:>14,.0f} RMB")
    logger.info(f"    Total deposits:      {total_deposits:>14,.0f} RMB")
    logger.info(f"    Total invested:      {final_capital:>14,.0f} RMB")
    logger.info(f"    Final value:         {final_equity:>14,.0f} RMB")
    logger.info(f"    Net profit:          {total_profit:>14,.0f} RMB")

    # ================================================================
    # 对比输出
    # ================================================================
    logger.info("\n" + "=" * 60)
    logger.info("  Performance Comparison: Original vs DCA+Deposit")
    logger.info("=" * 60)

    # MWR — 投资者视角
    logger.info(f"\n  {'MWR (Money-Weighted Return) — 投资者体验':<50}")
    logger.info(f"  {'Metric':<30} {'Original':>14} {'DCA (MWR)':>14} {'Diff':>10}")
    logger.info(f"  {'-' * 70}")

    mwr_compare = [
        ('Annual Return', 'annual_return', 'mwr_annual', True),
        ('Annual Volatility', 'annual_volatility', 'annual_volatility', False),
        ('Sharpe Ratio', 'sharpe_ratio', 'sharpe_ratio', False),
        ('Max Drawdown', 'max_drawdown', 'max_drawdown', True),
        ('Max Drawdown Days', 'max_drawdown_duration_days', 'max_drawdown_duration_days', False),
        ('Recovery Days', 'recovery_days', 'recovery_days', False),
        ('Benchmark Annual Return', 'benchmark_annual_return', 'benchmark_annual_return', True),
        ('Excess Return (vs bench)', 'excess_return', 'excess_return', True),
        ('Tracking Error', 'tracking_error', 'tracking_error', True),
        ('Information Ratio', 'information_ratio', 'information_ratio', False),
    ]

    for label, base_key, dca_key, is_pct in mwr_compare:
        orig = base_perf.get(base_key)
        dca = dca_perf.get(dca_key)
        if orig is None or dca is None:
            logger.info(f"  {label:<30} {'N/A':>14} {'N/A':>14}")
            continue
        if is_pct:
            orig_s = f"{orig * 100:.2f}%"
            dca_s = f"{dca * 100:.2f}%"
            diff_s = f"{(dca - orig) * 100:+.2f}%"
        else:
            orig_s = f"{orig:.2f}"
            dca_s = f"{dca:.2f}"
            diff_s = f"{dca - orig:+.2f}"
        logger.info(f"  {label:<30} {orig_s:>14} {dca_s:>14} {diff_s:>10}")

    # TWR — 策略能力视角
    logger.info(f"\n  {'TWR (Time-Weighted Return) — 策略能力':<50}")
    logger.info(f"  {'Metric':<30} {'Original':>14} {'DCA (TWR)':>14}")
    logger.info(f"  {'-' * 60}")
    logger.info(f"  {'Cumulative Return':<30} {base_perf['cumulative_return'] * 100:>13.2f}% {dca_perf['twr_cumulative'] * 100:>13.2f}%")
    logger.info(f"  {'Annual Return':<30} {base_perf['annual_return'] * 100:>13.2f}% {dca_perf['twr_annual'] * 100:>13.2f}%")

    # 年度收益对比
    logger.info("\n  Annual Returns Comparison:")
    logger.info(f"  {'Year':<6} {'Original':>12} {'DCA+Deposit':>12} {'Diff':>10}")
    logger.info("  " + "-" * 42)

    base_annual = base_perf.get('annual_returns')
    dca_annual = dca_perf.get('annual_returns')
    if base_annual is not None and dca_annual is not None:
        for _, row in base_annual.iterrows():
            year = int(row['year'])
            orig_ret = row['strategy_return']
            dca_row = dca_annual[dca_annual['year'] == year]
            dca_ret = dca_row.iloc[0]['strategy_return'] if not dca_row.empty else 0
            diff = dca_ret - orig_ret
            logger.info(
                f"  {year:<6} {orig_ret:>11.2%} {dca_ret:>11.2%} {diff:>+10.2f}%"
            )

    # 加仓日志
    logger.info(f"\n  Deposit Trigger Log ({len(deposit_log)} triggers total):")
    logger.info(f"  {'#':<4} {'Date':<12} {'Amount':>12} {'Invested':>12} {'Pos':>5} {'Drawdown':>10} {'Reason':<10}")
    logger.info("  " + "-" * 62)
    for i, dep in enumerate(deposit_log, 1):
        logger.info(
            f"  {i:<4} {dep['date'].strftime('%Y-%m-%d'):<12} "
            f"{dep['deposit_amount']:>12,.0f} {dep['actual_invested']:>12,.0f} "
            f"{dep['n_positions']:>5} {dep['drawdown']:>10.1%} {dep['reason']:<10}"
        )

    total_invested_actual = sum(d['actual_invested'] for d in deposit_log)
    logger.info(f"\n  Total deposited:         {total_deposits:>12,.0f} RMB")
    logger.info(f"  Actually invested:       {total_invested_actual:>12,.0f} RMB")
    logger.info(f"  Deposit holdings value:  {final_equity - dca_df.iloc[-1]['strategy_equity']:>12,.0f} RMB")

    # 保存
    config.ensure_dirs()
    curve_path = os.path.join(config.PERFORMANCE_DIR, "equity_curve_dca.csv")
    dca_df.to_csv(curve_path, index=False)
    logger.info(f"\n  Saved DCA equity curve: {curve_path}")

    comp_path = os.path.join(config.PERFORMANCE_DIR, "performance_comparison_dca.csv")
    rows = []
    for label, base_key, dca_key, is_pct in mwr_compare:
        orig = base_perf.get(base_key)
        dca = dca_perf.get(dca_key)
        if orig is None or dca is None:
            rows.append({'Metric': label, 'Original': 'N/A', 'DCA': 'N/A'})
        elif is_pct:
            rows.append({'Metric': label, 'Original': f"{orig * 100:.2f}%", 'DCA': f"{dca * 100:.2f}%"})
        else:
            rows.append({'Metric': label, 'Original': f"{orig:.2f}", 'DCA': f"{dca:.2f}"})
    rows.append({'Metric': 'TWR Cumulative', 'Original': f"{base_perf['cumulative_return'] * 100:.2f}%", 'DCA': f"{dca_perf['twr_cumulative'] * 100:.2f}%"})
    rows.append({'Metric': 'TWR Annual', 'Original': f"{base_perf['annual_return'] * 100:.2f}%", 'DCA': f"{dca_perf['twr_annual'] * 100:.2f}%"})
    pd.DataFrame(rows).to_csv(comp_path, index=False)
    logger.info(f"  Saved comparison: {comp_path}")

    logger.info("\n" + "=" * 60)
    logger.info("  DCA Simulation Complete!")
    logger.info("=" * 60)


if __name__ == "__main__":
    setup_logger("dca", "backtest_dca")
    main()
