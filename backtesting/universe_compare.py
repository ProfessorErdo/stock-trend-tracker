#!/usr/bin/env python3
"""
全股票池（1052 只）多角度回测对比驱动脚本。

背景
----
2026-11 指数清单更新后，股票池从旧版 932 只（仅 2025-12 ~ 2026-03 一期清单）
合并为 1052 只（历史各期清单取并集）。本脚本用现有 backtest_engine 重新跑
历史上做过的各角度对比：

  1. core      : 7 种 Step2 过滤组合 × 5 种排名方式（年度、N=5、裁尾 1%）
  2. pool      : 股票池版本对比（932 旧池 / 953 仅最新清单 / 1052 历史并集）
  3. trim      : 阈值单边裁尾 0%~5%
  4. positions : 最大持仓数 N=1..10
  5. threshold : 估值分位与 ROE 分位扫描
  6. frequency : 周/月/季/年度/年度+Q3/半年/Q3
  7. special   : 纯 PB、止损、关闭裁尾等单点实验

所有回测统一截止到 --end-date（默认 2026-10-30，即上一周最后一个交易日），
避免本周尚未更新完的价格数据导致截面不一致。

每个实验的完整结果写入 runs/<id>/，汇总写入 summary.csv。
"""

import argparse
import copy
import gc
import json
import logging
import os
import sys
import time
from datetime import datetime

import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
sys.path.insert(0, BASE_DIR)

import config  # noqa: E402
import data_loader  # noqa: E402
import stock_selector  # noqa: E402
import backtest_engine  # noqa: E402
from backtest_engine import run_backtest  # noqa: E402
from performance import calculate_performance  # noqa: E402

DEFAULT_POOL_FILES = copy.deepcopy(config.EXISTING_STOCK_POOL_FILES)

# 旧版 932 只池：合并清单之前使用的 7 份单期清单
LEGACY_POOL_FILES = {
    "hs300": [os.path.join(PROJECT_DIR, "data", "input", "hs300_list_20251213.csv")],
    "zz500": [os.path.join(PROJECT_DIR, "data", "input", "zz500_list_20251216.csv")],
    "hongli": [os.path.join(PROJECT_DIR, "data", "input", "hongli_list_20251213.csv")],
    "honglidibo": [os.path.join(PROJECT_DIR, "data", "input", "honglidibo_list_20251213.csv")],
    "gz100": [os.path.join(PROJECT_DIR, "data", "input", "gz100_list_20260227.csv")],
    "gzfc": [os.path.join(PROJECT_DIR, "data", "input", "gzfc_list_20260227.csv")],
    "zzfc": [os.path.join(PROJECT_DIR, "data", "input", "zzfc_list_20260316.csv")],
}

FILTER_SETS = [
    ["pe"],
    ["pb"],
    ["pr"],
    ["pe", "pb"],
    ["pe", "pr"],
    ["pb", "pr"],
    ["pe", "pb", "pr"],
]
RANKINGS = ["pb", "pe", "pr", "roe", "pure_pb"]

_log = logging.getLogger("universe_compare")

# ---------------------------------------------------------------------------
# 数据缓存：1052 只股票 × 数百个截面，原始实现每个截面都会重新读 CSV，
# 这里把价格/财务/交易日历/基准缓存到内存，单次回测从 ~21s 降到数秒。
# ---------------------------------------------------------------------------
_price_cache = {}
_fin_cache = {}
_calendar_cache = {}
_benchmark_cache = {}

_orig_load_price = data_loader.load_price_data
_orig_load_fin = data_loader.load_financial_data
_orig_build_calendar = backtest_engine.build_trading_calendar
_orig_benchmark = backtest_engine.compute_benchmark_equity_curve


def _cached_price(code):
    if code not in _price_cache:
        _price_cache[code] = _orig_load_price(code)
    return _price_cache[code]


def _cached_fin(code):
    if code not in _fin_cache:
        _fin_cache[code] = _orig_load_fin(code)
    return _fin_cache[code]


def _cached_calendar(start_date="2015-01-01", end_date=None):
    key = (start_date, end_date)
    if key not in _calendar_cache:
        _calendar_cache[key] = _orig_build_calendar(start_date, end_date)
    return _calendar_cache[key]


def _cached_benchmark(stock_codes, trading_days, cutoffs, price_cache, initial_capital):
    key = (
        tuple(stock_codes),
        trading_days[0],
        trading_days[-1],
        len(cutoffs),
        initial_capital,
    )
    if key not in _benchmark_cache:
        _benchmark_cache[key] = _orig_benchmark(
            stock_codes, trading_days, cutoffs, price_cache, initial_capital
        )
    return _benchmark_cache[key].copy()


def install_caches():
    data_loader.load_price_data = _cached_price
    data_loader.load_financial_data = _cached_fin
    stock_selector.load_price_data = _cached_price
    stock_selector.load_financial_data = _cached_fin
    backtest_engine.load_price_data = _cached_price
    backtest_engine.build_trading_calendar = _cached_calendar
    backtest_engine.compute_benchmark_equity_curve = _cached_benchmark
    # 静默 tqdm 进度条
    backtest_engine.tqdm = lambda iterable, **kwargs: iterable


# ---------------------------------------------------------------------------
# 实验配置
# ---------------------------------------------------------------------------
# 当前整轮实验使用的股票池："union"（并集 1052）、"legacy"（旧 932）、"latest"（953）
ACTIVE_POOL = "union"


def base_spec(**overrides):
    spec = {
        "id": None,
        "phase": "core",
        "pool": ACTIVE_POOL,
        "frequency": "annual",
        "ranking": "pb",
        "filters": ["pe", "pb", "pr"],
        "trim": 0.01,
        "max_positions": 5,
        "pe_thr": 0.25,
        "pb_thr": 0.25,
        "pr_thr": 0.25,
        "roe_thr": 0.75,
        "stop_loss": False,
    }
    spec.update(overrides)
    return spec


def trim_tag(trim):
    return "raw" if trim is None else f"trim{trim * 100:g}pct"


def make_id(spec):
    parts = [
        spec["phase"],
        spec["pool"],
        spec["frequency"],
        "+".join(spec["filters"]) if spec["filters"] else "nofilter",
        spec["ranking"],
        trim_tag(spec["trim"]),
        f"N{spec['max_positions']}",
        f"pe{spec['pe_thr']:g}-pb{spec['pb_thr']:g}-pr{spec['pr_thr']:g}-roe{spec['roe_thr']:g}",
    ]
    if spec["stop_loss"]:
        parts.append("sl")
    return "_".join(parts)


def set_pool(mode):
    if mode == "legacy":
        config.EXISTING_STOCK_POOL_FILES = copy.deepcopy(LEGACY_POOL_FILES)
        config.STOCK_POOL_LATEST_ONLY = False
    elif mode == "latest":
        config.EXISTING_STOCK_POOL_FILES = copy.deepcopy(DEFAULT_POOL_FILES)
        config.STOCK_POOL_LATEST_ONLY = True
    else:
        config.EXISTING_STOCK_POOL_FILES = copy.deepcopy(DEFAULT_POOL_FILES)
        config.STOCK_POOL_LATEST_ONLY = False


def apply_spec(spec):
    set_pool(spec["pool"])
    config.FILTER_INDICATORS = list(spec["filters"])
    config.PE_THRESHOLD = spec["pe_thr"]
    config.PB_THRESHOLD = spec["pb_thr"]
    config.PR_THRESHOLD = spec["pr_thr"]
    config.ROE_THRESHOLD = spec["roe_thr"]
    config.MAX_POSITIONS = spec["max_positions"]
    config.WINSORIZE_ENABLED = spec["trim"] is not None
    config.THRESHOLD_TRIM_RATIO = spec["trim"] if spec["trim"] is not None else 0.01
    config.STOP_LOSS_ENABLED = spec["stop_loss"]


# ---------------------------------------------------------------------------
# 指标计算
# ---------------------------------------------------------------------------
def period_cagr(equity_df, start, end):
    sub = equity_df[
        (equity_df["date"] >= pd.Timestamp(start)) & (equity_df["date"] <= pd.Timestamp(end))
    ]
    if len(sub) < 2:
        return None
    cumulative = sub["strategy_equity"].iloc[-1] / sub["strategy_equity"].iloc[0] - 1
    return float((1 + cumulative) ** (252 / len(sub)) - 1)


def positions_stats(result):
    snaps = [s for s in result["holding_snapshots"] if not s.empty]
    counts = [len(s) for s in snaps]
    invested = [float(s["weight"].sum()) if "weight" in s.columns else None for s in snaps]
    invested = [x for x in invested if x is not None]
    return {
        "n_rebalances": len(counts),
        "avg_positions": float(pd.Series(counts).mean()) if counts else None,
        "min_positions": int(min(counts)) if counts else None,
        "pct_rebalances_under5": float((pd.Series(counts) < 5).mean()) if counts else None,
        "avg_invested_weight": float(pd.Series(invested).mean()) if invested else None,
    }


def run_one(spec, args, out_root):
    spec = dict(spec)
    spec["id"] = make_id(spec)
    apply_spec(spec)
    pool = data_loader.load_stock_pool()
    started = time.time()

    result = run_backtest(
        start_date=args.start_date,
        end_date=args.end_date,
        frequency=spec["frequency"],
        ranking_method=spec["ranking"],
        filter_indicators=spec["filters"],
    )
    if result is None:
        raise RuntimeError(f"backtest returned None for {spec['id']}")

    performance = calculate_performance(
        result["equity_curve"], result["cutoff_dates"], result["trade_records"]
    )
    equity = result["equity_curve"].copy()
    equity["date"] = pd.to_datetime(equity["date"])
    annual = performance["annual_returns"].copy()

    row = {
        "id": spec["id"],
        "phase": spec["phase"],
        "pool": spec["pool"],
        "pool_size": len(pool),
        "frequency": spec["frequency"],
        "ranking": spec["ranking"],
        "filters": "+".join(spec["filters"]) if spec["filters"] else "none",
        "trim": "raw" if spec["trim"] is None else spec["trim"],
        "max_positions": spec["max_positions"],
        "pe_thr": spec["pe_thr"],
        "pb_thr": spec["pb_thr"],
        "pr_thr": spec["pr_thr"],
        "roe_thr": spec["roe_thr"],
        "stop_loss": spec["stop_loss"],
        "annual_return": performance["annual_return"],
        "cumulative_return": performance["cumulative_return"],
        "annual_volatility": performance["annual_volatility"],
        "sharpe_ratio": performance["sharpe_ratio"],
        "max_drawdown": performance["max_drawdown"],
        "calmar": (
            performance["annual_return"] / abs(performance["max_drawdown"])
            if performance["max_drawdown"]
            else None
        ),
        "final_equity": performance["final_equity"],
        "win_rate": performance["win_rate"],
        "profit_loss_ratio": performance["profit_loss_ratio"],
        "benchmark_annual_return": performance["benchmark_annual_return"],
        "excess_return": performance["excess_return"],
        "information_ratio": performance["information_ratio"],
        "trading_days": performance["trading_days"],
        "n_trades": len(result["trade_records"]),
        "first_cutoff": str(result["cutoff_dates"][0].date()),
        "last_cutoff": str(result["cutoff_dates"][-1].date()),
        "equity_end": str(equity["date"].max().date()),
        "cagr_2015_2020": period_cagr(equity, "2015-01-01", "2020-12-31"),
        "cagr_2021_2026": period_cagr(equity, "2021-01-01", "2099-12-31"),
        "cagr_2023_2026": period_cagr(equity, "2023-01-01", "2099-12-31"),
        "best_year": float(annual["strategy_return"].max()),
        "worst_year": float(annual["strategy_return"].min()),
        "positive_years": int((annual["strategy_return"] > 0).sum()),
        "n_years": int(len(annual)),
        "elapsed_s": round(time.time() - started, 1),
    }
    row.update(positions_stats(result))

    # 落盘
    run_dir = os.path.join(out_root, "runs", spec["id"])
    os.makedirs(run_dir, exist_ok=True)
    equity.to_csv(os.path.join(run_dir, "equity_curve.csv"), index=False)
    annual.to_csv(os.path.join(run_dir, "annual_returns.csv"), index=False)
    snapshots = [s for s in result["holding_snapshots"] if not s.empty]
    if snapshots:
        pd.concat(snapshots, ignore_index=True).to_csv(
            os.path.join(run_dir, "holdings_summary.csv"), index=False
        )
    pd.DataFrame(result["trade_records"]).to_csv(
        os.path.join(run_dir, "trades_record.csv"), index=False
    )
    with open(os.path.join(run_dir, "spec.json"), "w", encoding="utf-8") as handle:
        json.dump(spec, handle, ensure_ascii=False, indent=2)

    _log.info(
        "%-72s annual=%6.2f%% sharpe=%5.3f mdd=%6.2f%% N=%.1f  %4.1fs",
        spec["id"],
        row["annual_return"] * 100,
        row["sharpe_ratio"],
        row["max_drawdown"] * 100,
        row["avg_positions"] or 0,
        row["elapsed_s"],
    )

    del result, performance, equity
    gc.collect()
    return row


# ---------------------------------------------------------------------------
# 各阶段实验
# ---------------------------------------------------------------------------
def phase_core():
    specs = []
    for filters in FILTER_SETS:
        for ranking in RANKINGS:
            specs.append(
                base_spec(phase="core", filters=filters, ranking=ranking)
            )
    return specs


def best_filters(best):
    if best["filters"] in ("none", "", None):
        return ["pe", "pb", "pr"]
    return best["filters"].split("+")


def pick_best(rows, phase="core"):
    candidates = [
        r
        for r in rows
        if r["phase"] == phase and r.get("annual_return") is not None
    ]
    if not candidates:
        raise RuntimeError(f"no completed rows in phase {phase}")
    candidates.sort(
        key=lambda r: (r["annual_return"], r["sharpe_ratio"]), reverse=True
    )
    return candidates[0]


def phase_pool(best):
    if ACTIVE_POOL != "union":
        return []
    specs = [
        base_spec(
            phase="pool",
            pool=mode,
            filters=best_filters(best),
            ranking=best["ranking"],
            trim=None if best["trim"] == "raw" else float(best["trim"]),
            max_positions=best["max_positions"],
        )
        for mode in ("legacy", "latest")
    ]
    return specs


def phase_trim(best, core_rows):
    # 最优配置 + 核心网格前 3 名 + 传统基准配置
    configs = [
        (
            best_filters(best),
            best["ranking"],
            best["max_positions"],
        )
    ]
    ranked = sorted(
        [r for r in core_rows if r["phase"] == "core"],
        key=lambda r: (r["annual_return"], r["sharpe_ratio"]),
        reverse=True,
    )
    for row in ranked[:3]:
        configs.append(
            (
                best_filters(row),
                row["ranking"],
                row["max_positions"],
            )
        )
    configs.append((["pe", "pb", "pr"], "pb", 5))

    seen = set()
    specs = []
    trims = [None, 0.0, 0.005, 0.01, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05]
    for filters, ranking, max_pos in configs:
        key = (tuple(filters), ranking, max_pos)
        if key in seen:
            continue
        seen.add(key)
        for trim in trims:
            specs.append(
                base_spec(
                    phase="trim",
                    filters=filters,
                    ranking=ranking,
                    trim=trim,
                    max_positions=max_pos,
                )
            )
    return specs


def phase_positions(best):
    filters = best_filters(best)
    trim = None if best["trim"] == "raw" else float(best["trim"])
    specs = []
    for n in range(1, 11):
        specs.append(
            base_spec(
                phase="positions",
                filters=filters,
                ranking=best["ranking"],
                trim=trim,
                max_positions=n,
            )
        )
    return specs


def phase_refine():
    """与 1052 池那轮相同的阈值细化实验（PB 过滤 + PE 排名）。"""
    specs = []
    for roe in (0.55, 0.60, 0.65, 0.70):
        for trim in (None, 0.01, 0.02):
            specs.append(
                base_spec(
                    phase="refine",
                    filters=["pb"],
                    ranking="pe",
                    roe_thr=roe,
                    trim=trim,
                    max_positions=5,
                )
            )
    for n in (6, 7):
        specs.append(
            base_spec(
                phase="refine",
                filters=["pb"],
                ranking="pe",
                roe_thr=0.60,
                trim=0.01,
                max_positions=n,
            )
        )
    specs.append(
        base_spec(
            phase="refine",
            filters=["pb"],
            ranking="pb",
            roe_thr=0.60,
            trim=0.01,
            max_positions=5,
        )
    )
    for pe_thr, roe_thr in ((0.15, 0.60), (0.20, 0.60), (0.15, 0.70)):
        specs.append(
            base_spec(
                phase="refine",
                filters=["pb"],
                ranking="pe",
                pe_thr=pe_thr,
                pb_thr=pe_thr,
                roe_thr=roe_thr,
                trim=0.01,
                max_positions=5,
            )
        )
    specs.append(
        base_spec(
            phase="refine",
            filters=["pb"],
            ranking="pe",
            pe_thr=0.15,
            pb_thr=0.15,
            roe_thr=0.65,
            trim=0.01,
            max_positions=6,
        )
    )
    return specs


def phase_threshold(best):
    filters = best_filters(best)
    trim = None if best["trim"] == "raw" else float(best["trim"])
    specs = []
    base = dict(
        phase="threshold",
        filters=filters,
        ranking=best["ranking"],
        trim=trim,
        max_positions=best["max_positions"],
    )
    for level in (0.10, 0.15, 0.20, 0.30, 0.35, 0.40):
        specs.append(
            base_spec(**base, pe_thr=level, pb_thr=level, pr_thr=level)
        )
    for roe in (0.60, 0.65, 0.70, 0.80, 0.85, 0.90):
        specs.append(base_spec(**base, roe_thr=roe))
    for level in (0.15, 0.25, 0.35):
        for roe in (0.65, 0.75, 0.85):
            specs.append(
                base_spec(**base, pe_thr=level, pb_thr=level, pr_thr=level, roe_thr=roe)
            )
    return specs


def phase_frequency(best):
    filters = best_filters(best)
    trim = None if best["trim"] == "raw" else float(best["trim"])
    specs = []
    for frequency in ("weekly", "monthly", "quarterly", "annual_q3", "mid_year", "q3"):
        specs.append(
            base_spec(
                phase="frequency",
                frequency=frequency,
                filters=filters,
                ranking=best["ranking"],
                trim=trim,
                max_positions=best["max_positions"],
            )
        )
    return specs


def phase_special(best):
    filters = best_filters(best)
    trim = None if best["trim"] == "raw" else float(best["trim"])
    common = dict(
        phase="special",
        filters=filters,
        ranking=best["ranking"],
        trim=trim,
        max_positions=best["max_positions"],
    )
    return [
        base_spec(**common, stop_loss=True),
        base_spec(**{**common, "trim": None}),
        base_spec(
            phase="special",
            filters=[],
            ranking="pure_pb",
            trim=None,
        ),
        base_spec(
            phase="special",
            filters=["pe", "pb", "pr"],
            ranking="pb",
            trim=0.02,
        ),
    ]


def dedupe(specs, done_ids):
    seen = set(done_ids)
    out = []
    for spec in specs:
        spec_id = make_id(spec)
        if spec_id in seen:
            continue
        seen.add(spec_id)
        out.append(spec)
    return out


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end-date", default="2026-10-30",
                        help="统一回测截止日（默认上一周最后一个交易日）")
    parser.add_argument("--start-date", default="2015-01-01")
    parser.add_argument("--output-root", default=None)
    parser.add_argument(
        "--pool",
        default="union",
        choices=["union", "legacy", "latest"],
        help="整轮实验使用的股票池（默认 union=1052）",
    )
    parser.add_argument(
        "--phases",
        default="core,pool,trim,positions,threshold,refine,frequency,special",
        help="逗号分隔的阶段列表",
    )
    args = parser.parse_args()

    global ACTIVE_POOL
    ACTIVE_POOL = args.pool

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_root = args.output_root or os.path.join(
        config.DATA_OUTPUT_DIR, f"universe_compare_{timestamp}"
    )
    os.makedirs(os.path.join(out_root, "runs"), exist_ok=True)

    log_path = os.path.join(out_root, "run.log")
    logging.basicConfig(
        level=logging.WARNING,
        filename=log_path,
        filemode="a",
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    _log.setLevel(logging.INFO)
    _log.propagate = False
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
    _log.addHandler(handler)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    _log.addHandler(file_handler)

    install_caches()

    phases = [p.strip() for p in args.phases.split(",") if p.strip()]
    _log.info("Output: %s", out_root)
    _log.info("Backtest window: %s ~ %s", args.start_date, args.end_date)

    rows = []
    summary_path = os.path.join(out_root, "summary.csv")

    def flush():
        pd.DataFrame(rows).to_csv(summary_path, index=False)

    def execute(specs):
        for spec in specs:
            try:
                rows.append(run_one(spec, args, out_root))
            except Exception as exc:  # noqa: BLE001
                _log.exception("FAILED %s: %s", make_id(spec), exc)
            flush()

    # 记录池子规模
    set_pool("union")
    union_size = len(data_loader.load_stock_pool())
    set_pool("legacy")
    legacy_size = len(data_loader.load_stock_pool())
    set_pool("latest")
    latest_size = len(data_loader.load_stock_pool())
    set_pool("union")
    pool_sizes = {"union": union_size, "legacy": legacy_size, "latest": latest_size}
    _log.info("Pool sizes: %s", pool_sizes)
    with open(os.path.join(out_root, "run_config.json"), "w", encoding="utf-8") as handle:
        json.dump(
            {
                "created_at": timestamp,
                "start_date": args.start_date,
                "end_date": args.end_date,
                "pool_sizes": pool_sizes,
                "active_pool": ACTIVE_POOL,
                "phases": phases,
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )

    if "core" in phases:
        _log.info("\n=== Phase core: 7 filters x 5 rankings ===")
        execute(dedupe(phase_core(), []))

    best = pick_best(rows, "core")
    _log.info(
        "\nBest core config: %s (annual %.2f%%, sharpe %.3f)",
        best["id"], best["annual_return"] * 100, best["sharpe_ratio"],
    )

    for name, builder in (
        ("pool", lambda: phase_pool(best)),
        ("trim", lambda: phase_trim(best, rows)),
        ("positions", lambda: phase_positions(best)),
        ("threshold", lambda: phase_threshold(best)),
        ("refine", lambda: phase_refine()),
        ("frequency", lambda: phase_frequency(best)),
        ("special", lambda: phase_special(best)),
    ):
        if name not in phases:
            continue
        _log.info("\n=== Phase %s ===", name)
        execute(dedupe(builder(), [r["id"] for r in rows]))

    flush()
    _log.info("\nAll done. %d variants -> %s", len(rows), summary_path)


if __name__ == "__main__":
    main()
