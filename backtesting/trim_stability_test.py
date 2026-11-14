"""
年度调仓阈值裁尾稳定性测试。

固定股票池、选股指标、排名方式和调仓频率，只改变分位阈值的不利尾部
裁尾比例，并把每个参数的结果保存到独立目录。同时输出 1%/2%/3% 在
每个年度截面的目标前五名重合情况。
"""

import argparse
import gc
import os
import pickle
import sys
from datetime import datetime

import pandas as pd
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from backtest_engine import run_backtest
from data_loader import load_stock_pool
from log_util import setup_logger
from performance import calculate_performance
from stock_selector import rank_and_limit, select_stocks


DEFAULT_TRIMS = [0.0, 0.005, 0.01, 0.015, 0.02, 0.025, 0.03]
SELECTION_TRIMS = {0.01, 0.02, 0.03}


def trim_slug(trim: float) -> str:
    return f"trim_{trim * 100:g}pct"


def save_trim_result(output_dir: str, trim: float, result: dict, performance: dict):
    os.makedirs(output_dir, exist_ok=True)

    snapshots = [
        snapshot for snapshot in result["holding_snapshots"] if not snapshot.empty
    ]
    if snapshots:
        holdings = pd.concat(snapshots, ignore_index=True)
    else:
        holdings = pd.DataFrame(
            columns=[
                "rebalance_date",
                "stock_code",
                "shares",
                "cost_price",
                "current_price",
                "market_value",
                "weight",
            ]
        )
    holdings.to_csv(os.path.join(output_dir, "holdings_summary.csv"), index=False)

    trades = pd.DataFrame(result["trade_records"])
    trades.to_csv(os.path.join(output_dir, "trades_record.csv"), index=False)
    result["equity_curve"].to_csv(
        os.path.join(output_dir, "equity_curve.csv"), index=False
    )
    performance["annual_returns"].to_csv(
        os.path.join(output_dir, "annual_returns.csv"), index=False
    )

    summary = {
        "metric": [
            "Trading Days",
            "Initial Capital",
            "Final Equity",
            "Cumulative Return",
            "Annual Return",
            "Annual Volatility",
            "Sharpe Ratio",
            "Max Drawdown",
            "Max Drawdown Days",
            "Recovery Days",
            "Win Rate",
            "Profit/Loss Ratio",
            "Average Weekly Turnover",
            "Benchmark Cumulative Return",
            "Benchmark Annual Return",
            "Excess Return",
            "Tracking Error",
            "Information Ratio",
            "Pool Size",
            "Threshold Trim Ratio",
            "Rebalance Frequency",
            "Filter Indicators",
            "Ranking Method",
            "Max Positions",
        ],
        "value": [
            performance["trading_days"],
            performance["initial_capital"],
            performance["final_equity"],
            performance["cumulative_return"],
            performance["annual_return"],
            performance["annual_volatility"],
            performance["sharpe_ratio"],
            performance["max_drawdown"],
            performance["max_drawdown_duration_days"],
            performance["recovery_days"],
            performance["win_rate"],
            performance["profit_loss_ratio"],
            performance["avg_weekly_turnover"],
            performance["benchmark_cumulative_return"],
            performance["benchmark_annual_return"],
            performance["excess_return"],
            performance["tracking_error"],
            performance["information_ratio"],
            len(load_stock_pool()),
            trim,
            "annual",
            "+".join(config.FILTER_INDICATORS),
            "pb",
            config.MAX_POSITIONS,
        ],
    }
    pd.DataFrame(summary).to_csv(
        os.path.join(output_dir, "performance_summary.csv"), index=False
    )


def select_top_five(result: dict, stock_codes: list, trim: float) -> dict:
    config.WINSORIZE_ENABLED = True
    config.THRESHOLD_TRIM_RATIO = trim
    config.FILTER_INDICATORS = ["pe", "pb", "pr"]
    config.MAX_POSITIONS = 5

    selections = {}
    for cutoff in tqdm(result["cutoff_dates"], desc=f"Selecting top 5 @ {trim:.1%}"):
        selected, valuations = select_stocks(
            stock_codes,
            cutoff,
            price_cache=result["price_cache"],
            filter_indicators=config.FILTER_INDICATORS,
        )
        picks = rank_and_limit(
            selected,
            valuations,
            config.MAX_POSITIONS,
            ranking_method="pb",
        )
        if picks:
            selections[pd.Timestamp(cutoff)] = picks
    return selections


def compare_selections(selections: dict) -> pd.DataFrame:
    labels = ("1pct", "2pct", "3pct")
    rows = []
    for cutoff in sorted(selections[labels[0]]):
        picks = {
            label: set(selections[label].get(cutoff, []))
            for label in labels
        }
        overlap_1_2 = len(picks["1pct"] & picks["2pct"])
        overlap_1_3 = len(picks["1pct"] & picks["3pct"])
        overlap_2_3 = len(picks["2pct"] & picks["3pct"])
        rows.append(
            {
                "cutoff": cutoff.date(),
                "top5_1pct": ",".join(selections["1pct"][cutoff]),
                "top5_2pct": ",".join(selections["2pct"][cutoff]),
                "top5_3pct": ",".join(selections["3pct"][cutoff]),
                "overlap_1pct_2pct": overlap_1_2,
                "overlap_1pct_3pct": overlap_1_3,
                "overlap_2pct_3pct": overlap_2_3,
                "changed_1pct_to_2pct": len(picks["1pct"]) - overlap_1_2,
                "changed_1pct_to_3pct": len(picks["1pct"]) - overlap_1_3,
                "changed_2pct_to_3pct": len(picks["2pct"]) - overlap_2_3,
                "only_in_1pct_vs_2pct": ",".join(
                    sorted(picks["1pct"] - picks["2pct"])
                ),
                "only_in_2pct_vs_1pct": ",".join(
                    sorted(picks["2pct"] - picks["1pct"])
                ),
                "only_in_1pct_vs_3pct": ",".join(
                    sorted(picks["1pct"] - picks["3pct"])
                ),
                "only_in_3pct_vs_1pct": ",".join(
                    sorted(picks["3pct"] - picks["1pct"])
                ),
            }
        )
    return pd.DataFrame(rows)


def selection_summary(comparison: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for pair, col in (
        ("1% vs 2%", "overlap_1pct_2pct"),
        ("1% vs 3%", "overlap_1pct_3pct"),
        ("2% vs 3%", "overlap_2pct_3pct"),
    ):
        values = comparison[col]
        rows.append(
            {
                "comparison": pair,
                "years": len(values),
                "mean_overlap": values.mean(),
                "median_overlap": values.median(),
                "min_overlap": values.min(),
                "max_overlap": values.max(),
                "years_overlap_ge_4": int((values >= 4).sum()),
                "years_overlap_ge_3": int((values >= 3).sum()),
                "years_overlap_lt_3": int((values < 3).sum()),
            }
        )
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        default=None,
        help="输出根目录；默认在 data/processed/backtesting 下新建带时间戳目录",
    )
    parser.add_argument(
        "--no-selection-compare",
        action="store_true",
        help="跳过 1%/2%/3% 前五名重合分析",
    )
    args = parser.parse_args()

    logger = setup_logger("trim_stability_test", "trim_stability")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = args.output_root or os.path.join(
        config.DATA_OUTPUT_DIR, f"trim_stability_{timestamp}"
    )
    os.makedirs(output_root, exist_ok=True)

    config.WINSORIZE_ENABLED = True
    config.FILTER_INDICATORS = ["pe", "pb", "pr"]
    config.REBALANCE_FREQUENCY = "annual"
    config.MAX_POSITIONS = 5
    config.STOP_LOSS_ENABLED = False

    pool = load_stock_pool()
    stock_codes = pool["code"].tolist()
    logger.info(
        "Fixed test configuration: pool=%d, frequency=annual, ranking=pb, "
        "filters=%s, max_positions=%d",
        len(stock_codes),
        "+".join(config.FILTER_INDICATORS),
        config.MAX_POSITIONS,
    )

    parameter_rows = []
    annual_returns = []
    selections = {}

    for trim in DEFAULT_TRIMS:
        logger.info("\n%s", "=" * 72)
        logger.info("Running threshold trim %.1f%%", trim * 100)
        logger.info("%s", "=" * 72)
        config.THRESHOLD_TRIM_RATIO = trim
        config.WINSORIZE_ENABLED = True

        result = run_backtest(
            start_date=config.START_DATE,
            end_date=None,
            frequency="annual",
            ranking_method="pb",
            filter_indicators=config.FILTER_INDICATORS,
        )
        if result is None:
            raise RuntimeError(f"Backtest returned no result for trim={trim}")

        performance = calculate_performance(
            result["equity_curve"],
            result["cutoff_dates"],
            result["trade_records"],
        )
        trim_dir = os.path.join(output_root, trim_slug(trim))
        save_trim_result(trim_dir, trim, result, performance)

        parameter_rows.append(
            {
                "trim_ratio": trim,
                "annual_return": performance["annual_return"],
                "cumulative_return": performance["cumulative_return"],
                "annual_volatility": performance["annual_volatility"],
                "sharpe_ratio": performance["sharpe_ratio"],
                "max_drawdown": performance["max_drawdown"],
                "max_drawdown_days": performance["max_drawdown_duration_days"],
                "final_equity": performance["final_equity"],
                "win_rate": performance["win_rate"],
                "profit_loss_ratio": performance["profit_loss_ratio"],
            }
        )
        for _, row in performance["annual_returns"].iterrows():
            annual_returns.append(
                {
                    "trim_ratio": trim,
                    "year": int(row["year"]),
                    "strategy_return": row["strategy_return"],
                    "benchmark_return": row["benchmark_return"],
                    "excess_return": row["excess_return"],
                }
            )

        if not args.no_selection_compare and trim in SELECTION_TRIMS:
            label = f"{trim * 100:g}pct"
            selections[label] = select_top_five(result, stock_codes, trim)

        logger.info(
            "Completed trim %.1f%%: annual=%.2f%%, sharpe=%.4f, "
            "max_drawdown=%.2f%%",
            trim * 100,
            performance["annual_return"] * 100,
            performance["sharpe_ratio"],
            performance["max_drawdown"] * 100,
        )

        del result, performance
        gc.collect()

    parameters = pd.DataFrame(parameter_rows)
    parameters.to_csv(
        os.path.join(output_root, "trim_parameter_summary.csv"), index=False
    )
    pd.DataFrame(annual_returns).to_csv(
        os.path.join(output_root, "trim_annual_returns.csv"), index=False
    )

    if not args.no_selection_compare:
        comparison = compare_selections(selections)
        comparison.to_csv(
            os.path.join(output_root, "top5_overlap_by_year.csv"), index=False
        )
        summary = selection_summary(comparison)
        summary.to_csv(
            os.path.join(output_root, "top5_overlap_summary.csv"), index=False
        )
        with open(os.path.join(output_root, "top5_selections.pkl"), "wb") as file:
            pickle.dump(selections, file)

        logger.info("\nTop-5 overlap summary:\n%s", summary.to_string(index=False))
        logger.info("\nTop-5 overlap by year:\n%s", comparison.to_string(index=False))

    with open(os.path.join(output_root, "run_config.txt"), "w", encoding="utf-8") as file:
        file.write(f"created_at={datetime.now().isoformat(timespec='seconds')}\n")
        file.write(f"pool_size={len(stock_codes)}\n")
        file.write("frequency=annual\n")
        file.write("ranking=pb\n")
        file.write(f"filter_indicators={','.join(config.FILTER_INDICATORS)}\n")
        file.write(f"max_positions={config.MAX_POSITIONS}\n")
        file.write(f"trim_ratios={','.join(str(x) for x in DEFAULT_TRIMS)}\n")
        file.write(f"start_date={config.START_DATE}\n")
        file.write("end_date=latest\n")

    logger.info("\nAll results saved to %s", output_root)
    logger.info("\nParameter summary:\n%s", parameters.to_string(index=False))


if __name__ == "__main__":
    main()
