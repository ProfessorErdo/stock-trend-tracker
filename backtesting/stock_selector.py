"""
股票筛选模块 - 四步选股逻辑
每周截面日执行，通过四步过滤筛选低估值高ROE股票

选股流程:
1. 基础过滤: 停牌、无财务数据、负估值指标
2. 估值过滤: PE/PB/PR去极值后取25%分位，保留低于三者的股票
3. ROE过滤: 保留ROE在第二步结果75%分位以上的股票
4. 新股排除: 排除上市不足120个交易日的股票
"""

import pandas as pd
import logging

logger = logging.getLogger("stock_selector")
import numpy as np
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from data_loader import load_price_data, load_financial_data


def get_latest_financial_data(stock_code: str, as_of_date: pd.Timestamp) -> dict:
    """
    加载单只股票的最新可用财务数据（尊重财报披露延迟）

    Args:
        stock_code: 股票代码
        as_of_date: 截至日期（只使用在此日期前已可披露的财报）

    Returns:
        最新可用财务数据 dict: {'eps_ttm': float, 'bps_ttm': float, 'roe_ttm': float}
        如果没有可用数据返回 None
    """
    df = load_financial_data(stock_code)
    if df.empty:
        return None

    # 过滤到 ann_available_date <= as_of_date 的财报
    df = df[df["ann_available_date"] <= as_of_date]
    if df.empty:
        return None

    # 按报告期排序，取最新的
    df = df.sort_values("report_date", ascending=False).iloc[0]

    result = {}
    for key in ["eps_ttm", "bps_ttm", "roe_ttm"]:
        if key in df.index:
            val = df[key]
            if pd.notna(val):
                result[key] = float(val)
            else:
                return None
        else:
            return None

    return result


def calculate_valuation(
    price_df: pd.DataFrame,
    trade_date: pd.Timestamp,
    financial_data: dict
) -> dict:
    """
    计算估值指标: PE_TTM, PB_TTM, PR_TTM

    Uses non-adjusted close (close_na) if available, falls back to close.
    Non-adjusted prices reflect the actual market price at each point in time,
    which is required for correct valuation calculations.

    Args:
        price_df: 价格数据 DataFrame（需含 trade_date, close 或 close_na 列）
        trade_date: 交易日期
        financial_data: 来自 get_latest_financial_data 的财务数据

    Returns:
        估值指标 dict: {'pe_ttm': float, 'pb_ttm': float, 'pr_ttm': float, 'roe_ttm': float}
        如果无法计算返回 None
    """
    row = price_df[price_df["trade_date"] == trade_date]
    if row.empty:
        return None

    # Use non-adjusted close for valuation if available
    close_col = "close_na" if "close_na" in row.columns else "close"
    close = row[close_col].iloc[0]
    if pd.isna(close) or close <= 0:
        return None

    eps = financial_data["eps_ttm"]
    bps = financial_data["bps_ttm"]
    roe = financial_data["roe_ttm"]

    if eps <= 0 or bps <= 0 or roe <= 0:
        return None

    pe_ttm = close / eps
    pb_ttm = close / bps
    pr_ttm = pe_ttm / roe

    return {
        "pe_ttm": pe_ttm,
        "pb_ttm": pb_ttm,
        "pr_ttm": pr_ttm,
        "roe_ttm": roe,
    }


def winsorize(series: pd.Series, lower: float = 0.01, upper: float = 0.99) -> pd.Series:
    """
    将序列值截断到 [lower 分位数, upper 分位数] 范围内

    Args:
        series: 输入序列
        lower: 下限分位数（默认 0.01）
        upper: 上限分位数（默认 0.99）

    Returns:
        截断后的序列
    """
    lower_val = series.quantile(lower)
    upper_val = series.quantile(upper)
    return series.clip(lower=lower_val, upper=upper_val)


def is_new_stock(
    stock_code: str,
    price_df: pd.DataFrame,
    as_of_date: pd.Timestamp,
    exclude_days: int = 120
) -> bool:
    """
    检查是否为新股（上市不足 exclude_days 个交易日）

    估算方式: 交易日数 = 日历天数 * 252 / 365

    Args:
        stock_code: 股票代码
        price_df: 价格数据 DataFrame（需含 trade_date 列）
        as_of_date: 截至日期
        exclude_days: 排除阈值（默认 120 个交易日）

    Returns:
        True 表示是新股（应排除），False 表示不是新股
    """
    if price_df.empty:
        return True

    # 找到最早的交易日（上市日期近似）
    earliest_date = price_df["trade_date"].min()
    as_of = pd.Timestamp(as_of_date)

    if earliest_date >= as_of:
        return True

    calendar_days = (as_of - earliest_date).days
    trading_days_listed = int(calendar_days * 252 / 365)

    return trading_days_listed < exclude_days


def select_stocks(
    stock_codes: list,
    trade_date: pd.Timestamp,
    price_cache: dict = None,
    filter_indicators: list = None
) -> tuple:
    """
    执行完整的四步选股流程

    Args:
        stock_codes: 候选股票代码列表
        trade_date: 截面日/调仓日
        price_cache: 价格数据缓存 {code: DataFrame}，传入可避免重复读取文件
        filter_indicators: Step 2 估值过滤使用的指标列表，如 ["pe","pb"]。
                          None 时使用 config.FILTER_INDICATORS.

    Returns:
        (selected_codes, all_valuations)
        selected_codes: 通过筛选的股票代码列表
        all_valuations: 所有股票的估值 DataFrame（含 code, pe_ttm, pb_ttm, pr_ttm, roe_ttm）
    """
    all_valuations = []

    for code in stock_codes:
        # 获取价格数据（从缓存或文件）
        if price_cache is not None and code in price_cache:
            price_df = price_cache[code]
        else:
            price_df = load_price_data(code)

        if price_df.empty:
            continue

        # Step 1a - 停牌检测：trade_date 不在价格数据中
        if trade_date not in price_df["trade_date"].values:
            continue

        # Step 1b - 获取财务数据
        fin_data = get_latest_financial_data(code, trade_date)
        if fin_data is None:
            continue

        # 计算估值
        valuation = calculate_valuation(price_df, trade_date, fin_data)
        if valuation is None:
            continue

        # Step 1c - 所有估值指标必须为正
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

    # Step 2 - Valuation filter: dynamic based on filter_indicators
    if filter_indicators is None:
        filter_indicators = list(config.FILTER_INDICATORS)

    indicator_col_map = {"pe": "pe_ttm", "pb": "pb_ttm", "pr": "pr_ttm"}
    threshold_map = {"pe": config.PE_THRESHOLD, "pb": config.PB_THRESHOLD, "pr": config.PR_THRESHOLD}

    unknown = [ind for ind in filter_indicators if ind not in indicator_col_map]
    if unknown:
        raise ValueError(
            f"不支持的第 2 步过滤指标 {unknown}；只允许 pe/pb/pr"
            "（ROE 是第 3 步，始终启用）"
        )

    # Winsorize ALL three indicators (needed for quantile stability)
    winsorize_cols = []
    if config.WINSORIZE_ENABLED:
        for ind in ["pe", "pb", "pr"]:
            wcol = f"{ind}_winsorized"
            val_df[wcol] = winsorize(val_df[indicator_col_map[ind]], config.WINSORIZE_LOWER, config.WINSORIZE_UPPER)
            winsorize_cols.append(wcol)

    # Build filter mask using only active indicators
    mask = None
    for ind in filter_indicators:
        col = indicator_col_map[ind]
        if config.WINSORIZE_ENABLED:
            cut = val_df[f"{ind}_winsorized"].quantile(threshold_map[ind])
        else:
            cut = val_df[col].quantile(threshold_map[ind])
        ind_mask = val_df[col] <= cut
        mask = ind_mask if mask is None else (mask & ind_mask)

    step2_df = val_df[mask] if mask is not None else val_df.copy()

    if step2_df.empty:
        return [], val_df.drop(columns=winsorize_cols, errors="ignore")

    # Step 3 - ROE过滤: ROE阈值在全部候选股票上计算
    roe_cut = val_df["roe_ttm"].quantile(config.ROE_THRESHOLD)
    step3_df = step2_df[step2_df["roe_ttm"] >= roe_cut]

    if step3_df.empty:
        return [], val_df.drop(columns=winsorize_cols, errors="ignore")

    # Step 4 - 新股排除
    selected = []
    for _, row in step3_df.iterrows():
        code = row["code"]
        if price_cache is not None and code in price_cache:
            p_df = price_cache[code]
        else:
            p_df = load_price_data(code)

        if not is_new_stock(code, p_df, trade_date, config.NEW_STOCK_EXCLUDE_DAYS):
            selected.append(code)

    # 清理辅助列
    clean_df = val_df.drop(columns=winsorize_cols, errors="ignore")

    return selected, clean_df


def rank_and_limit(selected: list, val_df: pd.DataFrame, max_positions: int = 10,
                   ranking_method: str = "roe") -> list:
    """
    当通过筛选的股票超过 max_positions 时，按指定指标排序取前 N 只。

    Args:
        selected: 通过四步筛选的股票代码列表
        val_df: 所有候选股票的估值 DataFrame（含 code, pe_ttm, pb_ttm, pr_ttm, roe_ttm）
        max_positions: 最大持仓数量（默认 10）
        ranking_method: 排序方式 — "roe"(最高), "pe"(最低), "pb"(最低), "pr"(最低)

    Returns:
        排序后的股票代码列表（不超过 max_positions）
    """
    if len(selected) <= max_positions:
        return selected

    val_map = val_df.set_index("code")
    method_map = {
        "roe": lambda c: -val_map.loc[c, "roe_ttm"],   # 越高越好 → 负号取反
        "pe":  lambda c:  val_map.loc[c, "pe_ttm"],     # 越低越好
        "pb":  lambda c:  val_map.loc[c, "pb_ttm"],
        "pr":  lambda c:  val_map.loc[c, "pr_ttm"],
    }
    if ranking_method not in method_map:
        return selected[:max_positions]

    key_func = method_map[ranking_method]
    ranked = sorted(selected, key=key_func)
    return ranked[:max_positions]


def main():
    """测试函数"""
    logger.info("=" * 60)
    logger.info("Stock Selector - Test Run")
    logger.info("=" * 60)

    # 测试 winsorize
    test_series = pd.Series([1, 2, 3, 4, 5, 100, -50])
    w = winsorize(test_series, 0.05, 0.95)
    logger.info(f"\nWinsorize test: {test_series.tolist()}")
    logger.info(f"  -> {w.tolist()}")

    # 尝试加载股票池
    try:
        from data_loader import load_stock_pool
        pool_df = load_stock_pool()
        stock_codes = pool_df["code"].tolist()[:10]  # 只测试前10只
        logger.info(f"\nTesting with {len(stock_codes)} stocks from pool")

        trade_date = pd.Timestamp("2024-01-19")
        selected, val_df = select_stocks(stock_codes, trade_date)

        logger.info(f"\nTrade date: {trade_date.date()}")
        logger.info(f"Candidates with valid valuations: {len(val_df)}")
        if not val_df.empty:
            logger.info(val_df.head().to_string(index=False))
        logger.info(f"Selected after 4-step filter: {len(selected)}")
        if selected:
            logger.info(f"  Selected: {selected}")
    except Exception as e:
        logger.info(f"\nFull test skipped: {e}")
        logger.info("(This is expected if no price/financial data has been downloaded yet.)")

        # Minimal test with mock data
        logger.info("\nRunning minimal mock tests...")

        mock_fin = {"eps_ttm": 1.5, "bps_ttm": 10.0, "roe_ttm": 0.15}
        mock_prices = pd.DataFrame({
            "trade_date": [pd.Timestamp("2024-01-18"), pd.Timestamp("2024-01-19")],
            "close": [15.0, 16.0]
        })
        td = pd.Timestamp("2024-01-19")

        result = calculate_valuation(mock_prices, td, mock_fin)
        logger.info(f"  calculate_valuation: {result}")

        result2 = get_latest_financial_data("000001", td)
        logger.info(f"  get_latest_financial_data: {result2}")

    logger.info("\n" + "=" * 60)
    logger.info("Stock Selector tests complete.")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
