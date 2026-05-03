"""
存款时机对比：
1. DCA: 每月定投（累积即投）
2. Lump on Dip: 攒到阈值金额后，等回撤触发才一次性投入
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
from log_util import setup_logger

MONTHLY_DEPOSIT = 30000
DEPOSIT_START = "2015-01-01"
DRAWDOWN_THRESHOLD = 0.10

# 两种方案
SCENARIOS = {
    "dca_monthly": {
        "name": "DCA 月度定投",
        "lump_threshold": 0,
        "description": "每月累积的3万立即投入",
    },
    "lump_12w": {
        "name": "攒12万一次性投",
        "lump_threshold": 120000,
        "description": "攒够4个月(12万)后，等回撤>10%时一次性投入",
    },
    "lump_24w": {
        "name": "攒24万一次性投",
        "lump_threshold": 240000,
        "description": "攒够8个月(24万)后，等回撤>10%时一次性投入",
    },
    "lump_36w": {
        "name": "攒36万一次性投",
        "lump_threshold": 360000,
        "description": "攒够12个月(36万)后，等回撤>10%时一次性投入",
    },
    "lump_60w": {
        "name": "攒60万一次性投",
        "lump_threshold": 600000,
        "description": "攒够20个月(60万)后，等回撤>10%时一次性投入",
    },
}


def _xirr(cash_flows: list) -> float:
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


def simulate_deposit_strategy(result: dict, scenario_key: str) -> dict:
    """
    模拟一种存款策略。

    lump_threshold = 0: 每月累积即投入（DCA）
    lump_threshold > 0: 攒够 lump_threshold 后，等回撤>10%或年度调仓才投入
    """
    equity_curve = result['equity_curve'].copy()
    portfolio_states = result['portfolio_states']
    price_cache = result['price_cache']
    trading_days = result['trading_days']
    initial_capital = config.INITIAL_CAPITAL

    stock_close_map = {}
    for code, df in price_cache.items():
        if 'close' not in df.columns:
            continue
        stock_close_map[code] = dict(zip(df['trade_date'], df['close']))

    first_rebalance = portfolio_states[0][0]
    annual_rebalances = [
        pd.Timestamp(r) for _, r in get_annual_cutoff_dates(trading_days) if r
    ]

    is_lump = scenario_key.startswith("lump_")
    lump_threshold = SCENARIOS[scenario_key]["lump_threshold"]

    deposit_shares = {}
    accumulated = 0.0
    deposit_start_ts = pd.Timestamp(DEPOSIT_START)

    daily_deposits = []
    deposit_log = []
    daily_equity = []

    state_idx = 0
    current_cash = portfolio_states[0][1]
    current_shares = portfolio_states[0][2]

    invested_yearly_peak = 0.0
    current_year = None
    deposited_today = False

    for day in trading_days:
        day_ts = pd.Timestamp(day)

        while state_idx + 1 < len(portfolio_states) and portfolio_states[state_idx + 1][0] <= day_ts:
            state_idx += 1
            current_cash = portfolio_states[state_idx][1]
            current_shares = portfolio_states[state_idx][2]

        # Base equity (original strategy)
        if day_ts < first_rebalance:
            base_equity = initial_capital
        else:
            base_equity = current_cash
            for code, shares in current_shares.items():
                if shares > 0 and code in stock_close_map:
                    price = stock_close_map[code].get(day_ts)
                    if price is None:
                        before = {d: p for d, p in stock_close_map[code].items() if d < day_ts}
                        price = before[max(before)] if before else 0
                    base_equity += shares * price

        # Deposit holdings value
        deposit_value = 0.0
        for code, shares in deposit_shares.items():
            if shares > 0 and code in stock_close_map:
                price = stock_close_map[code].get(day_ts)
                if price is None:
                    before = {d: p for d, p in stock_close_map[code].items() if d < day_ts}
                    price = before[max(before)] if before else 0
                deposit_value += shares * price

        invested_value = base_equity + deposit_value

        # Monthly accumulation
        months = (day_ts.year - deposit_start_ts.year) * 12 + (day_ts.month - deposit_start_ts.month)
        expected = months * MONTHLY_DEPOSIT
        if expected > accumulated:
            accumulated = expected

        if current_year != day_ts.year:
            current_year = day_ts.year
            invested_yearly_peak = 0.0
            deposited_today = False

        if not deposited_today:
            if invested_value > invested_yearly_peak:
                invested_yearly_peak = invested_value

        # Decide if we should invest today
        should_invest = False
        trigger_reason = ""

        if accumulated > 0 and not deposited_today and len(current_shares) > 0:
            if is_lump:
                # Lump strategy: only invest when threshold reached AND (drawdown or rebalance)
                threshold_reached = accumulated >= lump_threshold
                is_rebalance_day = day_ts in annual_rebalances
                drawdown = 0.0
                if invested_yearly_peak > 0:
                    drawdown = (invested_value - invested_yearly_peak) / invested_yearly_peak

                if is_rebalance_day:
                    should_invest = True
                    trigger_reason = "年度调仓"
                elif threshold_reached and drawdown < -DRAWDOWN_THRESHOLD:
                    should_invest = True
                    trigger_reason = f"回撤 {drawdown:.1%}"
            else:
                # DCA: invest immediately every day
                should_invest = True
                trigger_reason = "月度定投"

        if should_invest:
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

            drawdown_at = 0.0
            if invested_yearly_peak > 0:
                drawdown_at = (invested_value - invested_yearly_peak) / invested_yearly_peak

            deposit_log.append({
                'date': day_ts,
                'deposit_amount': deposit_amount,
                'actual_invested': actual_invested,
                'n_positions': n,
                'reason': trigger_reason,
                'drawdown': drawdown_at,
            })

            daily_deposits.append({'date': day_ts, 'amount': deposit_amount})

            accumulated = 0.0
            deposit_start_ts = day_ts
            deposited_today = True

            # Recalculate after deposit
            deposit_value = 0.0
            for code, shares in deposit_shares.items():
                if shares > 0 and code in stock_close_map:
                    price = stock_close_map[code].get(day_ts, 0)
                    if price is None:
                        before = {d: p for d, p in stock_close_map[code].items() if d < day_ts}
                        price = before[max(before)] if before else 0
                    deposit_value += shares * price
            invested_value = base_equity + deposit_value

        total_equity = invested_value + accumulated

        daily_equity.append({
            'date': day_ts,
            'total_equity': total_equity,
            'invested_value': invested_value,
            'cash': accumulated,
        })

    eq_df = pd.DataFrame(daily_equity)

    # Calculate MWR and TWR
    t_start = pd.Timestamp(trading_days[0])
    t_end = pd.Timestamp(trading_days[-1])
    t_days = (t_end - t_start).days

    eq_values = eq_df['total_equity'].values
    dates_arr = eq_df['date'].values
    n_days = len(eq_df)

    # MWR (XIRR)
    cash_flows = []
    cash_flows.append((t_start, -initial_capital))
    for d in daily_deposits:
        cash_flows.append((pd.Timestamp(d['date']), -d['amount']))
    cash_flows.append((t_end, eq_values[-1]))
    mwr = _xirr(cash_flows)

    # TWR
    deposit_map = {d['date']: d['amount'] for d in daily_deposits}
    twr = 1.0
    for i in range(1, n_days):
        cf = deposit_map.get(pd.Timestamp(dates_arr[i]), 0.0)
        prev = eq_values[i - 1]
        if prev > 0:
            twr *= ((eq_values[i] - cf) / prev)
    twr -= 1
    twr_annual = (1 + twr) ** (252 / t_days) - 1 if t_days > 0 else 0.0

    # Max drawdown
    eq_df['peak'] = eq_df['total_equity'].cummax()
    eq_df['dd'] = (eq_df['total_equity'] - eq_df['peak']) / eq_df['peak']
    max_dd = eq_df['dd'].min()

    total_deposited = sum(d['amount'] for d in daily_deposits)
    final_equity = eq_values[-1]
    total_invested = initial_capital + total_deposited
    net_profit = final_equity - total_invested

    return {
        'scenario_key': scenario_key,
        'mwr': mwr,
        'twr': twr,
        'twr_annual': twr_annual,
        'max_dd': max_dd,
        'total_deposits': total_deposited,
        'total_invested': total_invested,
        'final_equity': final_equity,
        'net_profit': net_profit,
        'deposit_log': deposit_log,
        'n_deposits': len(deposit_log),
    }


def main():
    config.INITIAL_CAPITAL = 300_000

    logger.info("=" * 60)
    logger.info("  Deposit Timing Comparison")
    logger.info("=" * 60)
    logger.info(f"  Initial capital: {config.INITIAL_CAPITAL:,.0f} RMB")
    logger.info(f"  Monthly deposit: {MONTHLY_DEPOSIT:,.0f} RMB")
    logger.info(f"  Drawdown trigger: {DRAWDOWN_THRESHOLD:.0%}")
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

    # Calculate base performance
    eq = result['equity_curve']
    base_final = eq['strategy_equity'].iloc[-1]
    base_initial = eq['strategy_equity'].iloc[0]
    base_mwr = (base_final / base_initial - 1)  # simple for no-deposit case
    base_cum_ret = base_final / base_initial - 1
    t_start = pd.Timestamp(result['trading_days'][0])
    t_end = pd.Timestamp(result['trading_days'][-1])
    t_days = (t_end - t_start).days
    base_annual = (1 + base_cum_ret) ** (252 / t_days) - 1

    # Max drawdown of original
    orig_peak = eq['strategy_equity'].cummax()
    orig_dd = ((eq['strategy_equity'] - orig_peak) / orig_peak).min()

    logger.info(f"\n  Original (no deposit): Annual {base_annual:.2%}, Max DD {orig_dd:.1%}")

    # Run all scenarios
    results = {}
    for key, info in SCENARIOS.items():
        logger.info(f"\n>>> Simulating: {info['name']}...")
        r = simulate_deposit_strategy(result, key)
        results[key] = r
        logger.info(f"  {info['name']}: MWR {r['mwr']:.2%}, TWR {r['twr_annual']:.2%}, "
                     f"MaxDD {r['max_dd']:.1%}, Final {r['final_equity']:,.0f}, "
                     f"Triggers: {r['n_deposits']}")

    # Print comparison table
    logger.info("\n" + "=" * 80)
    logger.info("  Summary Comparison")
    logger.info("=" * 80)
    logger.info(f"  {'Strategy':<20} {'MWR':>10} {'TWR Annual':>12} {'Max DD':>10} "
                f"{'Total In':>12} {'Final':>12} {'Profit':>12} {'Triggers':>8}")
    logger.info("  " + "-" * 78)

    # Original row
    logger.info(f"  {'原始策略(无定投)':<20} {base_annual:>9.2%} {'N/A':>12} "
                f"{orig_dd:>9.1%} {base_initial:>12,.0f} {base_final:>12,.0f} "
                f"{base_final - base_initial:>12,.0f} {'N/A':>8}")

    for key, info in SCENARIOS.items():
        r = results[key]
        logger.info(f"  {info['name']:<20} {r['mwr']:>9.2%} {r['twr_annual']:>11.2%} "
                     f"{r['max_dd']:>9.1%} {r['total_invested']:>12,.0f} "
                     f"{r['final_equity']:>12,.0f} {r['net_profit']:>12,.0f} "
                     f"{r['n_deposits']:>8}")

    # Print deposit logs for lump strategies
    for key, info in SCENARIOS.items():
        if key.startswith("lump_"):
            r = results[key]
            logger.info(f"\n  {info['name']} - Deposit Log ({r['n_deposits']} triggers):")
            for i, dep in enumerate(r['deposit_log'], 1):
                logger.info(f"    {i:>3}. {dep['date'].strftime('%Y-%m-%d')} "
                            f"{dep['deposit_amount']:>12,.0f}  {dep['reason']:<15} "
                            f"dd={dep['drawdown']:.1%}")


if __name__ == "__main__":
    logger = setup_logger("deposit_timing", "backtest_timing")
    main()
