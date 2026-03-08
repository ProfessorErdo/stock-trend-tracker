import pandas as pd
import numpy as np
import os
import argparse
from datetime import datetime

import matplotlib.pyplot as plt
import seaborn as sns
import matplotlib.font_manager as fm
[f.name for f in fm.fontManager.ttflist if "PingFang" in f.name or "Heiti" in f.name]
plt.rcParams['font.sans-serif'] = ['Heiti TC']


def load_stock_valuation(stock_code):
    """
    Load stock valuation data for a specific stock
    """
    valuation_file = f"../data/processed/stock-valuation/all/stock_valuation_{stock_code}.csv"
    
    if not os.path.exists(valuation_file):
        raise FileNotFoundError(f"Valuation data not found for stock {stock_code}")
    
    df = pd.read_csv(valuation_file)
    df['report_date'] = pd.to_datetime(df['report_date'])
    return df


def load_all_stocks_valuation():
    """
    Load valuation data for all stocks to calculate quantiles
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


def calculate_quantiles(all_stocks_df, metric, value):
    """
    Calculate the quantile rank of a value within all stocks
    """
    valid_values = all_stocks_df[metric].dropna()
    valid_values = valid_values[valid_values > 0]  # Only positive values
    
    if len(valid_values) == 0:
        return None
    
    return (valid_values <= value).mean()


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


def print_comparison_table(stock_codes, all_stocks_df):
    """
    Print a comparison table for multiple stocks
    """
    # Collect data for all stocks
    stocks_data = []
    
    for stock_code in stock_codes:
        try:
            stock_df = load_stock_valuation(stock_code)
            latest = stock_df.iloc[-1]
            
            # Calculate quantiles
            pe_quantile = calculate_quantiles(all_stocks_df, 'pe_ttm', latest['pe_ttm'])
            pb_quantile = calculate_quantiles(all_stocks_df, 'pb_ttm', latest['pb_ttm'])
            pr_quantile = calculate_quantiles(all_stocks_df, 'pr_ttm', latest['pr_ttm'])
            roe_quantile = calculate_quantiles(all_stocks_df, 'roe_ttm', latest['roe_ttm'])
            
            # Calculate target prices
            pr_25 = stock_df['pr_ttm'].quantile(0.25)
            pr_75 = stock_df['pr_ttm'].quantile(0.75)
            current_pr = latest['pr_ttm']
            
            price_25th = latest['close'] * pr_25 / current_pr if current_pr > 0 else None
            price_75th = latest['close'] * pr_75 / current_pr if current_pr > 0 else None
            
            stocks_data.append({
                'code': stock_code,
                'name': get_stock_name(stock_code),
                'close': latest['close'],
                'pe_ttm': latest['pe_ttm'],
                'pe_quantile': pe_quantile,
                'pb_ttm': latest['pb_ttm'],
                'pb_quantile': pb_quantile,
                'pr_ttm': latest['pr_ttm'],
                'pr_quantile': pr_quantile,
                'roe_ttm': latest['roe_ttm'],
                'roe_quantile': roe_quantile,
                'price_25th': price_25th,
                'price_75th': price_75th
            })
        except FileNotFoundError as e:
            print(f"Warning: {e}")
            continue
    
    if not stocks_data:
        print("No valid stock data found.")
        return
    
    # Print comparison table
    print("\n" + "=" * 120)
    print("  Stock Valuation Comparison")
    print("=" * 120)
    
    # Header
    print(f"  {'Code':<8} {'Name':<10} {'Price':>10} {'PE-TTM':>10} {'PE%':>8} {'PB-TTM':>10} {'PB%':>8} {'PR-TTM':>10} {'PR%':>8} {'ROE-TTM':>10} {'ROE%':>8}")
    print("-" * 120)
    
    # Data rows
    for stock in stocks_data:
        print(f"  {stock['code']:<8} {stock['name']:<10} {stock['close']:>10.2f} "
              f"{stock['pe_ttm']:>10.2f} {stock['pe_quantile']*100:>7.1f}% "
              f"{stock['pb_ttm']:>10.2f} {stock['pb_quantile']*100:>7.1f}% "
              f"{stock['pr_ttm']:>10.2f} {stock['pr_quantile']*100:>7.1f}% "
              f"{stock['roe_ttm']:>10.2f} {stock['roe_quantile']*100:>7.1f}%")
    
    print("-" * 120)
    
    # Target prices table
    print(f"\n  Target Prices (based on historical PR percentiles):")
    print("-" * 120)
    print(f"  {'Code':<8} {'Name':<10} {'Current':>12} {'Target (25th)':>15} {'Upside':>10} {'Target (75th)':>15} {'Upside':>10}")
    print("-" * 120)
    
    for stock in stocks_data:
        if stock['price_25th'] and stock['price_75th']:
            upside_25 = (stock['price_25th'] / stock['close'] - 1) * 100
            upside_75 = (stock['price_75th'] / stock['close'] - 1) * 100
            print(f"  {stock['code']:<8} {stock['name']:<10} {stock['close']:>12.2f} "
                  f"{stock['price_25th']:>15.2f} {upside_25:>9.1f}% "
                  f"{stock['price_75th']:>15.2f} {upside_75:>9.1f}%")
        else:
            print(f"  {stock['code']:<8} {stock['name']:<10} {stock['close']:>12.2f} {'N/A':>15} {'N/A':>10} {'N/A':>15} {'N/A':>10}")
    
    print("=" * 120 + "\n")
    
    return stocks_data


def print_stock_info(stock_code, stock_df, all_stocks_df):
    """
    Print stock information in a nice layout
    """
    # Get stock name
    stock_name = get_stock_name(stock_code)
    
    # Get latest data
    latest = stock_df.iloc[-1]
    latest_date = latest['report_date']
    
    # Print header
    print("\n" + "=" * 80)
    print(f"  Stock Valuation Report: {stock_code} - {stock_name}")
    print("=" * 80)
    
    # Print latest metrics
    print(f"\n  Latest Data (as of {latest_date.strftime('%Y-%m-%d')}):")
    print("-" * 80)
    
    # Calculate quantiles
    pe_quantile = calculate_quantiles(all_stocks_df, 'pe_ttm', latest['pe_ttm'])
    pb_quantile = calculate_quantiles(all_stocks_df, 'pb_ttm', latest['pb_ttm'])
    pr_quantile = calculate_quantiles(all_stocks_df, 'pr_ttm', latest['pr_ttm'])
    roe_quantile = calculate_quantiles(all_stocks_df, 'roe_ttm', latest['roe_ttm'])
    
    print(f"  {'Metric':<15} {'Value':>12} {'Quantile':>12} {'Interpretation':>25}")
    print("-" * 80)
    print(f"  {'PE-TTM':<15} {latest['pe_ttm']:>12.2f} {pe_quantile*100:>11.1f}%  {'Lower is better' if pe_quantile < 0.5 else 'Higher than median':>25}")
    print(f"  {'PB-TTM':<15} {latest['pb_ttm']:>12.2f} {pb_quantile*100:>11.1f}%  {'Lower is better' if pb_quantile < 0.5 else 'Higher than median':>25}")
    print(f"  {'PR-TTM':<15} {latest['pr_ttm']:>12.2f} {pr_quantile*100:>11.1f}%  {'Lower is better' if pr_quantile < 0.5 else 'Higher than median':>25}")
    print(f"  {'ROE-TTM':<15} {latest['roe_ttm']:>12.2f} {roe_quantile*100:>11.1f}%  {'Higher is better' if roe_quantile > 0.5 else 'Lower than median':>25}")
    print("-" * 80)
    
    # Print last 24 report dates
    print(f"\n  Last 24 Report Dates:")
    print("-" * 80)
    
    last_24 = stock_df.tail(24)[['report_date', 'eps', 'bps', 'roe']].copy()
    last_24['report_date'] = last_24['report_date'].dt.strftime('%Y-%m-%d')
    
    print(f"  {'Report Date':<15} {'EPS':>12} {'BPS':>12} {'ROE':>12}")
    print("-" * 80)
    for _, row in last_24.iterrows():
        print(f"  {row['report_date']:<15} {row['eps']:>12.2f} {row['bps']:>12.2f} {row['roe']:>12.2f}")
    print("-" * 80)
    
    # Print price info
    print(f"\n  Price Information:")
    print("-" * 80)
    print(f"  {'Latest Close':<20} {latest['close']:>15.2f}")
    
    # Calculate target prices based on PR quantiles
    pr_25 = stock_df['pr_ttm'].quantile(0.25)
    pr_75 = stock_df['pr_ttm'].quantile(0.75)
    current_pr = latest['pr_ttm']
    
    if current_pr > 0:
        price_25th = latest['close'] * pr_25 / current_pr
        price_75th = latest['close'] * pr_75 / current_pr
        print(f"  {'Target (PR 25th)':<20} {price_25th:>15.2f}  (if PR drops to {pr_25:.2f})")
        print(f"  {'Target (PR 75th)':<20} {price_75th:>15.2f}  (if PR rises to {pr_75:.2f})")
    
    print("=" * 80 + "\n")


def plot_distributions(stock_code, stock_df):
    """
    Plot distribution of PE, PB, PR, ROE for the stock's own historical values
    """
    latest = stock_df.iloc[-1]
    
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    axes = axes.flatten()
    
    metrics = [
        ('pe_ttm', 'PE-TTM', latest['pe_ttm']),
        ('pb_ttm', 'PB-TTM', latest['pb_ttm']),
        ('pr_ttm', 'PR-TTM', latest['pr_ttm']),
        ('roe_ttm', 'ROE-TTM', latest['roe_ttm'])
    ]
    
    for i, (metric, title, current_value) in enumerate(metrics):
        # Filter positive values from stock's own history
        data = stock_df[metric].dropna()
        data = data[data > 0]
        
        if len(data) == 0:
            axes[i].text(0.5, 0.5, 'No valid data', ha='center', va='center', transform=axes[i].transAxes)
            continue
        
        # Plot histogram
        sns.histplot(data, color="#eeb908", ax=axes[i], kde=True, stat='density')
        axes[i].set_xlim(0, None)
        axes[i].set_title(f'{title} Distribution (Historical)', fontsize=12)
        axes[i].set_xlabel(title, fontsize=10)
        axes[i].set_ylabel('Density', fontsize=10)
        
        # Add percentile lines
        axes[i].axvline(x=data.quantile(0.25), color='green', linestyle='--', alpha=0.7, label='25th percentile')
        axes[i].axvline(x=data.median(), color='blue', linestyle='--', alpha=0.7, label='Median')
        axes[i].axvline(x=data.quantile(0.75), color='orange', linestyle='--', alpha=0.7, label='75th percentile')
        
        # Add current value
        if current_value > 0:
            axes[i].axvline(x=current_value, color='red', linestyle='-', linewidth=2, label=f'Current: {current_value:.2f}')
        
        axes[i].legend(fontsize=8)
    
    stock_name = get_stock_name(stock_code)
    
    fig.suptitle(f"{stock_code} - {stock_name} | Historical Valuation Distribution", fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.show()


def plot_comparison(stock_codes, stocks_data):
    """
    Plot comparison charts for multiple stocks
    """
    if not stocks_data or len(stocks_data) < 2:
        return
    
    # Create comparison bar chart
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    axes = axes.flatten()
    
    metrics = [
        ('pe_ttm', 'PE-TTM', 'lower'),
        ('pb_ttm', 'PB-TTM', 'lower'),
        ('pr_ttm', 'PR-TTM', 'lower'),
        ('roe_ttm', 'ROE-TTM', 'higher')
    ]
    
    codes = [s['code'] for s in stocks_data]
    names = [s['name'][:6] for s in stocks_data]  # Truncate long names
    labels = [f"{c}\n{n}" for c, n in zip(codes, names)]
    
    colors = ['#eeb908', '#4CAF50', '#2196F3', '#FF5722', '#9C27B0', '#00BCD4']
    
    for i, (metric, title, better) in enumerate(metrics):
        values = [s[metric] for s in stocks_data]
        
        # Sort by value
        sorted_indices = np.argsort(values)
        if better == 'higher':
            sorted_indices = sorted_indices[::-1]
        
        sorted_labels = [labels[j] for j in sorted_indices]
        sorted_values = [values[j] for j in sorted_indices]
        sorted_colors = [colors[j % len(colors)] for j in range(len(sorted_indices))]
        
        bars = axes[i].bar(sorted_labels, sorted_values, color=sorted_colors)
        axes[i].set_title(f'{title} Comparison ({better} is better)', fontsize=12)
        axes[i].set_ylabel(title, fontsize=10)
        
        # Add value labels on bars
        for bar, val in zip(bars, sorted_values):
            axes[i].text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                        f'{val:.2f}', ha='center', va='bottom', fontsize=9)
    
    fig.suptitle("Stock Valuation Comparison", fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.show()


def main():
    parser = argparse.ArgumentParser(description="Query and visualize stock valuation data")
    parser.add_argument("--stock_codes", type=str, required=True,
                        help="Stock codes to query, comma-separated (e.g., '600519,000858,600036')")
    parser.add_argument("--no_plot", action="store_true",
                        help="Skip plotting distribution charts")
    
    args = parser.parse_args()
    
    # Parse stock codes
    stock_codes = [code.strip().zfill(6) for code in args.stock_codes.split(',')]
    
    try:
        # Load all stocks data for quantile calculation
        all_stocks_df = load_all_stocks_valuation()
        
        # Print comparison table if multiple stocks
        if len(stock_codes) > 1:
            stocks_data = print_comparison_table(stock_codes, all_stocks_df)
            
            # Plot comparison charts
            if not args.no_plot and stocks_data:
                plot_comparison(stock_codes, stocks_data)
        else:
            # Single stock - print detailed info
            stock_code = stock_codes[0]
            stock_df = load_stock_valuation(stock_code)
            print_stock_info(stock_code, stock_df, all_stocks_df)
            
            # Plot distributions
            if not args.no_plot:
                plot_distributions(stock_code, stock_df)
        
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("Run 'python calculation_and_visualization_new.py --step value' first to generate valuation data.")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()