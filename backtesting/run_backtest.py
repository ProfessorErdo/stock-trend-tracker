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
from log_util import setup_logger


INTERMEDIATE_RESULTS = os.path.join(config.DATA_OUTPUT_DIR, "intermediate.pkl")


def run_performance_only(logger):
    """Load saved intermediate results, compute performance and visualizations only"""
    if not os.path.exists(INTERMEDIATE_RESULTS):
        logger.error(f"Intermediate results not found at {INTERMEDIATE_RESULTS}")
        logger.error("Run with --fetch_data or without --results_only first.")
        return

    logger.info(f"\n>>> Loading saved intermediate results...")
    with open(INTERMEDIATE_RESULTS, "rb") as f:
        result = pickle.load(f)

    logger.info(f"  Trades: {len(result['trade_records'])}")
    logger.info(f"  Holdings: {len(result['holding_snapshots'])}")
    logger.info(f"  Equity curve days: {len(result['equity_curve'])}")

    logger.info("\n>>> Phase 3: Computing performance")
    performance = calculate_performance(
        result['equity_curve'],
        result['cutoff_dates'],
        result['trade_records']
    )

    logger.info("\n>>> Phase 4: Generating visualizations")
    generate_all_visualizations(performance, result['equity_curve'], logger=logger)

    logger.info(f"\nResults saved to:")
    logger.info(f"  Holdings: {config.HOLDINGS_DIR}/")
    logger.info(f"  Trades: {config.TRADES_DIR}/")
    logger.info(f"  Performance: {config.PERFORMANCE_DIR}/")
    logger.info(f"  Charts: {config.CHARTS_DIR}/")


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
                        help="Rebalance frequency: weekly/monthly/quarterly/annual/annual_q3/mid_year/q3")
    parser.add_argument("--ranking", type=str, default="pb",
                        help="Ranking method when filtered > 10: pe/pb/pr/roe/pure_pb (default: pb)")
    parser.add_argument("--no_winsorize", action="store_true",
                        help="Disable 1%%/99%% winsorization (use raw quantiles)")
    parser.add_argument("--results_only", action="store_true",
                        help="Skip backtest, compute performance from saved intermediate results")
    parser.add_argument("--incremental", action="store_true",
                        help="Incremental backtest (auto-detect intermediate results)")
    parser.add_argument("--full", action="store_true",
                        help="Full data download (re-download everything, not incremental)")
    parser.add_argument("--update_financial", action="store_true",
                        help="Download financial data only (skip already downloaded)")
    parser.add_argument("--pe_threshold", type=float, default=None,
                        help="PE quantile threshold (default: from config)")
    parser.add_argument("--pb_threshold", type=float, default=None,
                        help="PB quantile threshold (default: from config)")
    parser.add_argument("--pr_threshold", type=float, default=None,
                        help="PR quantile threshold (default: from config)")
    parser.add_argument("--roe_threshold", type=float, default=None,
                        help="ROE quantile threshold (default: from config)")
    parser.add_argument("--max_positions", type=int, default=None,
                        help="Max positions in portfolio (default: from config)")
    parser.add_argument("--stop_loss", action="store_true",
                        help="Enable stop-loss: 15% halve, 25% liquidate")
    parser.add_argument("--stop_loss_half", type=float, default=None,
                        help="Half stop-loss drawdown threshold (default: 0.15)")
    parser.add_argument("--stop_loss_full", type=float, default=None,
                        help="Full stop-loss drawdown threshold (default: 0.25)")
    parser.add_argument("--filter_indicators", type=str, default=None,
                        help="Step 2 filter indicators, comma-separated: pe,pb  or  pb  or  pe,pb,pr (default: from config)")

    args = parser.parse_args()

    # Initialize logger
    logger = setup_logger("run_backtest", "backtest")

    # Apply CLI overrides
    if args.pe_threshold is not None:
        config.PE_THRESHOLD = args.pe_threshold
    if args.pb_threshold is not None:
        config.PB_THRESHOLD = args.pb_threshold
    if args.pr_threshold is not None:
        config.PR_THRESHOLD = args.pr_threshold
    if args.roe_threshold is not None:
        config.ROE_THRESHOLD = args.roe_threshold
    if args.max_positions is not None:
        config.MAX_POSITIONS = args.max_positions
    if args.filter_indicators is not None:
        config.FILTER_INDICATORS = [x.strip() for x in args.filter_indicators.split(",")]

    # Run performance only mode
    if args.results_only:
        run_performance_only(logger)
        return

    # Compatibility: --fetch_data == --update_all
    fetch_data = args.fetch_data or args.update_all
    update_price_only = args.update_price

    freq_display = args.frequency or config.REBALANCE_FREQUENCY
    freq_labels = {
        "weekly": "Weekly", "monthly": "Monthly", "quarterly": "Quarterly",
        "annual": "Annual", "annual_q3": "Annual+Q3",
        "mid_year": "Mid-Year (Aug/Sep)", "q3": "Q3 (Oct/Nov)",
    }
    freq_label = freq_labels.get(freq_display, freq_display)

    rank_labels = {
        "pe": "PE-lowest", "pb": "PB-lowest", "pr": "PR-lowest",
        "roe": "ROE-highest", "pure_pb": "Pure-PB-lowest",
    }
    rank_label = rank_labels.get(args.ranking, args.ranking)

    # Apply stop-loss override
    if args.stop_loss:
        config.STOP_LOSS_ENABLED = True
    if args.stop_loss_half is not None:
        config.STOP_LOSS_HALF_DRAWDOWN = args.stop_loss_half
    if args.stop_loss_full is not None:
        config.STOP_LOSS_FULL_DRAWDOWN = args.stop_loss_full

    # Apply winsorize override
    if args.no_winsorize:
        config.WINSORIZE_ENABLED = False

    logger.info("=" * 60)
    logger.info("  Stock Selection Strategy Backtest v2.0")
    logger.info("=" * 60)
    logger.info(f"  Backtest period: {args.start_date} ~ {args.end_date or 'latest'}")
    logger.info(f"  Initial capital: {config.INITIAL_CAPITAL:,.0f} RMB")
    logger.info(f"  Stock pools: {len(config.STOCK_POOLS)} lists")
    logger.info(f"  Rebalance frequency: {freq_label}")
    logger.info(f"  Ranking method: {rank_label}")
    filter_display = "+".join(ind.upper() for ind in config.FILTER_INDICATORS)
    logger.info(f"  Step 2 filter: {filter_display}")
    logger.info(f"  Valuation thresholds: PE<={config.PE_THRESHOLD}, PB<={config.PB_THRESHOLD}, PR<={config.PR_THRESHOLD}")
    logger.info(f"  ROE threshold: >{config.ROE_THRESHOLD} quantile")
    logger.info(f"  Max positions: {config.MAX_POSITIONS}")
    logger.info(f"  Winsorization: {'Off' if not config.WINSORIZE_ENABLED else 'On (1%/99%)'}")
    if config.STOP_LOSS_ENABLED:
        half_pct = f"{config.STOP_LOSS_HALF_DRAWDOWN:.0%}"
        full_pct = f"{config.STOP_LOSS_FULL_DRAWDOWN:.0%}"
        logger.info(f"  Stop-loss: On ({half_pct}减半 / {full_pct}清仓)")
    else:
        logger.info(f"  Stop-loss: Off")
    logger.info("=" * 60)

    # Ensure output directories exist
    config.ensure_dirs()

    # Handle financial-only data update
    if args.update_financial:
        logger.info("\n>>> Phase 1: Updating financial data only...")
        stock_df = load_stock_pool()
        stock_codes = stock_df['code'].tolist()
        query_financial_data(stock_codes, full=args.full)

    # Fetch data if needed
    elif fetch_data or update_price_only:
        stock_df = load_stock_pool()
        stock_codes = stock_df['code'].tolist()

        full_label = " (full re-download)" if args.full else ""
        if update_price_only:
            logger.info(f"\n>>> Phase 1: Updating price data only{full_label}...")
            logger.info("\n[1a] Updating price data...")
            query_price_data(stock_codes, start_date=args.price_start, full=args.full)
        else:
            logger.info(f"\n>>> Phase 1: Fetching data{full_label}")
            logger.info("\n[1a] Downloading price data...")
            query_price_data(stock_codes, start_date=args.price_start, full=args.full)

            logger.info("\n[1b] Downloading financial data...")
            query_financial_data(stock_codes, full=args.full)

    # Run backtest
    logger.info("\n>>> Phase 2: Running backtest")

    # Only use incremental mode when explicitly requested via --incremental
    if args.incremental:
        if not os.path.exists(INTERMEDIATE_RESULTS):
            logger.error("--incremental specified but no intermediate results found.")
            exit(1)
        incremental_flag = INTERMEDIATE_RESULTS
    else:
        incremental_flag = None
        # Clean up old intermediate results so a full backtest starts fresh
        if os.path.exists(INTERMEDIATE_RESULTS):
            os.remove(INTERMEDIATE_RESULTS)
            logger.info("  Removed old intermediate results for full backtest")

    result = run_backtest(
        args.start_date, args.end_date,
        incremental_from=incremental_flag,
        frequency=args.frequency,
        ranking_method=args.ranking,
        filter_indicators=config.FILTER_INDICATORS,
    )

    if result is None:
        logger.error("Backtest failed, aborting.")
        return

    # Save intermediate results (avoid re-running expensive steps on errors)
    logger.info("\n>>> Saving intermediate results...")
    os.makedirs(config.DATA_OUTPUT_DIR, exist_ok=True)
    with open(INTERMEDIATE_RESULTS, "wb") as f:
        pickle.dump(result, f)
    logger.info(f"  Saved to {INTERMEDIATE_RESULTS}")

    # Save standard output (holdings, trades, equity curve CSV)
    save_results(result)

    # Compute performance
    logger.info("\n>>> Phase 3: Computing performance")
    performance = calculate_performance(
        result['equity_curve'],
        result['cutoff_dates'],
        result['trade_records']
    )

    # Generate visualizations
    logger.info("\n>>> Phase 4: Generating visualizations")
    generate_all_visualizations(performance, result['equity_curve'], logger=logger)

    logger.info("\n" + "=" * 60)
    logger.info("  Backtest Complete!")
    logger.info("=" * 60)
    logger.info(f"\nResults saved to:")
    logger.info(f"  Holdings: {config.HOLDINGS_DIR}/")
    logger.info(f"  Trades: {config.TRADES_DIR}/")
    logger.info(f"  Performance: {config.PERFORMANCE_DIR}/")
    logger.info(f"  Charts: {config.CHARTS_DIR}/")
    logger.info(f"\nIntermediate results: {INTERMEDIATE_RESULTS}")
    logger.info(f"\nCommon commands:")
    logger.info(f"  Performance only:     ./run.sh --results_only")
    logger.info(f"  Update price + run:   ./run.sh --update_price")
    logger.info(f"  Full re-download:     ./run.sh --update_all --full")
    logger.info(f"  Financial only:       ./run.sh --update_financial")
    logger.info(f"  Custom thresholds:    ./run.sh --pe_threshold 0.3 --pb_threshold 0.3")
    logger.info(f"  Fewer positions:      ./run.sh --max_positions 5")
    logger.info(f"  Annual, PB rank:      ./run.sh --frequency annual --ranking pb")
    logger.info(f"  Annual+Q3, PE rank:   ./run.sh --frequency annual_q3 --ranking pe")
    logger.info(f"  Pure PB ranking:      ./run.sh --ranking pure_pb")
    logger.info(f"  PB-only filter:       ./run.sh --filter_indicators pb --ranking pb")
    logger.info(f"  PE+ROE filter:        ./run.sh --filter_indicators pe,roe --ranking pb")
    logger.info(f"  Comparison scripts:")
    logger.info(f"    python compare_ranking_methods.py        (4 rankings, quarterly)")
    logger.info(f"    python compare_rebalance_frequency.py    (annual vs semi-annual, PB)")
    logger.info(f"    python compare_frequency_ranking.py      (2 freqs × 5 rankings)")
    logger.info(f"    python analyze_selection.py quarterly    (selection step analysis)")
    logger.info(f"    python test_thresholds.py                (threshold parameter sweep)")


if __name__ == "__main__":
    main()
