#!/usr/bin/env python3
"""
生成单股票池（默认旧 932 池）的全角度回测报告，并与 1052 并集池做同条件对比。
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

import build_universe_report as bur  # noqa: E402

FILTER_ORDER = bur.FILTER_ORDER
RANK_ORDER = bur.RANK_ORDER
KEY = [
    "filters", "ranking", "trim", "max_positions",
    "pe_thr", "pb_thr", "pr_thr", "roe_thr", "frequency", "stop_loss",
]


def load_pool(root):
    summary, annual = bur.load_runs(root)
    summary = bur.add_robustness(summary, annual)
    return summary, annual


def pick(summary, **conds):
    sub = summary
    for key, value in conds.items():
        sub = sub[sub[key] == value]
    return sub.iloc[0] if not sub.empty else None


def chart_core(summary, charts_dir, label):
    core = summary[summary["phase"] == "core"]
    pivot = core.pivot(index="filters", columns="ranking", values="annual_return")
    pivot = pivot.reindex(index=FILTER_ORDER, columns=RANK_ORDER)
    values = pivot.to_numpy(dtype=float) * 100
    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    im = ax.imshow(values, cmap="RdYlGn", aspect="auto")
    ax.set_xticks(range(len(pivot.columns)), pivot.columns)
    ax.set_yticks(range(len(pivot.index)), pivot.index)
    ax.set_xlabel("Ranking method")
    ax.set_ylabel("Step-2 valuation filter (ROE always step 3)")
    ax.set_title(f"Core grid — annualized return (%) — {label}")
    for i in range(values.shape[0]):
        for j in range(values.shape[1]):
            if np.isnan(values[i, j]):
                continue
            ax.text(j, i, f"{values[i, j]:.2f}", ha="center", va="center", fontsize=9)
    fig.colorbar(im, ax=ax, shrink=0.85)
    fig.tight_layout()
    fig.savefig(os.path.join(charts_dir, "core_heatmap_932.png"), dpi=160)
    plt.close(fig)


def chart_ranking_compare(legacy, union, charts_dir):
    rows = []
    for ranking in RANK_ORDER:
        a = legacy[legacy["phase"] == "core"]
        a = a[a["ranking"] == ranking].sort_values("annual_return", ascending=False)
        b = union[union["phase"] == "core"]
        b = b[b["ranking"] == ranking].sort_values("annual_return", ascending=False)
        if a.empty or b.empty:
            continue
        rows.append(
            {
                "ranking": ranking,
                "932": a.iloc[0]["annual_return"] * 100,
                "1052": b.iloc[0]["annual_return"] * 100,
            }
        )
    frame = pd.DataFrame(rows)
    x = np.arange(len(frame))
    fig, ax = plt.subplots(figsize=(8, 4.6))
    ax.bar(x - 0.2, frame["932"], 0.4, label="932 legacy pool", color="#4C72B0")
    ax.bar(x + 0.2, frame["1052"], 0.4, label="1052 union pool", color="#DD8452")
    for i, (a, b) in enumerate(zip(frame["932"], frame["1052"])):
        ax.text(i - 0.2, a + 0.1, f"{a:.2f}", ha="center", fontsize=8)
        ax.text(i + 0.2, b + 0.1, f"{b:.2f}", ha="center", fontsize=8)
    ax.set_xticks(x, frame["ranking"])
    ax.set_ylabel("Annualized return (%)")
    ax.set_title("Best annualized return per ranking: 932 vs 1052")
    ax.grid(axis="y", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(charts_dir, "ranking_compare_932_vs_1052.png"), dpi=160)
    plt.close(fig)


def chart_yearly_compare(selected, annual, charts_dir):
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
    ax.set_title("Annual returns: 932 vs 1052 (%)")
    fig.colorbar(im, ax=ax, shrink=0.8)
    fig.tight_layout()
    fig.savefig(os.path.join(charts_dir, "yearly_compare_932_vs_1052.png"), dpi=160)
    plt.close(fig)


def chart_top_equity(summary, out_root, charts_dir, selected, pool_label):
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
    ax.set_title(f"Selected schemes — {pool_label}")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=9, loc="upper left")
    fig.tight_layout()
    fig.savefig(os.path.join(charts_dir, "top_equity_932.png"), dpi=160)
    plt.close(fig)


def comparison_rows(legacy, union):
    """同一组参数在两个池子上的结果。"""
    conditions = [
        ("PB+ROE 25/75 → PB rank, 裁尾 1%",
         dict(filters="pe+pb+pr", ranking="pb", trim="0.01", max_positions=5,
              pe_thr=0.25, pb_thr=0.25, pr_thr=0.25, roe_thr=0.75)),
        ("PB+ROE 25/75 → PB rank, 裁尾 2%",
         dict(filters="pe+pb+pr", ranking="pb", trim="0.02", max_positions=5,
              pe_thr=0.25, pb_thr=0.25, pr_thr=0.25, roe_thr=0.75)),
        ("PB+ROE 25/75 → PB rank, 原始阈值",
         dict(filters="pe+pb+pr", ranking="pb", trim="raw", max_positions=5,
              pe_thr=0.25, pb_thr=0.25, pr_thr=0.25, roe_thr=0.75)),
        ("PB+ROE 25/75 → PE rank, 裁尾 1%",
         dict(filters="pb", ranking="pe", trim="0.01", max_positions=5,
              pe_thr=0.25, pb_thr=0.25, pr_thr=0.25, roe_thr=0.75)),
        ("PB 15% + ROE 70% → PE rank, 裁尾 1%",
         dict(filters="pb", ranking="pe", trim="0.01", max_positions=5,
              pe_thr=0.15, pb_thr=0.15, pr_thr=0.25, roe_thr=0.70)),
    ]
    rows = []
    for label, cond in conditions:
        a = pick(legacy, **cond)
        b = pick(union, **cond) if union is not None else None
        rows.append(
            {
                "条件": label,
                "932 年化": bur.pct(a["annual_return"]) if a is not None else "—",
                "932 夏普": f"{a['sharpe_ratio']:.3f}" if a is not None else "—",
                "932 回撤": bur.pct(a["max_drawdown"]) if a is not None else "—",
                "1052 年化": bur.pct(b["annual_return"]) if b is not None else "—",
                "1052 夏普": f"{b['sharpe_ratio']:.3f}" if b is not None else "—",
                "1052 回撤": bur.pct(b["max_drawdown"]) if b is not None else "—",
            }
        )
    return pd.DataFrame(rows)


def fmt(df, cols, rename=None):
    return bur.fmt_table(df, cols, rename=rename)


def build(out_root, report_path, end_date, compare_root=None, image_prefix="charts/"):
    image_prefix = image_prefix.rstrip("/") + "/"
    summary, annual = load_pool(out_root)
    union, union_annual = (load_pool(compare_root) if compare_root else (None, None))
    if union is not None:
        union = union[
            (union["pool"] == "union")
            & (~union["phase"].astype(str).str.startswith("val"))
        ].copy()
    charts_dir = os.path.join(out_root, "charts")
    os.makedirs(charts_dir, exist_ok=True)

    summary = summary.sort_values("annual_return", ascending=False)
    best = summary.iloc[0]
    best_sharpe = summary.loc[summary["sharpe_ratio"].idxmax()]
    best_robust = summary.sort_values("robust_rank").iloc[0]
    core = summary[summary["phase"] == "core"]
    core_best = core.sort_values("annual_return", ascending=False).iloc[0]
    pool_size = int(summary["pool_size"].max())
    names = bur.load_stock_names()

    chart_core(summary, charts_dir, "932 legacy pool")
    chart_ranking_compare(summary, union, charts_dir) if union is not None else None

    def find(**conds):
        sub = summary
        for k, v in conds.items():
            sub = sub[sub[k] == v]
        return sub.iloc[0]["id"] if not sub.empty else None

    selected = {f"Best 932 ({best['annual_return']*100:.2f}%)": best["id"]}
    for key, prefix in [
        ((("phase", "core"), ("filters", "pe+pb+pr"), ("ranking", "pb")),
         "Classic: PB25/ROE75→PB, 1%"),
        ((("phase", "core"), ("filters", "pb"), ("ranking", "pe")),
         "PB25/ROE75→PE, 1%"),
    ]:
        run_id = find(**dict(key))
        if run_id:
            row = summary[summary["id"] == run_id].iloc[0]
            selected[f"{prefix} ({row['annual_return']*100:.2f}%)"] = run_id
    chart_top_equity(summary, out_root, charts_dir, selected, "932 legacy pool")

    if union is not None:
        u_best = union.sort_values("annual_return", ascending=False).iloc[0]
        yearly_selected = {
            f"932 best ({best['annual_return']*100:.2f}%)": best["id"],
            f"1052 best ({u_best['annual_return']*100:.2f}%)": u_best["id"],
        }
        legacy_classic = find(phase="trim", filters="pe+pb+pr", ranking="pb", trim="raw")
        if legacy_classic:
            yearly_selected["932 classic PB-rank raw"] = legacy_classic
        u_classic = pick(union, phase="trim", filters="pe+pb+pr", ranking="pb", trim="0.02")
        if u_classic is not None:
            yearly_selected["1052 classic PB-rank 2%"] = u_classic["id"]
        merged_annual = dict(annual)
        merged_annual.update(union_annual)
        chart_yearly_compare(yearly_selected, merged_annual, charts_dir)

    lines = []
    lines.append(f"# {pool_size} 只旧股票池（932 版）：全角度回测、最佳条件与 1052 池对比\n")
    lines.append(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"- 回测区间：2015-01-01 ~ {end_date}")
    lines.append(
        f"- 股票池：**{pool_size} 只**，由 7 份单期清单（2025-12 ~ 2026-03）直接并集，"
        "不含后来新增的历史清单"
    )
    lines.append(f"- 实验数量：{len(summary)} 组")
    lines.append("- 成本、数据、引擎与 1052 池那轮完全一致")
    lines.append("")
    lines.append(
        "> 先澄清：上一轮跑的不是 1050 只，而是 7 个指数池全部 14 份清单的并集 **1052 只**。"
        "本报告是用户要求的 932 旧池版本，用于和 1052 池做同条件对比。"
    )
    lines.append(
        "> 932 池只用了一期清单，本质上是“今天还留在指数里的股票”，"
        "幸存者偏差比 1052 并集更重，因此它的绝对收益会天然偏高。"
    )
    lines.append("")
    lines.append("## 1. 932 池的最佳条件\n")
    lines.append(
        "筛选方法：131 组参数组合，统一引擎、数据（截至 2026-11-06）、成本与 2015-01-01 起点。"
        "先跑核心网格（7 种 Step2 过滤 × 5 种排名，固定裁尾 1%、N=5）共 35 组；"
        "再围绕核心优胜者扫描裁尾 0~5%、N=1~10、估值分位 10%~40%、ROE 分位 60%~90%、"
        "7 种调仓频率、止损和纯 PB。按全期年化收益排序（同分看夏普），"
        "并用 2015-2020 / 2021-2026 分段、剔除最好年份、正收益年数和回撤做稳健性检查。\n"
    )
    lines.append(
        f"**收益最高**：`{best['id']}`，年化 **{best['annual_return']*100:.2f}%**，"
        f"夏普 {best['sharpe_ratio']:.3f}，最大回撤 {best['max_drawdown']*100:.2f}%，"
        f"剔除最好年份后 {best['cagr_ex_best_year']*100:.2f}%，"
        f"正收益 {int(best['positive_years'])}/{int(best['n_years'])} 年。"
    )
    lines.append(
        f"**风险调整最优**：`{best_sharpe['id']}`，夏普 {best_sharpe['sharpe_ratio']:.3f}，"
        f"年化 {best_sharpe['annual_return']*100:.2f}%。"
    )
    lines.append(
        f"**核心网格最佳**：`{core_best['filters']} 过滤 + {core_best['ranking']} 排名`，"
        f"年化 {core_best['annual_return']*100:.2f}%。"
    )
    lines.append(
        "注意：最佳条件的估值分位在 15%~40% 之间结果完全相同，"
        "说明真正起作用的是“排除高 PE/高 PR”这道粗筛，具体分位点并不敏感；"
        "决定选股的是 PB 最低排名。\n"
    )
    lines.append("**最佳条件写法**：\n")
    lines.append("| 维度 | 取值 |")
    lines.append("|---|---|")
    lines.append("| 调仓频率 | 年度（4 月底截面，5 月第一个交易日执行） |")
    lines.append("| Step2 过滤 | PE < 25% 分位（15%~40% 结果相同） |")
    lines.append("| Step3 ROE | ROE > 75% 分位 |")
    lines.append("| 排名 | PB 最低，取前 5 |")
    lines.append("| 阈值裁尾 | 单边 1% |")
    lines.append("| 最大持仓 | 5 只等权 |")
    lines.append(
        f"| 回测结果 | 年化 {best['annual_return']*100:.2f}%，"
        f"夏普 {best['sharpe_ratio']:.3f}，回撤 {best['max_drawdown']*100:.2f}% |"
    )
    lines.append("")
    lines.append("### 1.1 推荐方案当前持仓\n")
    lines.append(bur.holdings_table(out_root, best["id"], names))
    lines.append("")
    lines.append("### 1.2 为什么这次是常熟银行，而不是东航物流？\n")
    lines.append(
        "2026-04-30 截面、932 池、846 只有估值数据的股票。两种阈值下的分位线：\n"
    )
    lines.append("| 阈值 | 原始分位（无裁尾） | 单边裁尾 1% |")
    lines.append("|---|---:|---:|")
    lines.append("| PE 25% 分位 | < 15.38 | < 15.56 |")
    lines.append("| PB 25% 分位 | < 1.352 | < 1.373 |")
    lines.append("| PR 25% 分位 | < 1.187 | < 1.214 |")
    lines.append("| ROE 75% 分位 | > 14.105 | > 13.855 |")
    lines.append("")
    lines.append("| 股票 | PE | PB | PR | ROE |")
    lines.append("|---|---:|---:|---:|---:|")
    lines.append("| 601128 常熟银行 | 5.63 | 0.780 | 0.400 | 14.090 |")
    lines.append("| 601156 东航物流 | 9.36 | 1.314 | 0.657 | 14.250 |")
    lines.append("")
    lines.append(
        "- **原始阈值**：常熟银行 ROE 14.090，比 14.105 的门槛低 **0.015 个百分点**，"
        "Step 3 被剔除；恰好只有 5 只通过四步，东航物流是第 5 只，所以全部持有。"
    )
    lines.append(
        "- **裁尾 1%**：ROE 门槛降到 13.855，常熟银行入选；共 7 只通过，"
        "按 PB 排序常熟 0.780 排第 1，东航 1.314 排第 6（第 7 是京能电力 1.367），"
        "东航被挤出前 5。"
    )
    lines.append(
        "- 过滤条件在这个截面也不影响结果：只用 PE 过滤与 PE+PB+PR 三指标过滤，"
        "在原始阈值和 1% 裁尾下选出的 5 只完全相同，所以不是“PE 过滤换掉了东航”。"
    )
    lines.append(
        "- 所以差别来自**裁尾**，不是股票池：常熟银行和东航物流在 932 池和 1052 池里都有。"
        "这也说明在“恰好 5 只通过”的年份，组合对阈值极其敏感——0.015pp 的 ROE 差异就能换掉一只持仓。"
    )
    lines.append("")

    lines.append("### 1.3 两套持仓从 2026-05-06 到 2026-11-06 的实际走势\n")
    lines.append(f"![compare]({image_prefix}holdings_compare_since_20260506.png)\n")
    lines.append("| 组合 | 区间收益 | 最大回撤 |")
    lines.append("|---|---:|---:|")
    lines.append("| A：原始阈值（持有东航物流） | **+7.74%** | -10.93% |")
    lines.append("| B：裁尾 1%（持有常熟银行） | **+2.31%** | -12.12% |")
    lines.append("")
    lines.append(
        "差异全部来自第 5 只股票：东航物流 +26.04%，常熟银行 -1.41%，各占 20% 权重。"
        "其余 4 只完全相同：成都银行 +13.35%、中国人保 +5.19%、杭州银行 +3.88%、中国太保 -9.49%。\n"
    )
    lines.append(f"![stocks]({image_prefix}holdings_stock_returns_since_20260506.png)\n")
    lines.append(
        "也就是说，12.55% 的历史优势在这 5 个月里没有兑现。"
        "两套组合只差一只股票，短期胜负的随机性很大，不能据此判断哪套规则更好。\n"
    )

    lines.append("## 2. 核心网格：过滤 × 排名\n")
    lines.append(f"![core]({image_prefix}core_heatmap_932.png)\n")
    lines.append(bur.core_pivot(summary))
    lines.append(
        "\n932 池的结论和 1052 池不一样：这里 **PE/PR 过滤（不含 PB）+ PB 排名** 是 12.55%，"
        "而含 PB 的过滤组合是 12.06%。原因是 PE/PR 先排除了高估值的股票，"
        "PB 排名再从中选最便宜的 5 只；如果过滤层已经要求低 PB，"
        "反而会把一些低 PE 但 PB 略高的股票提前剔除。\n"
    )
    lines.append(
        fmt(
            core.sort_values("annual_return", ascending=False).head(10),
            ["filters", "ranking", "annual_return", "sharpe_ratio", "max_drawdown",
             "cagr_2015_2020", "cagr_2021_2026", "avg_positions"],
            rename={"filters": "过滤", "ranking": "排名", "annual_return": "年化",
                    "sharpe_ratio": "夏普", "max_drawdown": "最大回撤",
                    "cagr_2015_2020": "2015-2020", "cagr_2021_2026": "2021-2026",
                    "avg_positions": "平均持仓"},
        )
    )
    lines.append("")

    lines.append("## 3. 阈值裁尾\n")
    trim = summary[summary["phase"] == "trim"].copy()
    trim["trim_label"] = trim["trim"].map(
        lambda x: "raw" if x == "raw" else f"{float(x) * 100:g}%"
    )
    trim["config"] = trim.apply(
        lambda r: "PE+ROE → PB rank"
        if r["filters"] == "pe" and r["ranking"] == "pb"
        else (
            "PB+ROE → PB rank"
            if r["filters"] == "pe+pb+pr" and r["ranking"] == "pb"
            else None
        ),
        axis=1,
    )
    trim = trim[trim["config"].notna()].drop_duplicates(subset=["config", "trim_label"])
    pivot = trim.pivot(index="trim_label", columns="config", values="annual_return")
    pivot = pivot.reindex(
        columns=[c for c in ["PE+ROE → PB rank", "PB+ROE → PB rank"] if c in pivot.columns]
    )
    order = ["raw", "0%", "0.5%", "1%", "1.5%", "2%", "2.5%", "3%", "4%", "5%"]
    pivot = pivot.reindex([x for x in order if x in pivot.index])
    lines.append(
        pivot.map(lambda x: bur.pct(x) if pd.notna(x) else "—")
        .rename_axis("裁尾")
        .reset_index()
        .to_markdown(index=False)
        + "\n"
    )

    lines.append("## 4. 最大持仓数 N\n")
    lines.append(
        fmt(
            summary[summary["phase"] == "positions"].sort_values("max_positions"),
            ["max_positions", "annual_return", "sharpe_ratio", "max_drawdown",
             "avg_invested_weight", "cagr_2021_2026"],
            rename={"max_positions": "N", "annual_return": "年化", "sharpe_ratio": "夏普",
                    "max_drawdown": "最大回撤", "avg_invested_weight": "平均仓位",
                    "cagr_2021_2026": "2021-2026 年化"},
        )
    )
    lines.append("")

    lines.append("## 5. 估值分位与 ROE 分位\n")
    lines.append(
        fmt(
            summary[summary["phase"] == "threshold"].sort_values("annual_return", ascending=False),
            ["pe_thr", "roe_thr", "annual_return", "sharpe_ratio", "max_drawdown", "avg_positions"],
            rename={"pe_thr": "估值分位", "roe_thr": "ROE 分位", "annual_return": "年化",
                    "sharpe_ratio": "夏普", "max_drawdown": "最大回撤", "avg_positions": "平均持仓"},
        )
    )
    lines.append("\n### 5.1 阈值细化\n")
    lines.append(
        fmt(
            summary[summary["phase"] == "refine"].sort_values("annual_return", ascending=False),
            ["pe_thr", "roe_thr", "trim", "max_positions", "annual_return",
             "sharpe_ratio", "max_drawdown", "cagr_ex_best_year", "worst_year"],
            rename={"pe_thr": "估值分位", "roe_thr": "ROE 分位", "trim": "裁尾",
                    "max_positions": "N", "annual_return": "年化", "sharpe_ratio": "夏普",
                    "max_drawdown": "最大回撤", "cagr_ex_best_year": "剔除最好年份",
                    "worst_year": "最差年份"},
        )
    )
    lines.append("")

    lines.append("## 6. 调仓频率\n")
    lines.append(
        fmt(
            summary[summary["phase"] == "frequency"].sort_values("annual_return", ascending=False),
            ["frequency", "annual_return", "sharpe_ratio", "max_drawdown", "n_trades"],
            rename={"frequency": "频率", "annual_return": "年化", "sharpe_ratio": "夏普",
                    "max_drawdown": "最大回撤", "n_trades": "交易次数"},
        )
    )
    lines.append("")

    lines.append("## 7. 全实验排行榜（前 15）\n")
    top = (
        summary.drop_duplicates(
            subset=["annual_return", "sharpe_ratio", "max_drawdown"]
        )
        .sort_values("annual_return", ascending=False)
        .head(15)
    )
    lines.append(
        fmt(
            top,
            ["id", "annual_return", "sharpe_ratio", "max_drawdown", "cagr_2015_2020",
             "cagr_2021_2026", "cagr_ex_best_year", "positive_years", "avg_positions"],
            rename={"id": "实验", "annual_return": "年化", "sharpe_ratio": "夏普",
                    "max_drawdown": "最大回撤", "cagr_2015_2020": "2015-2020",
                    "cagr_2021_2026": "2021-2026", "cagr_ex_best_year": "剔除最好年份",
                    "positive_years": "正收益年数", "avg_positions": "平均持仓"},
        )
    )
    lines.append("")
    lines.append(f"![top equity]({image_prefix}top_equity_932.png)\n")

    if union is not None:
        u_best = union.sort_values("annual_return", ascending=False).iloc[0]
        lines.append("## 8. 932 vs 1052：同条件对比\n")
        lines.append("### 8.1 关键条件\n")
        lines.append(comparison_rows(summary, union).to_markdown(index=False))
        lines.append(
            "\n这张表说明两件事："
            "（1）经典 PB 排名配置在 932 池上有 12.06%（1% 裁尾）/ 11.59%（原始阈值），"
            "搬到 1052 池只剩 8.63% / 8.04%，扩容主要破坏了 PB 排序；"
            "（2）反过来，1052 池的最佳条件（PB 15% + ROE 70% + PE 排名）在 932 池只有 10.61%。"
            "**两个池子的最优解互不通用。**\n"
        )
        lines.append("### 8.2 各排名的池间差异\n")
        lines.append(f"![ranking]({image_prefix}ranking_compare_932_vs_1052.png)\n")
        lines.append(
            f"932 池的最佳是 `{best['filters']} 过滤 + {best['ranking']} 排名`"
            f"（{best['annual_return']*100:.2f}%）；"
            f"1052 池的最佳是 `{u_best['filters']} 过滤 + {u_best['ranking']} 排名`"
            f"（{u_best['annual_return']*100:.2f}%）。"
            "两池的排名偏好并不一致，说明“最佳排名”会随股票池变化，不是一个稳定参数。\n"
        )
        lines.append("### 8.3 逐年收益\n")
        lines.append(f"![yearly]({image_prefix}yearly_compare_932_vs_1052.png)\n")
        lines.append(
            "932 最佳方案在 2021 年 +56%、2022 年 -23%，波动明显大于 1052 最佳"
            "（2021 +26%、2022 +1%）。两者年化接近（12.55% vs 12.37%），"
            "但 1052 最佳更平滑，剔除最好年份后也略高（9.65% vs 9.20%）。\n"
        )

    lines.append("## 9. 结论\n")
    lines.append(
        f"1. 932 池上收益最好的条件是“PE 过滤 + ROE>75% + PB 最低排名 + 裁尾 1% + N=5 + 年度”，"
        f"年化 {best['annual_return']*100:.2f}%，夏普 {best['sharpe_ratio']:.3f}，"
        f"回撤 {best['max_drawdown']*100:.2f}%。"
    )
    legacy_classic_raw = pick(
        summary, phase="trim", filters="pe+pb+pr", ranking="pb", trim="raw"
    )
    if legacy_classic_raw is not None:
        lines.append(
            f"2. 经典配置（PB+ROE → PB 排名、原始阈值）在 932 池上是 "
            f"{bur.pct(legacy_classic_raw['annual_return'])}，"
            "与历史记录的 11.37% 同量级；差额来自数据延长到 2026-11-06。"
        )
    lines.append(
        "2b. 但把最佳条件换到另一个池子就不成立：932 最佳条件在 1052 只有 8.63%，"
        "1052 最佳条件在 932 只有 10.61%——说明“最优排名/阈值”本身高度依赖股票池。"
    )
    lines.append(
        "3. 持仓数：N=5 最好（12.55%），N=6 次之（11.87%），N<4 仓位不足；"
        "裁尾 1% 最好，1.5% 以后明显变差；频率必须年度。"
    )
    lines.append(
        "4. 932 池的高收益不能直接搬到 1052 池：经典的 PB 排名配置在并集池低约 3pp，"
        "但 PE 排名/更严 PB 的角落并非如此。**最优解依赖股票池，不存在一套跨池都最好的参数。**"
    )
    lines.append("")
    lines.append("## 10. 使用限制\n")
    lines.append("1. 932 池是单期清单，幸存者偏差比 1052 并集更重，绝对收益只能用于“同池内比较”。")
    lines.append("2. 最佳条件是全期参数扫描的结果，存在过拟合风险。")
    lines.append("3. 数据截止 2026-11-06；成本假设与主回测一致。")

    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--compare-root", default=None)
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

    summary = build(
        args.output_root, report_path, args.end_date, args.compare_root,
        image_prefix=image_prefix,
    )
    if args.assets_dir:
        import shutil
        charts_dir = os.path.join(args.output_root, "charts")
        for name in os.listdir(charts_dir):
            if name.endswith(".png"):
                shutil.copy2(os.path.join(charts_dir, name), os.path.join(args.assets_dir, name))
    print(f"report -> {report_path}")
    print(f"variants: {len(summary)}")


if __name__ == "__main__":
    main()
