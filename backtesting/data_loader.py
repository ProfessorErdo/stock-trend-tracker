"""
数据加载模块 - 从 AkShare API 获取 A 股数据
"""

import sys
import os
import logging
import json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

import pandas as pd
from datetime import datetime, timedelta
from tqdm import tqdm
import akshare as ak

logger = logging.getLogger("data_loader")


def load_update_metadata() -> dict:
    """Load per-stock update timestamps for backtesting data."""
    if not os.path.exists(config.UPDATE_METADATA_FILE):
        return {"financial": {}, "price": {}}

    try:
        with open(config.UPDATE_METADATA_FILE, "r") as f:
            metadata = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"Could not read update metadata: {e}")
        return {"financial": {}, "price": {}}

    metadata.setdefault("financial", {})
    metadata.setdefault("price", {})
    return metadata


def save_update_metadata(metadata: dict):
    """Persist per-stock update timestamps for backtesting data."""
    os.makedirs(os.path.dirname(config.UPDATE_METADATA_FILE), exist_ok=True)
    with open(config.UPDATE_METADATA_FILE, "w") as f:
        json.dump(metadata, f, indent=2)


def should_update_data(
    metadata: dict,
    data_type: str,
    stock_code: str,
    max_age_days: int,
    force: bool = False,
) -> bool:
    """
    Return whether a stock is due for an incremental data refresh.

    Missing or invalid timestamps are treated as due. A full refresh bypasses
    the timestamp check.
    """
    if force:
        return True

    last_date_str = metadata.get(data_type, {}).get(str(stock_code))
    if not last_date_str:
        return True

    try:
        last_date = datetime.strptime(last_date_str, "%Y-%m-%d")
    except (TypeError, ValueError):
        return True

    return (datetime.now() - last_date).days >= max_age_days


def mark_data_updated(metadata: dict, data_type: str, stock_code: str):
    """Record a successful refresh for a stock and data type."""
    metadata.setdefault(data_type, {})[str(stock_code)] = datetime.now().strftime("%Y-%m-%d")


def format_symbol(code: str) -> str:
    """
    将股票代码格式化为 AkShare 所需的 symbol 格式（sh/sz/bj 前缀）

    Args:
        code: 6 位股票代码

    Returns:
        AkShare symbol，如 "sh600519"、"sz000001"、"bj830799"
    """
    code = str(code).strip()
    if code.startswith(("600", "601", "603", "605", "688", "689")):
        return f"sh{code}"
    elif code.startswith(("000", "001", "002", "003", "300", "301")):
        return f"sz{code}"
    elif code.startswith(("83", "87", "92", "43")):
        return f"bj{code}"
    else:
        # 默认上海交易所
        return f"sh{code}"


def load_stock_pool() -> pd.DataFrame:
    """
    从 config.EXISTING_STOCK_POOL_FILES 加载并合并所有股票池，去重。

    每个池子可以配置一个文件列表（历史各期 + 最新一期），这里逐文件读取后取并集，
    使被调出指数的股票仍留在池子里，避免幸存者偏差。

    Returns:
        DataFrame with ['code'] column, deduplicated
    """
    all_codes = set()
    file_count = 0

    for pool_name, file_paths in config.EXISTING_STOCK_POOL_FILES.items():
        # 兼容旧的单文件写法（字符串）
        if isinstance(file_paths, (str, os.PathLike)):
            file_paths = [file_paths]

        # zz500 文件是 tab 分隔，其余是逗号分隔
        sep = "\t" if pool_name == "zz500" else ","

        for file_path in file_paths:
            if not os.path.exists(file_path):
                logger.warning(f"Warning: stock pool file not found: {file_path}")
                continue
            file_count += 1

            df = pd.read_csv(file_path, sep=sep)

            if "code" in df.columns:
                codes = df["code"].astype(str).str.strip().str.zfill(6)
                all_codes.update(codes.tolist())
            else:
                logger.warning(f"Warning: 'code' column not found in {file_path}")

    # Filter out stocks with no data on AkShare API
    SKIP_STOCKS = {"689009"}
    all_codes = {c for c in all_codes if c not in SKIP_STOCKS}

    result = pd.DataFrame({"code": sorted(all_codes)})
    logger.info(
        f"Loaded {len(result)} unique stocks from "
        f"{len(config.EXISTING_STOCK_POOL_FILES)} pools ({file_count} files)."
    )
    return result


def save_stock_pool(stock_codes: list):
    """
    保存股票池列表到 config.STOCK_POOL_DIR，文件名为 today's date

    Args:
        stock_codes: list of stock codes
    """
    os.makedirs(config.STOCK_POOL_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    file_path = os.path.join(config.STOCK_POOL_DIR, f"stock_pool_{today}.csv")

    df = pd.DataFrame({"code": stock_codes})
    df.to_csv(file_path, index=False)
    logger.info(f"Saved {len(stock_codes)} stocks to {file_path}")


def query_price_data(
    stock_codes,
    start_date: str = "20150101",
    end_date: str = None,
    adjust: str = "hfq",
    incremental: bool = True,
    full: bool = False,
) -> int:
    """
    从 AkShare 下载后复权价格数据，保存为每只股票的 CSV

    Args:
        stock_codes: list of stock codes
        start_date: start date string (YYYYMMDD)
        end_date: end date string (YYYYMMDD), None means today
        adjust: adjustment type, default "hfq" (后复权)
        incremental: 增量更新模式（默认True），只下载已有数据之后的新数据
        full: 全量下载（忽略已有数据，重新下载全部）

    Returns:
        Number of successfully downloaded stocks
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")

    os.makedirs(config.PRICE_DATA_DIR, exist_ok=True)
    metadata = load_update_metadata()
    if full:
        to_download = list(stock_codes)
        logger.info(f"Full download: re-downloading price data for all {len(to_download)} stocks.")
    else:
        to_download = [
            code for code in stock_codes
            if should_update_data(
                metadata,
                "price",
                code,
                config.PRICE_UPDATE_INTERVAL_DAYS,
            )
        ]
        logger.info(
            f"Skipping {len(stock_codes) - len(to_download)} price stocks updated "
            f"within {config.PRICE_UPDATE_INTERVAL_DAYS} day(s). "
            f"Downloading {len(to_download)} stocks."
        )

    success_count = 0
    for code in tqdm(to_download, desc="Downloading price data"):
        file_path = os.path.join(config.PRICE_DATA_DIR, f"price_{code}.csv")
        hfq_path = os.path.join(config.PRICE_DATA_DIR, f"price_{code}_hfq.csv")

        if full and os.path.exists(file_path):
            os.remove(file_path)

        if incremental and os.path.exists(file_path) and not full:
            # 增量模式：读取已有数据的最后一条日期
            try:
                existing = pd.read_csv(file_path, parse_dates=["trade_date"])
                if not existing.empty:
                    last_date = existing["trade_date"].max()
                    last_date_str = last_date.strftime("%Y%m%d")
                    if last_date_str >= end_date:
                        success_count += 1  # 数据已是最新
                        existing[["trade_date", "open", "high", "low", "close", "volume"]].to_csv(
                            hfq_path,
                            index=False,
                        )
                        mark_data_updated(metadata, "price", code)
                        continue
                    # 下载 last_date 之后的数据（保留一天重叠，避免缺失）
                    dl_start = (last_date - pd.Timedelta(days=2)).strftime("%Y%m%d")
                    df_new = ak.stock_zh_a_daily(
                        symbol=format_symbol(code),
                        start_date=dl_start,
                        end_date=end_date,
                        adjust=adjust
                    )
                    if df_new is None or df_new.empty:
                        success_count += 1
                        existing[["trade_date", "open", "high", "low", "close", "volume"]].to_csv(
                            hfq_path,
                            index=False,
                        )
                        mark_data_updated(metadata, "price", code)
                        continue
                    df_new = df_new.rename(columns={"date": "trade_date"})
                    df_new["trade_date"] = pd.to_datetime(df_new["trade_date"])
                    # 合并去重
                    combined = pd.concat([existing, df_new], ignore_index=True)
                    combined = combined.drop_duplicates(subset=["trade_date"], keep="last")
                    required_cols = ["trade_date", "open", "high", "low", "close", "volume"]
                    na_cols = [
                        "open_na", "high_na", "low_na", "close_na", "volume_na"
                    ]
                    combined = combined[
                        [c for c in required_cols + na_cols if c in combined.columns]
                    ]
                    combined = combined.sort_values("trade_date").reset_index(drop=True)
                    combined.to_csv(file_path, index=False)
                    combined[required_cols].to_csv(hfq_path, index=False)
                    success_count += 1
                    mark_data_updated(metadata, "price", code)
                    continue
            except Exception:
                pass  # 文件有问题，走全量下载路径

        # 全量下载（不存在或增量失败）
        try:
            symbol = format_symbol(code)
            df = ak.stock_zh_a_daily(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                adjust=adjust
            )

            if df is None or df.empty:
                continue

            # Normalize columns
            df = df.rename(columns={
                "date": "trade_date",
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume"
            })

            # Ensure required columns exist
            required_cols = ["trade_date", "open", "high", "low", "close", "volume"]
            if all(col in df.columns for col in required_cols):
                df = df[required_cols]
                df["trade_date"] = pd.to_datetime(df["trade_date"])
                df = df.sort_values("trade_date").reset_index(drop=True)

                output_path = os.path.join(config.PRICE_DATA_DIR, f"price_{code}.csv")
                df.to_csv(output_path, index=False)
                df[required_cols].to_csv(hfq_path, index=False)
                success_count += 1
                mark_data_updated(metadata, "price", code)

        except Exception as e:
            logger.warning(f"Error downloading price data for {code}: {e}")
            continue

    save_update_metadata(metadata)
    logger.info(f"Successfully downloaded price data for {success_count} stocks.")
    return success_count


def _calc_ann_available_date(report_date) -> pd.Timestamp:
    """
    根据报告期月份计算财报披露可用日期

    规则：
    - 年报（12月）：报告期 + 4 个月（次年 4 月底可用）
    - 半年报（6月）：报告期 + 2 个月（8 月底可用）
    - 一季报/三季报（3月/9月）：报告期 + 1 个月

    Args:
        report_date: report date (str or pd.Timestamp)

    Returns:
        pd.Timestamp of the announcement available date
    """
    report_date = pd.to_datetime(report_date)
    report_month = report_date.month

    offset_months = config.REPORT_AVAILABLE_MONTHS.get(report_month, 1)
    # Add offset months, then set to last day of that month
    ann_date = report_date + pd.DateOffset(months=offset_months)
    # Set to last day of the announcement month
    ann_date = ann_date + pd.offsets.MonthEnd(0)
    return pd.Timestamp(ann_date)


def _map_financial_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Map Chinese financial column names to English names.
    Uses specific keyword matching to avoid duplicate mappings.
    Only the first match per target column is kept.
    """
    target_map = {}  # target_name -> original_col_name (first match wins)
    for col in df.columns:
        cl = col.lower().strip()
        if "报告" in cl or "report_date" in cl:
            target_map.setdefault("report_date", col)
        # ROE: must contain "净资产收益" (most specific), skip "摊薄" version
        elif ("净资产收益" in cl or "roe" in cl) and "摊薄" not in cl:
            target_map.setdefault("roe", col)
        # EPS: must contain "每股收益" but NOT "净资产"
        elif ("每股收益" in cl or "eps" in cl) and "净资产" not in cl:
            target_map.setdefault("eps", col)
        # BPS: must contain "每股净资"
        elif "每股净资" in cl:
            target_map.setdefault("bps", col)

    return df.rename(columns={v: k for k, v in target_map.items() if v in df.columns})


def query_financial_data(
    stock_codes,
    season_end: str = "2026-04-30",
    full: bool = False,
) -> int:
    """
    从 AkShare 下载财务数据（同花顺单季度数据），计算 TTM 指标

    Args:
        stock_codes: list of stock codes
        season_end: season end date filter
        full: 全量下载（忽略已有文件，重新下载全部）

    Returns:
        Number of successfully downloaded stocks
    """
    os.makedirs(config.FINANCIAL_DATA_DIR, exist_ok=True)
    metadata = load_update_metadata()

    if full:
        to_download = list(stock_codes)
        logger.info(f"Full download: re-downloading all {len(to_download)} stocks.")
    else:
        to_download = [
            code for code in stock_codes
            if should_update_data(
                metadata,
                "financial",
                code,
                config.FINANCIAL_UPDATE_INTERVAL_DAYS,
            )
        ]
        logger.info(
            f"Skipping {len(stock_codes) - len(to_download)} financial stocks updated "
            f"within {config.FINANCIAL_UPDATE_INTERVAL_DAYS} days. "
            f"Downloading {len(to_download)} stocks."
        )

    success_count = 0
    for code in tqdm(to_download, desc="Downloading financial data"):
        try:
            df = ak.stock_financial_abstract_ths(
                symbol=str(code),
                indicator="按单季度"
            )

            if df is None or df.empty:
                continue

            # Normalize column names
            df = _map_financial_columns(df)

            # Ensure report_date exists and is datetime
            if "report_date" not in df.columns:
                # Try to find a date-like column
                date_cols = [c for c in df.columns if "date" in c.lower() or "日期" in c]
                if date_cols:
                    df = df.rename(columns={date_cols[0]: "report_date"})
                else:
                    continue

            df["report_date"] = pd.to_datetime(df["report_date"])
            df = df.sort_values("report_date").reset_index(drop=True)

            # Filter to season_end
            if season_end:
                season_dt = pd.to_datetime(season_end)
                df = df[df["report_date"] <= season_dt]

            if df.empty:
                continue

            # Compute TTM indicators
            # eps_ttm, roe_ttm: flow metrics, use 4-period rolling sum
            # bps_ttm: stock-point metric, use 4-period rolling mean
            for col_name in ["eps", "roe"]:
                if col_name in df.columns:
                    df[col_name] = df[col_name].astype(str).str.replace("%", "").str.replace("False", "").str.strip()
                    df[col_name] = pd.to_numeric(df[col_name], errors="coerce")
                    ttm_col = f"{col_name}_ttm"
                    df[ttm_col] = df[col_name].rolling(window=4).sum()
            if "bps" in df.columns:
                df["bps"] = df["bps"].astype(str).str.replace("%", "").str.replace("False", "").str.strip()
                df["bps"] = pd.to_numeric(df["bps"], errors="coerce")
                df["bps_ttm"] = df["bps"].rolling(window=4).mean()

            # Calculate ann_available_date
            df["ann_available_date"] = df["report_date"].apply(_calc_ann_available_date)

            # Select output columns
            output_cols = ["report_date", "ann_available_date"]
            for base in ["eps", "bps", "roe"]:
                if f"{base}_ttm" in df.columns:
                    output_cols.append(f"{base}_ttm")
                elif base in df.columns:
                    output_cols.append(base)

            output_cols = [c for c in output_cols if c in df.columns]
            df = df[output_cols]

            output_path = os.path.join(config.FINANCIAL_DATA_DIR, f"financial_{code}.csv")
            df.to_csv(output_path, index=False)
            success_count += 1
            mark_data_updated(metadata, "financial", code)

        except Exception as e:
            logger.warning(f"Error downloading financial data for {code}: {e}")
            continue

    save_update_metadata(metadata)
    logger.info(f"Successfully downloaded financial data for {success_count} stocks.")
    return success_count


def load_price_data(stock_code: str) -> pd.DataFrame:
    """
    加载单只股票的合并价格数据（含后复权 + 不复权）

    文件优先级:
      1. price_{code}.csv (合并文件，含 close + close_na)
      2. price_{code}_hfq.csv (仅后复权，向后兼容)

    Returns:
        DataFrame with columns: trade_date, open, high, low, close, volume
        Plus: open_na, high_na, low_na, close_na (if merged file exists)
        or empty DataFrame if not found
    """
    combined_path = os.path.join(config.PRICE_DATA_DIR, f"price_{stock_code}.csv")
    hfq_path = os.path.join(config.PRICE_DATA_DIR, f"price_{stock_code}_hfq.csv")

    if os.path.exists(combined_path):
        df = pd.read_csv(combined_path, parse_dates=["trade_date"])
        return df

    if os.path.exists(hfq_path):
        df = pd.read_csv(hfq_path, parse_dates=["trade_date"])
        return df

    return pd.DataFrame()


def query_price_data_no_adjust(
    stock_codes,
    start_date: str = "20150101",
    end_date: str = None,
    incremental: bool = True,
    full: bool = False,
) -> int:
    """
    从 AkShare 下载不复权价格数据，保存为 price_{code}_na.csv

    Args:
        stock_codes: list of stock codes
        start_date: start date string (YYYYMMDD)
        end_date: end date string (YYYYMMDD), None means today
        incremental: 增量更新模式（默认True）
        full: 全量下载（忽略已有文件，重新下载全部）

    Returns:
        Number of successfully downloaded stocks
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")

    os.makedirs(config.PRICE_DATA_DIR, exist_ok=True)

    success_count = 0
    for code in tqdm(stock_codes, desc="Downloading non-adjusted price data"):
        na_path = os.path.join(config.PRICE_DATA_DIR, f"price_{code}_na.csv")

        if full and os.path.exists(na_path):
            os.remove(na_path)

        if incremental and os.path.exists(na_path) and not full:
            try:
                existing = pd.read_csv(na_path, parse_dates=["trade_date"])
                if not existing.empty:
                    last_date = existing["trade_date"].max()
                    last_date_str = last_date.strftime("%Y%m%d")
                    if last_date_str >= end_date:
                        success_count += 1
                        continue
                    dl_start = (last_date - pd.Timedelta(days=2)).strftime("%Y%m%d")
                    df_new = ak.stock_zh_a_daily(
                        symbol=format_symbol(code),
                        start_date=dl_start,
                        end_date=end_date,
                        adjust=""
                    )
                    if df_new is None or df_new.empty:
                        success_count += 1
                        continue
                    df_new = df_new.rename(columns={"date": "trade_date"})
                    df_new["trade_date"] = pd.to_datetime(df_new["trade_date"])
                    combined = pd.concat([existing, df_new], ignore_index=True)
                    combined = combined.drop_duplicates(subset=["trade_date"], keep="last")
                    required_cols = ["trade_date", "open", "high", "low", "close", "volume"]
                    combined = combined[[c for c in required_cols if c in combined.columns]]
                    combined = combined.sort_values("trade_date").reset_index(drop=True)
                    combined.to_csv(na_path, index=False)
                    success_count += 1
                    continue
            except Exception:
                pass

        try:
            symbol = format_symbol(code)
            df = ak.stock_zh_a_daily(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                adjust=""
            )

            if df is None or df.empty:
                continue

            df = df.rename(columns={
                "date": "trade_date",
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume"
            })

            required_cols = ["trade_date", "open", "high", "low", "close", "volume"]
            if all(col in df.columns for col in required_cols):
                df = df[required_cols]
                df["trade_date"] = pd.to_datetime(df["trade_date"])
                df = df.sort_values("trade_date").reset_index(drop=True)
                df.to_csv(na_path, index=False)
                success_count += 1

        except Exception as e:
            logger.warning(f"Error downloading non-adjusted price data for {code}: {e}")
            continue

    logger.info(f"Successfully downloaded non-adjusted price data for {success_count} stocks.")
    return success_count


def merge_price_files(stock_codes=None) -> int:
    """
    Merge HFQ and non-adjusted price files into combined files.

    Output file: price_{code}.csv with columns:
      trade_date, open, high, low, close, volume,
      open_na, high_na, low_na, close_na, volume_na

    Args:
        stock_codes: optional list of codes to process. If None, auto-detect from _hfq files.

    Returns:
        Number of successfully merged files.
    """
    os.makedirs(config.PRICE_DATA_DIR, exist_ok=True)

    if stock_codes is None:
        # Auto-detect from _hfq files
        stock_codes = set()
        for f in os.listdir(config.PRICE_DATA_DIR):
            if f.startswith("price_") and f.endswith("_hfq.csv"):
                code = f.replace("price_", "").replace("_hfq.csv", "")
                stock_codes.add(code)
        stock_codes = sorted(stock_codes)

    merged_count = 0
    for code in tqdm(stock_codes, desc="Merging price files"):
        hfq_path = os.path.join(config.PRICE_DATA_DIR, f"price_{code}_hfq.csv")
        na_path = os.path.join(config.PRICE_DATA_DIR, f"price_{code}_na.csv")
        out_path = os.path.join(config.PRICE_DATA_DIR, f"price_{code}.csv")

        if not os.path.exists(hfq_path):
            continue

        hfq_df = pd.read_csv(hfq_path, parse_dates=["trade_date"])
        if hfq_df.empty:
            continue

        # Rename HFQ columns to standard names
        hfq_df = hfq_df.rename(columns={
            "open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"
        })

        if os.path.exists(na_path):
            try:
                na_df = pd.read_csv(na_path, parse_dates=["trade_date"])
                # Rename to _na suffix
                na_rename = {}
                for col in ["open", "high", "low", "close", "volume"]:
                    if col in na_df.columns:
                        na_rename[col] = f"{col}_na"
                na_df = na_df.rename(columns=na_rename)

                # Merge on trade_date
                merged = hfq_df.merge(na_df, on="trade_date", how="left")
            except Exception:
                merged = hfq_df.copy()
        else:
            merged = hfq_df.copy()

        merged = merged.sort_values("trade_date").reset_index(drop=True)
        merged.to_csv(out_path, index=False)
        merged_count += 1

    logger.info(f"Successfully merged {merged_count} price files.")
    return merged_count


def load_financial_data(stock_code: str) -> pd.DataFrame:
    """
    加载单只股票的财务数据

    Args:
        stock_code: stock code

    Returns:
        DataFrame with financial data, or empty DataFrame if not found
    """
    file_path = os.path.join(config.FINANCIAL_DATA_DIR, f"financial_{stock_code}.csv")
    if not os.path.exists(file_path):
        return pd.DataFrame()

    df = pd.read_csv(file_path, parse_dates=["report_date", "ann_available_date"])
    return df


def main():
    """CLI entry point for data downloading"""
    import argparse

    parser = argparse.ArgumentParser(description="Download stock data for backtesting")
    parser.add_argument(
        "--type",
        choices=["pool", "price", "financial", "all"],
        default="all",
        help="Type of data to download"
    )
    parser.add_argument(
        "--start-date",
        default="20150101",
        help="Start date for price data (YYYYMMDD)"
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help="End date for price data (YYYYMMDD)"
    )
    parser.add_argument(
        "--season-end",
        default="2026-04-30",
        help="Season end date for financial data (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--pool-file",
        default=None,
        help="Path to a custom stock pool CSV file (uses merged pool if not specified)"
    )

    args = parser.parse_args()

    # Ensure directories exist
    config.ensure_dirs()

    # Load stock pool
    if args.pool_file:
        pool_df = pd.read_csv(args.pool_file)
        stock_codes = pool_df["code"].astype(str).str.strip().str.zfill(6).tolist()
    else:
        pool_df = load_stock_pool()
        stock_codes = pool_df["code"].tolist()

    if args.type in ("pool", "all"):
        save_stock_pool(stock_codes)

    if args.type in ("price", "all"):
        query_price_data(
            stock_codes,
            start_date=args.start_date,
            end_date=args.end_date
        )

    if args.type in ("financial", "all"):
        query_financial_data(
            stock_codes,
            season_end=args.season_end
        )


if __name__ == "__main__":
    main()
