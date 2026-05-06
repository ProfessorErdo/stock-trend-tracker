"""
生成每只股票的每日 PE 时间序列，保存到 data/processed/backtesting/pe_history/

PE = close_na / eps_ttm
- close_na 来自价格 CSV（非复权收盘价）
- eps_ttm 来自财务 CSV，向前填充
- eps_ttm 为负/零 → PE 记为 NaN
"""

import sys
import os
import pickle
import pandas as pd
import numpy as np
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from data_loader import load_stock_pool, load_price_data, load_financial_data


OUTPUT_DIR = os.path.join(config.DATA_OUTPUT_DIR, "pe_history")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    pool_df = load_stock_pool()
    stock_codes = pool_df["code"].tolist()
    print(f"Stock pool: {len(stock_codes)} stocks")

    # Check existing files
    existing = set()
    if os.path.exists(OUTPUT_DIR):
        for f in os.listdir(OUTPUT_DIR):
            if f.startswith("pe_") and f.endswith(".csv"):
                existing.add(f.replace("pe_", "").replace(".csv", ""))
    print(f"Already have PE history for {len(existing)} stocks")

    todo = [c for c in stock_codes if c not in existing]
    if not todo:
        print("All stocks already have PE history. Done.")
        return
    print(f"Need to generate for {len(todo)} stocks")

    success = 0
    fail = 0

    for code in tqdm(todo, desc="Generating PE history"):
        try:
            # Load price data
            price_df = load_price_data(code)
            if price_df is None or price_df.empty:
                fail += 1
                continue
            if "close_na" not in price_df.columns:
                # Fallback to close
                price_col = "close"
            else:
                price_col = "close_na"
            price_df = price_df.sort_values("trade_date").reset_index(drop=True)

            # Load financial data
            fin_df = load_financial_data(code)
            if fin_df is None or fin_df.empty or "eps_ttm" not in fin_df.columns:
                fail += 1
                continue
            fin_df = fin_df.sort_values("report_date").reset_index(drop=True)

            # Build daily PE
            pe_rows = []
            current_eps = None
            fin_idx = 0

            for _, price_row in price_df.iterrows():
                trade_date = price_row["trade_date"]
                close_na = price_row[price_col]

                # Check if any new financial report is available
                while fin_idx < len(fin_df):
                    report = fin_df.iloc[fin_idx]
                    ann_date = pd.Timestamp(report["ann_available_date"])
                    if ann_date <= trade_date:
                        eps = report.get("eps_ttm", np.nan)
                        if pd.notna(eps) and eps != 0:
                            current_eps = eps
                        fin_idx += 1
                    else:
                        break

                # Calculate PE
                if current_eps is not None and close_na > 0:
                    pe = close_na / current_eps
                else:
                    pe = np.nan

                pe_rows.append({"trade_date": trade_date, "pe": pe})

            if not pe_rows:
                fail += 1
                continue

            pe_df = pd.DataFrame(pe_rows)

            # Summary stats
            valid_pe = pe_df["pe"].dropna()
            stats = {
                "total_days": len(pe_df),
                "valid_pe": len(valid_pe),
                "pe_mean": round(valid_pe.mean(), 2) if not valid_pe.empty else "N/A",
                "pe_median": round(valid_pe.median(), 2) if not valid_pe.empty else "N/A",
                "pe_min": round(valid_pe.min(), 2) if not valid_pe.empty else "N/A",
                "pe_max": round(valid_pe.max(), 2) if not valid_pe.empty else "N/A",
            }

            output_path = os.path.join(OUTPUT_DIR, f"pe_{code}.csv")
            pe_df.to_csv(output_path, index=False)
            success += 1

        except Exception as e:
            fail += 1
            tqdm.write(f"  FAIL {code}: {e}")

    print(f"\nDone! Success: {success}, Failed: {fail}")
    print(f"Output: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
