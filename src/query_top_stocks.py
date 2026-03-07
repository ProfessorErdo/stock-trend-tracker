import pandas as pd
import numpy as np
import os
import argparse


def load_all_stocks_valuation():
    """
    Load valuation data for all stocks
    """
    valuation_dir = "../data/processed/stock-valuation/all/"
    
    if not os.path.exists(valuation_dir):
        raise FileNotFoundError("Valuation directory not found. Please run calculation first.")
    
    all_stocks = []
    for file in os.listdir(valuation_dir):
        if file.endswith('.csv'):
            df = pd.read_csv(os.path.join(valuation_dir, file))
            all_stocks.append(df.iloc[-1])  # Get the latest row for each stock
    
    return pd.DataFrame(all_stocks)


def get_stock_name(stock_code):
    """
    Get stock name from stock code
    """
    stock_code = str(stock_code).zfill(6)
    stock_names_file = "../data/input/stock_names_full.csv"
    if os.path.exists(stock_names_file):
        stock_names = pd.read_csv(stock_names_file)
        stock_name = stock_names[stock_names['code'].astype(str).str.zfill(6) == stock_code]['name'].values
        return stock_name[0] if len(stock_name) > 0 else "Unknown"
    return "Unknown"


def find_top_stocks(all_stocks_df, indicator, top_n):
    """
    Find top N stocks based on the indicator
    - For pe_ttm, pb_ttm, pr_ttm: find smallest values (lower is better)
    - For roe_ttm: find highest values (higher is better)
    """
    # Filter valid values (positive only for the selected indicator)
    valid_df = all_stocks_df[all_stocks_df[indicator] > 0].copy()
    
    # Filter out negative pe_ttm, pr_ttm, roe_ttm
    if 'pe_ttm' in valid_df.columns:
        valid_df = valid_df[valid_df['pe_ttm'] > 0]
    if 'pr_ttm' in valid_df.columns:
        valid_df = valid_df[valid_df['pr_ttm'] > 0]
    if 'roe_ttm' in valid_df.columns:
        valid_df = valid_df[valid_df['roe_ttm'] > 0]
    
    if len(valid_df) == 0:
        return pd.DataFrame()
    
    # Sort based on indicator type
    if indicator == 'roe_ttm':
        # Higher is better for ROE
        valid_df = valid_df.sort_values(indicator, ascending=False)
    else:
        # Lower is better for PE, PB, PR
        valid_df = valid_df.sort_values(indicator, ascending=True)
    
    # Get top N
    top_stocks = valid_df.head(top_n).copy()
    
    # Ensure code is 6 digits
    top_stocks['code'] = top_stocks['code'].astype(str).str.zfill(6)
    
    # Add stock name
    top_stocks['name'] = top_stocks['code'].apply(lambda x: get_stock_name(x))
    
    return top_stocks


def print_top_stocks(top_stocks_df, indicator, top_n):
    """
    Print top stocks in a nice layout
    """
    if top_stocks_df.empty:
        print(f"No valid data found for indicator: {indicator}")
        return
    
    # Indicator descriptions
    indicator_desc = {
        'pe_ttm': 'PE-TTM (Price-to-Earnings, lower is better)',
        'pb_ttm': 'PB-TTM (Price-to-Book, lower is better)',
        'pr_ttm': 'PR-TTM (PE/ROE ratio, lower is better)',
        'roe_ttm': 'ROE-TTM (Return on Equity, higher is better)'
    }
    
    print("\n" + "=" * 100)
    print(f"  Top {top_n} Stocks by {indicator_desc.get(indicator, indicator)}")
    print("=" * 100)
    
    # Select columns to display
    display_cols = ['code', 'name', indicator, 'pe_ttm', 'pb_ttm', 'pr_ttm', 'roe_ttm', 'close']
    
    # Ensure all columns exist
    display_cols = [col for col in display_cols if col in top_stocks_df.columns]
    
    # Print header
    header = f"  {'Rank':<6} {'Code':<8} {'Name':<12}"
    for col in ['pe_ttm', 'pb_ttm', 'pr_ttm', 'roe_ttm', 'close']:
        if col in display_cols:
            if col == 'close':
                header += f" {'Price':>10}"
            else:
                header += f" {col.upper():>10}"
    print(header)
    print("-" * 100)
    
    # Print rows
    for rank, (_, row) in enumerate(top_stocks_df.iterrows(), 1):
        line = f"  {rank:<6} {str(row['code']).zfill(6):<8} {row['name']:<12}"
        for col in ['pe_ttm', 'pb_ttm', 'pr_ttm', 'roe_ttm', 'close']:
            if col in row:
                line += f" {row[col]:>10.2f}"
        print(line)
    
    print("-" * 100)
    print(f"  Total stocks analyzed: {len(top_stocks_df)}")
    print("=" * 100 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Query top N stocks based on valuation indicators")
    parser.add_argument("--top_n", type=int, default=10,
                        help="Number of top stocks to display (default: 10)")
    parser.add_argument("--indicator", type=str, default="pe_ttm",
                        choices=['pe_ttm', 'pb_ttm', 'pr_ttm', 'roe_ttm'],
                        help="Indicator to sort by: pe_ttm, pb_ttm, pr_ttm (lower is better), roe_ttm (higher is better)")
    
    args = parser.parse_args()
    
    try:
        # Load all stocks data
        all_stocks_df = load_all_stocks_valuation()
        
        print(f"\nLoaded {len(all_stocks_df)} stocks for analysis.")
        
        # Find top stocks
        top_stocks_df = find_top_stocks(all_stocks_df, args.indicator, args.top_n)
        
        # Print results
        print_top_stocks(top_stocks_df, args.indicator, args.top_n)
        
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("Run 'python calculation_and_visualization_new.py --step value' first to generate valuation data.")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()