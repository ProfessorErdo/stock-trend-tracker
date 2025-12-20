#!/bin/bash
python calculation_and_visualization.py --price_date 20251219 --step visualize --threshold 0.25
python calculation_and_visualization.py --price_date 20251219 --step visualize --threshold 0.26

# PRICE_DATE=$(date +"%Y%m%d")

# python calculation_and_visualization.py --price_date $PRICE_DATE --step visualize --threshold 0.25
# python calculation_and_visualization.py --price_date $PRICE_DATE --step visualize --threshold 0.26