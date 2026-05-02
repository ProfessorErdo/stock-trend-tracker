"""
快速测试不同选股阈值组合下的平均选股数量
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from tqdm import tqdm
import config
from data_loader import load_stock_pool
from trading_calendar import build_trading_calendar, get_weekly_cutoff_dates
from stock_selector import get_latest_financial_data, calculate_valuation, winsorize, is_new_stock


def quick_count(stock_codes, cutoffs, price_cache, pe_t, pb_t, pr_t, roe_t):
    """Quick count for a single threshold combo"""
    total = 0
    count = 0
    for cutoff, _ in cutoffs:
        valid = []
        for code in stock_codes:
            if code not in price_cache or price_cache[code].empty:
                continue
            price_df = price_cache[code]
            if cutoff not in price_df["trade_date"].values:
                continue
            fin_data = get_latest_financial_data(code, cutoff)
            if fin_data is None:
                continue
            valuation = calculate_valuation(price_df, cutoff, fin_data)
            if valuation is None:
                continue
            if (valuation["pe_ttm"] <= 0 or valuation["pb_ttm"] <= 0 or
                    valuation["pr_ttm"] <= 0 or valuation["roe_ttm"] <= 0):
                continue
            valid.append({"code": code, **valuation})

        if not valid:
            continue

        val_df = pd.DataFrame(valid)
        pe_cut = val_df["pe_ttm"].quantile(pe_t)
        pb_cut = val_df["pb_ttm"].quantile(pb_t)
        pr_cut = val_df["pr_ttm"].quantile(pr_t)
        step2 = val_df[
            (val_df["pe_ttm"] <= pe_cut) &
            (val_df["pb_ttm"] <= pb_cut) &
            (val_df["pr_ttm"] <= pr_cut)
        ]
        if step2.empty:
            continue

        roe_cut = step2["roe_ttm"].quantile(roe_t)
        step3 = step2[step2["roe_ttm"] >= roe_cut]
        if step3.empty:
            continue

        final = []
        for _, row in step3.iterrows():
            code = row["code"]
            p_df = price_cache.get(code)
            if p_df is not None and not is_new_stock(code, p_df, cutoff, config.NEW_STOCK_EXCLUDE_DAYS):
                final.append(code)

        total += len(final)
        count += 1

    return total / count if count > 0 else 0


def main():
    print("Loading data...")
    pool_df = load_stock_pool()
    stock_codes = pool_df["code"].tolist()

    trading_days = build_trading_calendar()
    cutoffs = get_weekly_cutoff_dates(trading_days)

    price_cache = {}
    for code in tqdm(stock_codes, desc="Loading prices"):
        try:
            from data_loader import load_price_data
            df = load_price_data(code)
            if not df.empty:
                price_cache[code] = df
        except Exception:
            continue

    print(f"\nTesting {len(cutoffs)} cutoff dates with various threshold combinations...\n")

    # Test combinations
    pe_pb_pr_vals = [0.10, 0.15, 0.20, 0.25, 0.30]
    roe_vals = [0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]

    total_combos = len(pe_pb_pr_vals) * len(roe_vals)

    print(f"{'PE/PB/PR':>10s}  {'ROE':>6s}  {'Avg Selected':>12s}")
    print("-" * 35)

    results = []
    for pe_t in tqdm(pe_pb_pr_vals, desc="Testing PE/PB/PR thresholds", leave=False):
        for roe_t in roe_vals:
            avg = quick_count(stock_codes, cutoffs, price_cache, pe_t, pe_t, pe_t, roe_t)
            results.append((pe_t, roe_t, avg))
            marker = " <--" if 8 <= avg <= 15 else ""
            print(f"{pe_t:>10.2f}  {roe_t:>6.2f}  {avg:>12.1f}{marker}")

    print("\n" + "=" * 50)
    print("Combinations that give 8-15 stocks on average:")
    print(f"{'PE/PB/PR':>10s}  {'ROE':>6s}  {'Avg Selected':>12s}  {'Per-stock (1M)':>15s}")
    print("-" * 50)
    for pe_t, roe_t, avg in results:
        if 8 <= avg <= 15:
            per_stock = f"{1_000_000 / avg:,.0f}" if avg > 0 else "N/A"
            print(f"{pe_t:>10.2f}  {roe_t:>6.2f}  {avg:>12.1f}  {per_stock:>15s} RMB")

    print("\n" + "=" * 50)
    print("Top 5 combos near 10 stocks:")
    near_10 = sorted(results, key=lambda x: abs(x[2] - 10))[:5]
    for pe_t, roe_t, avg in near_10:
        per_stock = f"{1_000_000 / avg:,.0f}" if avg > 0 else "N/A"
        print(f"  PE/PB/PR={pe_t:.2f}, ROE={roe_t:.2f}  -> avg {avg:.1f} stocks ({per_stock} RMB/stock)")


if __name__ == "__main__":
    main()
