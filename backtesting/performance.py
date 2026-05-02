"""
回测绩效指标计算模块
计算累计收益、夏普比率、最大回撤等标准绩效指标
"""

import pandas as pd
import numpy as np
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config


def calculate_performance(equity_df: pd.DataFrame, cutoffs: list = None, trade_records: list = None) -> dict:
    """
    计算回测绩效指标

    Args:
        equity_df: 权益曲线 DataFrame，列 ['date', 'strategy_equity', 'benchmark_equity']
        cutoffs: 调仓日期列表（用于计算胜率等）
        trade_records: 交易记录列表（用于计算换手率）

    Returns:
        绩效指标字典
    """
    df = equity_df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)

    initial_capital = df['strategy_equity'].iloc[0]
    final_equity = df['strategy_equity'].iloc[-1]
    trading_days = len(df)

    # --- 策略累计收益 ---
    cumulative_return = final_equity / initial_capital - 1

    # --- 策略年化收益 ---
    annual_return = (1 + cumulative_return) ** (252 / trading_days) - 1

    # --- 策略年化波动率 ---
    df['daily_return'] = df['strategy_equity'].pct_change()
    annual_volatility = df['daily_return'].std() * np.sqrt(252)

    # --- 夏普比率 ---
    sharpe_ratio = (annual_return - config.RISK_FREE_RATE) / annual_volatility if annual_volatility != 0 else 0

    # --- 最大回撤及回撤天数 ---
    df['cumulative_peak'] = df['strategy_equity'].cummax()
    df['drawdown'] = (df['strategy_equity'] - df['cumulative_peak']) / df['cumulative_peak']

    max_drawdown = df['drawdown'].min()
    trough_idx = df['drawdown'].idxmin()
    peak_idx = df.loc[:trough_idx, 'strategy_equity'].idxmax()
    max_drawdown_duration_days = (df.loc[trough_idx, 'date'] - df.loc[peak_idx, 'date']).days

    # --- 恢复天数 ---
    peak_equity = df.loc[peak_idx, 'strategy_equity']
    recovery_series = df.loc[trough_idx:, 'strategy_equity']
    recovered = recovery_series[recovery_series >= peak_equity]
    if len(recovered) > 0:
        recovery_date = recovered.index[0]
        recovery_days = (df.loc[recovery_date, 'date'] - df.loc[trough_idx, 'date']).days
    else:
        recovery_days = None

    # --- 胜率与盈亏比 ---
    if cutoffs is not None and len(cutoffs) > 0:
        win_rate, profit_loss_ratio = _calculate_win_rate(df, cutoffs)
    else:
        win_rate, profit_loss_ratio = None, None

    # --- 平均周换手率 ---
    if trade_records is not None and len(trade_records) > 0:
        avg_weekly_turnover = _calculate_turnover_from_trades(trade_records, df)
    else:
        avg_weekly_turnover = None

    # --- 基准指标 ---
    bench_initial = df['benchmark_equity'].iloc[0]
    bench_final = df['benchmark_equity'].iloc[-1]
    benchmark_cumulative_return = bench_final / bench_initial - 1
    benchmark_annual_return = (1 + benchmark_cumulative_return) ** (252 / trading_days) - 1

    # --- 超额收益 ---
    excess_return = cumulative_return - benchmark_cumulative_return

    # --- 跟踪误差 ---
    df['benchmark_daily_return'] = df['benchmark_equity'].pct_change()
    df['excess_daily_return'] = df['daily_return'] - df['benchmark_daily_return']
    tracking_error = df['excess_daily_return'].std() * np.sqrt(252)

    # --- 信息比率 ---
    excess_annual = annual_return - benchmark_annual_return
    information_ratio = excess_annual / tracking_error if tracking_error != 0 else 0

    # --- 年度收益表 ---
    annual_returns = _calculate_annual_returns(df)

    return {
        'cumulative_return': cumulative_return,
        'annual_return': annual_return,
        'annual_volatility': annual_volatility,
        'sharpe_ratio': sharpe_ratio,
        'max_drawdown': max_drawdown,
        'max_drawdown_duration_days': max_drawdown_duration_days,
        'recovery_days': recovery_days,
        'win_rate': win_rate,
        'profit_loss_ratio': profit_loss_ratio,
        'avg_weekly_turnover': avg_weekly_turnover,
        'benchmark_cumulative_return': benchmark_cumulative_return,
        'benchmark_annual_return': benchmark_annual_return,
        'excess_return': excess_return,
        'tracking_error': tracking_error,
        'information_ratio': information_ratio,
        'annual_returns': annual_returns,
        'trading_days': trading_days,
        'initial_capital': initial_capital,
        'final_equity': final_equity,
    }


def _calculate_win_rate(equity_df: pd.DataFrame, cutoffs: list) -> tuple:
    """
    计算调仓周期胜率和盈亏比

    Args:
        equity_df: 排序后的权益 DataFrame
        cutoffs: 调仓日期列表

    Returns:
        (win_rate, profit_loss_ratio)
    """
    df = equity_df.copy()
    df['date'] = pd.to_datetime(df['date'])
    cutoffs_dt = [pd.to_datetime(c) for c in cutoffs]

    returns = []
    for i in range(1, len(cutoffs_dt)):
        start_date = cutoffs_dt[i - 1]
        end_date = cutoffs_dt[i]

        # 找到起始日之后的第一条记录作为期初
        start_rows = df[df['date'] >= start_date]
        end_rows = df[df['date'] >= end_date]

        if len(start_rows) == 0 or len(end_rows) == 0:
            continue

        start_equity = start_rows.iloc[0]['strategy_equity']
        end_equity = end_rows.iloc[0]['strategy_equity']

        period_return = end_equity / start_equity - 1
        returns.append(period_return)

    if len(returns) == 0:
        return None, None

    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]

    win_rate = len(wins) / len(returns)

    avg_win = np.mean(wins) if len(wins) > 0 else 0
    avg_loss = abs(np.mean(losses)) if len(losses) > 0 else 0

    profit_loss_ratio = avg_win / avg_loss if avg_loss != 0 else float('inf')

    return win_rate, profit_loss_ratio


def _calculate_turnover_from_trades(trade_records: list, equity_df: pd.DataFrame) -> float:
    """
    根据交易记录计算平均换手率

    Args:
        trade_records: 交易记录列表，每个记录为包含 'date', 'amount' 的字典
        equity_df: 权益曲线 DataFrame

    Returns:
        平均换手率
    """
    trades_df = pd.DataFrame(trade_records)
    if trades_df.empty:
        return 0.0

    # Trade records use 'trade_date' column
    date_col = 'trade_date' if 'trade_date' in trades_df.columns else 'date'
    trades_df[date_col] = pd.to_datetime(trades_df[date_col])
    equity_df = equity_df.copy()
    equity_df['date'] = pd.to_datetime(equity_df['date'])

    # 按日期汇总交易额
    daily_turnover = trades_df.groupby(date_col)['amount'].sum().reset_index()

    turnover_rates = []
    for _, row in daily_turnover.iterrows():
        trade_date = row[date_col]
        amount = row['amount']

        # 取交易日前一天的权益作为基数
        prev_equity_rows = equity_df[equity_df['date'] < trade_date]
        if len(prev_equity_rows) == 0:
            continue
        prev_equity = prev_equity_rows.iloc[-1]['strategy_equity']

        if prev_equity > 0:
            turnover_rates.append(amount / 2 / prev_equity)

    return np.mean(turnover_rates) if len(turnover_rates) > 0 else 0.0


def _calculate_annual_returns(df: pd.DataFrame) -> pd.DataFrame:
    """
    按年度计算策略、基准和超额收益

    Args:
        df: 包含 date, strategy_equity, benchmark_equity 的 DataFrame

    Returns:
        DataFrame with columns ['year', 'strategy_return', 'benchmark_return', 'excess_return']
    """
    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df['year'] = df['date'].dt.year

    records = []
    for year, group in df.groupby('year'):
        group = group.sort_values('date')
        strat_ret = group['strategy_equity'].iloc[-1] / group['strategy_equity'].iloc[0] - 1
        bench_ret = group['benchmark_equity'].iloc[-1] / group['benchmark_equity'].iloc[0] - 1
        records.append({
            'year': year,
            'strategy_return': strat_ret,
            'benchmark_return': bench_ret,
            'excess_return': strat_ret - bench_ret,
        })

    return pd.DataFrame(records)


def save_performance_summary(performance: dict, filepath: str):
    """
    将绩效指标保存为 CSV 文件

    Args:
        performance: calculate_performance 返回的指标字典
        filepath: 输出文件路径
    """
    rows = []

    metric_map = [
        ('Trading Days', 'trading_days', False),
        ('Initial Capital', 'initial_capital', False),
        ('Final Equity', 'final_equity', False),
        ('Cumulative Return', 'cumulative_return', True),
        ('Annual Return', 'annual_return', True),
        ('Annual Volatility', 'annual_volatility', True),
        ('Sharpe Ratio', 'sharpe_ratio', False),
        ('Max Drawdown', 'max_drawdown', True),
        ('Max Drawdown Days', 'max_drawdown_duration_days', False),
        ('Recovery Days', 'recovery_days', False),
        ('Win Rate', 'win_rate', True),
        ('Profit/Loss Ratio', 'profit_loss_ratio', False),
        ('Avg Weekly Turnover', 'avg_weekly_turnover', True),
        ('Benchmark Cumulative Return', 'benchmark_cumulative_return', True),
        ('Benchmark Annual Return', 'benchmark_annual_return', True),
        ('Excess Return', 'excess_return', True),
        ('Tracking Error', 'tracking_error', True),
        ('Information Ratio', 'information_ratio', False),
    ]

    for label, key, is_pct in metric_map:
        value = performance.get(key)
        if value is None:
            rows.append({'Metric': label, 'Value': 'N/A'})
        elif is_pct:
            rows.append({'Metric': label, 'Value': f'{value * 100:.2f}%'})
        else:
            rows.append({'Metric': label, 'Value': str(value)})

    result_df = pd.DataFrame(rows, columns=['Metric', 'Value'])
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    result_df.to_csv(filepath, index=False, encoding='utf-8-sig')
    print(f'Performance summary saved to {filepath}')
