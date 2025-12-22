#!/bin/bash

# set the querying date for price
PRICE_DATE=$(date +"%Y%m%d")

# query the financial date when fiancial report released which means 4 times a year and change the season end date to the month end of the financial report
# python querying_data.py --data_type financial --stock_type honglidibo --season_end 2026-04-30 --query_date $PRICE_DATE
# python querying_data.py --data_type financial --stock_type hongli --season_end 2026-04-30 -- query_date $PRICE_DATE
# python querying_data.py --data_type financial --stock_type hs300 --season_end 2026-04-30 -- query_date $PRICE_DATE
# python querying_data.py --data_type financial --stock_type zz500 --season_end 2026-04-30 -- query_date $PRICE_DATE

# query the price data
python querying_data.py --data_type price --stock_type honglidibo --season_end 2025-12-31 --query_date $PRICE_DATE
python querying_data.py --data_type price --stock_type hongli --season_end 2025-12-31 --query_date $PRICE_DATE
python querying_data.py --data_type price --stock_type hs300 --season_end 2025-12-31 --query_date $PRICE_DATE
python querying_data.py --data_type price --stock_type zz500 --season_end 2025-12-31 --query_date $PRICE_DATE
python querying_data.py --data_type price --stock_type portfolio --season_end 2025-12-31 --query_date $PRICE_DATE

# calcualte the stock value and visualize the stocks meeting the criteria
python calculation_and_visualization.py --price_date $PRICE_DATE --step all --threshold 0.26

# send the email with the results
python send_emails.py --price_date $PRICE_DATE