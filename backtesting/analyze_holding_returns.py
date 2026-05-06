"""
列出所有持仓的 1-year return，从大到小排序
"""

import os
import sys
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config


def load_stock_names() -> dict:
    """从所有 stock pool CSV 中合并 code -> name 映射."""
    name_map = {}
    for pool_name, file_path in config.EXISTING_STOCK_POOL_FILES.items():
        if not os.path.exists(file_path):
            continue
        sep = "\t" if pool_name == "zz500" else ","
        df = pd.read_csv(file_path, sep=sep)
        if "code" in df.columns and "name" in df.columns:
            for _, row in df.iterrows():
                code = str(row["code"]).strip().zfill(6)
                name_map[code] = row["name"]
    return name_map


def main():
    csv_path = os.path.join(config.DATA_OUTPUT_DIR, "pe_trend_test", "pe_analysis.csv")
    df = pd.read_csv(csv_path, dtype={"stock_code": str})

    valid = df[df["pe_ratio"] != "N/A"].copy()
    valid["pe_ratio"] = valid["pe_ratio"].astype(float)
    valid["current_pe"] = valid["current_pe"].astype(float)
    valid["pe_3yr_avg"] = valid["pe_3yr_avg"].astype(float)
    valid["price_1yr_return"] = pd.to_numeric(valid["price_1yr_return"], errors="coerce")
    valid = valid.dropna(subset=["price_1yr_return"])

    # Exclude 2026 (no forward data yet)
    valid = valid[valid["year"] != 2026]

    # Add stock names
    name_map = load_stock_names()
    valid["name"] = valid["stock_code"].map(name_map).fillna("N/A")

    valid = valid.sort_values("price_1yr_return", ascending=False).reset_index(drop=True)

    # Print
    print(f"{'#':>3}  {'Year':>4}  {'Code':>8}  {'Name':<8}  {'PE_ratio':>9}  {'CurPE':>7}  {'3yrAvg':>8}  {'1yr Return':>11}")
    print("=" * 78)

    for i, row in valid.iterrows():
        sign = "+" if row["price_1yr_return"] > 0 else ""
        print(f"{i+1:>3}  {row['year']:>4}  {row['stock_code']:>8}  {row['name']:<8}  {row['pe_ratio']:>9.3f}  {row['current_pe']:>7.2f}  {row['pe_3yr_avg']:>8.2f}  {sign}{row['price_1yr_return']:>9.2f}%")

    print(f"\n总计: {len(valid)} 只持仓")
    print(f"正收益: {(valid['price_1yr_return'] > 0).sum()} ({(valid['price_1yr_return'] > 0).mean():.0%})")
    print(f"负收益: {(valid['price_1yr_return'] < 0).sum()} ({(valid['price_1yr_return'] < 0).mean():.0%})")

    # Save to CSV
    out_dir = os.path.join(config.DATA_OUTPUT_DIR, "pe_trend_test")
    out_path = os.path.join(out_dir, "holding_returns_sorted.csv")
    valid.to_csv(out_path, index=False)
    print(f"\nSaved to: {out_path}")


if __name__ == "__main__":
    main()
