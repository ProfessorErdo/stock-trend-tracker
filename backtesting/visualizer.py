"""
回测可视化输出模块
生成资金曲线图（含回撤区域）和年度收益热力图
"""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns
import pandas as pd
import numpy as np
import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger("visualizer")
import config
import performance as perf


def plot_equity_curve(equity_df: pd.DataFrame, save_path: str = None):
    """
    绘制策略资金曲线和回撤图

    Args:
        equity_df: 包含 ['date', 'strategy_equity', 'benchmark_equity'] 的 DataFrame
        save_path: 图片保存路径，若为 None 则不保存
    """
    df = equity_df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)

    # 归一化到初始资金 = 1
    initial = df['strategy_equity'].iloc[0]
    df['strategy_norm'] = df['strategy_equity'] / initial
    bench_initial = df['benchmark_equity'].iloc[0]
    df['benchmark_norm'] = df['benchmark_equity'] / bench_initial

    # 计算回撤
    df['cumulative_peak'] = df['strategy_norm'].cummax()
    df['drawdown'] = df['strategy_norm'] - df['cumulative_peak']

    # 创建 2 个子图，高度比 3:1
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(14, 10), gridspec_kw={'height_ratios': [3, 1]},
        sharex=True
    )

    # --- Top: equity curves ---
    ax1.plot(df['date'], df['strategy_norm'], color='#DAA520', linewidth=1.5, label='Strategy')
    ax1.plot(df['date'], df['benchmark_norm'], color='#808080', linestyle='--', linewidth=1, label='Benchmark')
    ax1.set_ylabel('Net Value', fontsize=12)
    ax1.legend(loc='upper left', fontsize=10)
    ax1.grid(True, alpha=0.3)
    ax1.set_title('Strategy Equity Curve', fontsize=14)

    # --- Bottom: drawdown ---
    ax2.fill_between(df['date'], df['drawdown'], 0, color='#FF4444', alpha=0.5, label='Drawdown')
    ax2.set_ylabel('Drawdown', fontsize=12)
    ax2.legend(loc='lower left', fontsize=10)
    ax2.grid(True, alpha=0.3)

    # x 轴日期格式化
    ax2.xaxis.set_major_locator(mdates.YearLocator())
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    plt.setp(ax2.get_xticklabels(), rotation=45, ha='right')

    fig.tight_layout()

    if save_path:
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        fig.savefig(save_path, dpi=200, bbox_inches='tight')
        logger.info(f'Equity curve saved to {save_path}')

    plt.close(fig)


def plot_annual_heatmap(annual_returns_df: pd.DataFrame, save_path: str = None):
    """
    绘制年度收益热力图

    Args:
        annual_returns_df: 包含 ['year', 'strategy_return', 'benchmark_return', 'excess_return'] 的 DataFrame
        save_path: 图片保存路径，若为 None 则不保存
    """
    df = annual_returns_df.copy()
    years = df['year'].values
    n_years = len(years)

    # 构建热力图数据矩阵
    labels = ['Strategy', 'Benchmark', 'Excess']
    data = df[['strategy_return', 'benchmark_return', 'excess_return']].values

    # 动态调整图高度
    fig_h = n_years * 0.5 + 2
    fig, ax = plt.subplots(figsize=(10, fig_h))

    sns.heatmap(
        data,
        annot=False,
        cmap='RdYlGn',
        vmin=-0.3,
        vmax=0.5,
        xticklabels=labels,
        yticklabels=[str(y) for y in years],
        ax=ax,
        cbar_kws={'label': 'Return'}
    )

    # 在每个单元格上添加数值标签
    for i in range(n_years):
        for j in range(3):
            value = data[i, j]
            label = f'{value * 100:.1f}%'
            # 根据背景色决定文字颜色
            text_color = 'white' if value < -0.1 or value > 0.3 else 'black'
            ax.text(j + 0.5, i + 0.5, label,
                    ha='center', va='center', fontsize=11,
                    color=text_color, fontweight='bold')

    ax.set_xlabel('')
    ax.set_ylabel('Year', fontsize=12)
    ax.set_title('Annual Returns Heatmap', fontsize=14)
    plt.setp(ax.get_yticklabels(), rotation=0, ha='right')

    fig.tight_layout()

    if save_path:
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        fig.savefig(save_path, dpi=200, bbox_inches='tight')
        logger.info(f'Annual heatmap saved to {save_path}')

    plt.close(fig)


def generate_all_visualizations(performance_dict: dict, equity_df: pd.DataFrame):
    """
    生成所有可视化图表并输出绩效摘要

    Args:
        performance_dict: calculate_performance 返回的指标字典
        equity_df: 权益曲线 DataFrame
    """
    config.ensure_dirs()

    # 1. 资金曲线图
    equity_path = os.path.join(config.CHARTS_DIR, 'equity_curve.png')
    plot_equity_curve(equity_df, save_path=equity_path)

    # 2. 年度收益热力图
    annual_returns = performance_dict.get('annual_returns')
    if annual_returns is not None and not annual_returns.empty:
        heatmap_path = os.path.join(config.CHARTS_DIR, 'annual_heatmap.png')
        plot_annual_heatmap(annual_returns, save_path=heatmap_path)

        # 保存年度收益 CSV
        annual_csv = os.path.join(config.PERFORMANCE_DIR, 'annual_returns.csv')
        os.makedirs(os.path.dirname(os.path.abspath(annual_csv)), exist_ok=True)
        annual_returns.to_csv(annual_csv, index=False, encoding='utf-8-sig')
        logger.info(f'Annual returns CSV saved to {annual_csv}')

    # 3. 打印绩效摘要到控制台
    p = performance_dict
    logger.info('\n========== Performance Summary ==========')
    logger.info(f"Cumulative Return:   {p.get('cumulative_return', 0) * 100:.2f}%")
    logger.info(f"Annual Return:       {p.get('annual_return', 0) * 100:.2f}%")
    logger.info(f"Annual Volatility:   {p.get('annual_volatility', 0) * 100:.2f}%")
    logger.info(f"Sharpe Ratio:        {p.get('sharpe_ratio', 0):.4f}")
    logger.info(f"Max Drawdown:        {p.get('max_drawdown', 0) * 100:.2f}%")

    wr = p.get('win_rate')
    logger.info(f"Win Rate:            {wr * 100:.2f}%" if wr is not None else "Win Rate:            N/A")

    plr = p.get('profit_loss_ratio')
    if plr is not None and plr != float('inf'):
        logger.info(f"Profit/Loss Ratio:   {plr:.2f}")
    elif plr == float('inf'):
        logger.info(f"Profit/Loss Ratio:   inf")
    else:
        logger.info(f"Profit/Loss Ratio:   N/A")

    logger.info(f"Excess Return:       {p.get('excess_return', 0) * 100:.2f}%")
    logger.info(f"Information Ratio:   {p.get('information_ratio', 0):.4f}")
    logger.info('=========================================\n')

    # 4. 保存绩效汇总 CSV
    perf_csv = os.path.join(config.PERFORMANCE_DIR, 'performance_summary.csv')
    perf.save_performance_summary(performance_dict, perf_csv)
