#!/usr/bin/env python3
"""
生成 1052 / 932 双池、M1/M2/M3/M3b 四口径的合并报告。
"""

from __future__ import annotations

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

DATA_DIR = os.path.join(PROJECT_DIR, "data", "processed", "backtesting", "consolidated_20261120")
IMG_DIR = os.path.join(PROJECT_DIR, "docs", "img", "consolidated-2026-11")
REPORT = os.path.join(PROJECT_DIR, "docs", "consolidated-metrics-2026-11.md")

FILTER_LABEL = {
    "pe": "PE",
    "pb": "PB",
    "pr": "PR",
    "pe+pb": "PE+PB",
    "pe+pr": "PE+PR",
    "pb+pr": "PB+PR",
    "pe+pb+pr": "PE+PB+PR",
}


def short(row) -> str:
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
    return (
        f"{filt}/ROE{int(row['roe_thr'] * 100)} "
        f"{row['ranking']} {trim} N{int(row['max_positions'])}"
    )


def pct(x) -> str:
    return f"{x * 100:.2f}%" if pd.notna(x) else "—"


def num(x) -> str:
    return f"{x:.3f}" if pd.notna(x) else "—"


def chart_best(best: pd.DataFrame) -> None:
    metrics = ["M1", "M2", "M3", "M3b"]
    labels = ["M1\nfull 2015", "M2\nsince 2016", "M3\n2015-start", "M3b\n2015 since"]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    x = np.arange(len(metrics))
    for offset, pool, color in [(-0.2, "1052", "#4C72B0"), (0.2, "932", "#C44E52")]:
        sub = best[best["池子"] == pool].set_index("指标").reindex(metrics)
        values = sub["数值"].values * 100
        ax.bar(x + offset, values, 0.4, label=f"{pool} best", color=color)
        for xi, v in zip(x + offset, values):
            ax.text(xi, v + 0.15, f"{v:.2f}", ha="center", fontsize=8)
    ax.set_xticks(x, labels)
    ax.set_ylabel("Annualized return (%)")
    ax.set_title("Best config per metric: 1052 vs 932")
    ax.grid(axis="y", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(IMG_DIR, "best_by_metric_pools.png"), dpi=160)
    plt.close(fig)


def chart_scatter(df: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(7.5, 6))
    for pool, color in [("1052", "#4C72B0"), ("932", "#C44E52")]:
        sub = df[df["pool"] == pool]
        ax.scatter(sub["M1"] * 100, sub["M3"] * 100, s=16, alpha=0.55, color=color, label=pool)
    lim = [0, 13]
    ax.plot(lim, lim, "k--", lw=0.8)
    for pool, color in [("1052", "#1f4e79"), ("932", "#8c1d1d")]:
        row = df[df["pool"] == pool].sort_values("M3", ascending=False).iloc[0]
        ax.scatter([row["M1"] * 100], [row["M3"] * 100], s=80, color=color, marker="*", zorder=5)
        offset = (-4.2, 1.2) if pool == "1052" else (0.5, -1.8)
        ax.annotate(
            f"{pool} best",
            (row["M1"] * 100, row["M3"] * 100),
            xytext=(row["M1"] * 100 + offset[0], row["M3"] * 100 + offset[1]),
            fontsize=8,
        )
    ax.set_xlabel("M1: full 2015 annualized (%)")
    ax.set_ylabel("M3: 2015-start annualized (%)")
    ax.set_title("All configs: M1 vs M3, colored by pool")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(IMG_DIR, "scatter_m1_m3_pools.png"), dpi=160)
    plt.close(fig)


def md_table(df: pd.DataFrame, columns: dict[str, str]) -> str:
    out = df[list(columns)].rename(columns=columns).copy()
    for col in out.columns:
        if col in {"M1", "M2", "M3", "M3b", "2015(M3)", "2016(M3)"}:
            out[col] = out[col].map(pct)
        elif col in {"M1 夏普", "M3 夏普", "M1 回撤", "M3 回撤"}:
            out[col] = out[col].map(lambda x: f"{x:.3f}" if pd.notna(x) else "—")
    return out.to_markdown(index=False)


def main():
    os.makedirs(IMG_DIR, exist_ok=True)
    df = pd.read_csv(os.path.join(DATA_DIR, "consolidated.csv"), dtype={"pool": str})
    keys = pd.read_csv(os.path.join(DATA_DIR, "key_configs.csv"), dtype={"池子": str})
    best = pd.read_csv(os.path.join(DATA_DIR, "best_by_metric.csv"), dtype={"池子": str})

    chart_best(best)
    chart_scatter(df)

    # top 8 by M1 / M3 per pool, short labels
    allowed = {"core", "trim", "positions", "threshold", "refine"}
    top_tables = {}
    for metric in ["M1", "M3"]:
        for pool in ["1052", "932"]:
            sub = df[
                (df["pool"] == pool) & (df["phase"].isin(allowed))
            ].drop_duplicates(subset=[metric]).sort_values(
                metric, ascending=False
            ).head(8).copy()
            sub["label"] = sub.apply(short, axis=1)
            top_tables[(metric, pool)] = sub

    # pool gap for key configs
    gap = keys.pivot_table(index="配置", columns="池子", values=["M1", "M3"])
    gap_rows = []
    for label in keys["配置"].unique():
        if label not in gap.index:
            continue
        m1 = gap.loc[label, "M1"]
        m3 = gap.loc[label, "M3"]
        gap_rows.append(
            {
                "配置": label,
                "1052 M1": m1.get("1052"),
                "932 M1": m1.get("932"),
                "M1 差(932-1052)": (m1.get("932") - m1.get("1052")) if pd.notna(m1.get("1052")) and pd.notna(m1.get("932")) else np.nan,
                "1052 M3": m3.get("1052"),
                "932 M3": m3.get("932"),
                "M3 差(932-1052)": (m3.get("932") - m3.get("1052")) if pd.notna(m3.get("1052")) and pd.notna(m3.get("932")) else np.nan,
            }
        )
    gap_df = pd.DataFrame(gap_rows)

    lines = []
    lines.append("# 1052 vs 932：全部回测合并对比（M1/M2/M3/M3b）\n")
    lines.append("- 数据：两池各 131/133 组参数，标准回测 + 2015-start 回测，共 **262 组匹配**")
    lines.append("- 截止日：2026-11-06（价格快照，统一截断）")
    lines.append("- M1 = 标准回测全期年化（2015-01 起，含 2015 空仓）")
    lines.append("- M2 = 标准回测首次建仓以来（2016-05 起）")
    lines.append("- M3 = 2015-start 回测全期年化（2015-05 建仓）")
    lines.append("- M3b = 2015-start 回测首次建仓以来（2015-05 起）")
    lines.append("")
    lines.append("## 0. 结论\n")
    lines.append(
        "1. **M1/M2 下 932 略高**：M1 12.55% vs 12.37%，M2 14.26% vs 14.05%。"
        "这主要是 932 单期清单的幸存者偏差。"
    )
    lines.append(
        "2. **M3/M3b 下 1052 反超**：M3 10.92% vs 10.73%，M3b 11.25% vs 11.05%。"
        "因为 1052 最佳配置的 2015 年损失更小（-7.91% vs -9.05%）。"
    )
    lines.append(
        "3. **两池的最佳配置不同**：1052 是 `PB15/ROE70 + PE 排名`，932 是 `PE25/ROE75 + PB 排名`。"
        "把对方的“最佳”搬过来会明显变差：1052 最佳在 932 只有 10.61%（M1），"
        "932 最佳在 1052 只有 8.63%（M1）。"
    )
    lines.append(
        "4. **经典配置的池间差异最大**：PE+PB+PR / PB 排名 / 1% 裁尾，"
        "932 是 12.06%，1052 只有 8.63%；2% 裁尾则收敛到 9.02% vs 9.55%。"
    )
    lines.append(
        "5. **结论**：参数必须绑定股票池；M1 用于历史对照，M3b 作为“自 2015 年首次可建仓以来”的主口径，M3 用于全期检查。"
    )
    lines.append("")
    lines.append("![best by metric](img/consolidated-2026-11/best_by_metric_pools.png)\n")
    lines.append("## 1. 各指标下的最佳\n")
    best_fmt = best.copy()
    best_fmt["数值"] = best_fmt["数值"].map(pct)
    lines.append(
        md_table(
            best_fmt,
            {"指标": "指标", "池子": "池子", "配置": "配置", "数值": "最佳值",
             "M1": "M1", "M3": "M3"},
        )
    )
    lines.append("")
    lines.append(
        "注意：M1/M2 的最佳是 932 的 PE25/ROE75/PB 配置；M3/M3b 的最佳是 1052 的 PB15/ROE70/PE 配置。"
    )
    lines.append("")
    lines.append("## 2. 关键配置的池间横向对比\n")
    lines.append(
        md_table(
            keys,
            {"配置": "配置", "池子": "池子", "M1": "M1", "M2": "M2", "M3": "M3", "M3b": "M3b",
             "M1 夏普": "M1 夏普", "M3 夏普": "M3 夏普", "2015(M3)": "2015(M3)", "2016(M3)": "2016(M3)"},
        )
    )
    lines.append("")
    lines.append("### 2.1 同一配置的池间差\n")
    gap_fmt = gap_df.copy()
    for col in ["1052 M1", "932 M1", "1052 M3", "932 M3"]:
        gap_fmt[col] = gap_fmt[col].map(lambda x: f"{x*100:.2f}%" if pd.notna(x) else "—")
    for col in ["M1 差(932-1052)", "M3 差(932-1052)"]:
        gap_fmt[col] = gap_fmt[col].map(lambda x: f"{x*100:+.2f}pp" if pd.notna(x) else "—")
    lines.append(
        md_table(
            gap_fmt,
            {"配置": "配置", "1052 M1": "1052 M1", "932 M1": "932 M1", "M1 差(932-1052)": "M1 差",
             "1052 M3": "1052 M3", "932 M3": "932 M3", "M3 差(932-1052)": "M3 差"},
        )
    )
    lines.append("")
    lines.append("## 3. 按 M1 的前 8 名（分池）\n")
    for pool in ["1052", "932"]:
        lines.append(f"### {pool} 池\n")
        sub = top_tables[("M1", pool)]
        lines.append(md_table(sub, {"label": "配置", "M1": "M1", "M2": "M2", "M3": "M3", "M3b": "M3b"}))
        lines.append("")
    lines.append("## 4. 按 M3 的前 8 名（分池）\n")
    for pool in ["1052", "932"]:
        lines.append(f"### {pool} 池\n")
        sub = top_tables[("M3", pool)]
        lines.append(md_table(sub, {"label": "配置", "M1": "M1", "M2": "M2", "M3": "M3", "M3b": "M3b"}))
        lines.append("")
    lines.append("## 5. 全部配置的 M1 vs M3\n")
    lines.append("![scatter](img/consolidated-2026-11/scatter_m1_m3_pools.png)\n")
    lines.append(
        "932 的点整体在 1052 上方（M1 更高），但差距在 M3 下明显收窄；"
        "45° 线附近的结构说明：股票池主要影响 2015-2016 的起点，2017 年以后两池的选股差异才是长期收益差异的来源。"
    )
    lines.append("")
    lines.append("## 6. 口径选择：为什么可以把 M3b 当主口径\n")
    lines.append(
        "如果回到 2015 年，真实流程是：4 月底知道 2014 年报 → 5 月第一个交易日建仓 → 经历 2015 年 5-12 月。"
        "M3b 正好对应这个路径：\n"
    )
    lines.append("- M1 把 2015 年 1-4 月空仓也算进分母（不真实：你 5 月就会建仓）；")
    lines.append("- M2 从 2016-05 才开始（完全跳过 2015 年股灾，过于乐观）；")
    lines.append("- M3 从 2015-01 算，但 1-4 月还是空仓；")
    lines.append("- **M3b 从 2015-05-04 实际建仓起算，是四者中最贴近真实年度建仓体验的。**")
    lines.append("")
    lines.append("| 口径 | 1052 最佳 | 932 最佳 | 适合回答 |")
    lines.append("|---|---:|---:|---|")
    lines.append("| M1 | 12.37% | 12.55% | 和历史记录对齐 |")
    lines.append("| M2 | 14.05% | 14.26% | 2016 年以来 |")
    lines.append("| M3 | 10.92% | 10.73% | 2015 全期（含 1-4 月空仓） |")
    lines.append("| **M3b** | **11.25%** | **11.05%** | **自 2015 年首次可建仓以来（推荐主口径）** |")
    lines.append("")
    lines.append("三点限制：")
    lines.append(
        "1. 2015 年的股票池仍是用 2025-26 年清单回推的，真实 2015 年投资者不知道这些成分股；"
        "M3b 没有消除这层偏差。"
    )
    lines.append(
        "2. 2015 截面跳过新股过滤是近似修复；真实上市日未知，2015 篮子里可能混有真正的新股。"
    )
    lines.append(
        "3. 2015 是单一极端年份（股灾），M3b 的水平受它影响很大；它更真实，但不比 M1 更“统计稳定”。"
        "排序上 M3b 与 M3 几乎完全一致（Spearman 0.9999），所以选参数时两者可以互相验证。"
    )
    lines.append("")
    lines.append("## 7. 建议\n")
    lines.append("1. **实际使用 1052 池**：用 1052 最佳（PB15/ROE70 + PE 排名 + 1% 裁尾 + N5，M3b 11.25%）或经典 2%（M3b 8.14%）。")
    lines.append("2. **不要套用 932 最佳**：它在 1052 上 M3b 只有 7.19%。")
    lines.append("3. **跨池比较看 M3b**：M1/M2 的 932 优势主要来自清单偏差；M3b 下 1052 反而略高（11.25% vs 11.05%）。")
    lines.append("4. **保留经典 2% 作为稳健基准**：两池 M3b 差距最小（8.14% vs 7.56%），参数平台也更宽。")
    lines.append("")
    lines.append("## 8. 文件\n")
    lines.append("- 合并总表：[consolidated.csv](../data/processed/backtesting/consolidated_20261120/consolidated.csv)")
    lines.append("- 关键配置：[key_configs.csv](../data/processed/backtesting/consolidated_20261120/key_configs.csv)")
    lines.append("- 各指标最佳：[best_by_metric.csv](../data/processed/backtesting/consolidated_20261120/best_by_metric.csv)")
    lines.append("- 生成脚本：[build_consolidated_metrics.py](../backtesting/build_consolidated_metrics.py)")
    lines.append("- 原始报告：[1052](universe-backtest-2026-11.md) / [932](universe-backtest-932-2026-11.md) / [三口径](three-start-metrics-2026-11.md)")

    with open(REPORT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    print(f"report -> {REPORT}")
    print(f"rows -> {len(df)}")


if __name__ == "__main__":
    main()
