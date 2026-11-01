#!/usr/bin/env python
"""补齐股票池中缺少价格/财务缓存的股票数据。

在 ``scripts/update_stock_lists.py`` 更新完清单之后运行本脚本：新进入指数的
股票在 ``data/input/backtesting/{price,financial}`` 里还没有数据，而
``load_price_data()`` 遇到缺失文件会返回空表、不自动下载，这些股票会在回测
第一步被当作“无数据”静默剔除。

用法::

    .venv/bin/python scripts/fill_missing_pool_data.py            # 补齐缺失的
    .venv/bin/python scripts/fill_missing_pool_data.py --dry-run  # 只看缺哪些
    .venv/bin/python scripts/fill_missing_pool_data.py --codes 000404,000788
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backtesting"))

import config  # noqa: E402
import data_loader  # noqa: E402


def pool_codes() -> list[str]:
    return data_loader.load_stock_pool()["code"].tolist()


def missing(codes: list[str]) -> tuple[list[str], list[str]]:
    price_missing = [
        c for c in codes
        if not os.path.exists(os.path.join(config.PRICE_DATA_DIR, f"price_{c}.csv"))
    ]
    fin_missing = [
        c for c in codes
        if not os.path.exists(
            os.path.join(config.FINANCIAL_DATA_DIR, f"financial_{c}.csv")
        )
    ]
    return price_missing, fin_missing


def report(codes: list[str]) -> tuple[list[str], list[str]]:
    price_missing, fin_missing = missing(codes)
    print(f"股票池 {len(codes)} 只 | 缺价格 {len(price_missing)} 只 | 缺财务 {len(fin_missing)} 只")
    if price_missing:
        print("  缺价格:", " ".join(price_missing))
    if fin_missing:
        print("  缺财务:", " ".join(fin_missing))
    return price_missing, fin_missing


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="只检查缺失情况，不下载")
    ap.add_argument("--codes", default="", help="只处理指定代码，逗号分隔")
    args = ap.parse_args()

    codes = [c.strip().zfill(6) for c in args.codes.split(",") if c.strip()] or pool_codes()
    price_missing, fin_missing = report(codes)
    if args.dry_run or not (price_missing or fin_missing):
        return 0

    if price_missing:
        print(f"\n→ 下载后复权价格 {len(price_missing)} 只 ...")
        data_loader.query_price_data(price_missing)
        print(f"\n→ 下载不复权价格 {len(price_missing)} 只 ...")
        data_loader.query_price_data_no_adjust(price_missing)
        print("\n→ 合并复权/不复权文件 ...")
        data_loader.merge_price_files(price_missing)

    if fin_missing:
        print(f"\n→ 下载财务数据 {len(fin_missing)} 只 ...")
        data_loader.query_financial_data(fin_missing)

    print("\n=== 补齐结果 ===")
    price_missing, fin_missing = report(codes)
    if price_missing or fin_missing:
        print("仍有缺失，可重跑本脚本或检查网络/akshare 接口。")
        return 1
    print("全部就绪。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
