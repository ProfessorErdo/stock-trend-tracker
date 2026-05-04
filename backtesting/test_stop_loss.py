"""
测试年度调仓 + 日内止损策略（多阈值对比）

规则：
1. 年度调仓选股逻辑不变（原四步过滤 + PB排序 Top5）
2. 持仓期间每日检查：如果某只股票从买入成本跌超阈值，止损卖出
3. 止损后每日监控：如果股价涨回止损价以上，用卖出金额重新买入
4. 如果一直没涨回，卖出金额保持现金
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
import numpy as np
import copy
from data_loader import load_stock_pool, load_price_data
from stock_selector import select_stocks, rank_and_limit, is_new_stock
from trading_calendar import build_trading_calendar, get_annual_cutoff_dates
from portfolio import Portfolio
from performance import calculate_performance
from backtest_engine import check_limit_up_down
import config

OUTPUT_DIR = os.path.join(config.DATA_OUTPUT_DIR, "stop_loss_test")


def run_stop_loss_test(stop_loss_pct):
    label = f"{stop_loss_pct:.0%}"
    print("=" * 80)
    print(f"年度调仓 + {label} 止损策略")
    print("=" * 80)

    pool_df = load_stock_pool()
    stock_codes = pool_df['code'].tolist()
    trading_days = build_trading_calendar(start_date=config.START_DATE, end_date=None)
    cutoffs = get_annual_cutoff_dates(trading_days)

    price_cache = {}
    for code in stock_codes:
        try:
            df = load_price_data(code)
            if not df.empty:
                price_cache[code] = df
        except:
            pass

    # 年度选股
    year_top5 = {}
    for cutoff, rebalance in cutoffs:
        year = pd.Timestamp(cutoff).year
        selected, val_df = select_stocks(stock_codes, cutoff, price_cache=price_cache)
        if not selected:
            continue
        top5 = rank_and_limit(selected, val_df, 5, "pb")
        year_top5[pd.Timestamp(cutoff).date()] = (top5, rebalance)

    # 模拟：从第一个 cutoff 开始，逐日运行
    portfolio = Portfolio(initial_capital=config.INITIAL_CAPITAL)
    trade_records = []
    portfolio_states = []

    # 跟踪止损状态
    stopped_out = {}

    for day in trading_days:
        day_ts = pd.Timestamp(day)
        day_date = day_ts.date()

        # 检查是否到达调仓日
        if day_date in year_top5:
            top5, rebalance = year_top5[day_date]
            execution_date = rebalance if rebalance else day

            prices = {}
            prev_prices = {}
            for code in stock_codes:
                if code in price_cache:
                    df = price_cache[code]
                    row = df[df['trade_date'] == day_ts]
                    if not row.empty:
                        prices[code] = row['close'].iloc[0]
                    before = df[df['trade_date'] < day_ts]
                    if not before.empty:
                        prev_prices[code] = before['close'].iloc[-1]

            if prices:
                can_buy_flags = {}
                can_sell_flags = {}
                if rebalance is not None:
                    for code in set(portfolio.positions.keys()) | set(top5):
                        if code in price_cache and code in prev_prices:
                            result = check_limit_up_down(code, execution_date, price_cache[code], prev_prices[code])
                            can_buy_flags[code] = result['can_buy']
                            can_sell_flags[code] = result['can_sell']
                        else:
                            can_buy_flags[code] = True
                            can_sell_flags[code] = True
                else:
                    for code in set(portfolio.positions.keys()) | set(top5):
                        can_buy_flags[code] = True
                        can_sell_flags[code] = True

                target_set = set(top5)
                sell_orders = []

                for code, pos in list(portfolio.positions.items()):
                    if code not in target_set and can_sell_flags.get(code, True):
                        sell_orders.append((code, pos['shares']))

                for code, shares in sell_orders:
                    price = prices.get(code, 0)
                    if price > 0:
                        exec_price = price * (1 - config.SLIPPAGE_RATE)
                        trade = portfolio.sell_shares(code, shares, exec_price, reason="调仓卖出")
                        if trade:
                            trade['trade_date'] = execution_date
                            trade_records.append(trade)

                total_equity = portfolio.get_total_equity(prices)
                N = len(top5)
                buy_orders = []
                if N >= 5:
                    target_value = total_equity / N
                else:
                    target_value = config.MAX_SINGLE_POSITION * total_equity

                for code in top5:
                    price = prices.get(code, 0)
                    if price <= 0:
                        continue
                    if code in price_cache and is_new_stock(code, price_cache[code], execution_date, config.NEW_STOCK_EXCLUDE_DAYS):
                        continue
                    current_shares = portfolio.positions[code]['shares'] if code in portfolio.positions else 0
                    target_shares = int(target_value / price)
                    target_shares = (target_shares // config.LOT_SIZE) * config.LOT_SIZE
                    diff = target_shares - current_shares
                    if diff > 0:
                        buy_orders.append((code, diff))

                for code, shares in buy_orders:
                    price = prices.get(code, 0)
                    if price > 0:
                        exec_price = price * (1 + config.SLIPPAGE_RATE)
                        trade = portfolio.buy_shares(code, shares, exec_price, reason="调仓买入")
                        if trade:
                            trade['trade_date'] = execution_date
                            trade_records.append(trade)
                        if code in stopped_out:
                            del stopped_out[code]

            positions_snapshot = copy.deepcopy(portfolio.positions)
            portfolio_states.append((day_ts, portfolio.cash, positions_snapshot))
            continue

        # 非调仓日：检查止损和重新买入
        positions_to_sell = []
        day_prices = {}

        for code, pos in list(portfolio.positions.items()):
            if code in price_cache:
                df = price_cache[code]
                row = df[df['trade_date'] == day_ts]
                if not row.empty:
                    current_price = row['close'].iloc[0]
                    day_prices[code] = current_price
                    cost = pos['cost_price']
                    stop_loss_price = cost * (1 - stop_loss_pct)
                    if current_price < stop_loss_price:
                        positions_to_sell.append((code, pos['shares'], stop_loss_price))

        for code, shares, stop_price in positions_to_sell:
            price = day_prices.get(code, 0)
            if price > 0:
                exec_price = price * (1 - config.SLIPPAGE_RATE)
                sell_amount = shares * exec_price
                trade = portfolio.sell_shares(code, shares, exec_price, reason="止损卖出")
                if trade:
                    trade['trade_date'] = day_ts
                    trade['stop_loss_price'] = stop_price
                    trade_records.append(trade)
                stopped_out[code] = (stop_price, sell_amount, day_ts)

        for code, (stop_price, amount, stop_date) in list(stopped_out.items()):
            if code in price_cache:
                df = price_cache[code]
                row = df[df['trade_date'] == day_ts]
                if not row.empty:
                    current_price = row['close'].iloc[0]
                    if current_price > stop_price:
                        if portfolio.cash > 0 and current_price > 0:
                            exec_price = current_price * (1 + config.SLIPPAGE_RATE)
                            shares = int(amount / exec_price)
                            shares = (shares // config.LOT_SIZE) * config.LOT_SIZE
                            if shares > 0:
                                trade = portfolio.buy_shares(code, shares, exec_price, reason="止损后重新买入")
                                if trade:
                                    trade['trade_date'] = day_ts
                                    trade_records.append(trade)
                                del stopped_out[code]

        # 记录每日状态
        all_codes = set()
        for code, pos in portfolio.positions.items():
            all_codes.add(code)
        for code in stopped_out:
            all_codes.add(code)

        val_prices = {}
        for code in all_codes:
            if code in price_cache:
                df = price_cache[code]
                before = df[df['trade_date'] <= day_ts]
                if not before.empty:
                    val_prices[code] = before['close'].iloc[-1]

        if val_prices or not portfolio.positions:
            equity = portfolio.cash
            for code, pos in portfolio.positions.items():
                price = val_prices.get(code, pos['cost_price'])
                equity += pos['shares'] * price
            positions_snapshot = copy.deepcopy(portfolio.positions)
            portfolio_states.append((day_ts, portfolio.cash, positions_snapshot))

    # 构建权益曲线
    strategy_equity = []
    if portfolio_states:
        stock_close_map = {}
        for code, df in price_cache.items():
            if 'close' in df.columns:
                stock_close_map[code] = dict(zip(df['trade_date'], df['close']))

        first_rebalance = portfolio_states[0][0]
        state_idx = 0

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
                for code, pos_or_shares in current_shares.items():
                    shares = pos_or_shares['shares'] if isinstance(pos_or_shares, dict) else pos_or_shares
                    if shares > 0 and code in stock_close_map:
                        price = stock_close_map[code].get(day_ts)
                        if price is not None:
                            equity += shares * price
                        else:
                            bp = {d: p for d, p in stock_close_map[code].items() if d < day_ts}
                            if bp:
                                equity += shares * bp[max(bp)]

            strategy_equity.append({'date': day_ts, 'strategy_equity': equity})

    benchmark = [{'date': pd.Timestamp(d), 'benchmark_equity': config.INITIAL_CAPITAL} for d in trading_days]
    strategy_df = pd.DataFrame(strategy_equity)
    benchmark_df = pd.DataFrame(benchmark)
    equity_curve = strategy_df.merge(benchmark_df[['date', 'benchmark_equity']], on='date', how='left')
    equity_curve['benchmark_equity'] = equity_curve['benchmark_equity'].fillna(config.INITIAL_CAPITAL)

    perf = calculate_performance(equity_curve, cutoffs=[c for c, _ in cutoffs], trade_records=trade_records)

    stop_trades = [t for t in trade_records if '止损' in t.get('reason', '')]
    rebuy_trades = [t for t in trade_records if '重新买入' in t.get('reason', '')]

    print(f"\n{'='*60}")
    print(f"止损策略结果 (阈值={label})")
    print(f"{'='*60}")
    print(f"  止损卖出次数: {len(stop_trades)}")
    print(f"  重新买入次数: {len(rebuy_trades)}")
    print(f"\n  性能指标:")
    print(f"    年化收益率:  {perf['annual_return']:+.2%}")
    print(f"    最大回撤:    {perf['max_drawdown']:.2%}")
    print(f"    Sharpe:      {perf['sharpe_ratio']:.3f}")
    print(f"    最终净值:    {perf['final_equity']:,.0f}")

    # 保存
    dir_name = f"stop_loss_{label.replace('.', '').replace('%', '')}"
    out_dir = os.path.join(OUTPUT_DIR, dir_name)
    os.makedirs(out_dir, exist_ok=True)
    equity_curve.to_csv(os.path.join(out_dir, "equity_curve.csv"), index=False)
    if trade_records:
        pd.DataFrame(trade_records).to_csv(os.path.join(out_dir, "trades_record.csv"), index=False)

    return {
        'threshold': label,
        'stop_count': len(stop_trades),
        'rebuy_count': len(rebuy_trades),
        'annual_return': perf['annual_return'],
        'max_drawdown': perf['max_drawdown'],
        'sharpe_ratio': perf['sharpe_ratio'],
        'final_equity': perf['final_equity'],
    }


if __name__ == '__main__':
    thresholds = [0.10, 0.15, 0.20]
    results = []
    for t in thresholds:
        r = run_stop_loss_test(t)
        results.append(r)
        print()

    print("=" * 80)
    print("汇总对比")
    print("=" * 80)
    print(f"{'阈值':>8}  {'止损次数':>8}  {'重买次数':>8}  {'年化收益':>10}  {'最大回撤':>10}  {'Sharpe':>8}  {'最终净值':>12}")
    print("-" * 80)
    for r in results:
        print(f"{r['threshold']:>8}  {r['stop_count']:>8}  {r['rebuy_count']:>8}  {r['annual_return']:>+10.2%}  {r['max_drawdown']:>10.2%}  {r['sharpe_ratio']:>8.3f}  {r['final_equity']:>12,.0f}")
    print("-" * 80)
    # 原策略基准
    print(f"{'原策略':>8}  {'—':>8}  {'—':>8}  {'+11.37%':>10}  {'-40.34%':>10}  {'—':>8}  {'—':>12}")
