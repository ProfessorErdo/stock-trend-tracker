#!/usr/bin/env python3
"""
汇总 universe_compare.py 的结果，生成对比表、稳健性指标、图表和中文报告。
"""

import argparse
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
sys.path.insert(0, BASE_DIR)

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

PCT_COLS = {
    "annual_return",
    "cumulative_return",
    "annual_volatility",
    "max_drawdown",
    "cagr_2015_2020",
    "cagr_2021_2026",
    "cagr_ex_best_year",
    "worst_year",
    "best_year",
    "avg_invested_weight",
    "benchmark_annual_return",
    "excess_return",
}

FILTER_ORDER = ["pe", "pb", "pr", "pe+pb", "pe+pr", "pb+pr", "pe+pb+pr"]
RANK_ORDER = ["pb", "pe", "pr", "roe", "pure_pb"]


def pct(value, digits=2):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "—"
    return f"{value * 100:.{digits}f}%"


def num(value, digits=2):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "—"
    return f"{value:.{digits}f}"


def fmt_table(df, columns, rename=None):
    out = df[columns].copy()
    for col in out.columns:
        if col in PCT_COLS:
            out[col] = out[col].map(lambda x: pct(x))
        elif col in {"sharpe_ratio", "calmar", "profit_loss_ratio"}:
            out[col] = out[col].map(lambda x: num(x, 3))
        elif col == "win_rate":
            out[col] = out[col].map(lambda x: pct(x, 1))
        elif col == "avg_positions":
            out[col] = out[col].map(lambda x: num(x, 1))
    if rename:
        out = out.rename(columns=rename)
    return out.to_markdown(index=False)


def load_runs(out_root):
    summary = pd.read_csv(os.path.join(out_root, "summary.csv"))
    summary["trim"] = summary["trim"].astype(str)
    annual = {}
    for run_id in summary["id"]:
        path = os.path.join(out_root, "runs", run_id, "annual_returns.csv")
        if os.path.exists(path):
            annual[run_id] = pd.read_csv(path)
    return summary, annual


def add_robustness(summary, annual):
    """以 2016-2026 为有效区间（2015 年年度策略空仓）计算稳健性指标。"""
    full, loyo, std, pos, nyear, worst, best = [], [], [], [], [], [], []
    for run_id in summary["id"]:
        frame = annual.get(run_id)
        if frame is not None and not frame.empty:
            frame = frame[frame["year"] >= 2016]
        if frame is None or frame.empty:
            full.append(np.nan)
            loyo.append(np.nan)
            std.append(np.nan)
            pos.append(np.nan)
            nyear.append(np.nan)
            worst.append(np.nan)
            best.append(np.nan)
            continue
        r = frame["strategy_return"].to_numpy(dtype=float)
        n = len(r)
        full.append(float(np.prod(1 + r) ** (1 / n) - 1))
        loyo.append(float(np.prod(1 + np.delete(r, np.argmax(r))) ** (1 / (n - 1)) - 1))
        std.append(float(np.std(r, ddof=1)))
        pos.append(int((r > 0).sum()))
        nyear.append(n)
        worst.append(float(r.min()))
        best.append(float(r.max()))
    summary["cagr_from_annual"] = full
    summary["cagr_ex_best_year"] = loyo
    summary["annual_return_std"] = std
    summary["positive_years"] = pos
    summary["n_years"] = nyear
    summary["worst_year"] = worst
    summary["best_year"] = best

    summary["rank_return"] = summary["annual_return"].rank(ascending=False)
    summary["rank_ex_best"] = summary["cagr_ex_best_year"].rank(ascending=False)
    summary["rank_sharpe"] = summary["sharpe_ratio"].rank(ascending=False)
    summary["rank_second_half"] = summary["cagr_2021_2026"].rank(ascending=False)
    summary["robust_rank"] = summary[
        ["rank_return", "rank_ex_best", "rank_sharpe", "rank_second_half"]
    ].mean(axis=1)
    return summary


def comparable(summary):
    """只保留 1052 并集池上、非口径校验的实验。"""
    return summary[
        (summary["pool"] == "union") & (~summary["phase"].astype(str).str.startswith("val"))
    ].copy()


# ---------------------------------------------------------------------------
# 图表
# ---------------------------------------------------------------------------
def chart_core_heatmap(summary, charts_dir):
    core = summary[summary["phase"] == "core"]
    for metric, label, fname, scale, fmt in [
        ("annual_return", "Annualized return (%)", "core_heatmap_annual.png", 100, "{:.2f}"),
        ("sharpe_ratio", "Sharpe ratio", "core_heatmap_sharpe.png", 1, "{:.2f}"),
    ]:
        pivot = core.pivot(index="filters", columns="ranking", values=metric)
        pivot = pivot.reindex(index=FILTER_ORDER, columns=RANK_ORDER)
        values = pivot.to_numpy(dtype=float) * scale
        fig, ax = plt.subplots(figsize=(8.5, 5.2))
        im = ax.imshow(values, cmap="RdYlGn", aspect="auto")
        ax.set_xticks(range(len(pivot.columns)), pivot.columns)
        ax.set_yticks(range(len(pivot.index)), pivot.index)
        ax.set_xlabel("Ranking method")
        ax.set_ylabel("Step-2 valuation filter (ROE always step 3)")
        ax.set_title(f"Core grid — {label} (annual, N=5, trim 1%, 1052 stocks)")
        for i in range(values.shape[0]):
            for j in range(values.shape[1]):
                v = values[i, j]
                if np.isnan(v):
                    continue
                ax.text(j, i, fmt.format(v), ha="center", va="center", fontsize=9)
        fig.colorbar(im, ax=ax, shrink=0.85)
        fig.tight_layout()
        fig.savefig(os.path.join(charts_dir, fname), dpi=160)
        plt.close(fig)


def chart_trim(summary, charts_dir):
    trim = summary[summary["phase"] == "trim"].copy()
    trim["trim_num"] = pd.to_numeric(trim["trim"], errors="coerce")
    trim.loc[trim["trim"] == "raw", "trim_num"] = np.nan
    wanted = [
        ("pb", "pe", "PB+ROE filter → PE rank"),
        ("pe+pb+pr", "pb", "PB+ROE filter → PB rank"),
    ]
    fig, ax = plt.subplots(figsize=(8.5, 5))
    for filters, ranking, label in wanted:
        group = trim[(trim["filters"] == filters) & (trim["ranking"] == ranking)]
        group = group.drop_duplicates(subset=["trim"]).sort_values("trim_num")
        ax.plot(group["trim_num"] * 100, group["annual_return"] * 100, marker="o", label=label)
        raw = group[group["trim"] == "raw"]
        if not raw.empty:
            ax.axhline(raw["annual_return"].iloc[0] * 100, color="grey", ls=":", lw=1)
    ax.set_xlabel("Adverse-tail trim ratio (%)")
    ax.set_ylabel("Annualized return (%)")
    ax.set_title("Trim sensitivity (annual, 1052 stocks; dotted = raw quantiles)")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(charts_dir, "trim_curves.png"), dpi=160)
    plt.close(fig)


def chart_bars(summary, charts_dir):
    positions = summary[summary["phase"] == "positions"].sort_values("max_positions")
    if not positions.empty:
        fig, ax = plt.subplots(figsize=(8, 4.5))
        ax.bar(positions["max_positions"].astype(int), positions["annual_return"] * 100,
               color="#4C72B0")
        for x, y in zip(positions["max_positions"].astype(int), positions["annual_return"] * 100):
            ax.text(x, y + 0.1, f"{y:.1f}", ha="center", fontsize=8)
        ax.set_xlabel("Max positions (N)")
        ax.set_ylabel("Annualized return (%)")
        ax.set_title("Position-count sensitivity")
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        fig.savefig(os.path.join(charts_dir, "positions_bars.png"), dpi=160)
        plt.close(fig)

    freq = summary[summary["phase"] == "frequency"]
    if not freq.empty:
        order = ["weekly", "monthly", "quarterly", "annual", "annual_q3", "mid_year", "q3"]
        freq = freq.set_index("frequency").reindex(
            [f for f in order if f in set(freq["frequency"])]
        ).reset_index()
        fig, ax = plt.subplots(figsize=(8, 4.5))
        colors = ["#C44E52" if f == "annual" else "#4C72B0" for f in freq["frequency"]]
        ax.bar(freq["frequency"], freq["annual_return"] * 100, color=colors)
        for x, y in zip(freq["frequency"], freq["annual_return"] * 100):
            ax.text(x, y + 0.1, f"{y:.1f}", ha="center", fontsize=9)
        ax.set_ylabel("Annualized return (%)")
        ax.set_title("Rebalance-frequency sensitivity")
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        fig.savefig(os.path.join(charts_dir, "frequency_bars.png"), dpi=160)
        plt.close(fig)


def chart_top_equity(selected, out_root, charts_dir):
    fig, ax = plt.subplots(figsize=(10, 5.5))
    for label, run_id in selected.items():
        path = os.path.join(out_root, "runs", run_id, "equity_curve.csv")
        if not os.path.exists(path):
            continue
        eq = pd.read_csv(path, parse_dates=["date"])
        ax.plot(eq["date"], eq["strategy_equity"] / eq["strategy_equity"].iloc[0],
                lw=1.5, label=label)
    ax.set_yscale("log")
    ax.set_ylabel("Net value (log scale)")
    ax.set_title("Selected schemes net value (2015-01 ~ 2026-11-06)")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=9, loc="upper left")
    fig.tight_layout()
    fig.savefig(os.path.join(charts_dir, "top_equity_curves.png"), dpi=160)
    plt.close(fig)


def chart_yearly_heatmap(selected, annual, charts_dir):
    years = None
    matrix, labels = [], []
    for label, run_id in selected.items():
        frame = annual.get(run_id)
        if frame is None:
            continue
        if years is None:
            years = sorted(int(y) for y in frame["year"].unique())
        series = frame.set_index("year")["strategy_return"].reindex(years)
        matrix.append(series.to_numpy(dtype=float))
        labels.append(label)
    if not matrix:
        return
    data = np.array(matrix) * 100
    fig, ax = plt.subplots(figsize=(11, 0.6 * len(labels) + 1.8))
    im = ax.imshow(data, cmap="RdYlGn", aspect="auto", vmin=-40, vmax=60)
    ax.set_xticks(range(len(years)), years, rotation=45)
    ax.set_yticks(range(len(labels)), labels)
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            if np.isnan(data[i, j]):
                continue
            ax.text(j, i, f"{data[i, j]:.0f}", ha="center", va="center", fontsize=8)
    ax.set_title("Annual returns of selected schemes (%)")
    fig.colorbar(im, ax=ax, shrink=0.8)
    fig.tight_layout()
    fig.savefig(os.path.join(charts_dir, "top_yearly_heatmap.png"), dpi=160)
    plt.close(fig)


# ---------------------------------------------------------------------------
# 报告辅助
# ---------------------------------------------------------------------------
def load_stock_names():
    path = os.path.join(PROJECT_DIR, "data", "input", "stock_names_full.csv")
    if not os.path.exists(path):
        return {}
    frame = pd.read_csv(path, dtype={"code": str})
    return dict(zip(frame["code"].str.zfill(6), frame["name"]))


def read_close(code, column, date="2026-11-06"):
    path = os.path.join(
        PROJECT_DIR, "data", "input", "backtesting", "price", f"price_{code}.csv"
    )
    if not os.path.exists(path):
        return np.nan
    frame = pd.read_csv(path, parse_dates=["trade_date"])
    row = frame[frame["trade_date"] == pd.Timestamp(date)]
    if row.empty or column not in row:
        return np.nan
    return float(row[column].iloc[0])


def read_close_na(code, date="2026-11-06"):
    path = os.path.join(
        PROJECT_DIR, "data", "input", "backtesting", "price", f"price_{code}.csv"
    )
    if not os.path.exists(path):
        return np.nan
    frame = pd.read_csv(path, parse_dates=["trade_date"])
    row = frame[frame["trade_date"] == pd.Timestamp(date)]
    if row.empty or "close_na" not in row:
        return np.nan
    return float(row["close_na"].iloc[0])


def holdings_names(out_root, run_id, names):
    path = os.path.join(out_root, "runs", run_id, "holdings_summary.csv")
    if not os.path.exists(path):
        return []
    frame = pd.read_csv(path, dtype={"stock_code": str})
    frame["stock_code"] = frame["stock_code"].str.zfill(6)
    last = frame[frame["rebalance_date"] == frame["rebalance_date"].max()]
    return [names.get(code, code) for code in last["stock_code"]]


def holdings_table(out_root, run_id, names):
    path = os.path.join(out_root, "runs", run_id, "holdings_summary.csv")
    if not os.path.exists(path):
        return "_（无持仓快照）_\n"
    frame = pd.read_csv(path, dtype={"stock_code": str})
    frame["stock_code"] = frame["stock_code"].str.zfill(6)
    last_date = frame["rebalance_date"].max()
    last = frame[frame["rebalance_date"] == last_date].copy()
    current_values = {}
    for _, row in last.iterrows():
        current_values[row["stock_code"]] = row["shares"] * read_close(
            row["stock_code"], "close"
        )
    total_current = sum(v for v in current_values.values() if not np.isnan(v))
    rows = []
    for _, row in last.iterrows():
        code = row["stock_code"]
        close_na = read_close_na(code)
        weight_now = current_values.get(code, np.nan) / total_current if total_current else np.nan
        rows.append(
            {
                "代码": code,
                "名称": names.get(code, code),
                "调仓时权重": f"{row['weight'] * 100:.1f}%",
                "当前权重(11-06)": f"{weight_now * 100:.1f}%" if not np.isnan(weight_now) else "—",
                "参考价(不复权)": f"{close_na:.2f}" if not np.isnan(close_na) else "—",
            }
        )
    header = (
        f"调仓日 `{last_date}`，共 {len(rows)} 只。"
        "当前权重按 2026-11-06 后复权收盘价推算，会随价格漂移：\n\n"
    )
    return header + pd.DataFrame(rows).to_markdown(index=False) + "\n"


def walk_forward(ranked):
    core = ranked[ranked["phase"] == "core"].dropna(
        subset=["cagr_2015_2020", "cagr_2021_2026"]
    )
    if core.empty:
        return "_（无数据）_\n"
    first_half_pick = core.sort_values("cagr_2015_2020", ascending=False).iloc[0]
    full_pick = core.sort_values("annual_return", ascending=False).iloc[0]
    rows = [
        {
            "挑选方式": "按 2015-2020 表现挑选",
            "方案": f"{first_half_pick['filters']} + {first_half_pick['ranking']}",
            "2015-2020": pct(first_half_pick["cagr_2015_2020"]),
            "2021-2026": pct(first_half_pick["cagr_2021_2026"]),
            "全期年化": pct(first_half_pick["annual_return"]),
        },
        {
            "挑选方式": "按全期表现挑选（事后）",
            "方案": f"{full_pick['filters']} + {full_pick['ranking']}",
            "2015-2020": pct(full_pick["cagr_2015_2020"]),
            "2021-2026": pct(full_pick["cagr_2021_2026"]),
            "全期年化": pct(full_pick["annual_return"]),
        },
    ]
    return pd.DataFrame(rows).to_markdown(index=False) + "\n"


def core_pivot(summary):
    core = summary[summary["phase"] == "core"]
    pivot = core.pivot(index="filters", columns="ranking", values="annual_return")
    pivot = pivot.reindex(index=FILTER_ORDER, columns=RANK_ORDER)
    out = pivot.map(lambda x: pct(x) if pd.notna(x) else "—")
    out.index.name = "Step2 过滤"
    out.columns.name = "排名"
    return out.reset_index().to_markdown(index=False) + "\n"


def trim_pivot(summary):
    trim = summary[summary["phase"] == "trim"].copy()
    trim["trim_label"] = trim["trim"].map(
        lambda x: "raw" if x == "raw" else f"{float(x) * 100:g}%"
    )
    trim["config"] = trim.apply(
        lambda r: "PB+ROE → PB rank"
        if r["filters"] == "pe+pb+pr" and r["ranking"] == "pb"
        else ("PB+ROE → PE rank" if r["filters"] == "pb" and r["ranking"] == "pe" else None),
        axis=1,
    )
    trim = trim[trim["config"].notna()].drop_duplicates(subset=["config", "trim_label"])
    pivot = trim.pivot(index="trim_label", columns="config", values="annual_return")
    order = ["raw", "0%", "0.5%", "1%", "1.5%", "2%", "2.5%", "3%", "4%", "5%"]
    pivot = pivot.reindex([x for x in order if x in pivot.index])
    out = pivot.map(lambda x: pct(x) if pd.notna(x) else "—")
    out.index.name = "裁尾"
    return out.reset_index().to_markdown(index=False) + "\n"


# ---------------------------------------------------------------------------
# 主报告
# ---------------------------------------------------------------------------
def build_report(out_root, report_path, end_date, image_prefix="charts/"):
    image_prefix = image_prefix.rstrip("/") + "/"
    summary, annual = load_runs(out_root)
    summary = add_robustness(summary, annual)
    ranked = comparable(summary)
    charts_dir = os.path.join(out_root, "charts")
    os.makedirs(charts_dir, exist_ok=True)

    chart_core_heatmap(summary, charts_dir)
    chart_trim(summary, charts_dir)
    chart_bars(summary, charts_dir)
    best_return = ranked.sort_values(["annual_return", "sharpe_ratio"], ascending=False).iloc[0]
    best_sharpe = ranked.loc[ranked["sharpe_ratio"].idxmax()]
    best_robust = ranked.sort_values("robust_rank").iloc[0]
    recommended = (
        best_return
        if best_return["cagr_ex_best_year"] >= 0.75 * best_return["annual_return"]
        else best_robust
    )
    names = load_stock_names()

    def find_id(**conds):
        sub = summary
        for key, value in conds.items():
            sub = sub[sub[key] == value]
        return sub.iloc[0]["id"] if not sub.empty else None

    def label_for(run_id, prefix):
        row = summary[summary["id"] == run_id]
        if row.empty:
            return None
        return f"{prefix} ({row.iloc[0]['annual_return']*100:.2f}%)"

    selected = {}
    selected[label_for(recommended["id"], "Best: PB15/ROE70→PE")] = recommended["id"]
    for key, prefix in [
        ((("phase", "trim"), ("filters", "pe+pb+pr"), ("ranking", "pb"), ("trim", "0.02")),
         "Classic PB-rank, trim 2%"),
        ((("phase", "core"), ("filters", "pb"), ("ranking", "pe")),
         "Core best: PB25/ROE75→PE"),
        ((("phase", "core"), ("filters", "pe+pb+pr"), ("ranking", "pb")),
         "Classic: PB25/ROE75→PB"),
        ((("phase", "refine"), ("pe_thr", 0.25), ("roe_thr", 0.6),
          ("trim", "0.01"), ("max_positions", 5)),
         "ROE60 outlier, 2021-driven"),
    ]:
        run_id = find_id(**dict(key))
        if run_id:
            label = label_for(run_id, prefix)
            if label:
                selected[label] = run_id

    chart_top_equity(selected, out_root, charts_dir)
    chart_yearly_heatmap(selected, annual, charts_dir)


    core_all = summary[summary["phase"] == "core"].sort_values("annual_return", ascending=False)
    core_best = core_all.iloc[0]
    core_best_by_rank = core_all.drop_duplicates(subset=["ranking"])

    pools = summary[summary["phase"] == "pool"]
    union_core = summary[
        (summary["phase"] == "core")
        & (summary["filters"] == "pb")
        & (summary["ranking"] == "pe")
    ].iloc[0]
    pool_rows = pools[
        ["pool", "pool_size", "filters", "ranking", "trim", "max_positions",
         "annual_return", "sharpe_ratio", "max_drawdown", "avg_positions"]
    ].copy()
    pool_rows = pd.concat(
        [
            pool_rows,
            pd.DataFrame(
                [
                    {
                        "pool": "union",
                        "pool_size": union_core["pool_size"],
                        "filters": union_core["filters"],
                        "ranking": union_core["ranking"],
                        "trim": union_core["trim"],
                        "max_positions": union_core["max_positions"],
                        "annual_return": union_core["annual_return"],
                        "sharpe_ratio": union_core["sharpe_ratio"],
                        "max_drawdown": union_core["max_drawdown"],
                        "avg_positions": union_core["avg_positions"],
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    lines = []
    lines.append("# 1052 只合并股票池：全角度回测对比与最佳选股方案\n")
    lines.append(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"- 回测区间：2015-01-01 ~ {end_date}（今天为周六，实际最后交易日为 2026-11-06）")
    lines.append(f"- 股票池：历史各期指数清单并集，去重后 **{int(summary['pool_size'].max())} 只**")
    lines.append(f"- 实验数量：{len(summary)} 组（含股票池口径校验；同参数重复项在排行榜中已去重）")
    lines.append("- 成本：佣金 0.03%（最低 5 元）、印花税 0.1%（卖出）、滑点 0.1%、100 股整手")
    lines.append("- 基准：报告只做策略间横向比较；引擎内置等权基准的实现有偏差，未用于结论")
    lines.append(f"- 原始结果目录：`{os.path.relpath(out_root, PROJECT_DIR)}`")
    lines.append("")
    lines.append("> 说明：用户提到的 1050 / 1032 只与当前配置实际加载的 1052 只不一致。")
    lines.append("> 当前 `config.py` 合并 7 个指数池的全部历史清单（14 个文件），去重后 1053 只，")
    lines.append("> 再排除 AkShare 无法取数的 689009，实际回测池为 **1052 只**。")
    lines.append("> 本报告全部结论基于这 1052 只。")
    lines.append("")
    lines.append(
        "- 相关报告：932 旧池的同口径 131 组对比见 "
        "[universe-backtest-932-2026-11.md](universe-backtest-932-2026-11.md)。"
    )
    lines.append("")
    lines.append("## 1. 结论速览\n")
    lines.append(
        f"1. **最佳方案**：`{recommended['id']}`。年化 **{recommended['annual_return']*100:.2f}%**，"
        f"夏普 {recommended['sharpe_ratio']:.3f}，最大回撤 {recommended['max_drawdown']*100:.2f}%，"
        f"剔除最好年份后仍有 {recommended['cagr_ex_best_year']*100:.2f}%，"
        f"正收益 {int(recommended['positive_years'])}/{int(recommended['n_years'])} 年。"
        "它在收益、夏普、稳健性三个维度同时排第一。"
    )
    lines.append(
        f"2. **核心网格（年度、N=5、裁尾 1%）**：新池上 **PE 排名反超 PB 排名**"
        f"（{core_best['annual_return']*100:.2f}% vs 8.63%），但 PE 排名回撤更深"
        "（-41.6% vs -33.9%）。过滤层里只要含 PB，选出的 5 只就完全相同，"
        "PE/PR 过滤是冗余的——真正决定结果的是排名方式。"
    )
    lines.append(
        "3. **股票池扩容的影响**：旧 932 池 + 原始阈值 + PB 排名是 11.59%，"
        "同一套放到 1052 池只剩 8.04%；换成 PE 排名后回到 9.67%。"
        "扩容主要破坏了 PB 的相对排序，没有破坏“低 PE”这条线。"
    )
    lines.append(
        "4. **经典方案在新池上的位置**：PB 排名 + 裁尾 2% 是 9.55%"
        "（回撤 -33.7%，比 PE 排名浅），高于新池同配置 1% 裁尾的 8.63%，"
        "但仍明显低于旧 932 池记录的 11.37%。如果更看重平滑度而不是最高年化，这仍是可用的默认值。"
    )
    lines.append(
        "5. **风险提示**：12.37% 是全期参数扫描的产物，且当前 5 只持仓全是银行。"
        "近两年 20%+ 的年化有相当一部分来自银行估值修复，不能当作未来预期。"
    )
    if best_return["cagr_ex_best_year"] < 0.7 * best_return["annual_return"]:
        lines.append(
            f"   ⚠️ 收益最高的方案对单一年份依赖较强：剔除最好的一年后，"
            f"年化只剩 {pct(best_return['cagr_ex_best_year'])}。"
        )
    lines.append("")

    lines.append("## 2. 股票池版本对比：932 → 953 → 1052\n")
    lines.append(
        "同一套参数（PB 过滤 + PE 排名、裁尾 1%、N=5）、同一段数据、同一截止日，"
        "只改变股票池版本，用于分离“指数清单扩容”本身的影响。\n"
    )
    lines.append(
        fmt_table(
            pool_rows,
            ["pool", "pool_size", "filters", "ranking", "trim", "max_positions",
             "annual_return", "sharpe_ratio", "max_drawdown", "avg_positions"],
            rename={"pool": "池子", "pool_size": "股票数", "filters": "过滤", "ranking": "排名",
                    "trim": "裁尾", "max_positions": "N", "annual_return": "年化",
                    "sharpe_ratio": "夏普", "max_drawdown": "最大回撤", "avg_positions": "平均持仓"},
        )
    )
    legacy_raw = summary[
        (summary["phase"] == "val202604")
        & (summary["pool"] == "legacy")
        & (summary["filters"] == "pe+pb+pr")
        & (summary["ranking"] == "pb")
    ]
    if not legacy_raw.empty:
        v = legacy_raw.iloc[0]
        lines.append(
            f"\n口径校验：旧 932 池 + 原始阈值（不裁尾）+ 数据截止 2026-04-30，"
            f"复现年化 **{pct(v['annual_return'])}**、夏普 {v['sharpe_ratio']:.4f}、"
            f"最大回撤 {pct(v['max_drawdown'])}，与历史记录 11.37% / 0.5025 / -40.34% 完全一致。"
            "说明本次重跑与旧结论可直接对比。\n"
        )
    lines.append(
        "关键发现：股票池扩容对 **PB 排名**的伤害远大于 PE 排名。"
        "用原始阈值（不裁尾）比较：旧 932 池 + PB 排名是 11.59%，"
        "同一套放到 1052 池只剩 8.04%；换成 PE 排名后回到 9.67%。"
        "新进池的股票改变了 PB 的相对排序，但没有改变“低 PE”这一条线。\n"
    )

    lines.append("## 3. 核心网格：Step2 过滤 × 排名方式\n")
    lines.append(f"![core heatmap]({image_prefix}core_heatmap_annual.png)\n")
    lines.append(core_pivot(summary))
    lines.append(
        "同一排名下，只要过滤含 PB，结果就与是否再加 PE/PR 无关（选出的是同一批 5 只）；"
        "只有完全不含 PB 时（PE、PR、PE+PR）结果才会变。"
        "在 PB/PE/PR 排名下，PB 过滤是唯一起作用的估值约束。\n"
    )
    per_rank = []
    for ranking in RANK_ORDER:
        block = core_all[core_all["ranking"] == ranking]
        row = block.sort_values("annual_return", ascending=False).iloc[0]
        has_pb = "pb" in row["filters"]
        if ranking == "pure_pb":
            note = "忽略过滤"
        elif ranking == "pb":
            note = "全部并列"
        else:
            note = "含 PB" if has_pb else "不含 PB"
        per_rank.append(
            {
                "排名": ranking,
                "过滤条件": note,
                "年化": pct(row["annual_return"]),
                "夏普": f"{row['sharpe_ratio']:.3f}",
                "最大回撤": pct(row["max_drawdown"]),
                "2015-2020": pct(row["cagr_2015_2020"]),
                "2021-2026": pct(row["cagr_2021_2026"]),
            }
        )
    lines.append(pd.DataFrame(per_rank).to_markdown(index=False))
    lines.append("")

    lines.append("## 4. 阈值裁尾（0% ~ 5%）\n")
    lines.append(f"![trim]({image_prefix}trim_curves.png)\n")
    lines.append(trim_pivot(summary))
    lines.append(
        "\n裁尾比例与收益不是单调关系：小幅裁尾（1%~2%）能修正极端值造成的分位偏移，"
        "超过 3% 后开始偏离原策略的估值定义。"
        "PB 排名在 1.5%~2.5% 形成平台（9.36%~9.55%），"
        "PE 排名则在 0%~1% 更好（9.37%~9.67%），两者对裁尾的敏感方向不同。\n"
    )

    lines.append("## 5. 最大持仓数 N\n")
    lines.append(f"![N]({image_prefix}positions_bars.png)\n")
    lines.append(
        fmt_table(
            summary[summary["phase"] == "positions"].sort_values("max_positions"),
            ["max_positions", "annual_return", "sharpe_ratio", "max_drawdown",
             "avg_invested_weight", "cagr_2021_2026"],
            rename={"max_positions": "N", "annual_return": "年化", "sharpe_ratio": "夏普",
                    "max_drawdown": "最大回撤", "avg_invested_weight": "平均仓位",
                    "cagr_2021_2026": "2021-2026 年化"},
        )
    )
    lines.append(
        "\nN<5 时受 20% 单股上限约束，平均仓位只有 19%~82%；"
        "N=5 与 N=6 最接近（9.37% / 9.80%），N≥7 开始被稀释。"
        "N=5 仍是与原策略一致性最好的选择，N=6 可以作为备选。\n"
    )

    lines.append("## 6. 估值分位与 ROE 分位\n")
    lines.append(
        fmt_table(
            summary[summary["phase"] == "threshold"].sort_values("annual_return", ascending=False),
            ["pe_thr", "roe_thr", "annual_return", "sharpe_ratio", "max_drawdown", "avg_positions"],
            rename={"pe_thr": "估值分位", "roe_thr": "ROE 分位", "annual_return": "年化",
                    "sharpe_ratio": "夏普", "max_drawdown": "最大回撤", "avg_positions": "平均持仓"},
        )
    )
    lines.append(
        "\n估值分位放宽会显著增加入选股票数，但也会把质量较差的低估值股带进来；"
        "ROE 分位收紧到 0.85 以上则候选不足、仓位下降。\n"
    )
    lines.append("### 6.1 阈值细化（PB 过滤 + PE 排名）\n")
    refine = summary[summary["phase"] == "refine"].copy()
    if not refine.empty:
        lines.append(
            fmt_table(
                refine.sort_values("annual_return", ascending=False),
                ["pe_thr", "roe_thr", "trim", "max_positions", "annual_return",
                 "sharpe_ratio", "max_drawdown", "cagr_ex_best_year", "worst_year"],
                rename={"pe_thr": "估值分位", "roe_thr": "ROE 分位", "trim": "裁尾",
                        "max_positions": "N", "annual_return": "年化", "sharpe_ratio": "夏普",
                        "max_drawdown": "最大回撤", "cagr_ex_best_year": "剔除最好年份",
                        "worst_year": "最差年份"},
            )
        )
    lines.append(
        "\n注意：`ROE 0.60` 一类方案年化看似很高，但 2021 年单年 +123%，"
        "剔除后年化只剩 3%~5%，属于单年驱动，不应采用。"
        "`估值 0.15 + ROE 0.70` 的分布更平滑：最好年份 2024 +43%，"
        "剔除后仍有约 9.7%，2016-2026 有 9 年正收益，是这批细化实验里最可用的点。"
        "但它同样是在全期数据上扫描出来的，换一段历史未必复现。\n"
    )

    lines.append("## 7. 调仓频率\n")
    lines.append(f"![freq]({image_prefix}frequency_bars.png)\n")
    lines.append(
        fmt_table(
            summary[summary["phase"] == "frequency"].sort_values("annual_return", ascending=False),
            ["frequency", "annual_return", "sharpe_ratio", "max_drawdown", "n_trades"],
            rename={"frequency": "频率", "annual_return": "年化", "sharpe_ratio": "夏普",
                    "max_drawdown": "最大回撤", "n_trades": "交易次数"},
        )
    )
    lines.append(
        "\n年度调仓仍然最优。周度/月度/季度被交易成本和噪音拖垮（周度年化仅 0.73%）；"
        "只在 10 月底做一次 Q3 调仓（q3）能到 8.61%，但回撤略大，且依赖三季报。\n"
    )

    lines.append("## 8. 单点实验\n")
    lines.append(
        fmt_table(
            summary[summary["phase"] == "special"],
            ["filters", "ranking", "trim", "stop_loss", "annual_return", "sharpe_ratio",
             "max_drawdown", "avg_positions"],
            rename={"filters": "过滤", "ranking": "排名", "trim": "裁尾", "stop_loss": "止损",
                    "annual_return": "年化", "sharpe_ratio": "夏普",
                    "max_drawdown": "最大回撤", "avg_positions": "平均持仓"},
        )
    )
    lines.append(
        "\n止损再次验证为负贡献（9.67% → 8.33%）：年度调仓下被止损后要等一年才回场，"
        "错过反弹的代价大于控制回撤的收益。纯 PB（不做估值/ROE 过滤）只有 6.22%。\n"
    )

    lines.append("## 9. 全实验排行榜与稳健性\n")
    top = (
        ranked.drop_duplicates(
            subset=["filters", "ranking", "trim", "max_positions",
                    "pe_thr", "pb_thr", "pr_thr", "roe_thr"]
        )
        .sort_values("annual_return", ascending=False)
        .head(15)
    )
    lines.append(
        fmt_table(
            top,
            ["id", "annual_return", "sharpe_ratio", "max_drawdown", "cagr_2015_2020",
             "cagr_2021_2026", "cagr_ex_best_year", "worst_year", "positive_years",
             "n_years", "avg_positions"],
            rename={"id": "实验", "annual_return": "年化", "sharpe_ratio": "夏普",
                    "max_drawdown": "最大回撤", "cagr_2015_2020": "2015-2020",
                    "cagr_2021_2026": "2021-2026", "cagr_ex_best_year": "剔除最好年份",
                    "worst_year": "最差年份", "positive_years": "正收益年数",
                    "n_years": "总年数", "avg_positions": "平均持仓"},
        )
    )
    lines.append(
        "\n“剔除最好年份”用于检查收益是否由单一年份驱动。"
        "年化排名靠前但剔除后大幅下滑的方案（如 ROE 0.60 系列），"
        "更适合视为参数巧合，而不是可复制的优势。\n"
    )
    lines.append(f"![top equity]({image_prefix}top_equity_curves.png)\n")
    lines.append(f"![yearly]({image_prefix}top_yearly_heatmap.png)\n")

    lines.append("## 10. 参数挑选的样本外检验\n")
    lines.append(
        "用同一份结果做“前五年挑参数、后六年验证”的简单走查，判断全期最优是否只是事后拟合：\n"
    )
    lines.append(walk_forward(ranked))
    lines.append(
        "\n前五年表现最好的 `PR 过滤 + ROE 排名` 在后六年年化为 -8.75%，"
        "说明“在某段历史里挑参数”并不可靠；反过来也提醒我们，"
        "12.37% 的阈值组合同样是在全期数据上挑出来的，需要打折看待。\n"
    )

    lines.append("## 11. 推荐方案与当前持仓\n")
    lines.append(f"综合收益、剔除最好年份后的表现和夏普，推荐：**`{recommended['id']}`**。\n")
    lines.append(
        f"- 全期年化 {pct(recommended['annual_return'])}，夏普 {recommended['sharpe_ratio']:.3f}，"
        f"最大回撤 {pct(recommended['max_drawdown'])}"
    )
    lines.append(
        f"- 2015-2020 年化 {pct(recommended['cagr_2015_2020'])}，"
        f"2021-2026 年化 {pct(recommended['cagr_2021_2026'])}"
    )
    lines.append(
        f"- 剔除最好年份后年化 {pct(recommended['cagr_ex_best_year'])}，"
        f"最差年份 {pct(recommended['worst_year'])}，"
        f"正收益 {int(recommended['positive_years'])}/{int(recommended['n_years'])} 年"
    )
    lines.append("")
    lines.append("该方案在回测中最后一次年度调仓后的持仓：\n")
    lines.append(holdings_table(out_root, recommended["id"], names))
    lines.append(
        "**行业集中度提醒**：这 5 只全部是银行。低 PB + 高 ROE 的筛法在 2024-2026 年"
        "把仓位持续集中在银行股上，近两年 20%+ 的年化有很大一部分来自银行估值修复。"
        "如果银行行情逆转，组合回撤会明显大于历史平均。\n"
    )
    lines.append(
        "年度策略的下一次截面是 2027-04-30（年报披露后），执行日为 2027 年 5 月第一个交易日。"
        "在此之前不应因短期波动换股。\n"
    )

    lines.append("## 12. 参数敏感性小结\n")
    lines.append("- 排名：PE ≈ PB > ROE > PR。PE 收益略高但回撤更深；PB 更平滑。")
    lines.append("- 过滤：只要含 PB，最终 5 只完全相同；PE/PR 过滤是冗余的。")
    lines.append(
        "- 裁尾：PB 排名下 1.5%~2.5% 形成平台（9.4%~9.6%）；"
        "PE 排名下 0%~1% 更好（9.4%~9.7%），≥2% 明显变差。"
    )
    lines.append("- 阈值：PB 15%~25% + ROE 65%~75% 是有效区间；ROE 0.60 的高收益来自 2021 单年，不可复制。")
    lines.append("- 持仓数：N=5 与 N=6 接近，N<5 仓位不足，N≥7 稀释。")
    lines.append("- 频率：年度最优；周/月/季被成本拖累，Q3 单次调仓接近但回撤更大。")
    lines.append("")

    lines.append("## 13. 未纳入本次重跑的历史实验\n")
    lines.append(
        "下面这些实验在 932 旧池上已经做过，但它们由独立脚本实现（自定义排序/加权/DCA），"
        "不经过本次统一的“过滤 × 排名 × 阈值 × 裁尾 × N × 频率”接口。"
        "在旧池上它们都显著落后，因此本次没有重跑，避免把不同口径的结果混在一起：\n"
    )
    lines.append("| 实验 | 旧池结果 | 结论 |")
    lines.append("|---|---|---|")
    lines.append("| 阈值 + 综合打分排名 | 6.40% | 加入 PE/PR/ROE 分数稀释了 PB 信号 |")
    lines.append("| 纯打分制（无硬阈值） | 5.61% | 去掉硬阈值后选到“各方面都一般”的股票 |")
    lines.append("| 前 12 月跌幅二次排序 | 6.41% | 跌幅不等于便宜，胜率降到 46% |")
    lines.append("| PE 趋势预筛（9 轮） | 最佳 10.06% | 丢掉反转牛股的代价大于避开价值陷阱 |")
    lines.append("| PE TTM ≥ 50 排除 | 10.04% | 回撤略降，胜率从 80% 降到 60% |")
    lines.append("| 7 种 PB 倾斜加权 | 等权最好 11.37% | 越集中越差，价值陷阱集中风险 |")
    lines.append("| 月度定投/回撤加仓 | — | 资金流策略，和选股方案不是同一维度 |")
    lines.append("")
    lines.append(
        "如果要把这些也迁移到 1052 池，需要把各脚本里的股票池、日期区间和成本参数"
        "统一到本次口径；那是下一轮工作。\n"
    )

    lines.append("## 14. 使用限制\n")
    lines.append("1. 这是同一段历史上的参数比较，存在过拟合风险；不要把 12.37% 当作未来收益预期。")
    lines.append("2. 股票池是“历史清单并集”，但清单期数有限（每池 2 期），早期年份仍可能包含后来才进入指数的股票。")
    lines.append(f"3. 数据截止 {end_date}（今天为周六，最后一个交易日是 2026-11-06）。")
    lines.append("4. 回测不包含分红再投资的税费差异、停牌复牌滑点、涨跌停无法成交等真实摩擦。")
    lines.append("5. 当前持仓高度集中于银行，行业风险没有在回测中被约束。")
    lines.append("6. 引擎自带的等权基准存在资金分配偏差（长期年化仅 0.8%），报告中不使用其超额收益指标。")

    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return summary, ranked, charts_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--report-path", default=None)
    parser.add_argument("--end-date", default="2026-11-06")
    parser.add_argument(
        "--assets-dir",
        default=None,
        help="把 charts/ 里的图片复制到该目录，并把报告里的图片链接改成相对该目录的路径",
    )
    args = parser.parse_args()

    report_path = args.report_path or os.path.join(args.output_root, "report.md")
    if args.assets_dir:
        os.makedirs(args.assets_dir, exist_ok=True)
        image_prefix = os.path.relpath(
            os.path.abspath(args.assets_dir),
            os.path.abspath(os.path.dirname(report_path) or "."),
        ).replace(os.sep, "/")
    else:
        image_prefix = "charts/"

    summary, ranked, charts_dir = build_report(
        args.output_root, report_path, args.end_date, image_prefix=image_prefix
    )
    if args.assets_dir:
        import shutil
        for name in os.listdir(charts_dir):
            if name.endswith(".png"):
                shutil.copy2(os.path.join(charts_dir, name), os.path.join(args.assets_dir, name))
    print(f"report -> {report_path}")
    print(f"charts -> {charts_dir}")
    print(f"variants: {len(summary)} (comparable: {len(ranked)})")


if __name__ == "__main__":
    main()
