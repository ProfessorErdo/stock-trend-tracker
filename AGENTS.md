# AGENTS.md

This file provides guidance to coding agents (DeepSeek Harness, Codex, and other coding agents) when working in this repository.

## Project Overview

A Python-based stock analysis tool for A-share market investing. Two main components:
1. **`src/`** — Data ingestion, valuation calculation, and daily reporting pipeline
2. **`backtesting/`** — Backtesting engine for low-valuation + high-ROE stock selection strategy (active development on `dev/backtest` branch)

## Current State & Docs (2026-11)

- Stock pool: **1052** — union of every historical list file in `config.EXISTING_STOCK_POOL_FILES`
  (currently 14 files across 7 pools; `689009` excluded). The union grows after each April list
  update; `--pool legacy` (932) is a fixed old-pool comparison.
- Backtest data: prices/financials through **2026-11-06** in `data/input/backtesting/`.
- Last annual rebalance: 2026-04-30 cutoff → 2026-05-06.
- **Next annual rebalance: 2027-04-30 cutoff → first trading day of May 2027.**
- Read first: [`docs/index-update-and-full-backtest-playbook.md`](docs/index-update-and-full-backtest-playbook.md)
  (annual/quarterly workflow), then the **M3b-primary report**
  [`docs/m3b-backtest-2026-11.md`](docs/m3b-backtest-2026-11.md), and the
  2×2 five-report summary [`docs/grid-v1-summary-2026-11.md`](docs/grid-v1-summary-2026-11.md)
  (older transition: `docs/matrix-summary-2026-11.md`). M1/M2/M3 are auxiliary metrics.
- M3b = annualized return since the first 2015-05-04 entry (2014 annual report available).
- Recommended 1052 strategy (2026-11): PB10/ROE65 + dividend-yield ranking (M3b 15.53%, paid 12.21%).
  Recent 2023-2026 OOS favors the no-dividend version, so keep monitoring.
- Report history: M1-primary (early 2026-11) -> M3b-primary (mid) -> 2x2 five-report
  standard grid (late 2026-11). Future 3x2/4x2 may add pools; weak pools can be retired
  the same way M1/M2/M3 stopped being primary.
- Report system (2026-11): M3b is the only primary metric; current grid is **grid_v1**:
  dividend 138 distinct/pool, non-dividend 87 distinct/pool, 450 distinct total; 4 cell reports
  plus `docs/grid-v1-summary-2026-11.md`. M1/M2/M3 are auxiliary and need not be computed unless asked.
- grid_v1 finding: dividend max is at ROE55 boundary (1052 17.92%, 932 16.63%), so the default
  stays at ROE65 (1052 15.53%, 932 15.07%); ROE55 is a boundary case, not a plateau.
- Ex-2021 check: ROE55's edge is 2021-driven (both +123.6% in 2021; ex-2021 only 12.14%/10.89%).
  Ex-2021 best: 1052 `pe+pb` PB35/ROE75 (16.65%); 932 PB10/ROE60 (15.34%).
- All ex-2021 / drop-own-best robustness checks are **dividend-only** (`ranking=div`); do not
  apply them to the non-dividend cells.
- Drop-own-best check: each strategy drops its own best 2016-2025 year. Best: 1052 PB10/ROE65
  (13.56%; own best 2017), 932 PB10/ROE60 (15.03%; own best 2017). The two robustness tests disagree
  for 1052 because PB35/ROE75's best year is 2025, not 2021; ROE65 is the only one strong in both.
  Always report full-period, ex-2021, and drop-own-best together.
- Dividend audit: `declared` uses final implemented amount at the first proposal date = look-ahead.
  Paid: 1052 div M3b 12.21%, 2020+ 13.84% (2020-2025 12.55%); 932 div M3b 9.36%, 2020+ 12.28%.
  Treat all declared dividend numbers as upper bounds; use paid for decisions.
- 932 (grid_v1): full-period max PB15/ROE65 + N6, M3b 15.07%, MDD -34.2%;
  robustness-first PB10/ROE60/N5, 14.79%, ex-2021 15.34%, drop-own-best 15.03%, MDD -32.8%.
- Full-sweep scripts: `backtesting/universe_compare.py`, `build_universe_report.py`,
  `build_pool_report.py`, `analyze_holdings_diff.py`, `test_within_basket.py`,
  `enrich_summary_metrics.py`, `compare_three_metrics.py`,
  `build_consolidated_metrics.py`, `build_consolidated_report.py`,
  `build_m3b_dataset.py`, `build_m3b_report.py`, `fetch_dividend_data.py`.

## Report Content Requirements (2026-11)

Every five-report run must follow the checklist in playbook §2.0.2. At minimum:

- 4 cell reports + 1 summary; M3b is the only primary metric.
- Each cell: top10, top5 annual heatmap, top15, **equity + drawdown**, 2026 holdings
  (grid-best and recommended), cell-specific caveats.
- Dividend cells: **dividend-yield history, 2026 holdings yields, yield bar**; default
  recommendation is ROE65; ROE55 is the grid_v1 boundary (do not default to it).
  ROE60 is an interior robust choice (not a boundary) and is the 932 robustness candidate.
  The ROE60 pilot's 2021 +118% was 中绿电 +365%.
- Summary: recommended 2x2 table, matrix, annual heatmap, **holdings comparison**,
  **equity/drawdown comparison**, dividend-yield history, links to 4 cell reports.
- Summary structure: §4 is a **link table** to the four cell reports; §5 is robustness
  (5.1 ex-2021, 5.2 drop-own-best). Each cell report starts with a nav block linking
  summary + all four cells.
- `build_matrix_reports.py` produces only the base tables/charts; the extra sections
  are mandatory and must be added/checked before delivery.
- Report bundle: `scripts/build_report_bundle.py` builds a self-contained, mobile-friendly
  HTML (`docs/html/grid-v1-reports-2026-11.html`) with all five reports, TOC/navigation,
  embedded images, and print CSS. No PDF artifact by default; use browser print if needed.

## Documentation Map Maintenance

- **Any new, renamed, or removed backtest document must be reflected in the doc map.**
  Update both in the same change:
  - `docs/index-update-and-full-backtest-playbook.md` §0.1 文档地图
  - the documentation table in `README.md`
- Keep the M3b report (`docs/m3b-backtest-2026-11.md`) as the primary entry; M1/M2/M3
  reports are supporting detail.
- Before finishing a doc change, check that all relative markdown links resolve.

## Environment Setup

Uses [uv](https://docs.astral.sh/uv/) for package management:
```bash
uv sync
```

Python 3.12+ required. Dependencies managed in `pyproject.toml`. PyPI mirror: `mirrors.aliyun.com`.

All backtesting scripts run from a `.venv` virtual environment via `backtesting/run.sh`.

## Directory Structure

```
stock-trend-tracker/
├── src/                          # Data pipeline (production)
│   ├── query_data_new.py         # Incremental price/financial data fetch from AkShare
│   ├── calculation_and_visualization_new.py  # Valuation calc + distribution plots
│   ├── query_stock_valuation.py  # Single stock valuation query
│   ├── query_top_stocks.py       # Top N stocks by PE/PB/PR/ROE
│   ├── send_emails_new.py        # Daily email report with inline charts
│   └── run_new.sh                # Pipeline runner
├── backtesting/                  # Backtesting engine (active dev)
│   ├── config.py                 # Centralized config: thresholds, costs, limits
│   ├── data_loader.py            # Data fetching (AkShare API + CSV caching)
│   ├── trading_calendar.py       # Trading calendar, cutoff/rebalance date generation
│   ├── stock_selector.py         # 4-step stock selection + ranking
│   ├── portfolio.py              # Portfolio state, position sizing, trade execution
│   ├── backtest_engine.py        # Core orchestrator: selection → trade → equity curve
│   ├── performance.py            # Metrics: Sharpe, drawdown, win rate, turnover
│   ├── visualizer.py             # Equity curve plot + annual returns heatmap
│   ├── run_backtest.py           # Main CLI entry point
│   ├── run.sh                    # Interactive menu for all backtest variants
│   ├── next_rebalance.py         # Calculate next rebalance allocation plan
│   ├── compare_*.py              # Cross-strategy comparison scripts
│   ├── universe_compare.py       # Full parameter sweep (filters × rankings × trim × N × thresholds × frequency)
│   ├── build_universe_report.py  # Build the union-pool report + charts
│   ├── build_pool_report.py      # Build a single-pool report and compare it with another pool
│   ├── analyze_selection.py      # Per-step stock count analysis
│   ├── analyze_rebalance_cycles.py  # Rebalance cycle + DCA simulation
│   └── test_thresholds.py        # Parameter sweep for PE/PB/PR/ROE thresholds
├── data/
│   ├── input/                    # Raw data (CSV stock lists, price, financial)
│   │   ├── backtesting/          # Backtesting-specific input data
│   │   │   ├── price/            # Per-stock price CSVs
│   │   │   └── financial/        # Per-stock financial CSVs
│   │   └── *.csv                 # Index constituent lists (HS300, ZZ500, etc.)
│   └── processed/                # Backtest output
│       └── backtesting/          # Holdings, trades, performance metrics, charts
└── notebooks/                    # Jupyter analysis notebooks
```

## Common Commands

### Backtesting (primary workflow)

```bash
cd backtesting
./run.sh                        # Interactive menu (9 options)
```

Non-interactive mode (pass any arguments to skip the menu):
```bash
./run.sh --frequency annual --ranking pb --full
./run.sh --frequency weekly --max_positions 5 --pe_threshold 0.3
./run.sh --results_only           # Recompute performance from saved intermediate
./run.sh --incremental            # Only run new dates since last backtest
./run.sh --update_price --update_only      # Incremental price update only
./run.sh --update_all --full --update_only # Full re-download only
```

Direct script execution (bypass run.sh):
```bash
cd backtesting
../.venv/bin/python run_backtest.py --frequency annual --ranking pb
../.venv/bin/python next_rebalance.py
../.venv/bin/python compare_frequency_ranking.py
../.venv/bin/python analyze_rebalance_cycles.py
```

### Data Pipeline (src/)

```bash
cd src
./run_new.sh                      # Complete pipeline

# Individual steps
python query_data_new.py --data_type price --stock_type hs300
python calculation_and_visualization_new.py --step all --threshold 0.26
python query_stock_valuation.py --stock_code 600519
python query_top_stocks.py --indicator roe_ttm --top_n 20
```

## Backtesting Architecture

### Strategy Logic

The backtest implements a **low-valuation + high-ROE** stock selection strategy:

1. **Stock pool**: ~1052 stocks — union of the current and historical members of 7 indices (HS300, ZZ500, Hongli, HongliDibo, GZ100, GZFC, ZZFC); every file matching `EXISTING_STOCK_POOL_FILES` is merged to avoid survivorship bias
2. **4-step filter** (each cutoff date):
   - Step 1: Basic filter — exclude suspended stocks, missing financial data, negative valuations
   - Step 2: Valuation filter — PE/PB/PR all below 25th percentile (AND logic)
   - Step 3: ROE filter — ROE above 75th percentile (computed on ALL candidates, not Step 2 survivors)
   - Step 4: New stock filter — exclude stocks with <120 trading days since listing
3. **Ranking**: When filtered stocks > max_positions (default 5), rank by PB-lowest and take top N
4. **Position sizing**: Equal weight, full investment when N >= 5; 20% cap per stock when N < 5
5. **Rebalance**: Annual (after annual report, April cutoff), with alternatives: weekly/monthly/quarterly/annual+Q3

### Execution Flow

```
run_backtest.py
  → load_stock_pool()              # 7 pools × all list files → ~1052 codes
  → build_trading_calendar()       # From price data, filtered by date range
  → get_*_cutoff_dates()           # (cutoff, rebalance) pairs per frequency
  → pre-load all price data
  → compute_benchmark_equity_curve()  # Equal-weight pool, weekly rebalance
  → For each cutoff:
      select_stocks()              # 4-step filter → rank_and_limit()
  → For each rebalance:
      check_limit_up_down()        # Skip if sealed at limit
      calculate_target_positions() # Sell all non-targets, buy targets
      execute sells first, then buys with costs
  → Build daily equity curve from portfolio states
  → calculate_performance()        # 19 metrics
  → generate_visualizations()      # Equity curve + annual heatmap
```

### Trading Costs

| Cost | Rate | Notes |
|------|------|-------|
| Commission | 0.03% | Min 5 RMB per trade |
| Stamp tax | 0.1% | Sell-side only |
| Slippage | 0.1% | Buy +0.1%, Sell -0.1% |
| Lot size | 100 shares | Floor-rounded |

### Key Config Defaults (`backtesting/config.py`)

| Parameter | Default |
|-----------|---------|
| PE_THRESHOLD | 0.25 |
| PB_THRESHOLD | 0.25 |
| PR_THRESHOLD | 0.25 |
| ROE_THRESHOLD | 0.75 |
| MAX_POSITIONS | 5 |
| WINSORIZE_ENABLED | True (compatibility flag for threshold-tail trimming) |
| THRESHOLD_TRIM_RATIO | 0.01 (PE/PB/PR trim low tail; ROE trims high tail) |
| REBALANCE_FREQUENCY | "weekly" |
| INITIAL_CAPITAL | 1,000,000 RMB |
| COMMISSION_RATE | 0.0003 |
| STAMP_TAX_RATE | 0.001 |
| SLIPPAGE_RATE | 0.001 |

### Data Model

- **Price data**: Per-stock CSVs with `trade_date`, `open`, `high`, `low`, `close` (HFQ/post-adjusted) + `close_na` (non-adjusted)
- **Financial data**: Per-stock CSVs with `report_date`, `ann_available_date`, `eps_ttm`, `bps_ttm`, `roe_ttm`
- **Valuation uses non-adjusted close** (`close_na`); **portfolio valuation uses HFQ close** (`close`)
- **Financial data respects disclosure delay**: annual reports available end of April, semi-annual end of August, Q3 end of October

### Important Design Decisions

- `stock_selector.py` line 250: ROE threshold uses `config.ROE_THRESHOLD` (0.75), computed on the full candidate pool, not just Step 2 survivors
- `backtest_engine.py`: Fill prices include slippage — buy = close × (1 + 0.001), sell = close × (1 - 0.001)
- Benchmark is equal-weight ALL pool stocks with weekly rebalancing
- Before first rebalance, strategy equity = INITIAL_CAPITAL (100% cash)
- Suspended stocks use most recent available price for valuation
- Incremental mode uses `intermediate.pkl` to skip already-processed cutoff dates

## Branches

- `main` — Stable version
- `dev/backtest` — Active development branch (current)
