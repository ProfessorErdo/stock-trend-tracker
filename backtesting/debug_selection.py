"""Debug script: trace how each stock passed through the 4-step selection"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import config
from data_loader import load_stock_pool, load_price_data
from stock_selector import (
    get_latest_financial_data, calculate_valuation,
    winsorize, is_new_stock,
)
from trading_calendar import build_trading_calendar, get_annual_cutoff_dates

# Parameters (matching the latest next_rebalance run)
PE_THRESHOLD = 0.25
PB_THRESHOLD = 0.25
PR_THRESHOLD = 0.25
ROE_THRESHOLD = 0.75
MAX_POSITIONS = 5
WINSORIZE_ENABLED = False
RANKING_METHOD = "pb"

# Get cutoff date (annual = April cutoff)
trading_days = build_trading_calendar()
cutoffs = get_annual_cutoff_dates(trading_days)
cutoff_date, rebalance_date = cutoffs[-1]
if rebalance_date is None:
    print(f"NOTE: rebalance_date is None — using cutoff date ({cutoff_date.date()}) close as fill price")

print("=" * 100)
print(f"  Debug: Stock Selection for cutoff={cutoff_date.date()}, rebalance={rebalance_date}")
print(f"  Thresholds: PE<={PE_THRESHOLD}, PB<={PB_THRESHOLD}, PR<={PR_THRESHOLD}, ROE>{ROE_THRESHOLD}")
print(f"  Winsorize: {WINSORIZE_ENABLED}, Ranking: {RANKING_METHOD}, Max positions: {MAX_POSITIONS}")
print("=" * 100)

# Load pool
pool_df = load_stock_pool()
stock_codes = pool_df["code"].tolist()
print(f"\nTotal stocks in pool: {len(stock_codes)}")

# === STEP 1: Build all valid valuations ===
print("\n" + "-" * 100)
print("  STEP 1: Building valuation data for all stocks")
print("-" * 100)

all_vals = []
for code in stock_codes:
    price_df = load_price_data(code)
    if price_df.empty:
        continue
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
    all_vals.append({"code": code, **valuation})

val_df = pd.DataFrame(all_vals)
print(f"Candidates with valid valuations: {len(val_df)}")

# Show financial data details for the 5 selected stocks
selected_codes = ["601838", "601919", "600926", "601156", "601601"]
print(f"\n{'='*100}")
print(f"  DETAILED FINANCIAL DATA FOR 5 SELECTED STOCKS")
print(f"{'='*100}")

for code in selected_codes:
    price_df = load_price_data(code)
    row = price_df[price_df["trade_date"] == cutoff_date]
    if not row.empty:
        close = row["close_na"].iloc[0] if "close_na" in row.columns else row["close"].iloc[0]
    else:
        close = None
    
    # Load financial data to see which report was used
    from data_loader import load_financial_data
    fin_df = load_financial_data(code)
    fin_df["report_date"] = pd.to_datetime(fin_df["report_date"])
    fin_df["ann_available_date"] = pd.to_datetime(fin_df["ann_available_date"])
    available = fin_df[fin_df["ann_available_date"] <= cutoff_date].sort_values("report_date", ascending=False)
    if not available.empty:
        latest = available.iloc[0]
        report_used = latest["report_date"]
        ann_date = latest["ann_available_date"]
    else:
        report_used = "N/A"
        ann_date = "N/A"
    
    fin_data = get_latest_financial_data(code, cutoff_date)
    val = calculate_valuation(price_df, cutoff_date, fin_data) if fin_data else None
    
    print(f"\n  {code}  (close={close}, PE={val['pe_ttm']:.2f}, PB={val['pb_ttm']:.2f}, PR={val['pr_ttm']:.2f}, ROE={val['roe_ttm']:.4f})")
    print(f"    Report used: {report_used.date()}, Available: {ann_date.date()}")
    print(f"    EPS_TTM={fin_data['eps_ttm']:.4f}, BPS_TTM={fin_data['bps_ttm']:.4f}, ROE_TTM={fin_data['roe_ttm']:.4f}")

# === STEP 2: Valuation filter ===
print(f"\n{'='*100}")
print(f"  STEP 2: Valuation Filter (PE/PB/PR <= 25th percentile)")
print(f"{'='*100}")

pe_cut = val_df["pe_ttm"].quantile(PE_THRESHOLD)
pb_cut = val_df["pb_ttm"].quantile(PB_THRESHOLD)
pr_cut = val_df["pr_ttm"].quantile(PR_THRESHOLD)

print(f"  PE cut (25%): {pe_cut:.4f}")
print(f"  PB cut (25%): {pb_cut:.4f}")
print(f"  PR cut (25%): {pr_cut:.4f}")

step2 = val_df[
    (val_df["pe_ttm"] <= pe_cut) &
    (val_df["pb_ttm"] <= pb_cut) &
    (val_df["pr_ttm"] <= pr_cut)
]
print(f"\nPassed Step 2: {len(step2)} stocks")

# Show the 5 selected stocks' position relative to cuts
print(f"\n  {'Code':<8s}  {'PE':>8s}  {'<=cut?':>6s}  {'PB':>8s}  {'<=cut?':>6s}  {'PR':>8s}  {'<=cut?':>6s}  {'ROE':>8s}")
print(f"  {'-'*75}")
for code in selected_codes:
    r = val_df[val_df["code"] == code].iloc[0]
    pe_ok = "Yes" if r["pe_ttm"] <= pe_cut else "No"
    pb_ok = "Yes" if r["pb_ttm"] <= pb_cut else "No"
    pr_ok = "Yes" if r["pr_ttm"] <= pr_cut else "No"
    print(f"  {code:<8s}  {r['pe_ttm']:>8.4f}  {pe_ok:>6s}  {r['pb_ttm']:>8.4f}  {pb_ok:>6s}  {r['pr_ttm']:>8.4f}  {pr_ok:>6s}  {r['roe_ttm']:>8.4f}")

# === STEP 3: ROE filter ===
print(f"\n{'='*100}")
print(f"  STEP 3: ROE Filter (ROE >= 75th percentile of ALL candidates)")
print(f"{'='*100}")

roe_cut = val_df["roe_ttm"].quantile(ROE_THRESHOLD)
print(f"  ROE cut (75% of all {len(val_df)} candidates): {roe_cut:.4f}")

step3 = step2[step2["roe_ttm"] >= roe_cut]
print(f"\nPassed Step 3: {len(step3)} stocks")

print(f"\n  {'Code':<8s}  {'ROE':>8s}  {'>=cut?':>6s}  {'ROE rank':>8s}")
print(f"  {'-'*40}")
for code in selected_codes:
    r = val_df[val_df["code"] == code].iloc[0]
    roe_ok = "Yes" if r["roe_ttm"] >= roe_cut else "No"
    pctile = (val_df["roe_ttm"] < r["roe_ttm"]).sum() / len(val_df) * 100
    print(f"  {code:<8s}  {r['roe_ttm']:>8.4f}  {roe_ok:>6s}  {pctile:>7.1f}%")

# === STEP 4: New stock filter ===
print(f"\n{'='*100}")
print(f"  STEP 4: New Stock Filter (>=120 trading days)")
print(f"{'='*100}")

final = []
for code in step3["code"].tolist():
    price_df = load_price_data(code)
    if not is_new_stock(code, price_df, cutoff_date, config.NEW_STOCK_EXCLUDE_DAYS):
        final.append(code)
print(f"Passed Step 4: {len(final)} stocks")
for code in selected_codes:
    if code in final:
        print(f"  {code}: Passed")
    else:
        print(f"  {code}: Filtered out (new stock)")

# === Ranking ===
print(f"\n{'='*100}")
print(f"  RANKING by PB (lowest first)")
print(f"{'='*100}")

final_val = val_df[val_df["code"].isin(final)].sort_values("pb_ttm")
print(f"\n  {'Rank':>4s}  {'Code':<8s}  {'PB':>8s}  {'PE':>8s}  {'PR':>8s}  {'ROE':>8s}")
print(f"  {'-'*55}")
for i, (_, r) in enumerate(final_val.iterrows()):
    marker = " <-- selected" if r["code"] in selected_codes else ""
    print(f"  {i+1:>4d}  {r['code']:<8s}  {r['pb_ttm']:>8.4f}  {r['pe_ttm']:>8.4f}  {r['pr_ttm']:>8.4f}  {r['roe_ttm']:>8.4f}{marker}")

