#!/usr/bin/env python3
"""
生成以 M3b 为主口径的 1052 / 932 全量回测报告。
M1 / M2 / M3 作为辅助列保留。
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
sys.path.insert(0, BASE_DIR)

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

DATA = os.path.join(PROJECT_DIR, "data", "processed", "backtesting", "m3b_20261120", "m3b_annual.csv")
IMG = os.path.join(PROJECT_DIR, "docs", "img", "m3b-2026-11")
REPORT = os.path.join(PROJECT_DIR, "docs", "m3b-backtest-2026-11.md")
ROOTS = {
    "1052": os.path.join(PROJECT_DIR, "data", "processed", "backtesting", "universe_compare_2015start_20261120"),
    "932": os.path.join(PROJECT_DIR, "data", "processed", "backtesting", "universe_compare_legacy932_2015start_20261120"),
}

FILTER_ORDER = ["pe", "pb", "pr", "pe+pb", "pe+pr", "pb+pr", "pe+pb+pr"]
RANK_ORDER = ["pb", "pe", "pr", "roe", "pure_pb"]
GRID_PHASES = {"core", "trim", "positions", "threshold", "refine"}
FILTER_LABEL = {
    "pe": "PE", "pb": "PB", "pr": "PR", "pe+pb": "PE+PB",
    "pe+pr": "PE+PR", "pb+pr": "PB+PR", "pe+pb+pr": "PE+PB+PR",
}


def pct(x, d=2):
    return f"{x * 100:.{d}f}%" if pd.notna(x) else "—"


def num(x, d=3):
    return f"{x:.{d}f}" if pd.notna(x) else "—"


def short(row):
    trim = "raw" if str(row["trim"]) == "raw" else f"{float(row['trim']) * 100:g}%"
    pe, pb, pr = (int(row[k] * 100) for k in ("pe_thr", "pb_thr", "pr_thr"))
    if row["filters"] == "pe":
        filt = f"PE{pe}"
    elif row["filters"] == "pb":
        filt = f"PB{pb}"
    elif row["filters"] == "pr":
        filt = f"PR{pr}"
    else:
        filt = f"{FILTER_LABEL.get(row['filters'], row['filters'])} {pe}/{pb}/{pr}"
    return f"{filt}/ROE{int(row['roe_thr'] * 100)} {row['ranking']} {trim} N{int(row['max_positions'])}"


def table(df, cols):
    out = df[list(cols)].rename(columns=cols).copy()
    for col in out.columns:
        if col in {"M1", "M2", "M3", "M3b", "2015", "2016"}:
            out[col] = out[col].map(pct)
        elif col in {"M3b 夏普", "M3b 回撤", "M1 夏普", "M1 回撤"}:
            out[col] = out[col].map(lambda x: f"{x:.3f}" if pd.notna(x) else "—")
    return out.to_markdown(index=False)


def chart_leaderboard(df):
    grid = df[df["phase"].isin(GRID_PHASES)]
    top = grid.sort_values("M3b", ascending=False).drop_duplicates(subset=["M3b"]).head(15).copy()
    top["label"] = top.apply(short, axis=1)
    top = top.sort_values("M3b")
    colors = ["#4C72B0" if p == "1052" else "#C44E52" for p in top["pool"]]
    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.barh(top["label"], top["M3b"] * 100, color=colors)
    for b, v in zip(bars, top["M3b"] * 100):
        ax.text(v + 0.08, b.get_y() + b.get_height() / 2, f"{v:.2f}", va="center", fontsize=8)
    ax.set_xlabel("M3b annualized return (%)")
    ax.set_title("Top 15 by M3b (since 2015-05-04) — blue=1052, red=932")
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(IMG, "m3b_leaderboard.png"), dpi=160)
    plt.close(fig)


def chart_core(df):
    core = df[df["phase"] == "core"]
    for pool in ["1052", "932"]:
        sub = core[core["pool"] == pool]
        pivot = sub.pivot(index="filters", columns="ranking", values="M3b")
        pivot = pivot.reindex(index=FILTER_ORDER, columns=RANK_ORDER)
        values = pivot.to_numpy(dtype=float) * 100
        fig, ax = plt.subplots(figsize=(8.5, 5.2))
        im = ax.imshow(values, cmap="RdYlGn", aspect="auto")
        ax.set_xticks(range(len(pivot.columns)), pivot.columns)
        ax.set_yticks(range(len(pivot.index)), pivot.index)
        ax.set_xlabel("Ranking method")
        ax.set_ylabel("Step-2 filter (ROE always step 3)")
        ax.set_title(f"{pool} pool — M3b annualized return (%)")
        for i in range(values.shape[0]):
            for j in range(values.shape[1]):
                if np.isnan(values[i, j]):
                    continue
                ax.text(j, i, f"{values[i, j]:.2f}", ha="center", va="center", fontsize=9)
        fig.colorbar(im, ax=ax, shrink=0.85)
        fig.tight_layout()
        fig.savefig(os.path.join(IMG, f"m3b_core_{pool}.png"), dpi=160)
        plt.close(fig)


def chart_pool_scatter(df):
    common = df[df["pool"] == "1052"].merge(
        df[df["pool"] == "932"], on="sig", suffixes=("_1052", "_932")
    )
    fig, ax = plt.subplots(figsize=(7.5, 6))
    ax.scatter(common["M3b_1052"] * 100, common["M3b_932"] * 100, s=16, alpha=0.6, color="#4C72B0")
    lim = [-1, 12]
    ax.plot(lim, lim, "k--", lw=0.8)
    ax.set_xlabel("M3b — 1052 pool (%)")
    ax.set_ylabel("M3b — 932 pool (%)")
    ax.set_title(f"Same config, both pools (n={len(common)}); dashed = equal")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(IMG, "m3b_pool_scatter.png"), dpi=160)
    plt.close(fig)


def chart_yearly(df):
    picks = []
    for pool in ["1052", "932"]:
        sub = df[(df["pool"] == pool) & (df["phase"].isin(GRID_PHASES))]
        sub = sub.sort_values("M3b", ascending=False).drop_duplicates(subset=["M3b"]).head(5)
        picks.append(sub)
    picks = pd.concat(picks)
    years = list(range(2015, 2027))
    data, labels = [], []
    for _, row in picks.iterrows():
        path = os.path.join(ROOTS[row["pool"]], "runs", row["y15_id"], "annual_returns.csv")
        if not os.path.exists(path):
            continue
        ar = pd.read_csv(path).set_index("year")["strategy_return"].reindex(years)
        data.append(ar.values * 100)
        labels.append(f"{row['pool']} | {short(row)}")
    data = np.array(data)
    fig, ax = plt.subplots(figsize=(12, 0.52 * len(labels) + 2))
    im = ax.imshow(data, cmap="RdYlGn", aspect="auto", vmin=-40, vmax=60)
    ax.set_xticks(range(len(years)), years, rotation=45)
    ax.set_yticks(range(len(labels)), labels, fontsize=7)
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            if np.isnan(data[i, j]):
                continue
            ax.text(j, i, f"{data[i, j]:.0f}", ha="center", va="center", fontsize=7)
    ax.set_title("Annual returns of top 5 M3b strategies per pool (%)")
    fig.colorbar(im, ax=ax, shrink=0.8)
    fig.tight_layout()
    fig.savefig(os.path.join(IMG, "m3b_yearly_top.png"), dpi=160)
    plt.close(fig)


def chart_best_vs(df):
    metrics = ["M1", "M2", "M3", "M3b"]
    labels = ["M1\nfull 2015", "M2\nsince 2016", "M3\n2015-start", "M3b\nsince 2015-05"]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    x = np.arange(len(metrics))
    for offset, pool, color in [(-0.2, "1052", "#4C72B0"), (0.2, "932", "#C44E52")]:
        row = df[df["pool"] == pool].sort_values("M3b", ascending=False).iloc[0]
        values = [row[m] * 100 for m in metrics]
        ax.bar(x + offset, values, 0.4, label=f"{pool} best by M3b", color=color)
        for xi, v in zip(x + offset, values):
            ax.text(xi, v + 0.15, f"{v:.2f}", ha="center", fontsize=8)
    ax.set_xticks(x, labels)
    ax.set_ylabel("Annualized return (%)")
    ax.set_title("Best M3b config, shown under all four metrics")
    ax.grid(axis="y", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(IMG, "m3b_best_vs_others.png"), dpi=160)
    plt.close(fig)


def main():
    global DATA, IMG, REPORT, ROOTS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default=DATA)
    parser.add_argument("--img-dir", default=IMG)
    parser.add_argument("--report", default=REPORT)
    parser.add_argument("--root-1052", default=ROOTS["1052"])
    parser.add_argument("--root-932", default=ROOTS["932"])
    args = parser.parse_args()

    DATA, IMG, REPORT = args.data, args.img_dir, args.report
    ROOTS = {"1052": args.root_1052, "932": args.root_932}

    os.makedirs(IMG, exist_ok=True)
    df = pd.read_csv(DATA, dtype={"pool": str})
    df["label"] = df.apply(short, axis=1)

    chart_leaderboard(df)
    chart_core(df)
    chart_pool_scatter(df)
    chart_yearly(df)
    chart_best_vs(df)

    best = {}
    for pool in ["1052", "932"]:
        best[pool] = df[df["pool"] == pool].sort_values("M3b", ascending=False).iloc[0]

    lines = []
    lines.append("# M3b 主口径：1052 vs 932 全量回测报告（2026-11）\n")
    lines.append(
        "- **主指标 M3b**：2015 年 5 月首个交易日建仓（2014 年报披露后），"
        "从实际建仓日起算的年化收益。"
    )
    lines.append("- 辅助指标：M1（2015 含空仓）、M2（2016 建仓以来）、M3（2015 全期）。")
    lines.append(f"- 样本：**{len(df)} 组年度配置**（1052: {(df.pool=='1052').sum()}，932: {(df.pool=='932').sum()}）")
    lines.append("- 数据：2026-11-20 价格快照，统一截止 **2026-11-06**。")
    lines.append("")
    lines.append("## 0. 结论\n")
    lines.append(
        f"1. **M3b 全场最佳**：`{best['1052']['key']}`，"
        f"M3b **{pct(best['1052']['M3b'])}**，夏普 {num(best['1052']['M3b_sharpe'])}，"
        f"回撤 {pct(best['1052']['M3b_mdd'])}。"
    )
    lines.append(
        f"2. **932 最佳**：`{best['932']['key']}`，M3b **{pct(best['932']['M3b'])}**，"
        f"夏普 {num(best['932']['M3b_sharpe'])}，回撤 {pct(best['932']['M3b_mdd'])}。"
    )
    lines.append(
        "3. **M3b 下 1052 略高**（11.25% vs 11.05%），与 M1 下 932 更高（12.55% vs 12.37%）相反；"
        "M3b 把 2015 年股灾计入后，1052 最佳配置的 2015 损失更小。"
    )
    lines.append(
        "4. **参数不能跨池套用**：1052 最佳在 932 的 M3b 是 9.51%，932 最佳在 1052 的 M3b 只有 7.19%。"
    )
    lines.append(
        "5. **经典 2% 仍是最稳的跨池基准**：M3b 1052 8.14%、932 7.56%。"
    )
    lines.append("")
    lines.append("![best](img/m3b-2026-11/m3b_best_vs_others.png)\n")
    lines.append("## 1. 口径与数据\n")
    lines.append("| 指标 | 起点 | 含义 |")
    lines.append("|---|---|---|")
    lines.append("| **M3b（主）** | 2015-05-04 | 2014 年报后首次建仓，满仓起算 |")
    lines.append("| M1 | 2015-01-05 | 含 2015 年 1-4 月空仓 |")
    lines.append("| M2 | 2016-05-03 | 跳过 2015 股灾 |")
    lines.append("| M3 | 2015-01-05 | 2015 全期，含 1-4 月空仓 |")
    lines.append("")
    lines.append(
        "2014 年报覆盖：1052 只财务文件中有 **730 只**含 2014-12-31 年报且 `ann_available_date <= 2015-04-30`；"
        "缺失的基本是 2014 年后上市的新股。2015 年 5 月建仓时同时可利用 2015 一季报（750 只），"
        "所以“知道 2014 年报后建仓”这个前提成立。"
    )
    lines.append("")
    lines.append("## 2. M3b 参数网格总排行榜（前 20）\n")
    lines.append(
        "只含参数网格（核心网格、裁尾、持仓数、阈值、细化），不含止损/纯 PB 等特殊实验；"
        "同分只保留一个代表。\n"
    )
    grid = df[df["phase"].isin(GRID_PHASES)]
    top = grid.sort_values("M3b", ascending=False).drop_duplicates(subset=["M3b"]).head(20)
    lines.append(
        table(
            top,
            {"pool": "池子", "label": "配置", "M3b": "M3b", "M1": "M1", "M3": "M3",
             "M3b_sharpe": "M3b 夏普", "M3b_mdd": "M3b 回撤"},
        )
    )
    lines.append("")
    lines.append("![leaderboard](img/m3b-2026-11/m3b_leaderboard.png)\n")
    lines.append("## 3. 分池前 10（M3b，参数网格）\n")
    for pool in ["1052", "932"]:
        lines.append(f"### {pool} 池\n")
        sub = grid[grid["pool"] == pool].sort_values("M3b", ascending=False).drop_duplicates(subset=["M3b"]).head(10)
        lines.append(
            table(
                sub,
                {"label": "配置", "M3b": "M3b", "M1": "M1", "M3": "M3",
                 "M3b_sharpe": "M3b 夏普", "M3b_mdd": "M3b 回撤"},
            )
        )
        lines.append("")
    lines.append("## 4. 核心网格（M3b）\n")
    lines.append(
        "核心网格固定为 Step2 25% / ROE 75% / 裁尾 1% / N=5，是基线；"
        "整体最佳来自第 5 节的阈值细化（1052 的 PB15/ROE70）。\n"
    )
    for pool in ["1052", "932"]:
        core = df[(df["pool"] == pool) & (df["phase"] == "core")]
        pivot = core.pivot(index="filters", columns="ranking", values="M3b")
        pivot = pivot.reindex(index=FILTER_ORDER, columns=RANK_ORDER)
        out = pivot.map(lambda x: pct(x) if pd.notna(x) else "—")
        out.index.name = "过滤"
        out.columns.name = "排名"
        lines.append(f"### {pool} 池\n")
        lines.append(out.reset_index().to_markdown(index=False))
        lines.append(f"\n![core {pool}](img/m3b-2026-11/m3b_core_{pool}.png)\n")
    lines.append("## 5. 裁尾 / 持仓数 / 阈值（M3b）\n")
    trim = df[(df["phase"] == "trim") & (df["filters"] == "pe+pb+pr") & (df["ranking"] == "pb")]
    lines.append("### 5.1 经典配置的裁尾\n")
    lines.append(
        table(
            trim.sort_values("trim"),
            {"pool": "池子", "trim": "裁尾", "M3b": "M3b", "M1": "M1", "M3b_sharpe": "M3b 夏普"},
        )
    )
    lines.append("")
    pos = df[df["phase"] == "positions"]
    lines.append("### 5.2 持仓数 N\n")
    lines.append(
        table(
            pos.sort_values(["pool", "max_positions"]),
            {"pool": "池子", "max_positions": "N", "M3b": "M3b", "M1": "M1",
             "M3b_sharpe": "M3b 夏普", "M3b_mdd": "M3b 回撤"},
        )
    )
    lines.append("")
    lines.append("### 5.3 阈值细化（前 12，M3b）\n")
    refine = df[df["phase"].isin(["threshold", "refine"])].sort_values("M3b", ascending=False).head(12)
    lines.append(
        table(
            refine,
            {"pool": "池子", "label": "配置", "M3b": "M3b", "M1": "M1", "M3": "M3"},
        )
    )
    lines.append("")
    lines.append("### 5.4 特殊实验（M3b）\n")
    special = df[df["phase"] == "special"].sort_values(["pool", "M3b"], ascending=[True, False])
    lines.append(
        table(
            special,
            {"pool": "池子", "key": "实验", "M3b": "M3b", "M1": "M1", "M3b_sharpe": "M3b 夏普"},
        )
    )
    lines.append("")
    lines.append("## 6. 1052 vs 932 同配置对比\n")
    common = df[df["pool"] == "1052"].merge(
        df[df["pool"] == "932"], on="sig", suffixes=("_1052", "_932")
    )
    lines.append(f"两池可匹配的年度配置：**{len(common)} 组**。\n")
    key_sigs = [
        ("1052 最佳", "pb", "pe", "0.01", 0.15, 0.70),
        ("932 最佳", "pe", "pb", "0.01", 0.25, 0.75),
        ("经典 1%", "pe+pb+pr", "pb", "0.01", 0.25, 0.75),
        ("经典 2%", "pe+pb+pr", "pb", "0.02", 0.25, 0.75),
        ("经典 raw", "pe+pb+pr", "pb", "raw", 0.25, 0.75),
    ]
    rows = []
    for label, filters, ranking, trim_v, pb_thr, roe in key_sigs:
        sub = common[
            (common["filters_1052"] == filters) & (common["ranking_1052"] == ranking)
            & (common["trim_1052"] == trim_v) & (common["pb_thr_1052"] == pb_thr)
            & (common["roe_thr_1052"] == roe)
        ]
        if sub.empty:
            continue
        r = sub.iloc[0]
        rows.append(
            {
                "配置": label,
                "1052 M3b": r["M3b_1052"],
                "932 M3b": r["M3b_932"],
                "差(932-1052)": r["M3b_932"] - r["M3b_1052"],
            }
        )
    if rows:
        gap = pd.DataFrame(rows)
        gap["1052 M3b"] = gap["1052 M3b"].map(pct)
        gap["932 M3b"] = gap["932 M3b"].map(pct)
        gap["差(932-1052)"] = gap["差(932-1052)"].map(lambda x: f"{x*100:+.2f}pp")
        lines.append(gap.to_markdown(index=False))
    lines.append("")
    lines.append("![pool scatter](img/m3b-2026-11/m3b_pool_scatter.png)\n")
    lines.append("## 7. 逐年收益（M3b 前 5 / 池）\n")
    lines.append("![yearly](img/m3b-2026-11/m3b_yearly_top.png)\n")
    lines.append("## 8. 与 M1 的排序一致性\n")
    for pool in ["1052", "932"]:
        sub = df[(df["pool"] == pool) & (df["phase"].isin(GRID_PHASES))]
        corr = sub[["M1", "M3b"]].corr(method="spearman").iloc[0, 1]
        t10_m1 = set(sub.sort_values("M1", ascending=False).head(10)["key"])
        t10_m3b = set(sub.sort_values("M3b", ascending=False).head(10)["key"])
        lines.append(
            f"- {pool}：Spearman **{corr:.4f}**，M1 前 10 与 M3b 前 10 重叠 **{len(t10_m1 & t10_m3b)}/10**。"
        )
    lines.append("")
    lines.append("## 9. 建议\n")
    lines.append("1. **主口径用 M3b**：它对应“2014 年报后、2015 年 5 月建仓”的真实路径。")
    lines.append("2. **1052 实际使用**：1052 最佳（PB15/ROE70 + PE 排名 + 1% 裁尾 + N5，M3b 11.25%）。")
    lines.append("3. **稳健基准**：经典 2%（M3b 1052 8.14% / 932 7.56%），跨池最稳。")
    lines.append("4. **不要套用 932 最佳**：它在 1052 的 M3b 只有 7.19%。")
    lines.append("5. **未来 2027 回测**：先跑标准 + 2015-start 两套矩阵，再用 `build_m3b_dataset.py` + 本报告脚本，M3b 自动成为主表。")
    lines.append("")
    lines.append("## 10. 复现\n")
    lines.append("```bash")
    lines.append("cd backtesting")
    lines.append("# 标准矩阵")
    lines.append("../.venv/bin/python universe_compare.py --pool union --end-date <最新交易日>")
    lines.append("../.venv/bin/python universe_compare.py --pool legacy --end-date <最新交易日>")
    lines.append("# 2015-start 矩阵")
    lines.append("../.venv/bin/python universe_compare.py --pool union --end-date <最新交易日> --ignore-first-new-stock")
    lines.append("../.venv/bin/python universe_compare.py --pool legacy --end-date <最新交易日> --ignore-first-new-stock")
    lines.append("# 汇总 + M3b 报告")
    lines.append("../.venv/bin/python build_consolidated_metrics.py")
    lines.append("../.venv/bin/python build_m3b_dataset.py")
    lines.append("../.venv/bin/python build_m3b_report.py")
    lines.append("```")
    lines.append("")
    lines.append("## 11. 文件\n")
    lines.append("- M3b 年度数据集：[m3b_annual.csv](../data/processed/backtesting/m3b_20261120/m3b_annual.csv)")
    lines.append("- 合并总表：[consolidated.csv](../data/processed/backtesting/consolidated_20261120/consolidated.csv)")
    lines.append("- 三口径报告：[three-start-metrics-2026-11.md](three-start-metrics-2026-11.md)")
    lines.append("- 1052 报告：[universe-backtest-2026-11.md](universe-backtest-2026-11.md)")
    lines.append("- 932 报告：[universe-backtest-932-2026-11.md](universe-backtest-932-2026-11.md)")

    with open(REPORT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    print(f"report -> {REPORT}")
    print(f"rows -> {len(df)}")


if __name__ == "__main__":
    main()
