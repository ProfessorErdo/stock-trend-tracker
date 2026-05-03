"""
分析每次截面选股时各步骤的股票数量
输出 CSV 和可视化图表
"""

import sys
import logging
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger("analyze_selection")

import pandas as pd
import numpy as np
from tqdm import tqdm
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

import config
from data_loader import load_stock_pool
from trading_calendar import build_trading_calendar, get_weekly_cutoff_dates, get_monthly_cutoff_dates, get_quarterly_cutoff_dates
from stock_selector import get_latest_financial_data, calculate_valuation, winsorize, is_new_stock


def analyze_selection_counts(
    stock_codes: list,
    trading_days: list,
    cutoffs: list,
    price_cache: dict,
    label: str = ""
) -> pd.DataFrame:
    """
    For each cutoff date, count stocks at each selection step.

    Returns DataFrame with columns:
        cutoff_date, step1_valid, step2_valuation, step3_roe, step4_final
    """
    records = []

    for cutoff, rebalance in tqdm(cutoffs, desc=f"Analyzing {label}"):
        counts = {
            "cutoff_date": pd.Timestamp(cutoff),
            "step1_valid": 0,
            "step2_valuation": 0,
            "step3_roe": 0,
            "step4_final": 0,
        }

        all_valuations = []
        # Step 1: Basic filter (suspended, no financial, negative valuation)
        for code in stock_codes:
            if code not in price_cache or price_cache[code].empty:
                continue

            price_df = price_cache[code]
            if cutoff not in price_df["trade_date"].values:
                continue  # suspended

            fin_data = get_latest_financial_data(code, cutoff)
            if fin_data is None:
                continue

            valuation = calculate_valuation(price_df, cutoff, fin_data)
            if valuation is None:
                continue

            if (valuation["pe_ttm"] <= 0 or valuation["pb_ttm"] <= 0 or
                    valuation["pr_ttm"] <= 0 or valuation["roe_ttm"] <= 0):
                continue

            all_valuations.append({"code": code, **valuation})

        counts["step1_valid"] = len(all_valuations)

        if not all_valuations:
            records.append(counts)
            continue

        val_df = pd.DataFrame(all_valuations)

        # Step 2: Valuation filter (PE/PB/PR <= 25th percentile after optional winsorization)
        if config.WINSORIZE_ENABLED:
            val_df["pe_w"] = winsorize(val_df["pe_ttm"], config.WINSORIZE_LOWER, config.WINSORIZE_UPPER)
            val_df["pb_w"] = winsorize(val_df["pb_ttm"], config.WINSORIZE_LOWER, config.WINSORIZE_UPPER)
            val_df["pr_w"] = winsorize(val_df["pr_ttm"], config.WINSORIZE_LOWER, config.WINSORIZE_UPPER)
            pe_cut = val_df["pe_w"].quantile(config.PE_THRESHOLD)
            pb_cut = val_df["pb_w"].quantile(config.PB_THRESHOLD)
            pr_cut = val_df["pr_w"].quantile(config.PR_THRESHOLD)
        else:
            pe_cut = val_df["pe_ttm"].quantile(config.PE_THRESHOLD)
            pb_cut = val_df["pb_ttm"].quantile(config.PB_THRESHOLD)
            pr_cut = val_df["pr_ttm"].quantile(config.PR_THRESHOLD)

        step2 = val_df[
            (val_df["pe_ttm"] <= pe_cut) &
            (val_df["pb_ttm"] <= pb_cut) &
            (val_df["pr_ttm"] <= pr_cut)
        ]
        counts["step2_valuation"] = len(step2)

        if step2.empty:
            records.append(counts)
            continue

        # Step 3: ROE filter (>= (1-threshold) percentile of all valid stocks, matching src logic)
        roe_cut = val_df["roe_ttm"].quantile(1 - config.PE_THRESHOLD)
        step3 = step2[step2["roe_ttm"] >= roe_cut]
        counts["step3_roe"] = len(step3)

        if step3.empty:
            records.append(counts)
            continue

        # Step 4: New stock filter
        final = []
        for _, row in step3.iterrows():
            code = row["code"]
            p_df = price_cache.get(code)
            if p_df is not None and not is_new_stock(code, p_df, cutoff, config.NEW_STOCK_EXCLUDE_DAYS):
                final.append(code)

        counts["step4_final"] = len(final)
        records.append(counts)

    return pd.DataFrame(records)


def plot_analysis(df: pd.DataFrame, save_path: str, frequency: str = "weekly"):
    """
    Plot:
    1. Line chart of stock counts per step over time
    2. Distribution histogram of final selected count
    """
    fig, axes = plt.subplots(2, 1, figsize=(16, 10))

    # --- Top: Line chart ---
    ax = axes[0]
    ax.plot(df["cutoff_date"], df["step1_valid"], label="Step 1: Valid candidates", linewidth=1)
    ax.plot(df["cutoff_date"], df["step2_valuation"], label="Step 2: Valuation filter", linewidth=1)
    ax.plot(df["cutoff_date"], df["step3_roe"], label="Step 3: ROE filter", linewidth=1)
    ax.plot(df["cutoff_date"], df["step4_final"], label="Step 4: Final selected", linewidth=1.5, color="#DAA520")

    ax.set_title(f"Stock Count at Each Selection Step ({frequency.title()})")
    ax.set_xlabel("Date")
    ax.set_ylabel("Number of Stocks")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    # --- Bottom: Distribution histogram ---
    ax2 = axes[1]
    ax2.hist(df["step4_final"], bins=30, color="#DAA520", edgecolor="white", alpha=0.8)
    mean_val = df["step4_final"].mean()
    ax2.axvline(mean_val, color="red", linestyle="--", linewidth=2, label=f"Mean = {mean_val:.1f}")
    ax2.set_title(f"Distribution of Final Selected Stocks (Mean: {mean_val:.1f})")
    ax2.set_xlabel("Number of Selected Stocks")
    ax2.set_ylabel("Frequency (number of cutoff dates)")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    fig.tight_layout()
    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
    fig.savefig(save_path, dpi=200, bbox_inches="tight")
    logger.info(f"Analysis chart saved to {save_path}")
    plt.close(fig)


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    frequency = sys.argv[1] if len(sys.argv) > 1 else "weekly"
    freq_labels = {"weekly": "Weekly", "monthly": "Monthly", "quarterly": "Quarterly"}
    label = freq_labels.get(frequency, "Weekly")
    logger.info(f"Analyzing stock selection counts ({label} rebalance)...")

    # Load stock pool
    pool_df = load_stock_pool()
    stock_codes = pool_df["code"].tolist()
    logger.info(f"Stock pool: {len(stock_codes)} stocks")

    # Build calendar
    trading_days = build_trading_calendar()
    if not trading_days:
        logger.info("No trading days found.")
        return

    if frequency == "monthly":
        cutoffs = get_monthly_cutoff_dates(trading_days)
    elif frequency == "quarterly":
        cutoffs = get_quarterly_cutoff_dates(trading_days)
    else:
        cutoffs = get_weekly_cutoff_dates(trading_days)
    logger.info(f"Cutoff dates: {len(cutoffs)}")

    # Load price cache
    price_cache = {}
    for code in tqdm(stock_codes, desc="Loading prices"):
        try:
            from data_loader import load_price_data
            df = load_price_data(code)
            if not df.empty:
                price_cache[code] = df
        except Exception:
            continue
    logger.info(f"Price cache: {len(price_cache)} stocks")

    # Analyze
    df = analyze_selection_counts(stock_codes, trading_days, cutoffs, price_cache, label)

    # Print summary stats
    logger.info("\n" + "=" * 60)
    logger.info(f"  Selection Count Summary ({label})")
    logger.info("=" * 60)
    for col in ["step1_valid", "step2_valuation", "step3_roe", "step4_final"]:
        logger.info(f"  {col:20s}: mean={df[col].mean():.1f},  median={df[col].median():.0f},  "
              f"min={df[col].min():.0f},  max={df[col].max():.0f},  std={df[col].std():.1f}")
    logger.info("=" * 60)

    # Print extremes
    max_idx = df["step4_final"].idxmax()
    min_idx = df["step4_final"].idxmin()
    logger.info(f"\n  Most stocks selected: {df.loc[max_idx, 'step4_final']:.0f} "
          f"on {df.loc[max_idx, 'cutoff_date'].date()}")
    logger.info(f"  Fewest stocks selected: {df.loc[min_idx, 'step4_final']:.0f} "
          f"on {df.loc[min_idx, 'cutoff_date'].date()}")

    # Save CSV
    csv_dir = os.path.join(config.DATA_OUTPUT_DIR, "analysis")
    os.makedirs(csv_dir, exist_ok=True)
    csv_path = os.path.join(csv_dir, f"selection_counts_{frequency}.csv")
    df.to_csv(csv_path, index=False)
    logger.info(f"\nCSV saved to {csv_path}")

    # Save chart
    chart_path = os.path.join(config.CHARTS_DIR, f"selection_counts_{frequency}.png")
    plot_analysis(df, chart_path, frequency)


if __name__ == "__main__":
    main()
