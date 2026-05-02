"""
回测主运行入口
整合各模块，执行完整回测流程
"""

import sys
import os
import argparse
import pickle
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from data_loader import load_stock_pool, query_price_data, query_financial_data
from backtest_engine import run_backtest, save_results
from performance import calculate_performance, save_performance_summary
from visualizer import generate_all_visualizations


INTERMEDIATE_RESULTS = os.path.join(config.DATA_OUTPUT_DIR, "intermediate.pkl")


def run_performance_only():
    """Load saved intermediate results, compute performance and visualizations only"""
    if not os.path.exists(INTERMEDIATE_RESULTS):
        print(f"Error: intermediate results not found at {INTERMEDIATE_RESULTS}")
        print("Run with --fetch_data or without --results_only first.")
        return

    print(f"\n>>> Loading saved intermediate results...")
    with open(INTERMEDIATE_RESULTS, "rb") as f:
        result = pickle.load(f)

    print(f"  Trades: {len(result['trade_records'])}")
    print(f"  Holdings: {len(result['holding_snapshots'])}")
    print(f"  Equity curve days: {len(result['equity_curve'])}")

    print("\n>>> Phase 3: Computing performance")
    performance = calculate_performance(
        result['equity_curve'],
        result['cutoff_dates'],
        result['trade_records']
    )

    print("\n>>> Phase 4: Generating visualizations")
    generate_all_visualizations(performance, result['equity_curve'])

    print(f"\nResults saved to:")
    print(f"  Holdings: {config.HOLDINGS_DIR}/")
    print(f"  Trades: {config.TRADES_DIR}/")
    print(f"  Performance: {config.PERFORMANCE_DIR}/")
    print(f"  Charts: {config.CHARTS_DIR}/")


def main():
    parser = argparse.ArgumentParser(description="选股策略回测系统")
    parser.add_argument("--fetch_data", action="store_true",
                        help="Download price/financial data, then backtest (same as --update_all)")
    parser.add_argument("--update_price", action="store_true",
                        help="Download price data only (skip financial), then backtest")
    parser.add_argument("--update_all", action="store_true",
                        help="Download all data (price + financial), then backtest")
    parser.add_argument("--start_date", type=str, default=config.START_DATE,
                        help="Backtest start date, YYYY-MM-DD")
    parser.add_argument("--end_date", type=str, default=None,
                        help="Backtest end date, YYYY-MM-DD")
    parser.add_argument("--price_start", type=str, default="20150101",
                        help="Price data start date, YYYYMMDD")
    parser.add_argument("--frequency", type=str, default=None,
                        help="Rebalance frequency: 'weekly' or 'monthly' (default from config)")
    parser.add_argument("--no_winsorize", action="store_true",
                        help="Disable 1%/99% winsorization (use raw quantiles)")
    parser.add_argument("--results_only", action="store_true",
                        help="Skip backtest, compute performance from saved intermediate results")

    args = parser.parse_args()

    # Run performance only mode
    if args.results_only:
        run_performance_only()
        return

    # Compatibility: --fetch_data == --update_all
    fetch_data = args.fetch_data or args.update_all
    update_price_only = args.update_price

    freq_display = args.frequency or config.REBALANCE_FREQUENCY
    if freq_display == "monthly":
        freq_label = "Monthly"
    elif freq_display == "quarterly":
        freq_label = "Quarterly"
    else:
        freq_label = "Weekly"

    # Apply winsorize override
    if args.no_winsorize:
        config.WINSORIZE_ENABLED = False

    print("=" * 60)
    print("  Stock Selection Strategy Backtest v1.0")
    print("=" * 60)
    print(f"  Backtest period: {args.start_date} ~ {args.end_date or 'latest'}")
    print(f"  Initial capital: {config.INITIAL_CAPITAL:,.0f} RMB")
    print(f"  Stock pools: {len(config.STOCK_POOLS)} lists")
    print(f"  Rebalance frequency: {freq_label}")
    print(f"  Winsorization: {'Off' if not config.WINSORIZE_ENABLED else 'On (1%/99%)'}")
    print("=" * 60)

    # Ensure output directories exist
    config.ensure_dirs()

    # Fetch data if needed
    if fetch_data or update_price_only:
        stock_df = load_stock_pool()
        stock_codes = stock_df['code'].tolist()

        if update_price_only:
            print("\n>>> Phase 1: Updating price data only...")
            print("\n[1a] Updating price data...")
            query_price_data(stock_codes, start_date=args.price_start)
        else:
            print("\n>>> Phase 1: Fetching data")
            print("\n[1a] Downloading price data...")
            query_price_data(stock_codes, start_date=args.price_start)

            print("\n[1b] Downloading financial data...")
            query_financial_data(stock_codes)

    # Run backtest
    print("\n>>> Phase 2: Running backtest")

    # Auto-incremental mode: if intermediate results exist, only run new dates
    incremental_flag = INTERMEDIATE_RESULTS if os.path.exists(INTERMEDIATE_RESULTS) else None

    result = run_backtest(args.start_date, args.end_date, incremental_from=incremental_flag, frequency=args.frequency)

    if result is None:
        print("Backtest failed, aborting.")
        return

    # Save intermediate results (avoid re-running expensive steps on errors)
    print("\n>>> Saving intermediate results...")
    os.makedirs(config.DATA_OUTPUT_DIR, exist_ok=True)
    with open(INTERMEDIATE_RESULTS, "wb") as f:
        pickle.dump(result, f)
    print(f"  Saved to {INTERMEDIATE_RESULTS}")

    # Save standard output (holdings, trades, equity curve CSV)
    save_results(result)

    # Compute performance
    print("\n>>> Phase 3: Computing performance")
    performance = calculate_performance(
        result['equity_curve'],
        result['cutoff_dates'],
        result['trade_records']
    )

    # Generate visualizations
    print("\n>>> Phase 4: Generating visualizations")
    generate_all_visualizations(performance, result['equity_curve'])

    print("\n" + "=" * 60)
    print("  Backtest Complete!")
    print("=" * 60)
    print(f"\nResults saved to:")
    print(f"  Holdings: {config.HOLDINGS_DIR}/")
    print(f"  Trades: {config.TRADES_DIR}/")
    print(f"  Performance: {config.PERFORMANCE_DIR}/")
    print(f"  Charts: {config.CHARTS_DIR}/")
    print(f"\nIntermediate results: {INTERMEDIATE_RESULTS}")
    print(f"\nCommon commands:")
    print(f"  Performance only:  ./run.sh --results_only")
    print(f"  Update price + backtest:  ./run.sh --update_price")
    print(f"  Update all + backtest:    ./run.sh --update_all")


if __name__ == "__main__":
    main()
