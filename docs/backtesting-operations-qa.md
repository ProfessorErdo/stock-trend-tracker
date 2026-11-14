# Stock Trend Tracker：年度回测操作与常见问题

最后整理：2026-11-07

> 年度/季度的完整更新流程（指数清单 → 补齐数据 → 全量回测 → 调仓计划）见
> [`index-update-and-full-backtest-playbook.md`](index-update-and-full-backtest-playbook.md)。
> 本文保留日常命令速查、结果解释和故障排查。

这份文档记录当前仓库的使用方法、年度回测流程、指数清单更新流程、最近实验结论和常见坑。
如果隔几个月后忘记菜单怎么选，优先看本文的“快速命令”和“明年 4 月检查清单”。

> 重要：仓库中的所有“调仓”和“持仓”默认都是历史模拟或本地计算，不会连接券商，
> 不会修改真实账户。

## 目录

1. [先记住这几个入口](#1-先记住这几个入口)
2. [第一次使用或环境损坏](#2-第一次使用或环境损坏)
3. [更新回测价格和财务数据](#3-更新回测价格和财务数据)
4. [更新指数成分股清单](#4-更新指数成分股清单)
5. [运行年度回测](#5-运行年度回测)
6. [阈值裁尾和 2% 版本](#6-阈值裁尾和-2-版本)
7. [查看和解释结果](#7-查看和解释结果)
8. [查看当前持仓与下一次调仓方案](#8-查看当前持仓与下一次调仓方案)
9. [数据和价格口径](#9-数据和价格口径)
10. [常见问题与故障排查](#10-常见问题与故障排查)
11. [2027 年 4 月调仓检查清单](#11-2027-年-4-月调仓检查清单)
12. [命令速查表](#12-命令速查表)

## 1. 先记住这几个入口

本仓库有三类容易混淆的入口：

| 文件 | 用途 |
|---|---|
| `stock-trend-tracker.sh` | 启动、停止 Web 服务；不负责回测数据更新 |
| `src/run_new.sh` | 旧的日常估值筛选、图表和邮件流程；与回测数据目录独立 |
| `backtesting/run.sh` | 年度策略回测、数据更新、调仓计划的主入口 |

如果目标是“PE/PB/PR + ROE 选股并做历史回测”，使用：

```bash
cd /Users/fanfan/Documents/github/stock-trend-tracker/backtesting
./run.sh
```

`backtesting/` 有自己的数据目录：

```text
data/input/backtesting/price/
data/input/backtesting/financial/
data/input/backtesting/query_metadata.json
```

运行 `src/run_new.sh` 不会更新这里的回测数据，反之亦然。

## 2. 第一次使用或环境损坏

在仓库根目录执行：

```bash
cd /Users/fanfan/Documents/github/stock-trend-tracker
uv sync
```

依赖已安装在 `.venv` 时，可以直接运行回测脚本。

检查 Git 状态：

```bash
git status --short
```

仓库通常包含大量生成数据文件，提交代码时不要无脑执行 `git add .`。只暂存本次确实修改的代码和文档。

## 3. 更新回测价格和财务数据

### 3.1 交互式菜单

```bash
cd /Users/fanfan/Documents/github/stock-trend-tracker/backtesting
./run.sh
```

选择：

```text
7) Data update only
4) All data (incremental)
Y
```

当前行为：

- 财务数据距上次成功更新满 30 天才刷新。
- 价格数据距上次成功更新满 1 天才刷新。
- 更新完成后立即退出，不会继续运行回测。
- 价格同时更新后复权、不复权并重新合并文件。

选项说明：

| 菜单 | 含义 |
|---|---|
| `7 → 1` | 只刷新到期的财务数据 |
| `7 → 2` | 只增量刷新价格 |
| `7 → 3` | 强制重下全部价格 |
| `7 → 4` | 财务和价格分别按 30 天/1 天规则更新 |
| `7 → 5` | 忽略更新时间，强制重下财务和价格 |

### 3.2 非交互式更新

只更新到期的数据，不跑回测：

```bash
cd backtesting
../.venv/bin/python run_backtest.py --update_all --update_only
```

强制重下全部数据，不跑回测：

```bash
../.venv/bin/python run_backtest.py --update_all --full --update_only
```

只更新财务：

```bash
../.venv/bin/python run_backtest.py --update_financial --update_only
```

### 3.3 为什么有时看起来没有更新财务

更新时间保存在：

```text
data/input/backtesting/query_metadata.json
```

如果某只股票最近 30 天内已经成功更新，`7 → 4` 会跳过它。这不是故障。

以下情况强制刷新全部：

```text
7 → 5
```

或：

```bash
../.venv/bin/python run_backtest.py --update_all --full --update_only
```

## 4. 更新指数成分股清单

DeepSeek harness 新增了两个脚本：

| 脚本 | 用途 |
|---|---|
| `scripts/update_stock_lists.py` | 从指数官方数据源更新 7 个清单文件，并自动把新文件加入 `backtesting/config.py` |
| `scripts/fill_missing_pool_data.py` | 为新进入股票池的股票补齐历史价格和财务数据 |

### 4.1 先预览，不写文件

在仓库根目录执行：

```bash
cd /Users/fanfan/Documents/github/stock-trend-tracker
.venv/bin/python scripts/update_stock_lists.py --dry-run
```

`--dry-run` 会联网拉取数据，但不会写 CSV，也不会改配置。先检查输出的池子数量、数据日期和合计股票数是否合理。

### 4.2 正式更新清单

```bash
.venv/bin/python scripts/update_stock_lists.py
```

它会：

1. 下载 HS300、ZZ500、中证红利、红利低波、国证价值 100、国证自由现金流、中证自由现金流。
2. 在 `data/input/` 写入类似 `hs300_list_20261030.csv` 的新文件。
3. 保持原来的列格式和分隔符。
4. 把新文件追加到 `backtesting/config.py` 对应池子的文件列表中。

文件名日期通常是指数数据源的成分日期，不一定是运行脚本的日期。

常用参数：

| 参数 | 用途 |
|---|---|
| `--dry-run` | 只预览，不写文件 |
| `--no-config-update` | 写 CSV，但不自动修改 `backtesting/config.py` |
| `--out-dir PATH` | 写到其他目录 |

如果使用 `--no-config-update`，回测不会自动使用新清单，除非之后手动把文件路径加入配置。

### 4.3 补齐新股票的数据

更新清单后先检查缺失：

```bash
.venv/bin/python scripts/fill_missing_pool_data.py --dry-run
```

正式补齐：

```bash
.venv/bin/python scripts/fill_missing_pool_data.py
```

只补指定股票：

```bash
.venv/bin/python scripts/fill_missing_pool_data.py --codes 000404,000788
```

该脚本会检查：

- 是否缺价格文件
- 是否缺财务文件
- 是否财务报告期落后于池内最新报告期

新股票会同时下载后复权、不复权价格，合并价格文件，并下载完整财务历史。

最后再运行一次增量数据更新，确保已有股票的价格和财务也是最新：

```bash
cd backtesting
../.venv/bin/python run_backtest.py --update_all --update_only
```

### 4.4 检查清单和配置改动

```bash
git status --short
git diff -- data/input backtesting/config.py
```

重点确认：

- 新清单日期是否正确。
- 每个池子的数量是否大致正常。
- `backtesting/config.py` 是否加入了新路径。
- 股票池去重后的总数是否与脚本输出一致。

### 4.5 当前 1052 只是怎么算出来的

截至 2026-11-01，`backtesting/config.py` 中每个指数池都保存多期清单文件。
当前各文件原始行数相加为 2,500，跨指数和跨期去重后为 1,053，
再排除 AkShare 无法可靠获取数据的 `689009`，最终回测股票池是 **1,052 只**。

因此：

- 1,250 是更早 932 版本七份清单直接相加的结果。
- 932 是早期版本的最终去重股票池。
- 1,052 是当前多期清单合并后的最新规模。
- “1,032”目前没有对应记录，通常是笔误或某次中间实验的临时数量。

未来更新指数清单后，这个数字可能继续变化，应以脚本输出和回测日志为准。

## 5. 运行年度回测

### 5.1 使用菜单

```bash
cd backtesting
./run.sh
```

选择：

```text
1) Single backtest

[1/10] Data update mode
1) Skip (use existing data)

[2/10] Rebalance frequency
4) Annual only

[3/10] Ranking method
1) PB lowest

[4/11] Step 2 filter indicators
1) PE + PB + PR

[5/11] Valuation thresholds
PE  = 25
PB  = 25
PR  = 25
ROE = 75

[6/11] Max positions
5

[7/11] Threshold trimming
按需要选择：
1 = 使用默认单边裁尾
2 = 使用原始分位阈值

[8/11] Stop-loss
1) Disabled

[9/11] Backtest mode
1) Full backtest

[10/11] Date range
Start: 2015-01-01
End:   留空

[11/11] Confirm
Y
```

注意：交互菜单不能直接输入 2%、3% 等裁尾比例，只能选择默认 1% 或关闭。

### 5.2 推荐的 2% 命令行版本

如果你希望复现当前表现最好的年度参数：

```bash
cd /Users/fanfan/Documents/github/stock-trend-tracker/backtesting

../.venv/bin/python run_backtest.py \
  --frequency annual \
  --ranking pb \
  --filter_indicators pe,pb,pr \
  --start_date 2015-01-01 \
  --threshold_trim_ratio 0.02
```

该命令不会更新数据，直接使用现有缓存。

### 5.3 原始 25%/75% 阈值版本

```bash
../.venv/bin/python run_backtest.py \
  --frequency annual \
  --ranking pb \
  --filter_indicators pe,pb,pr \
  --start_date 2015-01-01 \
  --no_winsorize
```

### 5.4 只使用最新一期指数成分

默认股票池会合并每类指数的所有历史清单。只使用当前最新成分：

```bash
../.venv/bin/python run_backtest.py --frequency annual --latest_pools_only
```

这更接近“按今天的指数成分回看历史”，但会引入幸存者偏差，适合对比，不适合当作严格历史回测。

### 5.5 回测模式和日期

- `Full backtest`：从 2015 年重新计算，数据更新后应选这个。
- `Incremental`：只计算上次之后的新截面，依赖已有 `intermediate.pkl`。
- `Performance only`：只从已有中间结果重算绩效和图表。

## 6. 阈值裁尾和 2% 版本

### 6.1 当前逻辑

阈值裁尾只影响分位阈值，不删除股票：

- PE、PB、PR：各自去掉最低 N%，再计算第 25% 分位。
- ROE：去掉最高 N%，再计算第 75% 分位。
- 四个指标分别从同一股票池独立计算。
- 原始指标仍用于判断股票是否低于或高于最终阈值。

### 6.2 常用参数

默认是 1%：

```bash
--threshold_trim_ratio 0.01
```

2%：

```bash
--threshold_trim_ratio 0.02
```

关闭裁尾：

```bash
--no_winsorize
```

### 6.3 当前 1052 只年度回测实验

| 裁尾 | 累计收益 | 年化收益 | 夏普 | 最大回撤 |
|---:|---:|---:|---:|---:|
| 0% | +136.32% | 7.84% | 0.310 | -33.90% |
| 1% | +155.04% | 8.56% | 0.330 | -33.85% |
| **2%** | **+180.90%** | **9.49%** | **0.379** | -33.69% |
| 3% | +126.11% | 7.42% | 0.272 | -33.72% |
| 4% | +132.51% | 7.68% | 0.290 | -32.87% |
| 5% | +165.45% | 8.94% | 0.350 | -33.01% |

2% 是这批参数中综合最好的版本，但它是同一段历史上的参数比较，存在过拟合风险。

当前 `config.py` 的默认裁尾仍是 **1%**，交互菜单也使用这个默认值。
通用输出目录目前保留的是 1% 版本；2% 版本保存在
`data/processed/backtesting/annual_1052_trim2pct_20261101_1549/`。

如果确定以后采用 2%，要么每次命令行显式传入 `--threshold_trim_ratio 0.02`，
要么把 `backtesting/config.py` 的 `THRESHOLD_TRIM_RATIO` 默认值改为 `0.02`。

### 6.4 932 只旧版为什么更高

旧 932 只年度策略年化约 11.40%，高于当前 1052 只 + 2% 的 9.49%。主要原因是：

- 股票池扩容改变了分位线和 PB 排名。
- 2% 裁尾补足了仓位，但没有恢复所有旧版赢家。
- 932 版本在 2017、2019、2023、2025 等年份选到了后来表现更好的股票。
- 932 版本的最大回撤更深，约 -40.34%，收益更高不等于风险更低。

不要把 11.40% 当作未来预期收益。

### 6.5 2026-11 全池复跑（1052 只，数据截至 2026-11-06）

指数清单合并后，用同一套引擎重跑了 137 组历史实验（口径、成本、日期区间一致）：

| 项目 | 结果 |
|---|---|
| 旧 932 池口径校验（原始阈值 + PB 排名，截至 2026-04-30） | 年化 11.37%、夏普 0.5025、回撤 -40.34%（与旧记录完全一致） |
| 1052 池核心网格最佳（PB 过滤 + PE 排名，裁尾 1%） | 年化 9.37%、夏普 0.356、回撤 -41.63% |
| 1052 池经典配置（PB+ROE → PB 排名，裁尾 2%） | 年化 9.55%、夏普 0.382、回撤 -33.69% |
| 1052 池最佳（PB<15% + ROE>70%，PE 排名，裁尾 1%，N=5） | 年化 12.37%、夏普 0.516、回撤 -34.51% |

要点：

- 新池上 **PE 排名反超 PB 排名**，但回撤更深；PB 排名更平滑。
- 阈值组合 `PB 15% + ROE 70%` 是本次扫描的高点，但它是全期参数搜索的产物；
  当前 5 只持仓全是银行，不能把 12.37% 当作未来预期。
- 完整对比、图表和推荐持仓见 [`universe-backtest-2026-11.md`](universe-backtest-2026-11.md)，
  原始结果在 `data/processed/backtesting/universe_compare_20261107_101219/`。

### 6.6 932 旧池的全量复跑（与 1052 对比）

用同一套引擎、同一截止日（2026-11-06）把 932 旧池也跑了 131 组：

| 项目 | 结果 |
|---|---|
| 932 池最佳（PE<25% + ROE>75% + PB 排名 + 裁尾 1% + N=5 + 年度） | 年化 12.55%、夏普 0.526、回撤 -33.84% |
| 932 经典配置（PB+ROE → PB 排名，原始阈值） | 年化 11.59%（历史记录 11.37%，差额来自数据延长） |
| 1052 池最佳（PB<15% + ROE>70% + PE 排名 + 裁尾 1% + N=5） | 年化 12.37%、夏普 0.516、回撤 -34.51% |
| 把 932 最佳条件搬到 1052 | 只剩 8.63% |
| 把 1052 最佳条件搬到 932 | 只有 10.61% |

结论：**两池的最优解互不通用**。932 偏好 PB 排名，1052 偏好 PE 排名；经典 PB 排名配置在扩容后损失约 3pp。
完整对比见 [`universe-backtest-932-2026-11.md`](universe-backtest-932-2026-11.md)。

## 7. 查看和解释结果

回测完成后，主要文件在：

```text
data/processed/backtesting/
```

| 文件/目录 | 内容 |
|---|---|
| `holdings/holdings_summary.csv` | 每次调仓后的持仓快照 |
| `trades/trades_record.csv` | 买卖记录、费用和原因 |
| `performance/equity_curve.csv` | 每日策略和基准净值 |
| `performance/annual_returns.csv` | 分年度收益 |
| `performance/performance_summary.csv` | 年化、波动率、夏普、最大回撤等 |
| `charts/equity_curve.png` | 净值曲线 |
| `charts/annual_heatmap.png` | 年度收益热图 |
| `intermediate.pkl` | 中间选股结果 |

查看最新持仓：

```bash
tail -n 20 data/processed/backtesting/holdings/holdings_summary.csv
```

`rebalance_date` 最新的一组记录就是最后调仓后的持仓。股数是回测口径，不一定是真实账户可下单股数。

查看最新一次回测日志：

```bash
ls -t backtesting/logs/backtest_*.log | head -1
```

回测一般会覆盖上面这些通用结果文件。运行重要实验前先归档：

```bash
cp -R data/processed/backtesting/holdings \
      data/processed/backtesting/trades \
      data/processed/backtesting/performance \
      data/processed/backtesting/charts \
      YOUR_ARCHIVE_DIRECTORY/
```

当前已经归档的年度版本：

- `annual_1052_raw_20261101_1102`
- `annual_1052_trim1pct_20261101_1101`
- `annual_1052_trim2pct_20261101_1549`
- `annual_1052_trim3pct_20261101_1549`
- `annual_1052_trim4pct_20261101_1550`
- `annual_1052_trim5pct_20261101_1551`
- `universe_compare_20261107_101219`（1052 只全角度对比，137 组实验）

## 8. 查看当前持仓与下一次调仓方案

### 8.1 当前策略应持有什么

如果按 **1052 只股票池 + 2% 裁尾 + 2026-04-30 年度截面**，模拟持仓为：

| 代码 | 名称 |
|---|---|
| 601128 | 常熟银行 |
| 601838 | 成都银行 |
| 600926 | 杭州银行 |
| 601319 | 中国人保 |
| 601601 | 中国太保 |

这些持仓按年度策略应继续持有，直到下一次年度调仓。

同样的 1052 只股票池但使用原始阈值时，只会选出：

```text
600926 杭州银行
601838 成都银行
601156 东航物流
601601 中国太保
```

### 8.2 菜单第 8 项是什么

```bash
./run.sh
```

选择：

```text
8) Next rebalance plan
```

它会：

- 找到当前频率下最新截面。
- 运行本地选股。
- 输入总资金。
- 按真实不复权价格和 100 股整手计算股数、金额、权重。
- 可选保存 `rebalance_plan_YYYYMMDD.csv`。

它不会执行真实交易，也不会修改券商账户。

菜单第 8 项使用 `config.THRESHOLD_TRIM_RATIO`，当前默认是 1%。如果要在交互计划里使用 2%，需要先把 `backtesting/config.py` 中的默认值改为 `0.02`，或以后为 `next_rebalance.py` 增加命令行参数。

### 8.3 4 月底截面的执行日期

年度策略通常在每年 4 月最后一个交易日形成截面，在 5 月第一个交易日执行。

例如：

- 截面日：`2026-04-30`
- 执行日：`2026-05-06`，因为五一休市

如果最新截面之后还没有新交易日，调仓计划可能使用截面日收盘价作为临时成交价，这一点需要人工确认。

## 9. 数据和价格口径

价格文件中同时存在两种价格：

| 列 | 用途 |
|---|---|
| `open/high/low/close/volume` | 后复权；用于历史成交、持仓和净值模拟 |
| `open_na/high_na/low_na/close_na/volume_na` | 不复权真实市场价；用于 PE/PB/PR 和实际调仓股数 |

对应文件：

```text
price_CODE.csv       # 合并文件，包含两种价格
price_CODE_hfq.csv   # 后复权
price_CODE_na.csv    # 不复权
```

财务文件：

```text
financial_CODE.csv
```

主要字段：

- `report_date`：报告期
- `ann_available_date`：按照披露延迟估算的可用日期
- `eps_ttm`：滚动四季 EPS
- `bps_ttm`：滚动四季平均 BPS
- `roe_ttm`：滚动四季 ROE

PE = 真实价格 / EPS

PB = 真实价格 / BPS

PR = PE / ROE

## 10. 常见问题与故障排查

### Q：熄屏后任务会不会停？

显示器熄灭不影响。Mac 进入系统睡眠会暂停进程，网络请求可能失败。

长任务开始前可运行：

```bash
caffeinate -dimsu
```

建议保持终端窗口打开，也不要合上笔记本盖子。

### Q：为什么菜单第 7 项以前跑完还会回测？

旧代码把更新参数传给 `run_backtest.py` 后没有提前退出。该问题已修复，当前第 7 项所有分支都带 `--update_only`。

### Q：为什么财务文件存在但日期没有变化？

增量模式会根据 `query_metadata.json` 检查最近成功更新时间。财务 30 天内不会重复下载。

### Q：如何强制刷新全部财务和价格？

```text
7 → 5
```

或：

```bash
../.venv/bin/python run_backtest.py --update_all --full --update_only
```

### Q：为什么原 25% 阈值在开启 winsorization 后没有变化？

旧实现做的是 1%/99% 双侧截尾，之后仍取 25%/75% 分位，因此正常不会改变阈值。现在已改为单边裁尾后计算分位，并且默认裁尾比例为 1%。

### Q：为什么不直接增加裁尾比例？

裁尾比例和收益不是单调关系。2% 在本次样本中最好，3% 明显变差，5% 又回升。过大的比例会让策略偏离原本的估值筛选。

### Q：为什么只取 5 只？

原来策略固定等于权重，5 只时每只约 20%。少于 5 只会保留现金，多于 5 只会按 PB 取前 5。

### Q：为什么会出现 4 只持仓和大量现金？

4 只时每只最多 20%，总仓位约 80%。这是原策略的集中度控制，不是数据缺失。

### Q：回测结果是 100 万还是 25 万？

主回测固定使用 100 万初始资金。25 万真实配置要使用菜单第 8 项并输入总资金。

### Q：回测会不会操作真实账户？

不会。所有交易都是模拟。

### Q：选股任务失败怎么办？

1. 检查网络。
2. 检查 AkShare 接口是否临时异常。
3. 重新运行同一个更新命令。
4. 失败的股票不会写入成功更新时间，因此会再次重试。

### Q：日志中 Matplotlib 缓存警告怎么办？

通常只是无法写入 `~/.matplotlib`。可以忽略，或设置：

```bash
export MPLCONFIGDIR=/private/tmp/matplotlib-cache
```

### Q：更新指数清单后为什么回测池仍是旧数量？

确认：

```bash
git diff -- backtesting/config.py
```

以及：

```bash
.venv/bin/python scripts/update_stock_lists.py --dry-run
```

如果使用了 `--no-config-update`，需要手动把新文件加入配置。

### Q：合并历史指数清单能完全消除幸存者偏差吗？

不能完全消除。当前做法是把已有各期清单取并集，让曾经属于指数、后来被调出的股票仍保留在回测池中，
这通常比只用最新成分更合理。

但如果只有少数几期清单，并且把这些清单统一用于全部历史年份，早期年份仍然可能包含后来才进入指数的股票，
存在一定的未来信息或选择偏差。要严格验证这一点，需要逐期真实成分数据，或至少同时对比：

```bash
--latest_pools_only
```

与默认历史并集版本，并理解两者的偏差方向不同。

### Q：为什么更新指数清单后重新回测，收益会明显变化？

新增股票会改变 PE/PB/PR/ROE 的相对分位线和 PB 排名。即使原持仓仍满足条件，也可能从 PB 前五名被挤出。

比较不同清单版本时，应保证以下条件相同：

- 调仓频率
- 排名方式
- 四项阈值
- 裁尾比例
- 最大持仓数
- 回测日期区间

否则无法判断收益差异来自股票池还是策略参数。

## 11. 2027 年 4 月调仓检查清单

年报披露截止后，按以下顺序操作：

### 第一步：更新指数清单

```bash
cd /Users/fanfan/Documents/github/stock-trend-tracker
.venv/bin/python scripts/update_stock_lists.py --dry-run
.venv/bin/python scripts/update_stock_lists.py
```

### 第二步：补齐新股票数据

```bash
.venv/bin/python scripts/fill_missing_pool_data.py --dry-run
.venv/bin/python scripts/fill_missing_pool_data.py
```

### 第三步：更新全部回测数据

```bash
cd backtesting
../.venv/bin/python run_backtest.py --update_all --update_only
```

如果希望强制重下全部历史：

```bash
../.venv/bin/python run_backtest.py --update_all --full --update_only
```

### 第四步：运行年度回测

2% 版本：

```bash
../.venv/bin/python run_backtest.py \
  --frequency annual \
  --ranking pb \
  --filter_indicators pe,pb,pr \
  --start_date 2015-01-01 \
  --threshold_trim_ratio 0.02
```

### 第五步：确认新的年度截面

检查最新日志和持仓：

```bash
ls -t logs/backtest_*.log | head -1
tail -n 20 ../data/processed/backtesting/holdings/holdings_summary.csv
```

2027 年 4 月底应出现新的年度截面和 5 月初执行日。

### 第六步：如需 25 万实际股数

运行主菜单：

```bash
./run.sh
```

选择：

```text
8) Next rebalance plan
4) Annual only
```

再按当前策略选择 PB 排名、PE+PB+PR、25/25/25/75、最多 5 只、关闭止损，并输入总资金。

注意：菜单第 8 项默认使用 1% 裁尾。要使用 2%，先确认或调整 `config.THRESHOLD_TRIM_RATIO`。

## 12. 命令速查表

```bash
# 环境
uv sync

# 年度回测菜单
cd backtesting
./run.sh

# 数据更新但不回测
../.venv/bin/python run_backtest.py --update_all --update_only

# 强制更新全部数据但不回测
../.venv/bin/python run_backtest.py --update_all --full --update_only

# 原始阈值年度回测
../.venv/bin/python run_backtest.py \
  --frequency annual --ranking pb --filter_indicators pe,pb,pr \
  --start_date 2015-01-01 --no_winsorize

# 1% 裁尾年度回测
../.venv/bin/python run_backtest.py \
  --frequency annual --ranking pb --filter_indicators pe,pb,pr \
  --start_date 2015-01-01 --threshold_trim_ratio 0.01

# 2% 裁尾年度回测
../.venv/bin/python run_backtest.py \
  --frequency annual --ranking pb --filter_indicators pe,pb,pr \
  --start_date 2015-01-01 --threshold_trim_ratio 0.02

# 更新指数清单
cd ..
.venv/bin/python scripts/update_stock_lists.py --dry-run
.venv/bin/python scripts/update_stock_lists.py

# 补齐新股票数据
.venv/bin/python scripts/fill_missing_pool_data.py --dry-run
.venv/bin/python scripts/fill_missing_pool_data.py

# 只重算现有中间结果的绩效和图表
cd backtesting
../.venv/bin/python run_backtest.py --results_only
```
