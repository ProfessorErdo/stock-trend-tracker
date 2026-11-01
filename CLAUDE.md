# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Python-based stock analysis tool for A-share market investing. Two main components:
1. **`src/`** — Data ingestion, valuation calculation, and daily reporting pipeline
2. **`backtesting/`** — Backtesting engine for low-valuation + high-ROE stock selection strategy (active development on `dev/backtest` branch)

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

1. **Stock pool**: ~1050 stocks — union of the current and historical members of 7 indices (HS300, ZZ500, Hongli, HongliDibo, GZ100, GZFC, ZZFC); every file matching `EXISTING_STOCK_POOL_FILES` is merged to avoid survivorship bias
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
  → load_stock_pool()              # 7 pools × all list files → ~1050 codes
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
| WINSORIZE_ENABLED | True (1%/99% clipping) |
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
