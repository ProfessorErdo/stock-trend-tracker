#!/usr/bin/env python3
"""Build the public dashboard payload from private local portfolio data.

The generated JSON intentionally contains only derived, display-safe fields:
no share counts, transaction amounts, cost basis, or personal information.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
BACKTESTING_DIR = ROOT / "backtesting"
sys.path.insert(0, str(BACKTESTING_DIR))

import config  # noqa: E402
from data_loader import load_price_data, load_stock_pool  # noqa: E402
from stock_selector import (  # noqa: E402
    adverse_tail_quantile,
    rank_and_limit,
    select_stocks,
)


HOLDINGS_FILE = ROOT / "data" / "processed" / "backtesting" / "holdings" / "holdings_summary.csv"
EQUITY_FILE = ROOT / "data" / "processed" / "backtesting" / "performance" / "equity_curve.csv"
STOCK_NAMES_FILE = ROOT / "data" / "input" / "stock_names_full.csv"
DEFAULT_OUTPUT = ROOT / "docs" / "data" / "dashboard.json"

# Fixed universe used to find the real 2026-04-30 annual holdings.
HOLDING_UNIVERSE_FILES = {
    "hs300": (ROOT / "data" / "input" / "hs300_list_20251213.csv", ","),
    "zz500": (ROOT / "data" / "input" / "zz500_list_20251216.csv", "\t"),
    "hongli": (ROOT / "data" / "input" / "hongli_list_20251213.csv", ","),
    "honglidibo": (ROOT / "data" / "input" / "honglidibo_list_20251213.csv", ","),
    "gz100": (ROOT / "data" / "input" / "gz100_list_20260227.csv", ","),
    "gzfc": (ROOT / "data" / "input" / "gzfc_list_20260227.csv", ","),
    "zzfc": (ROOT / "data" / "input" / "zzfc_list_20260316.csv", ","),
}
EXPECTED_HOLDING_UNIVERSE_SIZE = 932
EXPECTED_HOLDINGS = {"600926", "601838", "601128", "601319", "601601"}
PORTFOLIO_CUTOFF_DATE = pd.Timestamp("2026-04-30")
PORTFOLIO_REBALANCE_DATE = pd.Timestamp("2026-05-06")
SKIP_STOCKS = {"689009"}


def clean_number(value: float, digits: int = 4) -> float | None:
    """Return a JSON-safe rounded number."""
    if value is None or not math.isfinite(float(value)):
        return None
    return round(float(value), digits)


def get_stock_names() -> dict[str, str]:
    if not STOCK_NAMES_FILE.exists():
        return {}
    names = pd.read_csv(STOCK_NAMES_FILE, dtype={"code": str})
    return {
        str(row.code).zfill(6): str(row.name).replace(" ", "")
        for row in names.itertuples(index=False)
    }


def load_holding_universe() -> pd.DataFrame:
    """Load the exact 932-stock universe used to find the real holdings."""
    all_codes: set[str] = set()
    for file_path, separator in HOLDING_UNIVERSE_FILES.values():
        if not file_path.exists():
            raise FileNotFoundError(f"Missing fixed-universe file: {file_path}")
        frame = pd.read_csv(file_path, sep=separator)
        if "code" not in frame.columns:
            raise RuntimeError(f"No code column in universe file: {file_path}")
        all_codes.update(
            frame["code"].astype(str).str.strip().str.zfill(6).tolist()
        )
    all_codes.difference_update(SKIP_STOCKS)
    if len(all_codes) != EXPECTED_HOLDING_UNIVERSE_SIZE:
        raise RuntimeError(
            "The fixed portfolio universe changed: "
            f"expected {EXPECTED_HOLDING_UNIVERSE_SIZE}, found {len(all_codes)}."
        )
    return pd.DataFrame({"code": sorted(all_codes)})


def load_price_cache(stock_codes: list[str]) -> dict[str, pd.DataFrame]:
    frames = {}
    for code in stock_codes:
        frames[code] = load_price_data(code)
    if not frames:
        raise RuntimeError("No stock price data found.")
    return frames


def has_valuation_price(row: pd.Series) -> bool:
    if "close_na" in row.index:
        return pd.notna(row["close_na"]) and float(row["close_na"]) > 0
    return pd.notna(row["close"]) and float(row["close"]) > 0


def choose_screen_date(
    price_frames: dict[str, pd.DataFrame],
    preferred_dates: list[pd.Timestamp] | None = None,
) -> pd.Timestamp:
    """Choose the latest sufficiently complete valuation cross-section.

    Incremental updates first refresh adjusted prices and later refresh
    non-adjusted prices. During that interval, recent rows can have adjusted
    closes but empty valuation prices. Falling back to the latest date with at
    least 75% usable valuation coverage keeps the screen meaningful.
    """
    candidate_dates = set(pd.Timestamp(date).normalize() for date in preferred_dates or [])
    for frame in price_frames.values():
        if frame.empty or "trade_date" not in frame.columns:
            continue
        recent = pd.to_datetime(frame["trade_date"]).drop_duplicates().sort_values().tail(15)
        candidate_dates.update(pd.Timestamp(date).normalize() for date in recent)

    minimum_coverage = max(50, int(len(price_frames) * 0.75))
    for date in sorted(candidate_dates, reverse=True):
        usable = 0
        for frame in price_frames.values():
            if frame.empty or "trade_date" not in frame.columns:
                continue
            rows = frame.loc[pd.to_datetime(frame["trade_date"]).dt.normalize() == date]
            if not rows.empty and has_valuation_price(rows.iloc[-1]):
                usable += 1
        if usable >= minimum_coverage:
            return date

    fallback_dates = []
    for frame in price_frames.values():
        if not frame.empty and "trade_date" in frame.columns:
            fallback_dates.append(pd.to_datetime(frame["trade_date"]).max())
    if not fallback_dates:
        raise RuntimeError("No usable price dates found.")
    return min(fallback_dates).normalize()


def latest_available_date(price_frames: dict[str, pd.DataFrame]) -> pd.Timestamp | None:
    dates = []
    for frame in price_frames.values():
        if not frame.empty and "trade_date" in frame.columns:
            dates.append(pd.to_datetime(frame["trade_date"]).max())
    return max(dates).normalize() if dates else None


def load_holding_rows(
    expected_codes: list[str],
    price_cache: dict[str, pd.DataFrame],
) -> tuple[pd.Timestamp, pd.DataFrame]:
    if not HOLDINGS_FILE.exists():
        raise FileNotFoundError(
            f"Missing holdings file: {HOLDINGS_FILE}. "
            "Run the local portfolio backtest first."
        )

    holdings = pd.read_csv(HOLDINGS_FILE, dtype={"stock_code": str})
    holdings["rebalance_date"] = pd.to_datetime(holdings["rebalance_date"]).dt.normalize()
    holdings["stock_code"] = holdings["stock_code"].astype(str).str.zfill(6)
    current = holdings[holdings["rebalance_date"] == PORTFOLIO_REBALANCE_DATE].copy()

    if set(current["stock_code"]) != set(expected_codes):
        fallback_rows = []
        for code in expected_codes:
            frame = price_cache.get(code, pd.DataFrame())
            if frame.empty:
                raise RuntimeError(f"Missing rebalance price for {code}.")
            prices = frame.copy()
            prices["trade_date"] = pd.to_datetime(prices["trade_date"]).dt.normalize()
            available = prices[
                (prices["trade_date"] >= PORTFOLIO_REBALANCE_DATE)
            ].sort_values("trade_date")
            if available.empty:
                raise RuntimeError(f"No rebalance-day price for {code}.")
            fallback_rows.append(
                {
                    "rebalance_date": PORTFOLIO_REBALANCE_DATE,
                    "stock_code": code,
                    "current_price": float(available.iloc[0]["close"]),
                    "weight": 1 / len(expected_codes),
                }
            )
        current = pd.DataFrame(fallback_rows)

    if current.empty:
        raise RuntimeError("The fixed 2026-04-30 holdings could not be loaded.")

    total_weight = float(current["weight"].sum())
    if total_weight > 0:
        current["weight"] = current["weight"] / total_weight
    else:
        current["weight"] = 1 / len(current)
    return PORTFOLIO_REBALANCE_DATE, current


def weekly_series(frame: pd.DataFrame, date_col: str, value_cols: list[str]) -> pd.DataFrame:
    working = frame.copy()
    working[date_col] = pd.to_datetime(working[date_col])
    working = working.sort_values(date_col)
    working["_week"] = working[date_col].dt.to_period("W-FRI")
    weekly = working.groupby("_week", as_index=False).tail(1)
    first = working.iloc[[0]]
    first_date = working[date_col].iloc[0]
    weekly = pd.concat([first, weekly[weekly[date_col] > first_date]])
    last = working.iloc[[-1]]
    weekly = pd.concat([weekly, last])
    return weekly.drop_duplicates(subset=[date_col]).sort_values(date_col)[[date_col, *value_cols]]


def build_performance_history(
    rebalance_date: pd.Timestamp,
    as_of: pd.Timestamp,
) -> tuple[list[dict], float | None]:
    if not EQUITY_FILE.exists():
        raise FileNotFoundError(
            f"Missing equity curve: {EQUITY_FILE}. Run the local backtest first."
        )

    equity = pd.read_csv(EQUITY_FILE)
    equity["date"] = pd.to_datetime(equity["date"]).dt.normalize()
    equity = equity[(equity["date"] >= rebalance_date) & (equity["date"] <= as_of)].copy()
    if equity.empty:
        return [], None

    weekly = weekly_series(equity, "date", ["strategy_equity", "benchmark_equity"])
    strategy_base = float(weekly["strategy_equity"].iloc[0])
    benchmark_base = float(weekly["benchmark_equity"].iloc[0])
    if strategy_base <= 0 or benchmark_base <= 0:
        return [], None

    history: list[dict] = []
    for row in weekly.itertuples(index=False):
        history.append(
            {
                "date": row.date.strftime("%Y-%m-%d"),
                "portfolio": clean_number(row.strategy_equity / strategy_base * 100, 2),
                "benchmark": clean_number(row.benchmark_equity / benchmark_base * 100, 2),
            }
        )

    benchmark_return = float(weekly["benchmark_equity"].iloc[-1]) / benchmark_base - 1
    return history, benchmark_return


def holding_sparkline(price_df: pd.DataFrame, rebalance_date: pd.Timestamp, entry_price: float) -> list[float]:
    prices = price_df.copy()
    prices["trade_date"] = pd.to_datetime(prices["trade_date"]).dt.normalize()
    prices = prices[prices["trade_date"] >= rebalance_date].sort_values("trade_date")
    if prices.empty or entry_price <= 0:
        return []
    prices["_week"] = prices["trade_date"].dt.to_period("W-FRI")
    weekly = prices.groupby("_week", as_index=False).tail(1)
    return [
        clean_number(float(close) / entry_price * 100, 2)
        for close in weekly["close"].dropna().tolist()
    ]


def metric_conditions(row: pd.Series | None, thresholds: dict[str, float]) -> dict[str, bool | None]:
    if row is None:
        return {"pe": None, "pb": None, "pr": None, "roe": None}
    return {
        "pe": bool(float(row["pe_ttm"]) <= thresholds["pe_ttm"]),
        "pb": bool(float(row["pb_ttm"]) <= thresholds["pb_ttm"]),
        "pr": bool(float(row["pr_ttm"]) <= thresholds["pr_ttm"]),
        "roe": bool(float(row["roe_ttm"]) >= thresholds["roe_ttm"]),
    }


def failed_labels(conditions: dict[str, bool | None]) -> list[str]:
    labels = {"pe": "PE", "pb": "PB", "pr": "PR", "roe": "ROE"}
    failed = [labels[key] for key, passed in conditions.items() if passed is False]
    if any(value is None for value in conditions.values()):
        return ["数据不足"]
    return failed


def public_metrics(row: pd.Series | None) -> dict[str, float | None]:
    if row is None:
        return {"pe": None, "pb": None, "pr": None, "roe": None}
    return {
        "pe": clean_number(row["pe_ttm"], 2),
        "pb": clean_number(row["pb_ttm"], 2),
        "pr": clean_number(row["pr_ttm"], 2),
        "roe": clean_number(row["roe_ttm"], 2),
    }


def screen_stocks(
    screen_codes: list[str],
    holdings: pd.DataFrame,
    as_of: pd.Timestamp,
    names: dict[str, str],
    price_cache: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, dict, dict[str, float]]:
    print(f"Loading stock pool for {as_of.date()}...", flush=True)
    print(f"Screening {len(screen_codes)} stocks...", flush=True)
    passed, valuations = select_stocks(
        screen_codes,
        as_of,
        price_cache=price_cache,
    )

    if valuations.empty:
        return valuations, {
            "as_of": as_of.strftime("%Y-%m-%d"),
            "universe_size": len(screen_codes),
            "valid_samples": 0,
            "passed_count": 0,
            "target_count": 0,
            "thresholds": {},
            "candidates": [],
        }, {}

    thresholds = {
        "pe_ttm": adverse_tail_quantile(
            valuations["pe_ttm"],
            config.PE_THRESHOLD,
            config.THRESHOLD_TRIM_RATIO,
            "low",
        ),
        "pb_ttm": adverse_tail_quantile(
            valuations["pb_ttm"],
            config.PB_THRESHOLD,
            config.THRESHOLD_TRIM_RATIO,
            "low",
        ),
        "pr_ttm": adverse_tail_quantile(
            valuations["pr_ttm"],
            config.PR_THRESHOLD,
            config.THRESHOLD_TRIM_RATIO,
            "low",
        ),
        "roe_ttm": adverse_tail_quantile(
            valuations["roe_ttm"],
            config.ROE_THRESHOLD,
            config.THRESHOLD_TRIM_RATIO,
            "high",
        ),
    }

    ranked = rank_and_limit(passed, valuations, config.MAX_POSITIONS, "pb")
    valuation_map = valuations.set_index("code")
    holding_codes = set(holdings["stock_code"])
    rank_map = {code: index + 1 for index, code in enumerate(ranked)}
    target_codes = set(ranked)

    order = {code: index for index, code in enumerate(passed)}
    ordered_passed = sorted(passed, key=lambda code: (code not in target_codes, rank_map.get(code, 999), order[code]))
    candidates = []
    for code in ordered_passed:
        row = valuation_map.loc[code]
        candidates.append(
            {
                "code": code,
                "name": names.get(code, code),
                "rank": rank_map.get(code),
                "target": code in target_codes,
                "in_portfolio": code in holding_codes,
                "new_to_portfolio": code not in holding_codes,
                "metrics": public_metrics(row),
            }
        )

    rounded_thresholds = {
        "pe": clean_number(thresholds["pe_ttm"], 2),
        "pb": clean_number(thresholds["pb_ttm"], 2),
        "pr": clean_number(thresholds["pr_ttm"], 2),
        "roe": clean_number(thresholds["roe_ttm"], 2),
    }
    return valuation_map, {
        "as_of": as_of.strftime("%Y-%m-%d"),
        "universe_size": len(screen_codes),
        "valid_samples": int(len(valuations)),
        "passed_count": int(len(passed)),
        "target_count": int(len(ranked)),
        "thresholds": rounded_thresholds,
        "candidates": candidates,
    }, thresholds


def build_payload(as_of: pd.Timestamp | None) -> dict:
    names = get_stock_names()
    holding_pool = load_holding_universe()
    holding_codes = (
        holding_pool["code"].astype(str).str.zfill(6).drop_duplicates().tolist()
    )
    screen_pool = load_stock_pool()
    screen_codes = (
        screen_pool["code"].astype(str).str.zfill(6).drop_duplicates().tolist()
    )
    all_codes = sorted(set(holding_codes) | set(screen_codes))
    price_frames = load_price_cache(all_codes)

    selected_holdings, holdings_valuations = select_stocks(
        holding_codes,
        PORTFOLIO_CUTOFF_DATE,
        price_cache=price_frames,
    )
    fixed_holdings = rank_and_limit(
        selected_holdings,
        holdings_valuations,
        config.MAX_POSITIONS,
        "pb",
    )
    if set(fixed_holdings) != EXPECTED_HOLDINGS:
        raise RuntimeError(
            "The 932-stock selection no longer matches the locked portfolio: "
            f"expected {sorted(EXPECTED_HOLDINGS)}, found {sorted(fixed_holdings)}."
        )
    rebalance_date, holdings = load_holding_rows(fixed_holdings, price_frames)

    latest_price_date = latest_available_date(price_frames)
    latest_market_date = as_of or choose_screen_date(price_frames)
    equity_latest = None
    if EQUITY_FILE.exists():
        equity_dates = pd.to_datetime(pd.read_csv(EQUITY_FILE, usecols=["date"])["date"])
        equity_latest = equity_dates.max().normalize()
        latest_market_date = min(latest_market_date, equity_latest)
    if latest_market_date < rebalance_date:
        raise RuntimeError("The requested date is before the latest holding rebalance.")
    latest_market_date = latest_market_date.normalize()

    history, benchmark_return = build_performance_history(rebalance_date, latest_market_date)
    valuation_map, screen, raw_thresholds = screen_stocks(
        screen_codes,
        holdings,
        latest_market_date,
        names,
        price_frames,
    )

    holding_payload = []
    weighted_return = 0.0
    for row in holdings.itertuples(index=False):
        code = str(row.stock_code).zfill(6)
        prices = price_frames.get(code, pd.DataFrame())
        if prices.empty:
            continue
        prices = prices.copy()
        prices["trade_date"] = pd.to_datetime(prices["trade_date"]).dt.normalize()
        available = prices[prices["trade_date"] <= latest_market_date].sort_values("trade_date")
        if available.empty:
            continue

        latest = available.iloc[-1]
        previous = available.iloc[-2] if len(available) > 1 else latest
        entry_price = float(row.current_price)
        latest_price = float(latest["close"])
        stock_return = latest_price / entry_price - 1
        day_change = latest_price / float(previous["close"]) - 1 if float(previous["close"]) else 0
        weight = float(row.weight)
        weighted_return += weight * stock_return

        metrics_series = valuation_map.loc[code] if code in valuation_map.index else None
        conditions = metric_conditions(metrics_series, raw_thresholds)
        failed = failed_labels(conditions)
        holding_payload.append(
            {
                "code": code,
                "name": names.get(code, code),
                "weight_pct": clean_number(weight * 100, 2),
                "return_pct": clean_number(stock_return * 100, 2),
                "day_change_pct": clean_number(day_change * 100, 2),
                "latest_price": clean_number(latest_price, 2),
                "qualifies": not failed,
                "failed_metrics": failed,
                "metrics": public_metrics(metrics_series),
                "sparkline": holding_sparkline(prices, rebalance_date, entry_price),
            }
        )

    if history:
        portfolio_return = float(history[-1]["portfolio"]) / 100 - 1
        benchmark_return = float(history[-1]["benchmark"]) / 100 - 1
    else:
        portfolio_return = weighted_return

    excess_return = (
        (portfolio_return - benchmark_return) * 100
        if benchmark_return is not None
        else None
    )
    qualifying_count = sum(1 for item in holding_payload if item["qualifies"])
    new_names = [item["name"] for item in screen["candidates"] if item["new_to_portfolio"] and item["target"]]
    dropped_names = [item["name"] for item in holding_payload if not item["qualifies"]]

    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
        "data_as_of": latest_market_date.strftime("%Y-%m-%d"),
        "data_quality": {
            "latest_price_date": latest_price_date.strftime("%Y-%m-%d") if latest_price_date is not None else None,
            "latest_equity_date": equity_latest.strftime("%Y-%m-%d") if equity_latest is not None else None,
            "complete": bool(
                latest_price_date is not None
                and latest_market_date == latest_price_date
                and (equity_latest is None or latest_market_date <= equity_latest)
            ),
        },
        "rebalance_date": rebalance_date.strftime("%Y-%m-%d"),
        "holding_until": f"{rebalance_date.year + 1}-05",
        "summary": {
            "portfolio_return_pct": clean_number(portfolio_return * 100, 2),
            "benchmark_return_pct": clean_number(benchmark_return * 100, 2) if benchmark_return is not None else None,
            "excess_return_pp": clean_number(excess_return, 2),
            "qualifying_count": qualifying_count,
            "holding_count": len(holding_payload),
            "new_candidate_count": len(new_names),
            "dropped_count": len(dropped_names),
            "new_candidates": new_names,
            "dropped_names": dropped_names,
        },
        "history": history,
        "holdings": holding_payload,
        "screen": screen,
        "rules": {
            "holding_universe_size": len(holding_codes),
            "holding_universe_snapshot": "2026-04-30 持仓池",
            "screen_universe_size": len(screen_codes),
            "screen_universe_snapshot": "当前动态股票池",
            "valuation_quantile": int(config.PE_THRESHOLD * 100),
            "roe_quantile": int(config.ROE_THRESHOLD * 100),
            "max_positions": int(config.MAX_POSITIONS),
            "ranking": "PB 从低到高",
            "new_stock_exclusion_days": int(config.NEW_STOCK_EXCLUDE_DAYS),
            "trim_ratio": float(config.THRESHOLD_TRIM_RATIO),
        },
    }

    forbidden_keys = {"shares", "cost", "cost_price", "market_value", "amount", "cash"}
    leaked = sorted(
        key for key in forbidden_keys if f'"{key}"' in json.dumps(payload, ensure_ascii=False)
    )
    if leaked:
        raise RuntimeError(f"Privacy guard rejected output keys: {leaked}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of",
        help=(
            "Market date in YYYY-MM-DD. Defaults to the latest date with "
            "sufficient valuation-price coverage."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output JSON path (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()

    as_of = pd.Timestamp(args.as_of).normalize() if args.as_of else None
    payload = build_payload(as_of)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {args.output} | as of {payload['data_as_of']} | "
        f"{len(payload['holdings'])} holdings | "
        f"{payload['summary']['qualifying_count']} still qualify",
        flush=True,
    )


if __name__ == "__main__":
    main()
