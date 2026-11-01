#!/usr/bin/env python
"""按原有格式更新 data/input 下的 7 个指数成分股清单。

数据源
------
- 中证指数公司（官方）：000300 沪深300、000905 中证500、000922 中证红利、
  H30269 红利低波、932365 中证现金流 —— 通过 akshare 的 csindex 接口获取。
- 国证指数公司（官方）：980081 国证价值100、980092 国证自由现金流 ——
  通过 akshare 的 cni 接口获取。
- 东方财富「业绩报表」：每股收益 / 每股净资产 / 净资产收益率 / 所属行业
  （与原有 hs300、zz500 文件中 eps、bps、roe 的口径一致：取最近一期累计报表）。
- 腾讯行情：最新价 / 总市值 / 流通市值（用于 price、shares、sub_shares、
  market_cap）。

输出
----
每个池子写一个 ``{pool}_list_{YYYYMMDD}.csv``，列名与旧文件完全一致：

- hs300 / zz500（zz500 保持 TAB 分隔）:
  code,name,price,domain,eps,bps,roe,shares,sub_shares,market_cap
- hongli / honglidibo: date,index_code,code,name,weight
- zzfc: date,index_code,index_name,index_name_en,code,name,code_name,exchange,
  exchange_en,weight
- gz100 / gzfc: date,code,name,domain,market_cap,weight

文件名中的日期取该文件内部 ``date`` 字段的数据日期（中证/国证的最新成分日期），
而不是脚本运行日期。

用法
----
    .venv/bin/python scripts/update_stock_lists.py            # 下载、写文件并更新 config
    .venv/bin/python scripts/update_stock_lists.py --dry-run  # 只打印，不落盘
    .venv/bin/python scripts/update_stock_lists.py --no-config-update
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import datetime
from typing import Iterable

import pandas as pd
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_DIR = os.path.join(ROOT, "data", "input")
CONFIG_PATH = os.path.join(ROOT, "backtesting", "config.py")

# 池子 -> (数据源, 指数代码)
CSI_POOLS = {
    "hs300": "000300",
    "zz500": "000905",
    "hongli": "000922",
    "honglidibo": "H30269",
    "zzfc": "932365",
}
# 带权重的池子（使用 weight 接口）
CSI_WEIGHT_POOLS = {"hongli", "honglidibo", "zzfc"}

CNI_POOLS = {
    "gz100": "980081",   # 国证价值100
    "gzfc": "980092",    # 国证自由现金流
}

POOL_ORDER = ["hs300", "zz500", "hongli", "honglidibo", "gz100", "gzfc", "zzfc"]

# 与 backtesting/data_loader.py 中的 SKIP_STOCKS 保持一致（仅用于统计提示）
SKIP_STOCKS = {"689009"}


# --------------------------------------------------------------------------
# HTTP 辅助
# --------------------------------------------------------------------------
_session = requests.Session()
_session.trust_env = False  # 国内行情站点不走系统代理


def _get(url: str, **params) -> requests.Response:
    last = None
    for attempt in range(3):
        try:
            resp = _session.get(url, params=params or None, timeout=30)
            resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"请求失败: {url} {params} -> {last}")


# --------------------------------------------------------------------------
# 1. 成分股
# --------------------------------------------------------------------------
def fetch_csi_cons(symbol: str) -> pd.DataFrame:
    import akshare as ak

    df = ak.index_stock_cons_csindex(symbol=symbol)
    df = df.rename(
        columns={
            "日期": "date",
            "指数代码": "index_code",
            "指数名称": "index_name",
            "指数英文名称": "index_name_en",
            "成分券代码": "code",
            "成分券名称": "name",
            "成分券英文名称": "code_name",
            "交易所": "exchange",
            "交易所英文名称": "exchange_en",
        }
    )
    df["code"] = df["code"].astype(str).str.zfill(6)
    return df


def fetch_csi_weight(symbol: str) -> pd.DataFrame:
    import akshare as ak

    df = ak.index_stock_cons_weight_csindex(symbol=symbol)
    df = df.rename(
        columns={
            "日期": "date",
            "指数代码": "index_code",
            "指数名称": "index_name",
            "指数英文名称": "index_name_en",
            "成分券代码": "code",
            "成分券名称": "name",
            "成分券英文名称": "code_name",
            "交易所": "exchange",
            "交易所英文名称": "exchange_en",
            "权重": "weight",
        }
    )
    df["code"] = df["code"].astype(str).str.zfill(6)
    return df


def fetch_cni_detail(symbol: str) -> pd.DataFrame:
    import akshare as ak

    df = ak.index_detail_cni(symbol=symbol)
    df = df.rename(
        columns={
            "日期": "date",
            "样本代码": "code",
            "样本简称": "name",
            "所属行业": "domain",
            "总市值": "market_cap",
            "权重": "weight",
        }
    )
    df["code"] = df["code"].astype(str).str.zfill(6)
    return df


# --------------------------------------------------------------------------
# 2. 基本面快照（东财业绩报表）
# --------------------------------------------------------------------------
def fetch_fundamentals(period: str) -> pd.DataFrame:
    """返回 index=code，列: eps, bps, roe, domain(所属行业)。"""
    import akshare as ak

    df = ak.stock_yjbb_em(date=period)
    df = df.rename(
        columns={
            "股票代码": "code",
            "每股收益": "eps",
            "每股净资产": "bps",
            "净资产收益率": "roe",
            "所处行业": "domain",
        }
    )
    df["code"] = df["code"].astype(str).str.zfill(6)
    for col in ("eps", "bps", "roe"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.set_index("code")[["eps", "bps", "roe", "domain"]]


def latest_report_period(today: datetime | None = None) -> str:
    """按 A 股披露节奏挑选已披露的最近一期报告。"""
    today = today or datetime.now()
    y, m = today.year, today.month
    if m >= 11:                      # 10/31 前三季报披露完毕
        return f"{y}0930"
    if m >= 9:                       # 8/31 前中报披露完毕
        return f"{y}0630"
    if m >= 5:                       # 4/30 前一季报披露完毕
        return f"{y}0331"
    return f"{y - 1}0930"            # 年初：上一年三季报


def previous_periods(period: str, n: int = 3) -> list[str]:
    """返回 period 之前的 n 个报告期（从近到远）。"""
    year, md = int(period[:4]), int(period[4:])
    order = [1231, 930, 630, 331]
    idx = order.index(md)
    out: list[str] = []
    while len(out) < n:
        idx += 1
        if idx == len(order):
            idx = 0
            year -= 1
        out.append(f"{year}{order[idx]:04d}")
    return out


def fetch_fundamentals_with_fallback(
    primary: str, codes: Iterable[str], max_periods: int = 3
) -> pd.DataFrame:
    """个别公司（如部分科创板）最新一季报披露较晚，向前回退到上一期。"""
    codes = set(codes)
    frames = [fetch_fundamentals(primary)]

    def still_missing(df: pd.DataFrame) -> set[str]:
        return codes - set(df.dropna(subset=["eps", "bps", "roe"]).index)

    for period in previous_periods(primary, max_periods - 1):
        missing = still_missing(frames[-1])
        if not missing:
            break
        print(f"   回退到 {period} 补齐 {len(missing)} 只缺失股票的财务数据 ...")
        frames.append(fetch_fundamentals(period))

    combined = frames[0].copy()
    for extra in frames[1:]:
        combined = combined.combine_first(extra)
    return combined


# --------------------------------------------------------------------------
# 3. 行情快照（腾讯）
# --------------------------------------------------------------------------
def _tencent_prefix(code: str) -> str:
    if code.startswith(("60", "68", "50", "51", "58", "11", "90")):
        return "sh"
    if code.startswith(("00", "30", "12", "15", "16", "18", "20", "39")):
        return "sz"
    return "bj"


def fetch_quotes(codes: Iterable[str], batch_size: int = 60) -> pd.DataFrame:
    """返回 index=code，列: price, total_mv, float_mv, quote_time。"""
    codes = sorted(set(codes))
    rows: dict[str, tuple] = {}
    for i in range(0, len(codes), batch_size):
        chunk = codes[i : i + batch_size]
        symbols = ",".join(f"{_tencent_prefix(c)}{c}" for c in chunk)
        resp = _get(f"https://qt.gtimg.cn/q={symbols}")
        resp.encoding = "gbk"
        for line in resp.text.split(";"):
            line = line.strip()
            if "=" not in line or '~' not in line:
                continue
            payload = line.split('="', 1)[-1].rstrip('"')
            parts = payload.split("~")
            if len(parts) < 46:
                continue
            code = parts[2].zfill(6)
            try:
                rows[code] = (
                    float(parts[3]),    # 最新价
                    float(parts[45]),   # 总市值（亿元）
                    float(parts[44]),   # 流通市值（亿元）
                    parts[30],          # 行情时间 YYYYMMDDHHMMSS
                )
            except ValueError:
                continue
        time.sleep(0.3)

    df = pd.DataFrame.from_dict(
        rows, orient="index", columns=["price", "total_mv", "float_mv", "quote_time"]
    )
    df.index.name = "code"
    return df


# --------------------------------------------------------------------------
# 4. 组装各池子
# --------------------------------------------------------------------------
def _price_shares(quotes: pd.DataFrame, codes: list[str]) -> pd.DataFrame:
    q = quotes.reindex(codes)
    out = pd.DataFrame(index=pd.Index(codes, name="code"))
    out["price"] = q["price"].round(2)
    out["shares"] = (q["total_mv"] / q["price"]).round(2)
    out["sub_shares"] = (q["float_mv"] / q["price"]).round(2)
    out["market_cap"] = q["float_mv"].round(2)
    return out


def build_hs300_like(
    pool: str, cons: pd.DataFrame, fundamentals: pd.DataFrame, quotes: pd.DataFrame
) -> pd.DataFrame:
    codes = cons["code"].tolist()
    names = dict(zip(cons["code"], cons["name"]))
    df = pd.DataFrame({"code": codes})
    df["name"] = df["code"].map(names)
    df = df.join(_price_shares(quotes, codes), on="code")
    df = df.join(fundamentals.reindex(codes), on="code")
    df["domain"] = df["domain"].fillna("")
    df = df[["code", "name", "price", "domain", "eps", "bps", "roe",
             "shares", "sub_shares", "market_cap"]]
    for col in ("price", "eps", "bps", "roe", "shares", "sub_shares", "market_cap"):
        df[col] = pd.to_numeric(df[col], errors="coerce").round(
            {"price": 2, "eps": 4, "bps": 4, "roe": 2,
             "shares": 2, "sub_shares": 2, "market_cap": 2}[col]
        )
    # 旧文件里 bps 固定 4 位小数，保持一致
    df["bps"] = df["bps"].map(lambda v: f"{v:.4f}" if pd.notna(v) else "")
    return df


def build_weighted(pool: str, raw: pd.DataFrame) -> pd.DataFrame:
    if pool == "zzfc":
        cols = ["date", "index_code", "index_name", "index_name_en", "code",
                "name", "code_name", "exchange", "exchange_en", "weight"]
        out = raw[cols].copy()
        out["date"] = out["date"].astype(str).str.replace("-", "", regex=False)
    else:  # hongli / honglidibo
        out = raw[["date", "index_code", "code", "name", "weight"]].copy()
        out["date"] = out["date"].astype(str).str.replace("-", "", regex=False)
    out["weight"] = pd.to_numeric(out["weight"], errors="coerce").round(3)
    return out


def build_cni(raw: pd.DataFrame) -> pd.DataFrame:
    out = raw[["date", "code", "name", "domain", "market_cap", "weight"]].copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out["market_cap"] = pd.to_numeric(out["market_cap"], errors="coerce").round(2)
    out["weight"] = pd.to_numeric(out["weight"], errors="coerce").round(3)
    return out


# --------------------------------------------------------------------------
# 5. 落盘 + 更新 config
# --------------------------------------------------------------------------
def write_csv(df: pd.DataFrame, pool: str, data_date: str, out_dir: str) -> str:
    sep = "\t" if pool == "zz500" else ","
    # 旧文件：gz100/gzfc/zzfc 带 UTF-8 BOM，其余不带
    encoding = "utf-8-sig" if pool in {"gz100", "gzfc", "zzfc"} else "utf-8"
    path = os.path.join(out_dir, f"{pool}_list_{data_date}.csv")
    df.to_csv(path, sep=sep, index=False, encoding=encoding)
    return path


def update_config(new_files: dict[str, str]) -> None:
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        text = fh.read()
    for pool, path in new_files.items():
        rel = os.path.relpath(path, ROOT)
        parts = ", ".join(f'"{p}"' for p in rel.split(os.sep))
        pattern = rf'("{pool}":\s*os\.path\.join\()[^)]*(\))'
        text, n = re.subn(pattern, rf"\1BASE_DIR, {parts}\2", text)
        if n == 0:
            raise RuntimeError(f"config.py 中找不到 {pool} 的路径配置")
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        fh.write(text)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", default=INPUT_DIR)
    ap.add_argument("--dry-run", action="store_true", help="只打印结果，不写文件")
    ap.add_argument("--no-config-update", action="store_true")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    print("→ 拉取中证指数成分股 ...")
    csi_cons, csi_weight = {}, {}
    for pool, symbol in CSI_POOLS.items():
        if pool in CSI_WEIGHT_POOLS:
            csi_weight[pool] = fetch_csi_weight(symbol)
            print(f"   {pool:10s} {symbol:8s} {len(csi_weight[pool]):4d} 只")
        else:
            csi_cons[pool] = fetch_csi_cons(symbol)
            print(f"   {pool:10s} {symbol:8s} {len(csi_cons[pool]):4d} 只")

    print("→ 拉取国证指数成分股 ...")
    cni = {}
    for pool, symbol in CNI_POOLS.items():
        cni[pool] = fetch_cni_detail(symbol)
        print(f"   {pool:10s} {symbol:8s} {len(cni[pool]):4d} 只")

    all_codes = set()
    for df in list(csi_cons.values()) + list(csi_weight.values()) + list(cni.values()):
        all_codes |= set(df["code"])

    period = latest_report_period()
    print(f"→ 拉取基本面快照（东财业绩报表 {period}）...")
    fundamentals = fetch_fundamentals_with_fallback(period, all_codes)

    print(f"→ 拉取行情快照（腾讯，共 {len(all_codes)} 只）...")
    quotes = fetch_quotes(all_codes)

    built: dict[str, tuple[pd.DataFrame, str]] = {}
    for pool in ("hs300", "zz500"):
        built[pool] = (
            build_hs300_like(pool, csi_cons[pool], fundamentals, quotes),
            csi_cons[pool]["date"].astype(str).str.replace("-", "", regex=False).max(),
        )
    for pool in ("hongli", "honglidibo", "zzfc"):
        raw = csi_weight[pool]
        built[pool] = (
            build_weighted(pool, raw),
            raw["date"].astype(str).str.replace("-", "", regex=False).max(),
        )
    for pool in ("gz100", "gzfc"):
        raw = cni[pool]
        built[pool] = (
            build_cni(raw),
            pd.to_datetime(raw["date"]).max().strftime("%Y%m%d"),
        )

    new_files: dict[str, str] = {}
    print("\n池子       文件                              行数  数据日期")
    print("-" * 66)
    for pool in POOL_ORDER:
        df, data_date = built[pool]
        path = write_csv(df, pool, data_date, args.out_dir) if not args.dry_run else \
            os.path.join(args.out_dir, f"{pool}_list_{data_date}.csv")
        new_files[pool] = path
        print(f"{pool:10s} {os.path.basename(path):34s} {len(df):4d}  {data_date}")

    if args.dry_run:
        print("\n[dry-run] 未写入任何文件")
        return 0

    if not args.no_config_update:
        update_config(new_files)
        print(f"\n✓ 已更新 {os.path.relpath(CONFIG_PATH, ROOT)}")

    union = set()
    for pool in POOL_ORDER:
        df, _ = built[pool]
        union |= set(df["code"])
    effective = union - SKIP_STOCKS
    print(f"\n去重合计 {len(union)} 只；扣除 SKIP_STOCKS {sorted(SKIP_STOCKS)} 后 "
          f"{len(effective)} 只（与 backtest 日志一致）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
