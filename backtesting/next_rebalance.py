"""
下一次调仓计划脚本
根据最新截面日选股结果，计算每只股票的买入数量和分配金额

功能：
1. 自动识别最近的截面日（基于已有交易日历）
2. 交互式输入选股参数和资金总额
3. 执行四步选股 + 排名过滤
4. 输出调仓计划表（股票代码、名称、价格、买入股数、分配金额）
5. 可选：将结果保存为 CSV 文件
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np
from datetime import datetime
from tqdm import tqdm

import config
from log_util import setup_logger
from data_loader import load_stock_pool, load_price_data
from stock_selector import (
    select_stocks, get_latest_financial_data, calculate_valuation,
    winsorize, is_new_stock, rank_and_limit,
)
from trading_calendar import (
    build_trading_calendar,
    get_weekly_cutoff_dates,
    get_monthly_cutoff_dates,
    get_quarterly_cutoff_dates,
    get_annual_cutoff_dates,
    get_annual_q3_cutoff_dates,
)

logger = setup_logger("next_rebalance", "next_rebalance")

# 股票名称映射
_STOCK_NAMES_CACHE = {}


def load_stock_names() -> dict:
    """Load stock code -> name mapping from existing files."""
    if _STOCK_NAMES_CACHE:
        return _STOCK_NAMES_CACHE

    name_files = [
        os.path.join(config.DATA_INPUT_DIR, "..", "stock_names_full_20251212.csv"),
        os.path.join(config.DATA_INPUT_DIR, "..", "stock_names_full.csv"),
    ]
    for f in name_files:
        path = os.path.normpath(f)
        if os.path.exists(path):
            try:
                df = pd.read_csv(path)
                if "code" in df.columns and "name" in df.columns:
                    for _, row in df.iterrows():
                        code = str(row["code"]).strip().zfill(6)
                        _STOCK_NAMES_CACHE[code] = str(row["name"]).strip()
                    logger.info(f"Loaded {len(_STOCK_NAMES_CACHE)} stock names from {os.path.basename(path)}")
                    return _STOCK_NAMES_CACHE
            except Exception:
                continue
    logger.warning("No stock names file found, will use codes only")
    return _STOCK_NAMES_CACHE


def get_stock_name(code: str) -> str:
    """Get stock name by code, fallback to code if not found."""
    names = load_stock_names()
    return names.get(code, code)


def find_latest_cutoff(frequency: str) -> tuple:
    """
    Find the latest cutoff date based on frequency.

    Returns:
        (cutoff_date, rebalance_date) tuple
    """
    trading_days = build_trading_calendar()
    if not trading_days:
        return None, None

    cutoff_map = {
        "weekly": get_weekly_cutoff_dates,
        "monthly": get_monthly_cutoff_dates,
        "quarterly": get_quarterly_cutoff_dates,
        "annual": get_annual_cutoff_dates,
        "annual_q3": get_annual_q3_cutoff_dates,
    }

    func = cutoff_map.get(frequency)
    if func is None:
        logger.error(f"Unknown frequency: {frequency}")
        return None, None

    cutoffs = func(trading_days)
    if not cutoffs:
        return None, None

    today = pd.Timestamp(datetime.now())
    latest = cutoffs[-1]

    # If rebalance is None (no future trading day yet), use cutoff date as execution date
    if latest[1] is None:
        return latest

    # If the last rebalance date is before today, use it (we're catching up)
    # If it's in the future, use the second-to-last (already executed)
    if latest[1] > today:
        if len(cutoffs) > 1:
            latest = cutoffs[-2]

    return latest


def load_price_cache(stock_codes: list) -> dict:
    """Load price data for all stocks into memory cache."""
    cache = {}
    for code in tqdm(stock_codes, desc="Loading price data", leave=False):
        try:
            df = load_price_data(code)
            if not df.empty:
                cache[code] = df
        except Exception:
            continue
    logger.info(f"Price cache: {len(cache)} stocks loaded")
    return cache


def run_selection(
    stock_codes: list,
    cutoff_date: pd.Timestamp,
    price_cache: dict,
    pe_threshold: float,
    pb_threshold: float,
    pr_threshold: float,
    roe_threshold: float,
    max_positions: int,
    ranking_method: str,
    winsorize_enabled: bool,
    filter_indicators: list = None,
) -> list:
    """
    Run the 4-step stock selection with custom thresholds.

    Returns:
        List of selected stock codes
    """
    if filter_indicators is None:
        filter_indicators = ["pe", "pb", "pr"]

    indicator_col_map = {"pe": "pe_ttm", "pb": "pb_ttm", "pr": "pr_ttm"}
    threshold_map = {"pe": pe_threshold, "pb": pb_threshold, "pr": pr_threshold}

    all_valuations = []

    for code in stock_codes:
        if code not in price_cache or price_cache[code].empty:
            continue

        price_df = price_cache[code]
        if cutoff_date not in price_df["trade_date"].values:
            continue

        fin_data = get_latest_financial_data(code, cutoff_date)
        if fin_data is None:
            continue

        valuation = calculate_valuation(price_df, cutoff_date, fin_data)
        if valuation is None:
            continue

        if (valuation["pe_ttm"] <= 0 or valuation["pb_ttm"] <= 0 or
                valuation["pr_ttm"] <= 0 or valuation["roe_ttm"] <= 0):
            continue

        all_valuations.append({"code": code, **valuation})

    if not all_valuations:
        logger.warning("No valid candidates found")
        return []

    val_df = pd.DataFrame(all_valuations)
    logger.info(f"Step 1: {len(val_df)} candidates with valid valuations")

    # Step 2 - Valuation filter (dynamic indicators)
    winsorize_cols = []
    if winsorize_enabled:
        for ind in ["pe", "pb", "pr"]:
            wcol = f"{ind}_w"
            val_df[wcol] = winsorize(val_df[indicator_col_map[ind]], config.WINSORIZE_LOWER, config.WINSORIZE_UPPER)
            winsorize_cols.append(wcol)

    mask = None
    filter_desc_parts = []
    for ind in filter_indicators:
        col = indicator_col_map[ind]
        if winsorize_enabled:
            cut = val_df[f"{ind}_w"].quantile(threshold_map[ind])
        else:
            cut = val_df[col].quantile(threshold_map[ind])
        ind_mask = val_df[col] <= cut
        mask = ind_mask if mask is None else (mask & ind_mask)
        filter_desc_parts.append(f"{ind.upper()}<={cut:.1f}")

    step2 = val_df[mask] if mask is not None else val_df.copy()
    logger.info(f"Step 2: {len(step2)} after valuation filter ({', '.join(filter_desc_parts)})")

    if step2.empty:
        return []

    # Step 3 - ROE filter
    roe_cut = val_df["roe_ttm"].quantile(roe_threshold)
    step3 = step2[step2["roe_ttm"] >= roe_cut]
    logger.info(f"Step 3: {len(step3)} after ROE filter (ROE>={roe_cut:.1%})")

    if step3.empty:
        return []

    # Step 4 - New stock filter
    final = []
    for _, row in step3.iterrows():
        code = row["code"]
        p_df = price_cache.get(code)
        if p_df is not None and not is_new_stock(code, p_df, cutoff_date, config.NEW_STOCK_EXCLUDE_DAYS):
            final.append(code)

    logger.info(f"Step 4: {len(final)} after new stock filter")

    # Ranking
    if ranking_method == "pure_pb":
        if len(final) > max_positions:
            final = val_df[val_df["code"].isin(final)].sort_values("pb_ttm").head(max_positions)["code"].tolist()
    elif len(final) > max_positions:
        final = rank_and_limit(final, val_df, max_positions, ranking_method)

    logger.info(f"Final: {len(final)} selected (max positions: {max_positions})")
    return final


def calculate_allocation(
    selected: list,
    price_cache: dict,
    rebalance_date: pd.Timestamp,
    total_capital: float,
    lot_size: int = 100,
) -> pd.DataFrame:
    """
    Calculate equal-weight allocation for selected stocks.

    Returns:
        DataFrame with code, name, price, shares, amount, weight
    """
    if not selected:
        return pd.DataFrame()

    per_stock = total_capital / len(selected)
    records = []

    for code in selected:
        if code not in price_cache:
            continue

        price_df = price_cache[code]
        row = price_df[price_df["trade_date"] == rebalance_date]
        if row.empty:
            # Try the latest available price
            row = price_df[price_df["trade_date"] <= rebalance_date]
            if row.empty:
                continue
            row = row.tail(1)

        price = row["close_na"].iloc[0] if "close_na" in row.columns else row["close"].iloc[0]
        if pd.isna(price) or price <= 0:
            continue

        # Calculate shares (round down to lot size)
        shares = int(per_stock / price // lot_size) * lot_size
        if shares <= 0:
            continue

        actual_amount = shares * price
        records.append({
            "code": code,
            "name": get_stock_name(code),
            "price": round(price, 3),
            "shares": shares,
            "amount": round(actual_amount, 2),
            "weight": round(actual_amount / total_capital, 4),
        })

    df = pd.DataFrame(records)
    return df


def print_allocation_table(df: pd.DataFrame, total_capital: float):
    """Print formatted allocation table."""
    if df.empty:
        logger.warning("No stocks in allocation table")
        return

    logger.info("\n" + "=" * 80)
    logger.info(f"  Next Rebalance Plan")
    logger.info("=" * 80)
    logger.info(f"  Total Capital: {total_capital:,.0f} RMB")
    logger.info(f"  Selected Stocks: {len(df)}")
    logger.info(f"  Target per stock: {total_capital / len(df):,.0f} RMB ({100/len(df):.1f}%)")
    logger.info("-" * 80)

    # Table header
    header = f"{'#':>3s}  {'Code':<8s}  {'Name':<10s}  {'Price':>8s}  {'Shares':>8s}  {'Amount':>12s}  {'Weight':>6s}"
    logger.info(header)
    logger.info("-" * 80)

    for i, row in df.iterrows():
        logger.info(
            f"{i+1:>3d}  {row['code']:<8s}  {row['name']:<10s}  "
            f"{row['price']:>8.2f}  {row['shares']:>8,d}  "
            f"{row['amount']:>12,.2f}  {row['weight']:>6.1%}"
        )

    logger.info("-" * 80)
    total_amount = df["amount"].sum()
    total_shares_value = df["amount"].sum()
    unallocated = total_capital - total_amount
    logger.info(
        f"  Total allocated: {total_shares_value:>12,.2f} RMB  "
        f"({total_shares_value/total_capital:.1%})"
    )
    if unallocated > 0:
        logger.info(f"  Unallocated cash:  {unallocated:>12,.2f} RMB")
    logger.info("=" * 80 + "\n")


def main():
    logger.info("=" * 80)
    logger.info("  Next Rebalance Plan Calculator")
    logger.info("=" * 80)
    logger.info(f"  Today: {datetime.now().strftime('%Y-%m-%d')}")
    logger.info("")

    # --- 1. Frequency ---
    logger.info("[1/6] Rebalance frequency:")
    logger.info("  1) Weekly")
    logger.info("  2) Monthly")
    logger.info("  3) Quarterly (3x/year: annual/semi-annual/Q3 reports)")
    logger.info("  4) Annual only (1x/year: annual report)")
    logger.info("  5) Annual + Q3 (2x/year)")
    freq_input = input("  Choose [1-5] (default 4): ").strip() or "4"
    freq_map = {"1": "weekly", "2": "monthly", "3": "quarterly", "4": "annual", "5": "annual_q3"}
    frequency = freq_map.get(freq_input, "annual")
    freq_labels = {"weekly": "Weekly", "monthly": "Monthly", "quarterly": "Quarterly",
                   "annual": "Annual", "annual_q3": "Annual+Q3"}
    logger.info(f"  Selected: {freq_labels[frequency]}")
    logger.info("")

    # --- 2. Find latest cutoff ---
    logger.info("[2/6] Finding latest cutoff date...")
    cutoff_date, rebalance_date = find_latest_cutoff(frequency)
    if cutoff_date is None:
        logger.error("No cutoff dates found. Ensure price data exists.")
        return
    logger.info(f"  Cutoff date:    {cutoff_date.strftime('%Y-%m-%d')}")
    logger.info(f"  Rebalance date: {rebalance_date.strftime('%Y-%m-%d') if rebalance_date else 'N/A'}")
    logger.info("")

    # --- 3. Valuation thresholds ---
    logger.info("[3/6] Valuation thresholds (quantile cutoffs):")
    pe_input = input(f"  PE threshold [1-50] (default {int(config.PE_THRESHOLD*100)}): ").strip()
    pe_threshold = int(pe_input) / 100 if pe_input else config.PE_THRESHOLD

    pb_input = input(f"  PB threshold [1-50] (default {int(config.PB_THRESHOLD*100)}): ").strip()
    pb_threshold = int(pb_input) / 100 if pb_input else config.PB_THRESHOLD

    pr_input = input(f"  PR threshold [1-50] (default {int(config.PR_THRESHOLD*100)}): ").strip()
    pr_threshold = int(pr_input) / 100 if pr_input else config.PR_THRESHOLD

    roe_input = input(f"  ROE threshold [50-99] (default {int(config.ROE_THRESHOLD*100)}): ").strip()
    roe_threshold = int(roe_input) / 100 if roe_input else config.ROE_THRESHOLD

    logger.info(f"  PE<={pe_threshold}, PB<={pb_threshold}, PR<={pr_threshold}, ROE>{roe_threshold}")
    logger.info("")

    # --- 4. Max positions and ranking ---
    logger.info("[4/6] Max positions and ranking method:")
    pos_input = input(f"  Max positions [3-20] (default {config.MAX_POSITIONS}): ").strip()
    max_positions = int(pos_input) if pos_input else config.MAX_POSITIONS

    logger.info("  Ranking method (when filtered > max positions):")
    logger.info("    1) PB lowest (default)")
    logger.info("    2) PE lowest")
    logger.info("    3) PR lowest")
    logger.info("    4) ROE highest")
    logger.info("    5) Pure PB (skip 4-step filter)")
    rank_input = input("  Choose [1-5] (default 1): ").strip()
    rank_map = {"2": "pe", "3": "pr", "4": "roe", "5": "pure_pb"}
    ranking_method = rank_map.get(rank_input, "pb")
    rank_labels = {"pe": "PE lowest", "pb": "PB lowest", "pr": "PR lowest",
                   "roe": "ROE highest", "pure_pb": "Pure PB"}
    logger.info(f"  Max positions: {max_positions}, Ranking: {rank_labels[ranking_method]}")
    logger.info("")

    # --- 5. Filter indicators ---
    logger.info("[5/7] Step 2 valuation filter indicators:")
    logger.info("  1) PE + PB + PR (default, all three AND)")
    logger.info("  2) PE only")
    logger.info("  3) PB only")
    logger.info("  4) PR only")
    logger.info("  5) PE + PB")
    logger.info("  6) PE + PR")
    logger.info("  7) PB + PR")
    filter_input = input("  Choose [1-7] (default 1): ").strip()
    filter_map = {
        "2": ["pe"], "3": ["pb"], "4": ["pr"],
        "5": ["pe", "pb"], "6": ["pe", "pr"], "7": ["pb", "pr"],
    }
    filter_indicators = filter_map.get(filter_input, ["pe", "pb", "pr"])
    filter_label_map = {
        ("pe",): "PE only", ("pb",): "PB only", ("pr",): "PR only",
        ("pe", "pb"): "PE + PB", ("pe", "pr"): "PE + PR", ("pb", "pr"): "PB + PR",
        ("pe", "pb", "pr"): "PE + PB + PR",
    }
    filter_label = filter_label_map.get(tuple(filter_indicators), "+".join(i.upper() for i in filter_indicators))
    logger.info(f"  Selected: {filter_label}")
    logger.info("")

    # --- 6. Winsorization ---
    win_input = input(f"[6/7] Winsorization 1%/99%? [Y/n] (default {'Y' if config.WINSORIZE_ENABLED else 'n'}): ").strip()
    if win_input:
        winsorize_enabled = win_input.lower() != "n"
    else:
        winsorize_enabled = config.WINSORIZE_ENABLED
    logger.info(f"  Winsorization: {'On' if winsorize_enabled else 'Off'}")
    logger.info("")

    # --- 6. Capital ---
    capital_input = input(f"[7/7] Total capital (RMB) (default {config.INITIAL_CAPITAL:,}): ").strip()
    total_capital = float(capital_input.replace(",", "")) if capital_input else config.INITIAL_CAPITAL
    logger.info(f"  Total capital: {total_capital:,.0f} RMB")
    logger.info("")

    # === Confirm ===
    logger.info("=" * 60)
    logger.info("  Configuration Summary")
    logger.info("=" * 60)
    logger.info(f"  Frequency:       {freq_labels[frequency]}")
    logger.info(f"  Cutoff date:     {cutoff_date.strftime('%Y-%m-%d')}")
    if rebalance_date:
        logger.info(f"  Rebalance date:  {rebalance_date.strftime('%Y-%m-%d')}")
    else:
        logger.info(f"  Rebalance date:  (none yet) — will use cutoff date close as fill price")
    logger.info(f"  Step 2 filter:   {filter_label}")
    logger.info(f"  PE/PB/PR:        <={pe_threshold}/{pb_threshold}/{pr_threshold}")
    logger.info(f"  ROE:             >{roe_threshold}")
    logger.info(f"  Max positions:   {max_positions}")
    logger.info(f"  Ranking:         {rank_labels[ranking_method]}")
    logger.info(f"  Winsorization:   {'On' if winsorize_enabled else 'Off'}")
    logger.info(f"  Total capital:   {total_capital:,.0f} RMB")
    logger.info("=" * 60)
    logger.info("")

    confirm = input("Proceed with selection? [Y/n] ").strip()
    if confirm.lower() == "n":
        logger.info("Cancelled.")
        return

    # === Load data ===
    logger.info("\n>>> Loading stock pool...")
    pool_df = load_stock_pool()
    stock_codes = pool_df["code"].tolist()
    logger.info(f"  {len(stock_codes)} stocks in pool")

    logger.info("\n>>> Loading price data...")
    price_cache = load_price_cache(stock_codes)

    # === Run selection ===
    logger.info(f"\n>>> Running selection for cutoff date: {cutoff_date.strftime('%Y-%m-%d')}")
    selected = run_selection(
        stock_codes, cutoff_date, price_cache,
        pe_threshold, pb_threshold, pr_threshold, roe_threshold,
        max_positions, ranking_method, winsorize_enabled,
        filter_indicators,
    )

    if not selected:
        logger.warning("\nNo stocks selected. Try adjusting thresholds or frequency.")
        return

    # === Calculate allocation ===
    rebal = rebalance_date if rebalance_date else cutoff_date
    logger.info(f"\n>>> Calculating allocation for rebalance date: {rebal.strftime('%Y-%m-%d')}")
    alloc_df = calculate_allocation(selected, price_cache, rebal, total_capital)

    if alloc_df.empty:
        logger.warning("Could not calculate allocation (no valid prices found)")
        return

    # Sort by weight descending
    alloc_df = alloc_df.sort_values("amount", ascending=False).reset_index(drop=True)

    # === Output ===
    print_allocation_table(alloc_df, total_capital)

    # === Save to CSV ===
    save_csv = input("Save allocation table to CSV? [Y/n] ").strip()
    if save_csv.lower() != "n":
        csv_dir = config.DATA_OUTPUT_DIR
        os.makedirs(csv_dir, exist_ok=True)
        today_str = datetime.now().strftime("%Y%m%d")
        csv_path = os.path.join(csv_dir, f"rebalance_plan_{today_str}.csv")
        alloc_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        logger.info(f"Saved to {csv_path}")


if __name__ == "__main__":
    main()
