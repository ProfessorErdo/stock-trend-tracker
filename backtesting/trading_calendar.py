"""
交易日历管理模块
用于构建A股交易日历，确定每周截面日（选股日）和调仓日
"""

import pandas as pd
import numpy as np
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config


def build_trading_calendar(start_date: str = "2015-01-01", end_date: str = None) -> list:
    """
    从价格数据文件中构建交易日历。

    交易日定义为至少有一只股票有价格数据的日期。
    优先读取前10个样本文件提取日期，若样本不足则回退到读取所有文件。

    Args:
        start_date: 起始日期，格式 "YYYY-MM-DD"
        end_date: 结束日期，格式 "YYYY-MM-DD"，None表示不限制

    Returns:
        排序后的 pd.Timestamp 列表
    """
    price_dir = config.PRICE_DATA_DIR
    if not os.path.isdir(price_dir):
        return []

    csv_files = sorted([f for f in os.listdir(price_dir) if f.endswith(".csv")])
    if not csv_files:
        return []

    all_dates = set()

    # 先尝试读取前10个样本文件
    sample_files = csv_files[:10]
    for fname in sample_files:
        fpath = os.path.join(price_dir, fname)
        try:
            df = pd.read_csv(fpath, usecols=["trade_date"], dtype={"trade_date": str})
            dates = pd.to_datetime(df["trade_date"].dropna().unique())
            all_dates.update(dates.tolist())
        except Exception:
            continue

    # 如果样本文件提取的日期少于200个，回退到读取所有文件
    if len(all_dates) < 200 and len(csv_files) > 10:
        for fname in csv_files[10:]:
            fpath = os.path.join(price_dir, fname)
            try:
                df = pd.read_csv(fpath, usecols=["trade_date"], dtype={"trade_date": str})
                dates = pd.to_datetime(df["trade_date"].dropna().unique())
                all_dates.update(dates.tolist())
            except Exception:
                continue

    start_dt = pd.Timestamp(start_date)
    end_dt = pd.Timestamp(end_date) if end_date else pd.Timestamp("2099-12-31")

    trading_days = sorted([d for d in all_dates if start_dt <= d <= end_dt])
    return trading_days


def get_quarterly_cutoff_dates(trading_days: list) -> list:
    """
    Determine rebalance dates based on financial report availability.

    Rebalance 3 times per year after these reports become available:
    - Annual report (年报): available end of April
    - Semi-annual report (半年报): available end of August
    - Q3 report (三季报): available end of October

    Cutoff = last trading day of the report available month
    Rebalance = first trading day of the following month

    Args:
        trading_days: sorted list of trading days

    Returns:
        list of (cutoff_date, rebalance_date) tuples
    """
    if not trading_days:
        return []

    sorted_days = sorted(set(pd.to_datetime(trading_days)))

    # Report available months (month = when report disclosure period ends)
    report_months = [
        4,   # 年报 4月底可用
        8,   # 半年报 8月底可用
        10,  # 三季报 10月底可用
    ]

    years = sorted(set(d.year for d in sorted_days))

    results = []
    for year in years:
        for month in report_months:
            # Cutoff = last trading day of the available month
            month_start = pd.Timestamp(year, month, 1)
            if month == 12:
                month_end = pd.Timestamp(year + 1, 1, 1) - pd.Timedelta(days=1)
            else:
                month_end = pd.Timestamp(year, month + 1, 1) - pd.Timedelta(days=1)

            month_trades = [d for d in sorted_days if month_start <= d <= month_end]
            if not month_trades:
                continue
            cutoff = month_trades[-1]

            # Rebalance = first trading day of next month
            if month == 12:
                next_start = pd.Timestamp(year + 1, 1, 1)
            else:
                next_start = pd.Timestamp(year, month + 1, 1)

            next_trades = [d for d in sorted_days if d >= next_start]
            rebalance = next_trades[0] if next_trades else None

            results.append((cutoff, rebalance))

    results.sort(key=lambda x: x[0])
    return results


def get_annual_cutoff_dates(trading_days: list) -> list:
    """
    年报后调仓：每年4月底截止（年报已披露），5月初第一个交易日调仓。

    Args:
        trading_days: sorted list of trading days

    Returns:
        list of (cutoff_date, rebalance_date) tuples
    """
    if not trading_days:
        return []
    sorted_days = sorted(set(pd.to_datetime(trading_days)))
    years = sorted(set(d.year for d in sorted_days))
    results = []
    for year in years:
        month = 4  # 年报4月底可用
        month_start = pd.Timestamp(year, month, 1)
        month_end = pd.Timestamp(year, month + 1, 1) - pd.Timedelta(days=1)
        month_trades = [d for d in sorted_days if month_start <= d <= month_end]
        if not month_trades:
            continue
        cutoff = month_trades[-1]
        next_start = pd.Timestamp(year, month + 1, 1)
        next_trades = [d for d in sorted_days if d >= next_start]
        rebalance = next_trades[0] if next_trades else None
        results.append((cutoff, rebalance))
    results.sort(key=lambda x: x[0])
    return results


def get_semi_annual_cutoff_dates(trading_days: list) -> list:
    """
    半年报后调仓：每年4月底（年报）+ 8月底（半年报）各一次。

    Args:
        trading_days: sorted list of trading days

    Returns:
        list of (cutoff_date, rebalance_date) tuples
    """
    if not trading_days:
        return []
    sorted_days = sorted(set(pd.to_datetime(trading_days)))
    years = sorted(set(d.year for d in sorted_days))
    results = []
    for year in years:
        for month in [4, 8]:  # 年报4月底 + 半年报8月底
            month_start = pd.Timestamp(year, month, 1)
            month_end = pd.Timestamp(year, month + 1, 1) - pd.Timedelta(days=1)
            month_trades = [d for d in sorted_days if month_start <= d <= month_end]
            if not month_trades:
                continue
            cutoff = month_trades[-1]
            next_start = pd.Timestamp(year, month + 1, 1)
            next_trades = [d for d in sorted_days if d >= next_start]
            rebalance = next_trades[0] if next_trades else None
            results.append((cutoff, rebalance))
    results.sort(key=lambda x: x[0])
    return results


def get_annual_q3_cutoff_dates(trading_days: list) -> list:
    """
    年报+三季报后调仓：每年4月底（年报）+ 10月底（三季报）各一次。

    Args:
        trading_days: sorted list of trading days

    Returns:
        list of (cutoff_date, rebalance_date) tuples
    """
    if not trading_days:
        return []
    sorted_days = sorted(set(pd.to_datetime(trading_days)))
    years = sorted(set(d.year for d in sorted_days))
    results = []
    for year in years:
        for month in [4, 10]:  # 年报4月底 + 三季报10月底
            month_start = pd.Timestamp(year, month, 1)
            if month == 12:
                month_end = pd.Timestamp(year + 1, 1, 1) - pd.Timedelta(days=1)
            else:
                month_end = pd.Timestamp(year, month + 1, 1) - pd.Timedelta(days=1)
            month_trades = [d for d in sorted_days if month_start <= d <= month_end]
            if not month_trades:
                continue
            cutoff = month_trades[-1]
            if month == 12:
                next_start = pd.Timestamp(year + 1, 1, 1)
            else:
                next_start = pd.Timestamp(year, month + 1, 1)
            next_trades = [d for d in sorted_days if d >= next_start]
            rebalance = next_trades[0] if next_trades else None
            results.append((cutoff, rebalance))
    results.sort(key=lambda x: x[0])
    return results


def get_monthly_cutoff_dates(trading_days: list) -> list:
    """
    Determine monthly cutoff and rebalance dates.

    Cutoff = last trading day of each calendar month
    Rebalance = next trading day after cutoff

    Args:
        trading_days: sorted list of trading days

    Returns:
        list of (cutoff_date, rebalance_date) tuples
    """
    if not trading_days:
        return []

    df = pd.DataFrame({"date": pd.to_datetime(trading_days)})
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month

    monthly_last = (
        df.groupby(["year", "month"])["date"]
        .max()
        .sort_values()
        .tolist()
    )

    trading_day_set = set(pd.to_datetime(trading_days))
    sorted_days = sorted(trading_day_set)

    results = []
    for cutoff in monthly_last:
        idx = sorted_days.index(cutoff)
        if idx + 1 < len(sorted_days):
            rebalance = sorted_days[idx + 1]
        else:
            rebalance = None
        results.append((cutoff, rebalance))

    return results


def get_weekly_cutoff_dates(trading_days: list) -> list:
    """
    确定每周截面日和对应调仓日。

    截面日 = 每个日历周（ISO year + ISO week）的最后一个交易日
    调仓日 = 截面日之后的下一个交易日

    Args:
        trading_days: 排序后的交易日列表

    Returns:
        列表，元素为 (cutoff_date, rebalance_date) 元组
        如果截面日是最后一个交易日，则 rebalance_date 为 None
    """
    if not trading_days:
        return []

    # 构建 DataFrame 用于按周分组
    df = pd.DataFrame({"date": pd.to_datetime(trading_days)})
    df["iso_year"] = df["date"].dt.isocalendar().year
    df["iso_week"] = df["date"].dt.isocalendar().week

    # 按 (year, week) 分组，取每周最后一个交易日
    weekly_last = (
        df.groupby(["iso_year", "iso_week"])["date"]
        .max()
        .sort_values()
        .tolist()
    )

    # 将 trading_days 转为集合用于快速查找下一个交易日
    trading_day_set = set(pd.to_datetime(trading_days))
    sorted_days = sorted(trading_day_set)

    results = []
    for cutoff in weekly_last:
        # 找到 cutoff 之后的下一个交易日
        idx = sorted_days.index(cutoff)
        if idx + 1 < len(sorted_days):
            rebalance = sorted_days[idx + 1]
        else:
            rebalance = None
        results.append((cutoff, rebalance))

    return results


def get_cutoff_date_for_trade_date(trade_date: pd.Timestamp, cutoffs: list) -> pd.Timestamp:
    """
    给定调仓日，找到对应的截面日。

    Args:
        trade_date: 调仓日（pd.Timestamp）
        cutoffs: get_weekly_cutoff_dates 返回的列表

    Returns:
        对应的截面日（pd.Timestamp），找不到则返回 None
    """
    trade_dt = pd.Timestamp(trade_date)
    for cutoff, rebalance in cutoffs:
        if rebalance is not None and pd.Timestamp(rebalance) == trade_dt:
            return pd.Timestamp(cutoff)
    return None


def main():
    """测试函数：构建日历，获取截面日，打印前10条"""
    print("Building trading calendar...")
    trading_days = build_trading_calendar()
    print(f"Total trading days: {len(trading_days)}")

    if not trading_days:
        print("No trading days found. Ensure price data exists in config.PRICE_DATA_DIR.")
        return

    print(f"First trading day: {trading_days[0]}")
    print(f"Last trading day: {trading_days[-1]}")

    print("\nGetting weekly cutoff dates...")
    cutoffs = get_weekly_cutoff_dates(trading_days)
    print(f"Total cutoff dates: {len(cutoffs)}")

    print("\nFirst 10 cutoff/rebalance pairs:")
    for i, (cutoff, rebalance) in enumerate(cutoffs[:10]):
        print(f"  {i+1}. Cutoff: {cutoff.date()}, Rebalance: {rebalance.date() if rebalance else 'N/A'}")


if __name__ == "__main__":
    main()
