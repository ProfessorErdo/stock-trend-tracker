import akshare as ak
import pandas as pd
import numpy as np
import os
from datetime import datetime, timedelta
from tqdm import tqdm
import argparse
import json

STOCK_TYPE_MAPPING = {
    "hongli": "../data/input/hongli_list_20251213.csv",
    "honglidibo": "../data/input/honglidibo_list_20251213.csv",
    "hs300": "../data/input/hs300_list_20251213.csv",
    "zz500": "../data/input/zz500_list_20251216.csv",
    "portfolio": ["600519", "000858", "600938", "000333", "600926", "300866", "600900", "601128"],
    "all": "../data/input/stock_names_full.csv",
}

# Metadata file to track last update times
METADATA_FILE = "../data/input/query_metadata.json"


def load_metadata():
    """Load metadata containing last update times for each stock"""
    if os.path.exists(METADATA_FILE):
        with open(METADATA_FILE, 'r') as f:
            return json.load(f)
    return {"financial": {}, "price": {}}


def save_metadata(metadata):
    """Save metadata to file"""
    os.makedirs(os.path.dirname(METADATA_FILE), exist_ok=True)
    with open(METADATA_FILE, 'w') as f:
        json.dump(metadata, f, indent=2)


def get_stock_list(stock_type):
    """
    Get stock list based on the specified type
    """
    if stock_type == "zz500":
        df = pd.read_csv(STOCK_TYPE_MAPPING[stock_type], sep='\t')
    elif stock_type == "portfolio":
        df = pd.DataFrame(STOCK_TYPE_MAPPING[stock_type], columns=['code'])
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


def get_last_update_date(metadata, data_type, stock_code):
    """Get the last update date for a specific stock and data type"""
    return metadata.get(data_type, {}).get(stock_code, None)


def should_query_financial(metadata, stock_code, force=False):
    """
    Check if financial data should be queried (monthly basis)
    Returns: (should_query, last_date)
    """
    if force:
        return True, None

    last_date_str = get_last_update_date(metadata, "financial", stock_code)
    if not last_date_str:
        return True, None

    last_date = datetime.strptime(last_date_str, "%Y-%m-%d")
    today = datetime.now()

    # Query if more than 30 days have passed
    days_since_update = (today - last_date).days
    return days_since_update >= 30, last_date_str


def should_query_price(metadata, stock_code, force=False):
    """
    Check if price data should be queried (daily basis)
    Returns: (should_query, last_date)
    """
    if force:
        return True, None

    last_date_str = get_last_update_date(metadata, "price", stock_code)
    if not last_date_str:
        return True, None

    last_date = datetime.strptime(last_date_str, "%Y-%m-%d")
    today = datetime.now()

    # Query if more than 1 day has passed
    days_since_update = (today - last_date).days
    return days_since_update >= 1, last_date_str


def query_financial_data_incremental(stocks_df, output_dir, force=False, season_end='2025-12-31'):
    """
    Query financial data incrementally - only update stocks that haven't been updated in 30+ days
    """
    os.makedirs(output_dir, exist_ok=True)

    metadata = load_metadata()
    stock_codes = stocks_df['code'].tolist()

    # Determine which stocks need updating
    stocks_to_update = []
    for stock_code in stock_codes:
        should_query, last_date = should_query_financial(metadata, stock_code, force)
        if should_query:
            stocks_to_update.append((stock_code, last_date))

    print(f"Total stocks: {len(stock_codes)}, Need to update: {len(stocks_to_update)}")

    if not stocks_to_update:
        print("All financial data is up to date (within 30 days).")
        return

    # Retry loop - up to 20 iterations for failed stocks
    max_iterations = 20
    iteration = 0

    while stocks_to_update and iteration < max_iterations:
        iteration += 1
        if iteration > 1:
            print(f"Retry iteration {iteration}/{max_iterations} for {len(stocks_to_update)} stocks...")

        for stock_code, last_date in tqdm(stocks_to_update.copy(), desc=f"Querying financial data (iter {iteration})"):
            try:
                # Get the financial data
                financial_df = ak.stock_financial_abstract_ths(symbol=f"{stock_code}", indicator="按单季度")

                # Select and process key indicators
                financial_df = financial_df[['报告期', '每股净资产', '基本每股收益', '净资产收益率']]
                financial_df.columns = ['report_date', 'bps', 'eps', 'roe']
                financial_df['report_date'] = pd.to_datetime(financial_df['report_date'])
                financial_df = financial_df[financial_df['report_date'] >= '2010-01-01']

                financial_df['eps'] = financial_df['eps'].astype(float)
                financial_df['roe'] = financial_df['roe'].str.replace('%', '').astype(float)
                financial_df['bps'] = financial_df['bps'].astype(float)

                # Calculate TTM values
                financial_df['bps_ttm'] = financial_df['bps'].rolling(window=4).mean()
                financial_df['eps_ttm'] = financial_df['eps'].rolling(window=4).sum()
                financial_df['roe_ttm'] = financial_df['roe'].rolling(window=4).sum()
                financial_df.dropna(inplace=True)

                # Standardize report dates
                date_df = pd.DataFrame(pd.date_range(start='2010-12-31', end=season_end, freq='ME'), columns=['report_date'])
                financial_date = pd.merge(date_df, financial_df, on='report_date', how='left', validate="1:1")

                # Save to file
                output_file = f"{output_dir}/financial_indicators_{stock_code}.csv"
                financial_date.to_csv(output_file, index=False)

                # Update metadata
                metadata["financial"][stock_code] = datetime.now().strftime("%Y-%m-%d")

                # Remove from retry list on success
                stocks_to_update.remove((stock_code, last_date))

            except Exception as e:
                continue  # Keep in list for retry

    # Save updated metadata
    save_metadata(metadata)

    if stocks_to_update:
        failed_codes = [stock[0] for stock in stocks_to_update]
        print(f"Failed to query financial data for {len(failed_codes)} stocks after {iteration} iterations: {failed_codes}")
    else:
        print("Successfully queried financial data for all stocks needing update.")


def query_price_data_incremental(stocks_df, output_dir, force=False, adjust=""):
    """
    Query price data incrementally - only fetch new data since last update
    """
    os.makedirs(output_dir, exist_ok=True)

    metadata = load_metadata()
    stock_codes = stocks_df['code'].tolist()

    # Determine which stocks need updating
    stocks_to_update = []
    for stock_code in stock_codes:
        should_query, last_date = should_query_price(metadata, stock_code, force)
        if should_query:
            stocks_to_update.append((stock_code, last_date))

    print(f"Total stocks: {len(stock_codes)}, Need to update: {len(stocks_to_update)}")

    if not stocks_to_update:
        print("All price data is up to date (queried today).")
        return

    today = datetime.now().strftime("%Y%m%d")

    # Retry loop - up to 20 iterations for failed stocks
    max_iterations = 20
    iteration = 0

    while stocks_to_update and iteration < max_iterations:
        iteration += 1
        if iteration > 1:
            print(f"Retry iteration {iteration}/{max_iterations} for {len(stocks_to_update)} stocks...")

        for stock_code, last_date in tqdm(stocks_to_update.copy(), desc=f"Querying price data (iter {iteration})"):
            symbol = format_symbol(stock_code)

            try:
                # Determine start date for incremental query
                if last_date:
                    # Incremental: start from day after last date
                    start_date = (datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y%m%d")
                else:
                    # Full query: start from 2010
                    start_date = "20101231"

                # Query new data
                new_price_df = ak.stock_zh_a_daily(symbol=symbol, start_date=start_date, end_date=today, adjust=adjust)

                if new_price_df.empty:
                    # No new data, just update metadata
                    metadata["price"][stock_code] = datetime.now().strftime("%Y-%m-%d")
                    stocks_to_update.remove((stock_code, last_date))
                    continue

                new_price_df = new_price_df[['date', 'open', 'high', 'low', 'close']]
                new_price_df.columns = ['report_date', 'open', 'high', 'low', 'close']

                # Check if existing data file exists
                existing_file = f"{output_dir}/price_data_{stock_code}.csv"

                if os.path.exists(existing_file) and last_date:
                    # Load existing data and append new data
                    existing_df = pd.read_csv(existing_file)
                    existing_df['report_date'] = pd.to_datetime(existing_df['report_date'])
                    new_price_df['report_date'] = pd.to_datetime(new_price_df['report_date'])

                    # Remove any overlapping dates from existing data (in case of corrections)
                    existing_df = existing_df[existing_df['report_date'] < new_price_df['report_date'].min()]

                    # Combine and save
                    combined_df = pd.concat([existing_df, new_price_df], ignore_index=True)
                    combined_df = combined_df.sort_values('report_date').reset_index(drop=True)
                    combined_df.to_csv(existing_file, index=False)
                else:
                    # No existing data, save new data directly
                    new_price_df.to_csv(existing_file, index=False)

                # Update metadata
                metadata["price"][stock_code] = datetime.now().strftime("%Y-%m-%d")

                # Remove from retry list on success
                stocks_to_update.remove((stock_code, last_date))

            except Exception as e:
                continue  # Keep in list for retry

    # Save updated metadata
    save_metadata(metadata)

    if stocks_to_update:
        failed_codes = [stock[0] for stock in stocks_to_update]
        print(f"Failed to query price data for {len(failed_codes)} stocks after {iteration} iterations: {failed_codes}")
    else:
        print("Successfully queried price data for all stocks needing update.")


def query_data(data_type, stock_type, force=False, season_end="2025-12-31", adjust=""):
    """
    Main function to query either financial or price data incrementally

    Args:
        data_type: 'financial' or 'price'
        stock_type: Type of stocks to query
        force: If True, force query all stocks regardless of last update time
        season_end: End date for financial data standardization
        adjust: Price adjustment method ('qfq', 'hfq', or '')
    """
    # Get the stock list
    stocks_df = get_stock_list(stock_type)
    print(f"Loaded {len(stocks_df)} stocks for {stock_type}")

    if data_type.lower() == "financial":
        output_dir = "../data/input/financial-indicators/all"
        query_financial_data_incremental(stocks_df, output_dir, force=force, season_end=season_end)
    elif data_type.lower() == "price":
        output_dir = "../data/input/price-data/all"
        query_price_data_incremental(stocks_df, output_dir, force=force, adjust=adjust)
    else:
        raise ValueError(f"Unknown data type: {data_type}. Use 'financial' or 'price'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Query financial or price data incrementally for specified stock lists")
    parser.add_argument("--data_type", type=str, required=True,
                        choices=['financial', 'price'],
                        help="Type of data to query: 'financial' or 'price'")
    parser.add_argument("--stock_type", type=str, required=True,
                        choices=['hs300', 'zz500', 'hongli', 'honglidibo', 'portfolio', 'all'],
                        help="Type of stocks to query")
    parser.add_argument("--force", action="store_true",
                        help="Force query all stocks, ignoring last update time")
    parser.add_argument("--season_end", type=str, default='2025-12-31',
                        help="The end date of the season for financial data")
    parser.add_argument("--adjust", type=str, default="",
                        help="Price adjustment method: 'qfq', 'hfq', or '' for none")

    args = parser.parse_args()

    query_data(args.data_type, args.stock_type, args.force, args.season_end, args.adjust)