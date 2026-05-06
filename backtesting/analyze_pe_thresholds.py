"""
分析每年 PE_ratio 最低 10% 的阈值，以及被排除的股票情况
"""

import sys
import os
import pickle
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

PE_HISTORY_DIR = os.path.join(config.DATA_OUTPUT_DIR, "pe_history")
PE_NEG_VALUE = 1000


def load_pe_history(code):
    path = os.path.join(PE_HISTORY_DIR, f"pe_{code}.csv")
    if not os.path.exists(path):
        return None
    return pd.read_csv(path, parse_dates=["trade_date"])


def compute_pe_ratios_for_cutoff(cutoff_date, stock_codes, pe_cache):
    cutoff_ts = pd.Timestamp(cutoff_date)
    start_date = cutoff_ts - pd.DateOffset(years=3)
    results = {}
    for code in stock_codes:
        if code not in pe_cache:
            continue
        pe_df = pe_cache[code]
        if pe_df.empty:
            continue
        on_day = pe_df[pe_df["trade_date"] == cutoff_ts]
        if not on_day.empty:
            current_pe = on_day.iloc[0]["pe"]
        else:
            before = pe_df[pe_df["trade_date"] <= cutoff_ts]
            if before.empty:
                continue
            current_pe = before.iloc[-1]["pe"]
        window = pe_df[(pe_df["trade_date"] >= start_date) & (pe_df["trade_date"] <= cutoff_ts)]
        valid_pe = window["pe"].dropna()
        if valid_pe.empty or valid_pe.mean() <= 0:
            results[code] = 1.0
            continue
        avg_pe = valid_pe.mean()
        if pd.isna(current_pe) or current_pe <= 0:
            results[code] = PE_NEG_VALUE
        else:
            results[code] = current_pe / avg_pe
    return results


def main():
    with open(os.path.join(config.DATA_OUTPUT_DIR, "intermediate.pkl"), "rb") as f:
        intermediate = pickle.load(f)

    from data_loader import load_stock_pool
    pool_df = load_stock_pool()
    stock_codes = pool_df["code"].tolist()
    cutoff_dates = intermediate["cutoff_dates"]

    # Load PE history
    pe_cache = {}
    for code in stock_codes:
        df = load_pe_history(code)
        if df is not None and not df.empty:
            pe_cache[code] = df
    print(f"PE history loaded for {len(pe_cache)} stocks\n")

    print(f"{'Cutoff':>12}  {'P10':>8}  {'P20':>8}  {'P30':>8}  {'P50':>8}  {'Total':>6}  {'Excl@10%':>10}  {'Excl@20%':>10}")
    print("-" * 95)

    for cutoff in cutoff_dates:
        cutoff_ts = pd.Timestamp(cutoff)
        pe_ratios = compute_pe_ratios_for_cutoff(cutoff_ts, stock_codes, pe_cache)
        if not pe_ratios:
            continue
        vals = sorted(pe_ratios.values())
        n = len(vals)
        p10 = round(vals[int(n * 0.10)], 3)
        p20 = round(vals[int(n * 0.20)], 3)
        p30 = round(vals[int(n * 0.30)], 3)
        p50 = round(vals[int(n * 0.50)], 3)
        excl10 = max(1, int(n * 0.10))
        excl20 = max(1, int(n * 0.20))

        # Show which stocks in original portfolio were excluded at 10%
        portfolio_states = intermediate["portfolio_states"]
        excluded_at_10 = []
        for state_ts, cash, shares in portfolio_states:
            state_ts = pd.Timestamp(state_ts)
            if state_ts.year == cutoff_ts.year:
                for code in shares:
                    if shares[code] > 0 and code in pe_ratios and pe_ratios[code] <= p10:
                        excluded_at_10.append(f"{code}({pe_ratios[code]:.3f})")
                break

        excl_tag = f" [{', '.join(excluded_at_10)}]" if excluded_at_10 else ""

        print(f"{cutoff_ts.strftime('%Y-%m-%d'):>12}  {p10:>8}  {p20:>8}  {p30:>8}  {p50:>8}  {n:>6}  {excl10:>10}  {excl20:>10}{excl_tag}")


if __name__ == "__main__":
    main()
