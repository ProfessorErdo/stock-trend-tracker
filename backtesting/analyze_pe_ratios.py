"""
分析原策略入选股票的 PE_ratio 及后续一年股价变动

用原策略 intermediate.pkl 的 portfolio_states（持仓快照），
对每只入选股票计算截面日的 PE_ratio 和后续一年股价变动。
"""

import sys
import os
import pickle
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config


PE_HISTORY_DIR = os.path.join(config.DATA_OUTPUT_DIR, "pe_history")
PE_NEG_VALUE = 1000


def load_pe_history(code):
    path = os.path.join(PE_HISTORY_DIR, f"pe_{code}.csv")
    if not os.path.exists(path):
        return None
    return pd.read_csv(path, parse_dates=["trade_date"])


def get_pe_ratio(code, cutoff_ts, pe_cache, lookback_years=3):
    """PE_ratio = 截面日PE / 前3年PE均值."""
    if code not in pe_cache:
        return None
    pe_df = pe_cache[code]
    if pe_df.empty:
        return None

    on_day = pe_df[pe_df["trade_date"] == cutoff_ts]
    if not on_day.empty:
        current_pe = on_day.iloc[0]["pe"]
    else:
        before = pe_df[pe_df["trade_date"] <= cutoff_ts]
        if before.empty:
            return None
        current_pe = before.iloc[-1]["pe"]

    start_date = cutoff_ts - pd.DateOffset(years=lookback_years)
    window = pe_df[(pe_df["trade_date"] >= start_date) & (pe_df["trade_date"] <= cutoff_ts)]
    pe_vals = window["pe"].fillna(PE_NEG_VALUE)
    # 负 PE 也当成大值
    pe_vals = pe_vals.apply(lambda x: PE_NEG_VALUE if pd.isna(x) or x <= 0 else x)

    avg_pe = pe_vals.mean()
    if pd.isna(current_pe) or current_pe <= 0:
        current_pe_effective = PE_NEG_VALUE
    else:
        current_pe_effective = current_pe

    return current_pe_effective / avg_pe, current_pe, avg_pe


def get_1yr_return(code, rebalance_date, price_cache, months=12):
    """调仓日后12个月股价变动（后复权 close）。"""
    if code not in price_cache:
        return None
    price_df = price_cache[code]

    row = price_df[price_df["trade_date"] == rebalance_date]
    if row.empty:
        before = price_df[price_df["trade_date"] <= rebalance_date]
        if before.empty:
            return None
        price_start = before.iloc[-1]["close"]
    else:
        price_start = row["close"].iloc[0]

    if price_start <= 0:
        return None

    after_date = rebalance_date + pd.DateOffset(months=months)
    after = price_df[price_df["trade_date"] <= after_date]
    if after.empty:
        return None
    price_end = after.iloc[-1]["close"]

    return (price_end - price_start) / price_start * 100


def main():
    with open(os.path.join(config.DATA_OUTPUT_DIR, "intermediate.pkl"), "rb") as f:
        intermediate = pickle.load(f)

    price_cache = intermediate["price_cache"]
    cutoff_dates = intermediate["cutoff_dates"]
    portfolio_states = intermediate["portfolio_states"]

    # Load PE history
    pe_cache = {}
    all_files = os.listdir(PE_HISTORY_DIR)
    for f in all_files:
        if f.startswith("pe_") and f.endswith(".csv"):
            code = f.replace("pe_", "").replace(".csv", "")
            pe_cache[code] = pd.read_csv(os.path.join(PE_HISTORY_DIR, f), parse_dates=["trade_date"])
    print(f"PE history loaded for {len(pe_cache)} stocks")

    # Build mapping: rebalance_date -> cutoff_date
    # The intermediate cutoff_dates are just Timestamps.
    # We need to find which cutoff maps to which rebalance.
    # Use any stock code to get trading days
    any_code = list(price_cache.keys())[0]
    all_trading = sorted(set(pd.to_datetime(price_cache[any_code]["trade_date"].values)))

    cutoff_to_rebalance = {}
    for c in cutoff_dates:
        c_ts = pd.Timestamp(c)
        next_days = [d for d in all_trading if d > c_ts]
        rebalance = next_days[0] if next_days else c_ts
        cutoff_to_rebalance[c_ts] = rebalance

    print(f"\nCutoff -> Rebalance dates:")
    for c, r in cutoff_to_rebalance.items():
        print(f"  {c.strftime('%Y-%m-%d')} -> {r.strftime('%Y-%m-%d')}")

    # Analyze each holding
    rows = []
    print(f"\n{'Year':>4} {'Stock':>8} {'PE_ratio':>10} {'Current PE':>12} {'3yr Avg PE':>12} {'1yr Return':>12}")
    print("-" * 80)

    for state_ts, cash, shares_snap in portfolio_states:
        state_ts = pd.Timestamp(state_ts)

        # Find the cutoff that maps to this rebalance date
        cutoff = None
        for c_ts, r_ts in cutoff_to_rebalance.items():
            if r_ts == state_ts:
                cutoff = c_ts
                break

        if cutoff is None:
            # Might be the last one (cutoff == rebalance)
            cutoff = state_ts

        year = state_ts.year

        for code in sorted(shares_snap.keys()):
            if shares_snap[code] <= 0:
                continue

            result = get_pe_ratio(code, cutoff, pe_cache)
            if result is None:
                pe_ratio, cur_pe, avg_pe = "N/A", "N/A", "N/A"
            else:
                ratio, cur, avg = result
                pe_ratio = round(ratio, 3)
                cur_pe = round(cur, 2)
                avg_pe = round(avg, 2)

            ret = get_1yr_return(code, state_ts, price_cache)
            ret_str = round(ret, 2) if ret is not None else "N/A"

            print(f"{year:>4} {code:>8} {str(pe_ratio):>10} {str(cur_pe):>12} {str(avg_pe):>12} {str(ret_str):>11}%")

            rows.append({
                "year": year,
                "cutoff_date": cutoff,
                "rebalance_date": state_ts,
                "stock_code": code,
                "pe_ratio": pe_ratio,
                "current_pe": cur_pe,
                "pe_3yr_avg": avg_pe,
                "price_1yr_return": ret_str,
            })

    result_df = pd.DataFrame(rows)

    # Summary stats
    valid_pe = result_df[result_df["pe_ratio"] != "N/A"]["pe_ratio"].astype(float)
    print(f"\nPE_ratio distribution ({len(valid_pe)} observations):")
    print(f"  Mean: {valid_pe.mean():.3f}")
    print(f"  Median: {valid_pe.median():.3f}")
    print(f"  Min: {valid_pe.min():.3f}")
    print(f"  Max: {valid_pe.max():.3f}")

    valid_ret = result_df[result_df["price_1yr_return"] != "N/A"]["price_1yr_return"].astype(float)
    print(f"\n1-year price return distribution ({len(valid_ret)} observations):")
    print(f"  Mean: {valid_ret.mean():.2f}%")
    print(f"  Median: {valid_ret.median():.2f}%")
    print(f"  Min: {valid_ret.min():.2f}%")
    print(f"  Max: {valid_ret.max():.2f}%")
    print(f"  Positive: {(valid_ret > 0).sum()} / {len(valid_ret)} ({(valid_ret > 0).mean():.0%})")

    # Save
    output_path = os.path.join(config.DATA_OUTPUT_DIR, "pe_trend_test", "pe_analysis.csv")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    result_df.to_csv(output_path, index=False)
    print(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    main()
