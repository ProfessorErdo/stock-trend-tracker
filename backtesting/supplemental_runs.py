#!/usr/bin/env python3
"""
补充实验：修复后的 special 阶段、ROE/估值阈值细化、以及 932 旧记录口径校验。

结果追加到已有 universe_compare 输出目录的 summary.csv。
"""

import argparse
import json
import logging
import os
import sys

import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import universe_compare as uc  # noqa: E402


class Args:
    def __init__(self, end_date):
        self.start_date = "2015-01-01"
        self.end_date = end_date


def spec(**overrides):
    return uc.base_spec(**overrides)


def build_specs():
    """(spec, end_date) 列表。"""
    specs = []

    # ---- special：最优配置的单点实验 ----
    best = dict(
        phase="special",
        filters=["pb"],
        ranking="pe",
        trim=0.01,
        max_positions=5,
    )
    specs.append((spec(**{**best, "stop_loss": True}), "2026-11-06"))
    specs.append((spec(**{**best, "trim": None}), "2026-11-06"))
    specs.append(
        (spec(phase="special", filters=[], ranking="pure_pb", trim=None), "2026-11-06")
    )
    specs.append(
        (
            spec(
                phase="special",
                filters=["pe", "pb", "pr"],
                ranking="pb",
                trim=0.02,
            ),
            "2026-11-06",
        )
    )

    # ---- refine：ROE 阈值 × 裁尾 ----
    for roe in (0.55, 0.60, 0.65, 0.70):
        for trim in (None, 0.01, 0.02):
            specs.append(
                (
                    spec(
                        phase="refine",
                        filters=["pb"],
                        ranking="pe",
                        roe_thr=roe,
                        trim=trim,
                        max_positions=5,
                    ),
                    "2026-11-06",
                )
            )
    # ROE 0.60 下的持仓数与排名方式
    for n in (6, 7):
        specs.append(
            (
                spec(
                    phase="refine",
                    filters=["pb"],
                    ranking="pe",
                    roe_thr=0.60,
                    trim=0.01,
                    max_positions=n,
                ),
                "2026-11-06",
            )
        )
    specs.append(
        (
            spec(
                phase="refine",
                filters=["pb"],
                ranking="pb",
                roe_thr=0.60,
                trim=0.01,
                max_positions=5,
            ),
            "2026-11-06",
        )
    )
    # 估值分位 × ROE 的补充点
    for pe_thr, roe_thr in ((0.15, 0.60), (0.20, 0.60), (0.15, 0.70)):
        specs.append(
            (
                spec(
                    phase="refine",
                    filters=["pb"],
                    ranking="pe",
                    pe_thr=pe_thr,
                    pb_thr=pe_thr,
                    roe_thr=roe_thr,
                    trim=0.01,
                    max_positions=5,
                ),
                "2026-11-06",
            )
        )
    specs.append(
        (
            spec(
                phase="refine",
                filters=["pb"],
                ranking="pe",
                pe_thr=0.15,
                pb_thr=0.15,
                roe_thr=0.65,
                trim=0.01,
                max_positions=6,
            ),
            "2026-11-06",
        )
    )

    # ---- validation：932 旧记录口径校验 ----
    legacy_original = dict(
        filters=["pe", "pb", "pr"],
        ranking="pb",
        trim=None,
        max_positions=5,
    )
    specs.append((spec(phase="val202604", pool="legacy", **legacy_original), "2026-04-30"))
    specs.append((spec(phase="val202611", pool="legacy", **legacy_original), "2026-11-06"))
    specs.append((spec(phase="val202604", pool="union", **legacy_original), "2026-04-30"))
    specs.append(
        (
            spec(
                phase="val202611",
                pool="legacy",
                filters=["pb"],
                ranking="pe",
                trim=None,
                max_positions=5,
            ),
            "2026-11-06",
        )
    )
    return specs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()

    uc.install_caches()
    uc._log.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
    uc._log.addHandler(handler)
    uc._log.propagate = False

    summary_path = os.path.join(args.output_root, "summary.csv")
    existing = pd.read_csv(summary_path)
    rows = existing.to_dict("records")
    done = set(existing["id"])

    preds = build_specs()
    specs = []
    for item in preds:
        item_spec = item[0]
        item_id = uc.make_id(item_spec)
        if item_id in done:
            continue
        done.add(item_id)
        specs.append(item)

    uc._log.info("Supplemental runs: %d", len(specs))
    for item_spec, end_date in specs:
        try:
            row = uc.run_one(item_spec, Args(end_date), args.output_root)
            row["end_date"] = end_date
            rows.append(row)
        except Exception as exc:  # noqa: BLE001
            uc._log.exception("FAILED %s: %s", uc.make_id(item_spec), exc)
        pd.DataFrame(rows).to_csv(summary_path, index=False)

    uc._log.info("Done. total rows=%d", len(rows))


if __name__ == "__main__":
    main()
