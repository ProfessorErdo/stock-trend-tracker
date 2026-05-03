"""
调仓日后逐日累计收益分析

目的：分析每个调仓日后 252 个交易日的累计波动规律，
为每月 3 万元定投策略提供数据支持。
"""

import pandas as pd
import numpy as np
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from log_util import setup_logger

logger = setup_logger("analyze_rebalance_cycles")


def main():
    equity = pd.read_csv("data/processed/backtesting/performance/equity_curve.csv")
    equity["date"] = pd.to_datetime(equity["date"])

    trades = pd.read_csv("data/processed/backtesting/trades/trades_record.csv")
    trades["trade_date"] = pd.to_datetime(trades["trade_date"])

    rebalance_dates = sorted(trades["trade_date"].unique())
    logger.info(f"Rebalance dates ({len(rebalance_dates)}): {[str(d.date()) for d in rebalance_dates]}")

    # =========================================================================
    # 1. 每个调仓日后的逐日累计收益（每个周期独立计算，从 1.0 开始）
    # =========================================================================
    logger.info("\n" + "=" * 80)
    logger.info("1. 每个调仓周期的逐日累计收益")
    logger.info("=" * 80)

    cycle_data = []  # (rebalance_date, day_index, cum_return)
    cycle_summaries = []  # per-cycle stats

    for i, rb_date in enumerate(rebalance_dates):
        # 找到该调仓日及之后的交易日
        mask = equity["date"] >= rb_date
        subset = equity[mask].copy()

        if len(subset) == 0:
            continue

        # 起始市值
        start_equity = subset["strategy_equity"].iloc[0]

        # 确定结束日期（下一个调仓日前一天，或者最后一个交易日）
        if i + 1 < len(rebalance_dates):
            end_date = rebalance_dates[i + 1]
            subset = subset[subset["date"] < end_date]
        else:
            # 最后一个周期，取剩余所有数据
            pass

        if len(subset) == 0:
            continue

        # 计算逐日累计收益率（从 0 开始）
        subset["cum_return"] = subset["strategy_equity"] / start_equity - 1
        subset["day_index"] = range(len(subset))

        for _, row in subset.iterrows():
            cycle_data.append({
                "rebalance_date": rb_date,
                "day_index": row["day_index"],
                "cum_return": row["cum_return"],
                "strategy_equity": row["strategy_equity"],
            })

        # 周期汇总
        max_dd = subset["strategy_equity"].cummax()
        dd = (subset["strategy_equity"] - max_dd) / max_dd
        cycle_summaries.append({
            "rebalance_date": rb_date,
            "cycle_days": len(subset),
            "start_equity": start_equity,
            "end_equity": subset["strategy_equity"].iloc[-1],
            "cycle_return": subset["strategy_equity"].iloc[-1] / start_equity - 1,
            "max_dd": dd.min(),
            "max_dd_day": dd.idxmin() if len(dd) > 0 else 0,
        })

        logger.info(
            f"  {rb_date.date()} -> 周期 {len(subset)} 天, "
            f"收益 {cycle_summaries[-1]['cycle_return']:+.2%}, "
            f"最大回撤 {dd.min():+.2%}"
        )

    cycle_df = pd.DataFrame(cycle_data)
    summary_df = pd.DataFrame(cycle_summaries)

    # =========================================================================
    # 2. 跨周期对齐分析：每个调仓日后第 N 天的统计特征
    # =========================================================================
    logger.info("\n" + "=" * 80)
    logger.info("2. 调仓日后第 N 天的跨周期统计 (对齐 day 0)")
    logger.info("=" * 80)

    stats_by_day = cycle_df.groupby("day_index")["cum_return"].agg([
        ("mean", "mean"),
        ("median", "median"),
        ("std", "std"),
        ("min", "min"),
        ("max", "max"),
        ("p25", lambda x: x.quantile(0.25)),
        ("p75", lambda x: x.quantile(0.75)),
        ("count", "count"),
    ]).reset_index()

    # 打印关键节点
    key_days = [0, 5, 10, 20, 40, 60, 80, 100, 120, 150, 180, 200, 220, 240, 250]
    logger.info(f"\n  {'Day':>4}  {'Mean':>8}  {'Median':>8}  {'Std':>8}  "
                f"{'P25':>8}  {'P75':>8}  {'Min':>8}  {'Max':>8}  {'N':>3}")
    logger.info("  " + "-" * 85)

    for _, row in stats_by_day.iterrows():
        day = int(row["day_index"])
        if day in key_days and day <= 252:
            logger.info(
                f"  {day:>4}  {row['mean']:>+8.2%}  {row['median']:>+8.2%}  "
                f"{row['std']:>8.2%}  {row['p25']:>+8.2%}  {row['p75']:>+8.2%}  "
                f"{row['min']:>+8.2%}  {row['max']:>+8.2%}  {int(row['count']):>3}"
            )

    # =========================================================================
    # 3. 月度维度分析：调仓后第 M 个月的平均表现
    # =========================================================================
    logger.info("\n" + "=" * 80)
    logger.info("3. 调仓日后按月分组的平均累计收益 (每月≈21交易日)")
    logger.info("=" * 80)

    cycle_df["month"] = (cycle_df["day_index"] // 21).clip(upper=12)

    monthly_stats = cycle_df.groupby("month")["cum_return"].agg([
        ("mean", "mean"),
        ("std", "std"),
        ("min", "min"),
        ("max", "max"),
    ]).reset_index()

    logger.info(f"\n  {'Month':>6}  {'Mean Cum Ret':>12}  {'Std':>8}  {'Min':>8}  {'Max':>8}")
    logger.info("  " + "-" * 60)
    for _, row in monthly_stats.iterrows():
        m = int(row["month"])
        if m <= 12:
            logger.info(
                f"  M{m:>4}  {row['mean']:>+12.2%}  {row['std']:>8.2%}  "
                f"{row['min']:>+8.2%}  {row['max']:>+8.2%}"
            )

    # =========================================================================
    # 4. 跌幅阈值分析：调仓后多久会触发不同的跌幅
    # =========================================================================
    logger.info("\n" + "=" * 80)
    logger.info("4. 跌幅阈值触发分析")
    logger.info("=" * 80)

    thresholds = [-0.05, -0.08, -0.10, -0.15, -0.20, -0.25, -0.30]

    for thresh in thresholds:
        triggered = []
        for _, cycle in summary_df.iterrows():
            rb_date = cycle["rebalance_date"]
            mask = (cycle_df["rebalance_date"] == rb_date) & (cycle_df["cum_return"] <= thresh)
            hits = cycle_df[mask]
            if len(hits) > 0:
                first_hit_day = hits["day_index"].min()
                hit_return = hits.iloc[0]["cum_return"]
                triggered.append(first_hit_day)

        if triggered:
            logger.info(
                f"  跌幅 ≤ {thresh:+.0%}: "
                f"{len(triggered)}/{len(summary_df)} 次触发, "
                f"平均在第 {np.mean(triggered):.0f} 天触发, "
                f"中位数 {int(np.median(triggered))} 天"
            )
        else:
            logger.info(f"  跌幅 ≤ {thresh:+.0%}: 无触发")

    # =========================================================================
    # 5. 每月 3 万元定投策略模拟
    # =========================================================================
    logger.info("\n" + "=" * 80)
    logger.info("5. 每月 3 万元定投策略模拟")
    logger.info("=" * 80)

    _simulate_strategies(equity, rebalance_dates)


def _run_cycle_simulation(cycle_df, start_equity, rebalance_date, next_rb_date,
                          strategy: str, param=0.05):
    """
    对单个调仓周期，模拟增量资金的投入和收益。

    策略:
      'lump_sum'   — 调仓日一次性投入 36 万
      'monthly'    — 每 21 交易日定投 3 万
      'threshold'  — 每月存 3 万，累计跌幅达 param 时买入（冷却 21 天）
      'monthly_plus_threshold' — 每月定投 3 万 + 跌幅达 param 时额外加倍买

    返回: (total_invested, final_value, uninvested_cash, buy_dates)
    """
    MONTHLY_AMOUNT = 30_000

    incremental_shares = 0.0  # 用 3 万买入的份额
    cash = 0
    buy_dates = []
    last_buy_day = -999

    for day_i in range(len(cycle_df)):
        price = cycle_df.iloc[day_i]["strategy_equity"]
        cum_ret = price / start_equity - 1

        if strategy == "lump_sum":
            # 在调仓日（day 0）一次性投入全部
            if day_i == 0:
                deposit = MONTHLY_AMOUNT * 12
                incremental_shares = deposit / price
                cash = 0
                buy_dates.append((0, deposit))
            continue

        elif strategy == "monthly":
            if day_i % 21 == 0 and day_i < len(cycle_df):
                cash += MONTHLY_AMOUNT
                buy_amt = cash
                incremental_shares += buy_amt / price
                buy_dates.append((day_i, buy_amt))
                cash = 0

        elif strategy == "threshold":
            # 每月存钱
            if day_i % 21 == 0:
                cash += MONTHLY_AMOUNT

            # 跌幅触发时买入
            if cum_ret <= param and day_i - last_buy_day >= 21 and cash > 0:
                buy_amt = cash
                incremental_shares += buy_amt / price
                cash = 0
                last_buy_day = day_i
                buy_dates.append((day_i, buy_amt))

        elif strategy == "monthly_plus_threshold":
            # 每月定投
            if day_i % 21 == 0:
                cash += MONTHLY_AMOUNT
                buy_amt = MONTHLY_AMOUNT
                incremental_shares += buy_amt / price
                cash -= buy_amt
                buy_dates.append((day_i, buy_amt))

            # 跌幅触发额外买入
            if cum_ret <= param and day_i - last_buy_day >= 21 and cash > 0:
                buy_amt = min(cash, MONTHLY_AMOUNT)
                incremental_shares += buy_amt / price
                cash -= buy_amt
                last_buy_day = day_i
                buy_dates.append((day_i, buy_amt))

    end_price = cycle_df.iloc[-1]["strategy_equity"]
    total_invested = MONTHLY_AMOUNT * 12
    final_value = incremental_shares * end_price + cash

    return total_invested, final_value, cash, buy_dates


def _simulate_strategies(equity: pd.DataFrame, rebalance_dates: list):
    """
    对比几种每月 3 万元的投入策略：

    A. 累积到调仓日一次性买入（每年 36 万）
    B. 每月固定定投 3 万（每 ~21 交易日）
    C. 每月存 3 万，累计跌幅 ≥5% 时买入（阈值型）
    D. 每月定投 3 万 + 跌幅 ≥5% 时额外加倍
    """
    MONTHLY_AMOUNT = 30_000
    df = equity.copy()
    df = df.sort_values("date").reset_index(drop=True)

    strategies = {
        "A: 一次性买入": ("lump_sum", None),
        "B: 月定投": ("monthly", None),
        "C: 跌5%触发": ("threshold", -0.05),
        "D: 月定投+跌5%加倍": ("monthly_plus_threshold", -0.05),
    }

    results = {name: [] for name in strategies}

    for cycle_idx in range(len(rebalance_dates) - 1):
        rb_start = rebalance_dates[cycle_idx]
        rb_end = rebalance_dates[cycle_idx + 1]

        cycle_mask = (df["date"] >= rb_start) & (df["date"] < rb_end)
        cycle_df = df[cycle_mask].copy()

        if len(cycle_df) < 20:
            continue

        start_equity = cycle_df.iloc[0]["strategy_equity"]
        cycle_return = cycle_df.iloc[-1]["strategy_equity"] / start_equity - 1

        for name, (strat, param) in strategies.items():
            total_inv, final_val, uninvested, buy_dates = _run_cycle_simulation(
                cycle_df, start_equity, rb_start, rb_end, strat, param
            )
            profit = final_val - total_inv
            # 实际投入资金 = 总存款 - 未投入现金
            actually_invested = total_inv - uninvested
            # 收益率：如果全部投入，就是 profit / total_inv；
            # 如果有未投入现金，收益率 = (final_value - 总存款) / 总存款
            ret = (final_val - total_inv) / total_inv
            results[name].append({
                "date": rb_start,
                "cycle_return": cycle_return,
                "total_invested": total_inv,
                "final_value": final_val,
                "uninvested": uninvested,
                "profit": profit,
                "return": ret,
                "buy_count": len(buy_dates),
            })

    # 打印每周期明细
    logger.info("\n  每周期增量收益明细:")
    logger.info("  " + "-" * 110)
    for name in strategies:
        logger.info(f"\n  【{name}】")
        logger.info(f"  {'Period':>18}  {'周期收益':>10}  {'总投入':>10}  {'期末价值':>10}  "
                    f"{'未投入':>8}  {'利润':>10}  {'收益率':>10}  {'买入次数':>6}")
        logger.info("  " + "-" * 110)
        for entry in results[name]:
            logger.info(
                f"  {str(entry['date'].date()):>18}  "
                f"{entry['cycle_return']:>+10.2%}  "
                f"{entry['total_invested']:>10,.0f}  "
                f"{entry['final_value']:>10,.0f}  "
                f"{entry['uninvested']:>8,.0f}  "
                f"{entry['profit']:>10,.0f}  "
                f"{entry['return']:>+10.2%}  "
                f"{entry['buy_count']:>6}"
            )

    # 汇总
    logger.info("\n  策略汇总:")
    logger.info(f"  {'Strategy':>25}  {'Avg Return':>12}  {'Median Ret':>12}  "
                f"{'Avg Profit':>12}  {'Uninvested':>12}  {'Avg Buys':>10}")
    logger.info("  " + "-" * 90)
    for name in strategies:
        rets = [e["return"] for e in results[name]]
        profits = [e["profit"] for e in results[name]]
        uninvested = [e["uninvested"] for e in results[name]]
        buys = [e["buy_count"] for e in results[name]]
        logger.info(
            f"  {name:>25}  {np.mean(rets):+12.2%}  {np.median(rets):+12.2%}  "
            f"{np.mean(profits):>12,.0f}  {np.mean(uninvested):>12,.0f}  "
            f"{np.mean(buys):>10.1f}"
        )

    # =========================================================================
    # 6. 不同跌幅阈值的智能定投对比
    # =========================================================================
    logger.info("\n" + "=" * 80)
    logger.info("6. 不同跌幅阈值的阈值型策略对比")
    logger.info("=" * 80)

    for thresh in [-0.03, -0.05, -0.08, -0.10, -0.15]:
        returns_list = []
        uninvested_list = []

        for cycle_idx in range(len(rebalance_dates) - 1):
            rb_start = rebalance_dates[cycle_idx]
            rb_end = rebalance_dates[cycle_idx + 1]

            cycle_mask = (df["date"] >= rb_start) & (df["date"] < rb_end)
            cycle_df = df[cycle_mask].copy()

            if len(cycle_df) < 20:
                continue

            start_equity = cycle_df.iloc[0]["strategy_equity"]
            total_inv, final_val, uninvested, _ = _run_cycle_simulation(
                cycle_df, start_equity, rb_start, rb_end, "threshold", thresh
            )
            ret = (final_val - total_inv) / total_inv
            returns_list.append(ret)
            uninvested_list.append(uninvested)

        logger.info(
            f"  阈值 {thresh:+.0%}: 平均收益 {np.mean(returns_list):+.2%}, "
            f"中位数 {np.median(returns_list):+.2%}, "
            f"平均未投入 {np.mean(uninvested_list):,.0f} RMB"
        )


if __name__ == "__main__":
    main()
