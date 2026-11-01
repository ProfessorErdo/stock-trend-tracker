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
from data_loader import (
    load_stock_pool,
    query_price_data,
    query_price_data_no_adjust,
    merge_price_files,
    query_financial_data,
)
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


def update_data(args, logger):
    """Update selected backtesting datasets without invoking the backtest."""
    stock_codes = load_stock_pool()["code"].tolist()
    fetch_data = args.fetch_data or args.update_all
    full_label = " (full re-download)" if args.full else ""

    if args.update_financial:
        logger.info(f"\n>>> Updating financial data only{full_label}...")
        query_financial_data(
            stock_codes,
            season_end=args.financial_season_end,
            full=args.full,
        )
        return

    if not fetch_data and not args.update_price:
        return

    if args.update_price:
        logger.info(f"\n>>> Updating price data only{full_label}...")
    else:
        logger.info(f"\n>>> Fetching all data{full_label}...")

    logger.info("\n[1] Updating adjusted price data...")
    query_price_data(
        stock_codes,
        start_date=args.price_start,
        full=args.full,
    )

    logger.info("\n[2] Updating non-adjusted price data...")
    query_price_data_no_adjust(
        stock_codes,
        start_date=args.price_start,
        full=args.full,
    )

    logger.info("\n[3] Merging price data...")
    merge_price_files(stock_codes)

    if fetch_data:
        logger.info("\n[4] Updating financial data...")
        query_financial_data(
            stock_codes,
            season_end=args.financial_season_end,
            full=args.full,
        )


def main():
    parser = argparse.ArgumentParser(description="选股策略回测系统")
    parser.add_argument("--fetch_data", action="store_true",
                        help="Download price/financial data (same as --update_all)")
    parser.add_argument("--update_price", action="store_true",
                        help="Download price data (skip financial)")
    parser.add_argument("--update_all", action="store_true",
                        help="Download all data (price + financial)")
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
                        help="Disable one-sided 1%% threshold-tail trimming (use raw quantiles)")
    parser.add_argument("--results_only", action="store_true",
                        help="Skip backtest, compute performance from saved intermediate results")
    parser.add_argument("--incremental", action="store_true",
                        help="Incremental backtest (auto-detect intermediate results)")
    parser.add_argument("--full", action="store_true",
                        help="Full data download (re-download everything, not incremental)")
    parser.add_argument("--update_financial", action="store_true",
                        help="Download financial data only; continue to backtest unless --update_only is set")
    parser.add_argument("--update_only", action="store_true",
                        help="Only update the selected data and exit without running a backtest")
    parser.add_argument("--financial_season_end", type=str,
                        default=config.FINANCIAL_SEASON_END,
                        help="Latest financial report date to include, YYYY-MM-DD")
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
                        help="Enable stop-loss: 15%% halve, 25%% liquidate")
    parser.add_argument("--stop_loss_half", type=float, default=None,
                        help="Half stop-loss drawdown threshold (default: 0.15)")
    parser.add_argument("--stop_loss_full", type=float, default=None,
                        help="Full stop-loss drawdown threshold (default: 0.25)")
    parser.add_argument("--filter_indicators", type=str, default=None,
                        help="Step 2 filter indicators, comma-separated: pe,pb  or  pb  or  pe,pb,pr (default: from config)")
    parser.add_argument("--latest_pools_only", action="store_true",
                        help="每个池子只用最新一期清单（当前成分股，含幸存者偏差；默认合并历史各期）")

    args = parser.parse_args()

    # Initialize logger
    logger = setup_logger("run_backtest", "backtest")

    # Apply CLI overrides
    if args.latest_pools_only:
        config.STOCK_POOL_LATEST_ONLY = True
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
        indicators = [x.strip() for x in args.filter_indicators.split(",") if x.strip()]
        unknown = [x for x in indicators if x not in {"pe", "pb", "pr"}]
        if unknown or not indicators:
            parser.error(
                "--filter_indicators 只接受 pe/pb/pr 的组合（ROE 固定为第 3 步，"
                f"不需要也不允许写进 Step 2）；收到: {args.filter_indicators!r}"
            )
        config.FILTER_INDICATORS = indicators

    data_update_requested = (
        args.update_financial
        or args.update_price
        or args.update_all
        or args.fetch_data
    )
    if args.update_only and not data_update_requested:
        parser.error("--update_only requires --update_financial, --update_price, or --update_all")
    if args.update_only and args.results_only:
        parser.error("--update_only and --results_only cannot be used together")

    # Run performance only mode
    if args.results_only:
        run_performance_only(logger)
        return

    if data_update_requested:
        config.ensure_dirs()
        update_data(args, logger)
        if args.update_only:
            logger.info("\n" + "=" * 60)
            logger.info("  Data Update Complete")
            logger.info("=" * 60)
            logger.info("  Backtest skipped because --update_only was specified.")
            return

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
    logger.info(f"  Stock pools: {len(config.STOCK_POOLS)} lists"
                + (" (latest snapshot only)" if config.STOCK_POOL_LATEST_ONLY
                   else " (all historical snapshots, merged)"))
    logger.info(f"  Rebalance frequency: {freq_label}")
    logger.info(f"  Ranking method: {rank_label}")
    filter_display = "+".join(ind.upper() for ind in config.FILTER_INDICATORS)
    logger.info(f"  Step 2 filter: {filter_display}")
    logger.info(f"  Valuation thresholds: PE<={config.PE_THRESHOLD}, PB<={config.PB_THRESHOLD}, PR<={config.PR_THRESHOLD}")
    logger.info(f"  ROE threshold: >{config.ROE_THRESHOLD} quantile")
    logger.info(f"  Max positions: {config.MAX_POSITIONS}")
    logger.info(
        f"  Threshold trimming: "
        f"{'Off' if not config.WINSORIZE_ENABLED else 'On (adverse 1% tail)'}"
    )
    if config.STOP_LOSS_ENABLED:
        half_pct = f"{config.STOP_LOSS_HALF_DRAWDOWN:.0%}"
        full_pct = f"{config.STOP_LOSS_FULL_DRAWDOWN:.0%}"
        logger.info(f"  Stop-loss: On ({half_pct}减半 / {full_pct}清仓)")
    else:
        logger.info(f"  Stop-loss: Off")
    logger.info("=" * 60)

    # Ensure output directories exist
    config.ensure_dirs()

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
    logger.info(f"  Update all only:      ./run.sh --update_all --update_only")
    logger.info(f"  Financial only:       ./run.sh --update_financial --update_only")
    logger.info(f"  Custom thresholds:    ./run.sh --pe_threshold 0.3 --pb_threshold 0.3")
    logger.info(f"  Fewer positions:      ./run.sh --max_positions 5")
    logger.info(f"  Annual, PB rank:      ./run.sh --frequency annual --ranking pb")
    logger.info(f"  Annual+Q3, PE rank:   ./run.sh --frequency annual_q3 --ranking pe")
    logger.info(f"  Pure PB ranking:      ./run.sh --ranking pure_pb")
    logger.info(f"  PB-only filter:       ./run.sh --filter_indicators pb --ranking pb")
    logger.info(f"  PE+ROE filter:        ./run.sh --filter_indicators pe --ranking pb")
    logger.info(f"  Comparison scripts:")
    logger.info(f"    python compare_ranking_methods.py        (4 rankings, quarterly)")
    logger.info(f"    python compare_rebalance_frequency.py    (annual vs semi-annual, PB)")
    logger.info(f"    python compare_frequency_ranking.py      (2 freqs × 5 rankings)")
    logger.info(f"    python analyze_selection.py quarterly    (selection step analysis)")
    logger.info(f"    python test_thresholds.py                (threshold parameter sweep)")


if __name__ == "__main__":
    main()
