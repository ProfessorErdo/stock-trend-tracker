import akshare as ak
import pandas as pd
import numpy as np
import os
from datetime import datetime
from tqdm import tqdm
import argparse
import sys

STOCK_TYPE_MAPPING = {
    "hongli": "../data/input/hongli_list_20251213.csv",
    "honglidibo": "../data/input/honglidibo_list_20251213.csv",
    "hs300": "../data/input/hs300_list_20251213.csv",
    "zz500": "../data/input/zz500_list_20251216.csv"
}

def get_stock_list(stock_type):
    """
    Get stock list based on the specified type
    """
    if stock_type == "zz500": 
        df = pd.read_csv(STOCK_TYPE_MAPPING[stock_type], sep='\t')
    else: 
        df = pd.read_csv(STOCK_TYPE_MAPPING[stock_type])

    df['code'] = df['code'].astype(str).str.zfill(6)
    return df


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


def query_financial_data(stocks_df, output_dir, today, season_end='2025-12-31'):
    """
    Query financial data for the given stocks and save to the specified directory
    """
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    stock_codes = stocks_df['code'].tolist()
    # check financial data already loaded    
    files_in_folder = os.listdir(f'../data/input/financial-indicators/{today}/')
    loaded_stocks = [stock[21:27] for stock in files_in_folder]
    missed_codes = list(set(stock_codes) - set(loaded_stocks))
    print(f"There are already {len(loaded_stocks)} stocks loaded and {len(missed_codes)} stocks missed.")
    stock_codes = missed_codes

    iters = 0
    while (len(stock_codes)) > 0 & (iters <= 20):
        for stock_code in tqdm(stock_codes, desc="Querying financial data"):
            try:
                # Get the financial data
                financial_df = ak.stock_financial_abstract_ths(symbol=f"{stock_code}", indicator="按单季度")
                # select the key indicators
                financial_df = financial_df[['报告期', '每股净资产', '基本每股收益', '净资产收益率']]
                # rename the columns
                financial_df.columns = ['report_date', 'bps', 'eps', 'roe']
                # change the date format
                financial_df['report_date'] = pd.to_datetime(financial_df['report_date'])
                # choose the date later than 2010-01-01
                financial_df = financial_df[financial_df['report_date'] >= '2010-01-01']
                # change the data format
                financial_df['eps'] = financial_df['eps'].astype(float)
                financial_df['roe'] = financial_df['roe'].str.replace('%', '').astype(float)
                financial_df['bps'] = financial_df['bps'].astype(float)
                # calculate ttm eps and ttm roe
                financial_df['bps_ttm'] = financial_df['bps'].rolling(window=4).mean()
                financial_df['eps_ttm'] = financial_df['eps'].rolling(window=4).sum()
                financial_df['roe_ttm'] = financial_df['roe'].rolling(window=4).sum()
                # drop the values with null values
                financial_df.dropna(inplace=True)

                # merge the financial data with standardized report dates
                # standardize the report dates
                date_df = pd.DataFrame(pd.date_range(start='2010-12-31', end=season_end, freq='ME'), columns=['report_date'])
                financial_date = pd.merge(date_df, financial_df, on='report_date', how='left', validate="1:1")
                financial_date.to_csv(f"{output_dir}/financial_indicators_{stock_code}_{today}.csv", index=False)
                stock_codes.remove(stock_code)
            except Exception as e:
                continue
        iters += 1
    if stock_codes: 
        print(f"There are {len(stock_codes)} price data not received and the stock codes are {stock_codes}.")

    print("Successfully queried financial data for all stocks")


def query_price_data(stocks_df, output_dir, today):
    """
    Query price data for the given stocks and save to the specified directory
    """
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    stock_codes = stocks_df['code'].tolist()
    # check price data already loaded
    files_in_folder = os.listdir(f'../data/input/price-data/{today}/')
    loaded_stocks = [stock[13:19] for stock in files_in_folder]
    missed_codes = list(set(stock_codes) - set(loaded_stocks))
    print(f"There are already {len(loaded_stocks)} stocks loaded and {len(missed_codes)} stocks missed.")
    stock_symbols = [format_symbol(code) for code in missed_codes]

    iters = 0
    while (len(stock_symbols)) > 0 & (iters <= 20):
        for symbol in tqdm(stock_symbols, desc="Querying price data"):
            try:
                price_df = ak.stock_zh_a_daily(symbol=f"{symbol}", start_date="20101231", end_date=f"{today}", adjust="")
                price_df = price_df[['date', 'open', 'high', 'low', 'close']]
                price_df.columns = ['report_date', 'open', 'high', 'low', 'close']
                price_df.to_csv(f"{output_dir}/price_data_{symbol}_{today}.csv", index=False)
                stock_symbols.remove(symbol)
            except Exception as e:
                continue
        iters += 1
    if stock_symbols: 
        print(f"There are {len(stock_symbols)} price data not received and the stock codes are {stock_symbols}.")

    print("Successfully queried price data for all stocks")


def query_data(data_type, stock_type, query_date, season_end="2025-12-31"):
    """
    Main function to query either financial or price data for specified stock type
    """
    # Get current date for directory naming
    # today = pd.to_datetime("today").strftime("%Y%m%d")
    today = query_date
    
    # Get the stock list
    stocks_df = get_stock_list(stock_type)
    print(f"Loaded {len(stocks_df)} stocks for {stock_type}")
    
    if data_type.lower() == "financial":
        output_dir = f"../data/input/financial-indicators/{today}"
        os.makedirs(output_dir, exist_ok=True)
        query_financial_data(stocks_df, output_dir, today, season_end=season_end)
    elif data_type.lower() == "price":
        output_dir = f"../data/input/price-data/{today}"
        os.makedirs(output_dir, exist_ok=True)
        query_price_data(stocks_df, output_dir, today)
    else:
        raise ValueError(f"Unknown data type: {data_type}. Use 'financial' or 'price'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Query financial or price data for specified stock lists")
    parser.add_argument("--data_type", type=str, required=True, 
                        choices=['financial', 'price'], 
                        help="Type of data to query: 'financial' or 'price'")
    parser.add_argument("--stock_type", type=str, required=True,
                        choices=['ss300', 'zz500', 'hongli', 'honglidibo'],
                        help="Type of stocks to query: 'ss300', 'zz500', 'hongli', or 'honglidibo'")
    parser.add_argument("--season_end", type=str, default='2025-12-31',
                        help="The end date of the season for financial data")
    parser.add_argument("--query_date", type=str, default=pd.to_datetime("today").strftime("%Y%m%d"),
                        help="The date of the price data to process, in the format 'YYYYMMDD'")
    
    args = parser.parse_args()
    
    try:
        query_data(args.data_type, args.stock_type, args.query_date, args.season_end)
        print("Data querying completed successfully!")
    except Exception as e:
        print(f"Error during data querying: {e}")
        sys.exit(1)