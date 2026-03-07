#!/bin/bash

# ============================================================================
# Stock Trend Tracker - Incremental Data Pipeline
# ============================================================================
# This script runs the incremental data pipeline:
#   1. Query financial data (monthly basis - only if not updated in 30+ days)
#   2. Query price data (daily basis - only if not updated today)
#   3. Calculate stock valuations and visualize best stocks
#   4. Send email with results
# ============================================================================

# ============================================================================
# Command Line Parameters for query_data_new.py
# ============================================================================
# --data_type    : Type of data to query
#                  - 'financial': Financial indicators (EPS, BPS, ROE, etc.)
#                  - 'price'    : Daily stock price data (OHLC)
#
# --stock_type   : Stock list to query
#                  - 'hs300'     : CSI 300 stocks
#                  - 'zz500'     : CSI 500 stocks
#                  - 'hongli'    : Hongli stock list
#                  - 'honglidibo': Honglidibo stock list
#                  - 'portfolio' : Personal portfolio stocks
#                  - 'all'       : All stocks from full list
#
# --force        : (Optional) Force query all stocks, ignoring last update time
#                  - Without this flag: Only query stocks that need updating
#                  - With this flag: Query all stocks regardless of last update
#
# --season_end   : (Optional, for financial data) End date for financial data
#                  - Format: 'YYYY-MM-DD'
#                  - Default: '2025-12-31'
#                  - Used to standardize report dates
#
# --adjust       : (Optional, for price data) Price adjustment method
#                  - ''    : No adjustment (raw prices)
#                  - 'qfq' : Forward adjustment (前复权)
#                  - 'hfq' : Backward adjustment (后复权)
#                  - Default: '' (no adjustment)
#
# ============================================================================
# Command Line Parameters for calculation_and_visualization_new.py
# ============================================================================
# --step         : Which step to run
#                  - 'value'    : Only calculate stock valuations
#                  - 'visualize': Only visualize best stocks (requires existing valuations)
#                  - 'all'      : Run both steps (default)
#
# --threshold    : Quantile threshold for filtering stocks
#                  - Range: 0.0 to 1.0
#                  - Default: 0.26 (26th percentile)
#                  - Lower value = stricter filtering (fewer stocks selected)
#                  - Filters: PE, PB, PR < threshold percentile, ROE > (1-threshold) percentile
#
# ============================================================================
# Command Line Parameters for send_emails_new.py
# ============================================================================
# --date         : Date for image folder
#                  - Format: 'YYYYMMDD'
#                  - Default: Today's date
#                  - Specifies which img/{date} folder to attach
# ============================================================================


# ============================================================================
# STEP 1: Query Financial Data (Monthly - only if not updated in 30+ days)
# ============================================================================
# Financial data is queried monthly. The script automatically checks metadata
# and only queries stocks that haven't been updated in 30+ days.
# Uncomment the lines below to run financial data queries.

python query_data_new.py --data_type financial --stock_type honglidibo --season_end 2026-12-31
python query_data_new.py --data_type financial --stock_type hongli --season_end 2026-12-31
python query_data_new.py --data_type financial --stock_type hs300 --season_end 2026-12-31
python query_data_new.py --data_type financial --stock_type zz500 --season_end 2026-12-31

# Force query all financial data (ignore last update time):
# python query_data_new.py --data_type financial --stock_type hs300 --force


# ============================================================================
# STEP 2: Query Price Data (Daily - only if not updated today)
# ============================================================================
# Price data is queried daily. The script automatically checks metadata
# and only queries stocks that haven't been updated today.
# Incremental updates append new data to existing files.

python query_data_new.py --data_type price --stock_type honglidibo
python query_data_new.py --data_type price --stock_type hongli
python query_data_new.py --data_type price --stock_type hs300
python query_data_new.py --data_type price --stock_type zz500
python query_data_new.py --data_type price --stock_type portfolio

# Query all stocks:
# python query_data_new.py --data_type price --stock_type all

# Force query all price data (ignore last update time):
# python query_data_new.py --data_type price --stock_type hs300 --force

# Query with price adjustment (for backtesting):
# python query_data_new.py --data_type price --stock_type honglidibo --adjust hfq
# python query_data_new.py --data_type price --stock_type hongli --adjust hfq
# python query_data_new.py --data_type price --stock_type hs300 --adjust hfq
# python query_data_new.py --data_type price --stock_type zz500 --adjust hfq
# python query_data_new.py --data_type price --stock_type portfolio --adjust hfq


# ============================================================================
# STEP 3: Calculate Stock Valuations and Visualize Best Stocks
# ============================================================================
# This step:
#   1. Merges price data with financial data
#   2. Calculates PE, PB, PR ratios
#   3. Filters stocks based on threshold
#   4. Generates distribution plots for selected stocks

python calculation_and_visualization_new.py --step all --threshold 0.26

# Run only valuation calculation:
# python calculation_and_visualization_new.py --step value

# Run only visualization (requires existing valuation files):
# python calculation_and_visualization_new.py --step visualize --threshold 0.26

# Use stricter threshold (fewer stocks selected):
# python calculation_and_visualization_new.py --step all --threshold 0.20

# Use looser threshold (more stocks selected):
# python calculation_and_visualization_new.py --step all --threshold 0.35


# ============================================================================
# STEP 4: Send Email with Results
# ============================================================================
# Sends an email with:
#   - Summary of selected stocks
#   - Distribution plots as inline images

python send_emails_new.py

# Send email for a specific date:
# python send_emails_new.py --date 20250307


echo "Pipeline completed successfully!"