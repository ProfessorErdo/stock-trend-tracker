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

## 0.1 文档地图：先看哪一篇

**一句话**：M3b 是当前主口径，先看 M3b 主报告；其他文档是它的明细、口径定义或历史对照。

| 顺序 | 文档 | 角色 | 和主报告的关系 |
|---:|---|---|---|
| 1 | `README.md` | 总索引 | 入口 |
| 2 | 本 playbook | 操作流程 | 入口 |
| 3 | [`m3b-backtest-2026-11.md`](m3b-backtest-2026-11.md) | **主报告（M3b）** | 先看结论、排行、持仓 |
| 3b | [`1052-best-yearly-holdings-2026-11.md`](1052-best-yearly-holdings-2026-11.md) | 1052 最佳逐年持仓 | 主报告的逐年/持仓明细 |
| 3c | [`dividend-yield-strategy-2026-11.md`](dividend-yield-strategy-2026-11.md) | 股息率排名候选补丁 | 主报告的最强候选，待审计 |
| 3d | [`strategy-matrix-2026-11.md`](strategy-matrix-2026-11.md) | **2×2 总览**（旧版四宫格） | 过渡版，保留历史 |
| 3e | [`matrix-summary-2026-11.md`](matrix-summary-2026-11.md) | 2×2 五份报告汇总（过渡版，121+pilot） | 历史 |
| 3f | [`grid-v1-summary-2026-11.md`](grid-v1-summary-2026-11.md) | **grid_v1 2×2 汇总（当前标准）** | 138/87 网格、450 distinct、四格推荐 + 子报告 |
| 4 | [`universe-backtest-2026-11.md`](universe-backtest-2026-11.md) | 1052 池 M1/M2 明细 | 主报告 1052 部分的展开 |
| 5 | [`universe-backtest-932-2026-11.md`](universe-backtest-932-2026-11.md) | 932 池 M1/M2 对照 | 主报告 932 部分的展开 |
| 6 | [`three-start-metrics-2026-11.md`](three-start-metrics-2026-11.md) | M1/M2/M3/M3b 定义 | 解释主报告口径 |
| 7 | [`consolidated-metrics-2026-11.md`](consolidated-metrics-2026-11.md) | 两池四口径合并 | 横向比较、参数迁移 |
| 8 | [`within-basket-rebalance-2026-11.md`](within-basket-rebalance-2026-11.md) | 调仓频率实验 | 独立问题，不参与主排名 |
| 9 | [`earnings-outlier-filter-2026-11.md`](earnings-outlier-filter-2026-11.md) | 妖股/峰值业绩过滤实验 | 独立风险实验，默认不启用 |
| 10 | [`backtesting-operations-qa.md`](backtesting-operations-qa.md) | 数据维护排错 | 运维 |

关系图：

```text
README / playbook（入口）
   └─ M3b 主报告（当前结论）
        ├─ 1052 报告（M1/M2 明细）
        ├─ 932 报告（M1/M2 对照）
        ├─ 三口径报告（M1/M2/M3/M3b 定义）
        └─ 合并对比（两池 × 四口径）
   └─ 独立实验：within-basket（调仓频率）/ earnings-outlier（妖股过滤）
   └─ operations QA（数据维护，运维）
```

阅读建议：

- 只想知道“现在用什么参数”：README → M3b 主报告第 0/2/9 节。
- 要复核 1052 的 M1/M2：M3b 主报告 → 1052 报告。
- 要比较 932：M3b 主报告 → 932 报告 → 合并对比。
- 要理解 M3b 和 M1/M2/M3 的换算：三口径报告。
- 想看 1052 最佳每年买了什么、每只赚了多少：1052-best-yearly-holdings。
- 想看四宫格总览（1052/932 × 股息/非股息）：strategy-matrix。
- 想看“股息率排名”补丁：dividend-yield-strategy（候选，需先排除分红前视偏差）。
- 想看“妖股/峰值业绩过滤”：earnings-outlier-filter（结论：默认不启用）。
- 要重跑 2027：本 playbook 第 8/8b/9 步。

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

### 2.0 股票池版本和回测范围（每年 4 月先想清楚）

每年 4 月指数清单更新后，股票池会变，**不要把“1052”当成永久池子**：

| 池 | 命令 | 是否随 4 月更新变化 |
|---|---|---|
| 932 旧池 | `--pool legacy` | **不变**，固定旧的一期清单，作为历史对照 |
| 当前并集 | `--pool union` | **会变**，每年并集可能增加（1052 → 未来可能 11xx） |
| 未来新池 | `--pool union` | 会变；结果目录要带年份，不能和旧 union 混在一起 |

所以每年 4 月要**先决定这次跑多大范围**，再开始跑：

- **A. 全量（时间/精力充足）**：当前 union + legacy 932，标准 + 2015-start 四套矩阵，约 1.5-2 小时。这是最完整的做法。
- **B. 半量（时间中等）**：当前 union 跑全量；legacy 932 只跑核心网格/关键配置，或直接跳过（932 是固定旧池，主要用于和历史对照）。
- **C. 快速（时间紧）**：只跑当前策略 + 邻域参数（trim / N / 阈值），不做全矩阵，约 10-20 分钟；但这只能做单策略检查，**不能生成完整的 M3b 主报告**。

**最低要求**：如果要更新 M3b 主结论，至少跑当前 union 的 **标准 + 2015-start** 两套；只跑一套会导致 M3b 缺失。legacy 932 可以按时间和精力取舍。

具体每年选 A/B/C 哪一档，到时候结合当年的清单变化幅度、可用时间和是否要做正式决策再定；不要机械地每次都全量。



整个流程按顺序执行，任何一步失败都不要跳到下一步。

### 2.0.1 2×2 标准网格与五份报告（2026-11 起）

**以后只把 M3b 当主指标**；M1/M2/M3 只在需要解释时计算，不再作为排名依据。

**2×2 定义**：`(1052, 932) × (非股息排名, 股息率排名)`。当前用 **grid_v1**：

- 股息：**138 distinct/池**（PB-only 120 + 过滤 core 6 + 组合补充 12）
- 非股息：**87 distinct/池**（核心 35 + 阈值面 44 + trim/N 8）
- 单池 225，两池 **450 distinct**
- 报告里必须写 grid 版本和 distinct 数，不能只写行数。

- **121 是行数，不是 distinct**：非股息去重后 112 个，股息去重后 83 个（排名固定 div 会合并很多行）；股息 + 15 组 pilot（重叠 7、新增 8）= 91 个 distinct。报告里必须同时写“行数/去重数”。
- 7 种过滤：`pe`、`pb`、`pr`、`pe+pb`、`pe+pr`、`pb+pr`、`pe+pb+pr`
- 非股息排名：`pb`、`pe`、`pr`、`roe`、`pure_pb`；股息格固定 `div`
- PB/PE/PR 阈值 0.10-0.40；ROE 0.55-0.85；裁尾 raw-5%；N 1-10
- 阶段：core / trim / positions / threshold / refine

**数据更新清单（每次年度回测）**：

1. 股票清单：`scripts/update_stock_lists.py`
2. 新进池数据：`scripts/fill_missing_pool_data.py`
3. 价格 + 财务：`backtesting/run_backtest.py --update_all --update_only`
4. **分红面板**：`backtesting/fetch_dividend_data.py`（年报 + 中期，2014 至今）
5. 统一 `--end-date`，确认所有股票停在同一交易日

**跑四格 + 出五份报告**：

```bash
cd backtesting
../.venv/bin/python run_matrix_cell_fast.py --pool union  --mode nodiv --workers 2 --specs grids/grid_v1_nodiv.csv --out ../data/processed/backtesting/grid_v1_20261121/1052_nodiv
../.venv/bin/python run_matrix_cell_fast.py --pool union  --mode div   --workers 2 --specs grids/grid_v1_div.csv   --out ../data/processed/backtesting/grid_v1_20261121/1052_div
../.venv/bin/python run_matrix_cell_fast.py --pool legacy --mode nodiv --workers 2 --specs grids/grid_v1_nodiv.csv --out ../data/processed/backtesting/grid_v1_20261121/932_nodiv
../.venv/bin/python run_matrix_cell_fast.py --pool legacy --mode div   --workers 2 --specs grids/grid_v1_div.csv   --out ../data/processed/backtesting/grid_v1_20261121/932_div

# 合订 HTML + PDF（在仓库根目录执行）
python scripts/build_report_bundle.py
# 输出：docs/html/grid-v1-reports-2026-11.html
```

**五份报告**：

- [1052 非股息](matrix-1052-nodiv-2026-11.md)
- [1052 股息](matrix-1052-div-2026-11.md)
- [932 非股息](matrix-932-nodiv-2026-11.md)
- [932 股息](matrix-932-div-2026-11.md)
- [2×2 汇总](matrix-summary-2026-11.md)

**复用原则**：清单/价格/财务/分红都没变时，直接复用上次 `matrix_<date>/` 结果；变了就重跑对应格子。未来清单变成 3×2/4×2 时，加一行池子；如果某个池长期明显更差（如 932），可以移除，类似我们不再把 M1/M2/M3 当主指标。

### 2.0.2 五份报告的内容模板（验收清单）

以后每次出报告，按这个清单验收；缺一项就不算完成。

**每份子报告（4 份）必须包含：**

- [ ] 标题、池子（1052/932）、首买日（2015-05）、主指标 M3b
- [ ] 结论：**推荐配置** + M3b/M1/夏普/回撤
- [ ] 如果网格最高值在参数边界（例如 ROE55），必须注明“边界值”，并给出风险调整推荐（例如 ROE65），不能只放最高值
- [ ] 网格说明：spec 数、过滤/排名/PB/ROE/裁尾/N 的范围
- [ ] Top 10（按 M3b）
- [ ] Top5 年度收益热力图 + Top15 柱图
- [ ] **净值折线图 + 回撤曲线**
- [ ] 2026 持仓：网格最高版 + 推荐版（如果两者不同）
- [ ] 股息格子必须加：**股息率历史曲线 + 2026 持仓股息率表 + 2026 股息率柱图**
- [ ] 本格子特殊情况：池子偏差、分红“预案≈实施”假设、paid 压力测试、边界值、行业集中
- [ ] 复现命令

**总报告（第 5 份）必须包含：**

- [ ] 四格**推荐**表；股息格默认 ROE65；ROE55 是边界，ROE60 可作为稳健候选（不是边界）
- [ ] 2×2 M3b 矩阵图
- [ ] 四格推荐配置的年度收益热力图
- [ ] **四格当前持仓对比表**
- [ ] **四格净值 + 回撤对比图**
- [ ] 股息格组合股息率历史
- [ ] “网格最高 vs 推荐”的说明：ROE55 为什么不用（2021 单年 +123.6%、剔除后跌到 10-12%）；ROE60 若作为稳健候选要单独说明
- [ ] **剔除 2021 的稳健性表（仅股息模式）**：至少比较“网格最高 / 推荐 / 次优”，用 2016-2020+2022-2025 九完整年几何年化
- [ ] **剔除自身最高年的稳健性表（仅股息模式）**：每个策略各剔自己 2016-2025 的最高年，再看剩下 9 年年化；注意不同策略剔的年份可能不同
- [ ] 剔除检验只对 `ranking=div` 做；非股息格不适用，不能把结论套过去
- [ ] §4 用**链接表格**指向四份子报告；每份子报告顶部有“汇总 + 四格”导航
- [ ] §5 分 5.1 剔除 2021 / 5.2 剔除各自最高年，且标注“仅股息模式”
- [ ] 数据口径：价格/财务截止日、分红面板、M3b 定义

**生成方式**：

```bash
cd backtesting
../.venv/bin/python run_matrix_cell_mp.py ...   # 四格
../.venv/bin/python build_matrix_reports.py     # 基础表/热力图
```

> `build_matrix_reports.py` 目前只生成基础表、Top5 热力图、Top15、汇总矩阵；**净值、回撤、股息率、持仓对比是报告必须项，生成后要补齐**（或扩展该脚本）。不要只跑脚本就交报告。

**长期规则**：

- 只把 M3b 当主指标；M1/M2/M3 不要求计算，除非明确要求。
- 股息格默认推荐 **ROE65**；ROE55 只作为边界案例展示；ROE60 是内部稳健候选，不是边界。
- **股息口径**：`declared` 是“预案日 + 最终金额”的上限，含前视；决策默认看 `paid`。报告必须同时给 declared 和 paid，并链接 [股息口径审计](dividend-audit-2026-11.md)。
- 股票池变多时（3×2/4×2），加一行池子；长期明显更差的池子可以退役，并在 README/AGENTS 记录原因。
- 新增/改名/删除报告，必须同步更新 playbook §0.1 文档地图和 README 文档表。

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

### 第 8 步：跑标准矩阵（M1 / M2 辅助口径）

```bash
cd backtesting
OUT1052_STD=../data/processed/backtesting/universe_compare_2027-04
OUT932_STD=../data/processed/backtesting/universe_compare_legacy932_2027-04
OUT1052_15=../data/processed/backtesting/universe_compare_2015start_2027-04
OUT932_15=../data/processed/backtesting/universe_compare_legacy932_2015start_2027-04

../.venv/bin/python universe_compare.py --pool union --end-date 2027-04-30 \
  --output-root "$OUT1052_STD"
../.venv/bin/python universe_compare.py --pool legacy --end-date 2027-04-30 \
  --output-root "$OUT932_STD"
```

- `--pool union`：7 个池全部历史清单的并集（当前 1052 只）。
- `--pool legacy`：旧的一期清单（932 只），用于和旧记录对比。
- 默认跑完整矩阵：核心网格（7 过滤 × 5 排名）、股票池对比、裁尾、持仓数、阈值、细化、频率、止损，约 130 组。
- 每个池约 20-25 分钟，其中 weekly 那一组最慢（约 4-5 分钟）。
- 如果 4/30 当天收盘数据还没出，把 `--end-date` 改成实际最新交易日（例如 4/29）；关键是所有股票停在同一天。
- 标准矩阵给 M1/M2；M3b 需要下一步的 2015-start 矩阵。
- 四个目录变量（`OUT1052_STD` / `OUT932_STD` / `OUT1052_15` / `OUT932_15`）在同一个 shell 里沿用。

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

### 第 8b 步：跑 2015-start 矩阵（M3 / M3b 主口径）

M3b 需要“2015 年 5 月首次建仓”的 2015-start 回测。`--ignore-first-new-stock` 只跳过第一个截面（2015-04-30）的新股过滤，其他年份不变。

```bash
../.venv/bin/python universe_compare.py --pool union --end-date 2027-04-30 \
  --ignore-first-new-stock --output-root "$OUT1052_15"
../.venv/bin/python universe_compare.py --pool legacy --end-date 2027-04-30 \
  --ignore-first-new-stock --output-root "$OUT932_15"
```

这一步是 M3b 的基础，必须跑。四个矩阵（标准/2015-start × 1052/932）合计约 1.5-2 小时，可以分开跑。

> 时间紧时，legacy 932 可以跳过；M3b 报告脚本默认双池，届时可先出 union-only 版本，或只做单策略验证。具体范围按 2.0 节的 A/B/C 再定。

### 第 9 步：生成报告

先出 M1/M2 辅助报告：

```bash
../.venv/bin/python build_universe_report.py \
  --output-root "$OUT1052_STD" \
  --report-path ../docs/universe-backtest-2027-04.md \
  --end-date 2027-04-30 \
  --assets-dir ../docs/img/universe-backtest-2027-04

../.venv/bin/python build_pool_report.py \
  --output-root "$OUT932_STD" \
  --compare-root "$OUT1052_STD" \
  --report-path ../docs/universe-backtest-932-2027-04.md \
  --end-date 2027-04-30 \
  --assets-dir ../docs/img/universe-backtest-932-2027-04
```

再出 **M3b 主报告**：

```bash
../.venv/bin/python build_m3b_dataset.py \
  --std-1052 "$OUT1052_STD" --y15-1052 "$OUT1052_15" \
  --std-932 "$OUT932_STD" --y15-932 "$OUT932_15" \
  --out-dir ../data/processed/backtesting/m3b_2027-04

../.venv/bin/python build_m3b_report.py \
  --data ../data/processed/backtesting/m3b_2027-04/m3b_annual.csv \
  --root-1052 "$OUT1052_15" --root-932 "$OUT932_15" \
  --img-dir ../docs/img/m3b-2027-04 \
  --report ../docs/m3b-backtest-2027-04.md
```

- M3b 报告是主报告；M1/M2 报告只作对照。
- 图片由 `--assets-dir` / `--img-dir` 自动发布。
- `build_m3b_dataset.py` 会检查所有年度配置的首笔建仓日，只保留 2015-05-04 的配置。

### 第 10 步：读结果，决定今年的参数

先看 M3b 报告的“结论速览”和“分池前 10”，再核对：

- **股票池数量和数据截止日**是否与预期一致。
- **M3b 夏普、回撤**是否可接受。
- 当前持仓的行业集中度（低 PB + 高 ROE 经常集中在银行/保险/周期）。
- “最佳参数”是否和上一轮一致；不一致是正常的，说明它对股票池敏感。

**M3b 是主口径，M1 只作历史对照。** 2026-11 这轮的结论：

| 方案 | M3b | M1（对照） | M3b 夏普 | M3b 回撤 |
|---|---:|---:|---:|---:|
| 1052 最佳：PB<15% + ROE>70% + PE 排名 + 裁尾 1% + N=5 | 11.25% | 12.37% | 0.410 | -34.38% |
| 1052 经典：PB+ROE 25/75 + PB 排名 + 裁尾 2% + N=5 | 8.14% | 9.55% | 0.275 | -33.79% |
| 932 最佳：PE<25% + ROE>75% + PB 排名 + 裁尾 1% + N=5 | 11.05% | 12.55% | 0.401 | -33.83% |
| 932 经典：PB+ROE 25/75 + PB 排名 + 裁尾 2% + N=5 | 7.56% | 9.02% | 0.246 | -33.65% |

两池 M3b 最优解互不通用：1052 最佳在 932 只有 9.51%，932 最佳在 1052 只有 7.19%。下一轮必须重新验证，不要直接套用。

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
| `backtesting/enrich_summary_metrics.py` | 给已有 summary 补“首次建仓以来”指标 | `--output-root` |
| `backtesting/compare_three_metrics.py` | 比较 M1/M2/M3 三口径排名 | `--standard-root`、`--start2015-root` |
| `backtesting/build_m3b_dataset.py` | 从 2015-start 回测生成 M3b 年度数据集 | 默认读四个结果目录 |
| `backtesting/build_m3b_report.py` | 生成 M3b 主口径报告和图表 | 默认读 `m3b_annual.csv` |

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

- **M3b 主报告（当前主口径）**：[`m3b-backtest-2026-11.md`](m3b-backtest-2026-11.md)
- 1052 并集池全角度回测：[`universe-backtest-2026-11.md`](universe-backtest-2026-11.md)
- 932 旧池同口径对比：[`universe-backtest-932-2026-11.md`](universe-backtest-932-2026-11.md)
- 固定篮子内的再平衡频率与权重：[`within-basket-rebalance-2026-11.md`](within-basket-rebalance-2026-11.md)
- 三个起点口径 M1/M2/M3：[`three-start-metrics-2026-11.md`](three-start-metrics-2026-11.md)
- 1052 vs 932 全量合并：[`consolidated-metrics-2026-11.md`](consolidated-metrics-2026-11.md)
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
3. **`docs/m3b-backtest-2026-11.md`（M3b 主报告，当前主口径）**。
4. `docs/universe-backtest-2026-11.md` / `docs/universe-backtest-932-2026-11.md`（M1/M2 对照）。
5. `docs/three-start-metrics-2026-11.md`（M1/M2/M3/M3b 定义与排序一致性）。
6. `AGENTS.md`（目录结构、策略逻辑、成本假设）。

开始工作前确认：

- 当前股票池数量（`load_stock_pool()` 打印）。
- 数据截止日（价格文件最大 `trade_date`）。
- 下一次年度截面（当前是 2027-04-30）。
- 输出目录带时间戳，不要覆盖旧结果。
- 跑完报告用 `--assets-dir` 发布图片，并在 README 文档索引里登记。
