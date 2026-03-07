import akshare as ak
import pandas as pd
import numpy as np
import os
from datetime import datetime
from tqdm import tqdm
import argparse
import sys

import matplotlib.pyplot as plt
import seaborn as sns
import matplotlib.font_manager as fm
[f.name for f in fm.fontManager.ttflist if "PingFang" in f.name or "Heiti" in f.name]
plt.rcParams['font.sans-serif'] = ['Heiti TC']


def get_stock_codes():
    """
    Get stock codes from financial data and price data in the 'all' folder
    """
    files_in_financial_folder = os.listdir('../data/input/financial-indicators/all/')
    financial_stock_codes = [stock[21:27] for stock in files_in_financial_folder if stock.endswith('.csv')]

    files_in_price_folder = os.listdir('../data/input/price-data/all/')
    price_stock_codes = [stock[11:17] for stock in files_in_price_folder if stock.endswith('.csv')]

    stock_codes = list(set(financial_stock_codes) & set(price_stock_codes))
    print(f"There are {len(stock_codes)} stocks to be processed.")
    return stock_codes


def format_symbol(code):
    """
    Format stock symbol with proper prefix based on code
    """
    if code.startswith('6'):
        return f'sh{code}'
    elif code.startswith('9') or code.startswith('4'):
        return f'bj{code}'
    else:
        return f'sz{code}'


def calculate_stock_values(stock_codes):
    """
    Calculate stock values based on financial data and price data
    """
    financial_files = os.listdir('../data/input/financial-indicators/all/')
    price_files = os.listdir('../data/input/price-data/all/')

    today = datetime.now().strftime("%Y%m%d")

    for stock_code in tqdm(stock_codes):
        # Find matching files
        financial_file = [file for file in financial_files if stock_code in file]
        price_file = [file for file in price_files if stock_code in file]

        if not financial_file or not price_file:
            print(f"Missing data for {stock_code}")
            continue

        financial_file = financial_file[0]
        price_file = price_file[0]

        financial_df = pd.read_csv(f"../data/input/financial-indicators/all/{financial_file}")
        price_df = pd.read_csv(f"../data/input/price-data/all/{price_file}")

        # --- merge the price data with financial data ---
        financial_df['report_date'] = pd.to_datetime(financial_df['report_date'])
        price_df['report_date'] = pd.to_datetime(price_df['report_date'])
        financial_df['year'] = financial_df['report_date'].dt.year
        financial_df['month'] = financial_df['report_date'].dt.month
        price_df['year'] = price_df['report_date'].dt.year
        price_df['month'] = price_df['report_date'].dt.month
        # aggregate the daily price into monthly price
        price_month = price_df.groupby(['year', 'month']).agg({'open': 'first', 'close': 'last',
                                                        'high': 'max', 'low': 'min'}).reset_index()

        financial_price = pd.merge(price_month, financial_df, on=['year', 'month'], how='left', validate="1:1")
        financial_price = financial_price.ffill()

        # --- calculate pe_ttm, pb_ttm, pr_ttm ---
        financial_price['pe_ttm'] = financial_price['close'] / financial_price['eps_ttm']
        financial_price['pb_ttm'] = financial_price['close'] / financial_price['bps_ttm']
        financial_price['pr_ttm'] = financial_price['pe_ttm'] / financial_price['roe_ttm']
        financial_price['code'] = stock_code.zfill(6)
        financial_price['update_date'] = today

        os.makedirs(f"../data/processed/stock-valuation/all", exist_ok=True)
        financial_price.to_csv(f"../data/processed/stock-valuation/all/stock_valuation_{stock_code}.csv", index=False)


def find_and_visualize_best_stocks(threshold=0.35):
    """
    Find and visualize the best stocks based on stock valuation
    """
    today = datetime.now().strftime("%Y%m%d")

    # pe_ttm, pb_ttm, pr_ttm < 25 quantile
    # roe_ttm > 25 quantile
    stock_values = []
    for stock_value_file in os.listdir("../data/processed/stock-valuation/all"):
        if not stock_value_file.endswith('.csv'):
            continue
        stock_value = pd.read_csv(os.path.join("../data/processed/stock-valuation/all/", stock_value_file))
        stock_value['code'] = stock_value['code'].astype(int).astype(str).str.zfill(6)
        stock_values.append(stock_value.iloc[-1])

    stock_values = pd.DataFrame(stock_values, columns=stock_value.columns)
    pe_th = stock_values.query("pe_ttm > 0").pe_ttm.quantile(threshold)
    pb_th = stock_values.query("pe_ttm > 0").pb_ttm.quantile(threshold)
    pr_th = stock_values.query("pe_ttm > 0").pr_ttm.quantile(threshold)
    roe_th = stock_values.query("pe_ttm > 0").roe_ttm.quantile(1-threshold)

    stock_values_filtered = stock_values.query(f"(pe_ttm < {pe_th}) & (pb_ttm < {pb_th}) & (pr_ttm < {pr_th}) & (roe_ttm > {roe_th})")
    stock_values_filtered.to_csv(f"../data/processed/stock-valuation/stocks_values_filtered_{today}.csv", index=False)

    ob_stocks = stock_values_filtered.code.tolist()
    # create the img/{today} folder if it doesn't exist
    if not os.path.exists(f"../img/{today}"):
        os.makedirs(f"../img/{today}")
    print(f"The number of stocks that meet the criteria is {len(ob_stocks)} and are {ob_stocks}.")

    for stock_code in ob_stocks:
        stock_files = os.listdir("../data/processed/stock-valuation/all")
        ob_stock_file = [file for file in stock_files if stock_code in file]
        if not ob_stock_file:
            continue
        ob_stock_file = ob_stock_file[0]
        financial_price = pd.read_csv(os.path.join("../data/processed/stock-valuation/all/", ob_stock_file))

        fig, axes = plt.subplots(2, 2, figsize=(12, 6))
        axes = axes.flatten()

        # pe ttm distribution
        sns.kdeplot(financial_price, x='pe_ttm', fill=True, color="#eeb908", ax=axes[0])

        # median pettm
        axes[0].axvline(x=financial_price['pe_ttm'].median(), color='blue', linestyle='--', label='median')
        # 25th percentile
        axes[0].axvline(x=financial_price['pe_ttm'].quantile(0.25), color='blue', linestyle='--', label='25th percentile')
        # 75th percentile
        axes[0].axvline(x=financial_price['pe_ttm'].quantile(0.75), color='blue', linestyle='--', label='75th percentile')

        # current pe ttm
        axes[0].axvline(x=financial_price.iloc[-1, -5], color='red', linestyle='--', label='current')
        axes[0].legend()

        # pb ttm distribution
        sns.kdeplot(financial_price, x='pb_ttm', fill=True, color="#eeb908", ax=axes[1])

        # median pbttm
        axes[1].axvline(x=financial_price['pb_ttm'].median(), color='blue', linestyle='--')
        # 25th percentile
        axes[1].axvline(x=financial_price['pb_ttm'].quantile(0.25), color='blue', linestyle='--')
        # 75th percentile
        axes[1].axvline(x=financial_price['pb_ttm'].quantile(0.75), color='blue', linestyle='--')
        # current pb ttm
        axes[1].axvline(x=financial_price.iloc[-1, -4], color='red', linestyle='--')

        # pr ttm distribution
        sns.kdeplot(financial_price, x='pr_ttm', fill=True, color="#eeb908", ax=axes[2])

        # median prttm
        axes[2].axvline(x=financial_price['pr_ttm'].median(), color='blue', linestyle='--')
        # 25th percentile
        axes[2].axvline(x=financial_price['pr_ttm'].quantile(0.25), color='blue', linestyle='--')
        # 75th percentile
        axes[2].axvline(x=financial_price['pr_ttm'].quantile(0.75), color='blue', linestyle='--')
        # current pr ttm
        axes[2].axvline(x=financial_price.iloc[-1, -3], color='red', linestyle='--')

        # roe ttm distribution
        sns.kdeplot(financial_price, x='roe_ttm', fill=True, color="#eeb908", ax=axes[3])

        # median roettm
        axes[3].axvline(x=financial_price['roe_ttm'].median(), color='blue', linestyle='--')
        # 25th percentile
        axes[3].axvline(x=financial_price['roe_ttm'].quantile(0.25), color='blue', linestyle='--')
        # 75th percentile
        axes[3].axvline(x=financial_price['roe_ttm'].quantile(0.75), color='blue', linestyle='--')
        # current roe ttm
        axes[3].axvline(x=financial_price.iloc[-1, -6], color='red', linestyle='--')

        stock_names = pd.read_csv("../data/input/stock_names_full.csv")
        stock_name = stock_names[stock_names['code'] == int(stock_code)]['name'].values[0]

        fig.suptitle(f"{stock_code} {stock_name} | pettm {financial_price.iloc[-1, -5]:<10.2f} | \
            pbttm {financial_price.iloc[-1, -4]:<10.2f} | prttm {financial_price.iloc[-1, -3]:<10.2f} | roettm {financial_price.iloc[-1, -6]:<10.2f} | \
            price {financial_price.iloc[-1, 3]:<10.2f} \
            price_pr_25th {financial_price.iloc[-1, 3] * financial_price['pr_ttm'].quantile(0.25) / financial_price.iloc[-1, -3] :<10.2f} \
            price_pr_75th {financial_price.iloc[-1, 3] * financial_price['pr_ttm'].quantile(0.75) / financial_price.iloc[-1, -3] :<10.2f}",
            fontsize=10)
        plt.tight_layout()

        # save the image
        plt.savefig(f"../img/{today}/pe_pb_pr_roe_distribution_monthly_close_{stock_code}_{today}.png", dpi=300)
        plt.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=0.26,
                        help="The threshold value for filtering stocks")
    parser.add_argument("--step", type=str,
                        choices=['value', 'visualize', 'all'],
                        default='all',
                        help="The step to run, either 'value', 'visualize', or 'all'")

    args = parser.parse_args()

    stock_codes = get_stock_codes()
    if args.step == 'value':
        calculate_stock_values(stock_codes)
    elif args.step == 'visualize':
        find_and_visualize_best_stocks(args.threshold)
    elif args.step == 'all':
        calculate_stock_values(stock_codes)
        find_and_visualize_best_stocks(args.threshold)