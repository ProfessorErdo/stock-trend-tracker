# 指数清单更新与全量回测操作手册

> 适用场景：每年 4 月底的年度调仓；以及每季度（或指数公司临时调样时）只想更新数据、重新验证策略的时候。
>
> **下一次正式调仓：2027-04-30 形成截面，2027 年 5 月第一个交易日执行。**
> 在此之前，年度策略不换仓；平时更新数据不会产生新的买卖信号。

---

## 0. 先看这里（TL;DR）

| 你要做的事 | 一句话命令 |
|---|---|
| 每年 4 月底：更新指数清单 | `.venv/bin/python scripts/update_stock_lists.py` |
| 补齐新进池股票的数据 | `.venv/bin/python scripts/fill_missing_pool_data.py` |
| 更新回测价格/财务 | `cd backtesting && ../.venv/bin/python run_backtest.py --update_all --update_only` |
| 跑全量参数对比 | `cd backtesting && ../.venv/bin/python universe_compare.py --end-date <最新交易日>` |
| 生成对比报告 | `cd backtesting && ../.venv/bin/python build_universe_report.py --output-root <结果目录> --report-path ../docs/universe-backtest-<日期>.md --end-date <日期> --assets-dir ../docs/img/universe-backtest-<日期>` |
| 生成调仓计划 | `cd backtesting && ../.venv/bin/python next_rebalance.py`（交互式） |

**当前状态（2026-11-07）**：股票池 1052 只，数据截至 2026-11-06，下一次年度截面 2027-04-30。

---

## 1. 两种更新场景，不要混

| 场景 | 触发时间 | 要更新清单吗 | 要补新股票数据吗 | 要跑全量回测吗 | 会产生调仓吗 |
|---|---|---|---|---|---|
| **年度更新**（推荐） | 每年 4 月底 | 要 | 要 | 要 | 会，5 月首个交易日执行 |
| **季度数据更新** | 1/4/7/10 月 | 清单没变就不用 | 不用 | 可选，看是否要刷新报告 | 不会 |
| **指数临时调样** | 6 月/12 月或公告日 | 要 | 要 | 建议要 | 不会，仍等 4 月底 |

关键点：**只有 4 月底的年度截面会改变持仓**。其他时间更新清单和数据，只是让“下一次 4 月底”的选股更准确，不会提前调仓。

---

## 2. 年度标准流程（每年 4 月 30 日前后）

整个流程按顺序执行，任何一步失败都不要跳到下一步。

### 第 1 步：环境检查

```bash
cd /Users/fanfan/Documents/github/stock-trend-tracker
uv sync
git status --short
```

确认：

- `.venv/` 存在，Python 3.12+。
- 没有未提交的 `backtesting/config.py` 改动（有的话先看清楚是不是上次清单更新留下的）。
- 网络能访问中证指数、国证指数、东方财富、腾讯行情。

### 第 2 步：预览指数清单（不写文件）

```bash
.venv/bin/python scripts/update_stock_lists.py --dry-run
```

检查输出：

- 7 个池子的行数是否大致正常（HS300 300、ZZ500 500、红利 100、红利低波 50、国证价值 100、国证自由现金流 100、中证自由现金流 100）。
- 每个池子的“数据日期”是否是最近一期。
- 最后的“去重合计”和“扣除 SKIP_STOCKS 后”的数量是否合理。

### 第 3 步：正式更新清单

```bash
.venv/bin/python scripts/update_stock_lists.py
```

它会：

1. 从官方数据源下载 7 个指数的最新成分股。
2. 在 `data/input/` 写入 `{pool}_list_{YYYYMMDD}.csv`，列格式与旧文件一致。
3. 自动把新文件追加到 `backtesting/config.py` 的 `EXISTING_STOCK_POOL_FILES`，**保留历史各期**（回测取并集）。

如果只想写 CSV、不想改 config：

```bash
.venv/bin/python scripts/update_stock_lists.py --no-config-update
```

之后需要手动把新文件加入 `backtesting/config.py`，否则回测不会用它。

### 第 4 步：检查清单和配置改动

```bash
git status --short
git diff -- backtesting/config.py
ls -lt data/input/*_list_*.csv | head
```

重点确认：

- 新文件的日期是否正确。
- `config.py` 里每个池子是否多了新文件，历史文件是否还在。
- 去重后的股票池数量（脚本会打印）。

### 第 5 步：补齐新进池股票的数据

```bash
.venv/bin/python scripts/fill_missing_pool_data.py --dry-run
.venv/bin/python scripts/fill_missing_pool_data.py
```

它检查三类问题：

- 缺价格文件；
- 缺财务文件；
- 财务报告期落后于池内最新报告期。

新股票会同时下载后复权、不复权价格，合并价格文件，并下载完整财务历史。
只补指定股票：

```bash
.venv/bin/python scripts/fill_missing_pool_data.py --codes 000404,000788
```

### 第 6 步：更新全部回测数据

```bash
cd backtesting
../.venv/bin/python run_backtest.py --update_all --update_only
```

- 财务数据按 30 天间隔更新，价格按 1 天间隔更新。
- 更新完直接退出，不跑回测。
- 想强制重下全部历史（忽略时间戳）：

```bash
../.venv/bin/python run_backtest.py --update_all --full --update_only
```

### 第 7 步：确认数据截止日一致

这是最容易出错的一步。全量回测之前，确认所有股票的价格都更新到同一个交易日：

```bash
cd backtesting
../.venv/bin/python - <<'PY'
import os
import pandas as pd
import config

files = [
    f for f in os.listdir(config.PRICE_DATA_DIR)
    if f.startswith("price_") and f.endswith(".csv")
    and not f.endswith(("_hfq.csv", "_na.csv"))
]
ends = []
for f in files:
    df = pd.read_csv(os.path.join(config.PRICE_DATA_DIR, f), usecols=["trade_date"])
    ends.append(df["trade_date"].max())
print("股票数:", len(files))
print(pd.Series(ends).value_counts().head(10))
PY
```

正常情况：绝大多数股票停在同一个最新交易日；少数停牌股（例如 000831、002129 停在 10 月底，601059、601198 停在 9 月中）会早于最新日，这是停牌/重组，不是数据错误。

**跑全量回测时用 `--end-date` 固定到这个最新交易日**，避免不同股票的截止日不一致。

### 第 8 步：跑全量参数对比

```bash
cd backtesting
../.venv/bin/python universe_compare.py --pool union --end-date 2027-04-30
```

- `--pool union`：7 个池全部历史清单的并集（当前 1052 只）。
- `--pool legacy`：只用旧的一期清单（932 只），用于和旧记录对比。
- `--pool latest`：只用每个池最新一期（953 只），含幸存者偏差。
- 默认跑完整矩阵：核心网格（7 过滤 × 5 排名）、股票池对比、裁尾、持仓数、阈值、细化、频率、止损，约 130 组。
- 耗时约 20-25 分钟，其中 weekly 那一组最慢（约 4-5 分钟）。
- 输出目录会自动带时间戳：`data/processed/backtesting/universe_compare_<YYYYMMDD_HHMMSS>/`。
- 如果 4/30 当天收盘数据还没出，把 `--end-date` 改成实际最新交易日（例如 4/29）；关键是所有股票停在同一天。

如果只想快速验证某一组参数，用官方单策略 CLI（注意这里参数名是 `--end_date`，不是 `--end-date`）：

```bash
../.venv/bin/python run_backtest.py \
  --frequency annual \
  --ranking pe \
  --filter_indicators pb \
  --pb_threshold 0.15 \
  --roe_threshold 0.70 \
  --threshold_trim_ratio 0.01 \
  --end_date 2027-04-30
```

### 第 9 步：生成报告（图片自动发布）

```bash
cd backtesting
OUT=$(ls -dt ../data/processed/backtesting/universe_compare_2* | head -1)
../.venv/bin/python build_universe_report.py \
  --output-root "$OUT" \
  --report-path ../docs/universe-backtest-2027-04.md \
  --end-date 2027-04-30 \
  --assets-dir ../docs/img/universe-backtest-2027-04
```

`ls -dt ... | head -1` 取最新一次结果目录；`universe_compare_2*` 只匹配带时间戳的并集池目录，不会匹配 `universe_compare_legacy...`。

- `--assets-dir` 会把 `charts/` 里的图片复制过去，并把报告里的图片链接改成相对路径。
- 报告包含：结论速览、股票池对比、核心网格、裁尾、持仓数、阈值、频率、排行榜、稳健性、推荐方案与持仓。
- 如果还要看 932 旧池：

```bash
# 先跑 932
../.venv/bin/python universe_compare.py --pool legacy --end-date 2027-04-30 \
  --output-root ../data/processed/backtesting/universe_compare_legacy932_2027-04

# 再生成对比报告（--compare-root 指向并集池结果）
OUT932=../data/processed/backtesting/universe_compare_legacy932_2027-04
OUT=$(ls -dt ../data/processed/backtesting/universe_compare_2* | head -1)
../.venv/bin/python build_pool_report.py \
  --output-root "$OUT932" \
  --compare-root "$OUT" \
  --report-path ../docs/universe-backtest-932-2027-04.md \
  --end-date 2027-04-30 \
  --assets-dir ../docs/img/universe-backtest-932-2027-04
```

### 第 10 步：读结果，决定今年的参数

先看报告的“结论速览”和“推荐方案”，再重点核对：

- **股票池数量和数据截止日**是否与预期一致。
- 收益最高的方案，**剔除最好年份后**还剩多少（防止单年驱动）。
- 最大回撤和 2015-2020 / 2021-2026 两段是否都为正。
- 当前持仓的行业集中度（低 PB + 高 ROE 经常集中在银行/保险/周期）。
- “最佳参数”是否和上一轮一致；不一致是正常的，说明它对股票池敏感。

**不要只看最高年化。** 2026-11 这轮的结论是：

| 方案 | 年化 | 夏普 | 回撤 | 备注 |
|---|---:|---:|---:|---|
| 1052 池最佳：PB<15% + ROE>70% + PE 排名 + 裁尾 1% + N=5 | 12.37% | 0.516 | -34.51% | 参数扫描产物，当前持仓 5 只银行 |
| 1052 池经典：PB+ROE 25/75 + PB 排名 + 裁尾 2% + N=5 | 9.55% | 0.382 | -33.69% | 更平滑，当前含保险 |
| 932 池最佳：PE<25% + ROE>75% + PB 排名 + 裁尾 1% + N=5 | 12.55% | 0.526 | -33.84% | 旧池幸存者偏差更重 |
| 932 池经典原始阈值 | 11.59% | 0.513 | -40.34% | 历史记录 11.37% 的同口径复现 |

两池的最优解互不通用：932 最佳条件搬到 1052 只剩 8.63%，1052 最佳条件搬到 932 只有 10.61%。下一轮必须重新验证，不要直接套用。

### 第 11 步：生成下一次调仓计划

```bash
cd backtesting
../.venv/bin/python next_rebalance.py
```

交互式输入：

1. 频率选 `4`（Annual only）。
2. 估值分位、ROE 分位按你今年采用的方案输入（例如 1052 最佳：PB 15、ROE 70）。
3. 最大持仓 5。
4. 排名方式：1052 最佳选 `2`（PE lowest）；经典方案选 `1`（PB lowest）。
5. Step2 过滤：1052 最佳选 `3`（PB only）；经典方案选 `1`（三指标）。
6. 是否裁尾：选 `Y`（1%）。
7. 输入总资金。

它会输出代码、名称、真实价格、股数、金额、权重，可保存 CSV。**它不会下单，也不会改真实账户。**

注意：

- 在 2027-04-30 之前运行，它找到的“最新年度截面”仍然是 2026-04-30，输出的是现有持仓的复核，不是新调仓。
- 2027-04-30 数据更新后再运行，才会出现 2027-04-30 截面和 2027-05 执行日。

### 第 12 步：执行后归档

- 把 `universe_compare_<时间戳>/` 保留，不要覆盖。
- 报告写入 `docs/`，图片写入 `docs/img/`。
- 在 `README.md` 的“文档索引”里加一行新报告。
- 记录今年的参数、池子数量、数据截止日、最终持仓。

---

## 3. 季度数据更新（清单没变）

如果只是价格/财务更新，不跑清单脚本：

```bash
cd backtesting
../.venv/bin/python run_backtest.py --update_all --update_only
```

想刷新报告（可选，约 20 分钟）：

```bash
../.venv/bin/python universe_compare.py --end-date <最新交易日>
OUT=$(ls -dt ../data/processed/backtesting/universe_compare_2* | head -1)
../.venv/bin/python build_universe_report.py \
  --output-root "$OUT" \
  --report-path ../docs/universe-backtest-<YYYY-MM>.md \
  --end-date <最新交易日> \
  --assets-dir ../docs/img/universe-backtest-<YYYY-MM>
```

### 3.1 季度更新，但指数清单也变了

按第 2 节的第 2-7 步更新清单、补齐新股票、更新价格/财务，然后跑第 8-9 步的全量回测和报告。**但仍然不要执行调仓**：年度策略只在 4 月底换仓，季度的清单变化只影响下一次截面。

如果指数公司在 6 月/12 月调样，也按这个流程处理；不需要等到 4 月才更新数据。

> 季度检查时如果想让组合“回到目标”，只做**年度篮子内的权重再平衡**，不要重新选股。
> 2026-11 的实验显示：每季度重新选股会把年化从 12%+ 拖到 3.4%，而只做篮子内再平衡仍有 11.5%。
> 详见 [`within-basket-rebalance-2026-11.md`](within-basket-rebalance-2026-11.md)。

---

## 4. 脚本说明

### 4.1 清单与数据

| 脚本 | 作用 | 常用参数 |
|---|---|---|
| `scripts/update_stock_lists.py` | 下载 7 个指数最新成分股，写 `data/input/*.csv`，自动更新 `backtesting/config.py` | `--dry-run` 预览；`--no-config-update` 不自动改配置 |
| `scripts/fill_missing_pool_data.py` | 补齐新进池股票的价格/财务 | `--dry-run` 只检查；`--codes` 只补指定股票 |
| `backtesting/run_backtest.py` | 官方单策略回测/数据更新入口 | `--update_all --update_only` 只更新；`--end_date` 截止日；`--frequency annual` |

### 4.2 全量对比与报告

| 脚本 | 作用 | 关键参数 |
|---|---|---|
| `backtesting/universe_compare.py` | 跑完整参数矩阵，输出 `summary.csv` + 每组明细 | `--pool union/legacy/latest`、`--end-date`、`--phases`、`--output-root` |
| `backtesting/build_universe_report.py` | 生成并集池中文报告和图表 | `--output-root`、`--report-path`、`--end-date`、`--assets-dir` |
| `backtesting/build_pool_report.py` | 生成单池（如 932）报告，并与另一个池对比 | `--output-root`、`--compare-root`、`--report-path`、`--end-date`、`--assets-dir` |
| `backtesting/analyze_holdings_diff.py` | 对比两套持仓在某次调仓后的走势 | `--run-root`、`--out-dir` |
| `backtesting/test_within_basket.py` | 固定年度篮子，测试年内再平衡频率与不等权 | `--configs`、`--frequencies`、`--weightings` |

`universe_compare.py` 的 `--phases` 可选：

```text
core,pool,trim,positions,threshold,refine,frequency,special
```

- `core`：7 种 Step2 过滤 × 5 种排名。
- `pool`：legacy / latest / union 三种池子对比。
- `trim`：裁尾 0%~5%。
- `positions`：N=1~10。
- `threshold`：估值分位与 ROE 分位扫描。
- `refine`：阈值细化（与 1052 那轮相同）。
- `frequency`：7 种调仓频率。
- `special`：止损、纯 PB、经典 2% 等单点。

### 4.3 输出结构

```text
data/processed/backtesting/universe_compare_<时间戳>/
├── summary.csv              # 每组实验一行，核心指标
├── run_config.json          # 池子规模、日期、阶段
├── run.log                  # 运行日志
├── charts/                  # 报告用图
└── runs/<实验id>/
    ├── equity_curve.csv
    ├── annual_returns.csv
    ├── holdings_summary.csv
    ├── trades_record.csv
    └── spec.json
```

---

## 5. 成果索引（2026-11 这一轮）

### 报告

- 1052 并集池全角度回测：[`universe-backtest-2026-11.md`](universe-backtest-2026-11.md)
- 932 旧池同口径对比：[`universe-backtest-932-2026-11.md`](universe-backtest-932-2026-11.md)
- 固定篮子内的再平衡频率与权重：[`within-basket-rebalance-2026-11.md`](within-basket-rebalance-2026-11.md)
- 日常回测 Q&A：[`backtesting-operations-qa.md`](backtesting-operations-qa.md)
- 回测引擎说明：[`../backtesting/README.md`](../backtesting/README.md)

### 原始结果

- 1052 池汇总：[summary.csv](../data/processed/backtesting/universe_compare_20261107_101219/summary.csv)
  （完整目录 `data/processed/backtesting/universe_compare_20261107_101219/`）
- 932 池汇总：[summary.csv](../data/processed/backtesting/universe_compare_legacy932_20261107/summary.csv)
  （完整目录 `data/processed/backtesting/universe_compare_legacy932_20261107/`）
- 更早的 1052 归档：`data/processed/backtesting/annual_1052_*`

### 图表

- 1052：`docs/img/universe-backtest-2026-11/`
- 932：`docs/img/universe-backtest-932-2026-11/`

### 复现脚本

- `backtesting/universe_compare.py`
- `backtesting/build_universe_report.py`
- `backtesting/build_pool_report.py`
- `backtesting/analyze_holdings_diff.py`
- `scripts/update_stock_lists.py`
- `scripts/fill_missing_pool_data.py`

---

## 6. 决策规则与常见坑

1. **参数不跨池稳定。** 932 偏好 PB 排名，1052 偏好 PE 排名；不要把这轮的最佳参数直接套到下一轮。
2. **5 只组合对边际条件极其敏感。** 2026-04-30 常熟银行 ROE 14.090，比原始阈值 14.105 低 0.015pp 被剔除；加 1% 裁尾后入选，并把东航物流挤出前 5。0.015pp 就能换一只股票。
3. **最高年化 ≠ 最好。** 看剔除最好年份后的年化、最大回撤、两段收益、行业集中度。
4. **回测口径要一致。** 比较不同清单版本时，频率、排名、阈值、裁尾、N、日期区间必须相同。
5. **数据截止日要统一。** 全量回测用 `--end-date` 固定到最新交易日；不要让部分股票停在旧日期。
6. **不要并行跑多个 `universe_compare.py`。** 它用进程内缓存和全局 `config`，并行会互相覆盖结果。
7. **清单并集不是无偏的。** 每个池只有 2 期清单，早期年份仍可能包含后来才进入指数的股票。
8. **停牌股不是数据错误。** 000831、002129、601059、601198 的价格停在较早日期，回测会用最后可用价格估值。
9. **`--end_date` 和 `--end-date` 不一样。** `run_backtest.py` 用下划线，`universe_compare.py` 用连字符。
10. **报告图片不要手工复制。** 用 `--assets-dir`，脚本会自动复制并改链接。

---

## 7. 未来 12 个月时间表

| 时间 | 动作 | 是否调仓 |
|---|---|---|
| 2026-11 ~ 2027-03 | 季度数据更新（价格/财务）；清单没变就不跑清单脚本 | 否 |
| 2027-04-30 前后 | 年度标准流程：更新清单 → 补数据 → 更新行情财务 → 全量回测 → 生成报告 | 形成新截面 |
| 2027 年 5 月第一个交易日 | 按 `next_rebalance.py` 的计划执行 | **是** |
| 2027-08 / 2027-10 | 中报/三季报数据更新；年度策略不调仓 | 否 |
| 2028-04-30 | 下一轮年度流程 | 形成新截面 |
| 2028 年 5 月第一个交易日 | 执行 | **是** |

如果指数公司在 6 月/12 月调样，可以提前更新清单和补数据，但**不要提前调仓**；年度策略只在 4 月底换仓。

---

## 8. 常见问题

**Q：更新清单后，回测池数量为什么和上次不一样？**
A：清单并集取的是所有历史文件；新增/调出都会改变数量。以脚本打印的“去重合计”和回测日志为准。

**Q：`update_stock_lists.py` 报网络错误怎么办？**
A：重跑；确认能访问中证/国证/东财/腾讯。失败的池子不会写文件，也不会改 config。

**Q：财务数据看起来没更新？**
A：财务有 30 天更新间隔，属正常。需要强制刷新用 `--update_all --full --update_only`。

**Q：为什么这次回测结果和上次差很多？**
A：先核对股票池数量、数据截止日、裁尾、过滤、排名、N、成本。任何一项不同都不可直接比较。

**Q：跑全量回测太慢？**
A：weekly 那一组最慢，可以先用 `--phases core,trim,threshold` 快速看主要维度，确认后再跑全量。

**Q：报告里的图片不显示？**
A：生成报告时加 `--assets-dir ../docs/img/universe-backtest-<日期>`，不要手工 `cp` 后忘记改链接。

**Q：什么时候能看到 2027 年的新持仓？**
A：2027-04-30 数据更新后跑 `next_rebalance.py`；5 月首个交易日执行后，再用最新日期重跑一次回测，确认成交后的持仓和净值。

---

## 9. 给未来 agent 的快速开始

新 session 按这个顺序读：

1. `README.md` 的“文档索引”。
2. 本文件。
3. `docs/universe-backtest-2026-11.md`（1052 池结论）。
4. `docs/universe-backtest-932-2026-11.md`（932 池对照）。
5. `AGENTS.md`（目录结构、策略逻辑、成本假设）。

开始工作前确认：

- 当前股票池数量（`load_stock_pool()` 打印）。
- 数据截止日（价格文件最大 `trade_date`）。
- 下一次年度截面（当前是 2027-04-30）。
- 输出目录带时间戳，不要覆盖旧结果。
- 跑完报告用 `--assets-dir` 发布图片，并在 README 文档索引里登记。
