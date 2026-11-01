# Backtesting Module

Backtesting engine for a **low-valuation + high-ROE** A-share stock selection strategy. Part of the Stock Trend Tracker project (active development on the `dev/backtest` branch).

> Note: this module has its **own data directory** (`data/input/backtesting/`, HFQ-adjusted prices) and is independent of the `src/` data pipeline (`data/input/price-data/all`, unadjusted prices). Running `src/run_new.sh` does **not** update backtesting data, and vice versa.

## Quick Start

```bash
cd backtesting
./run.sh                    # Interactive menu (9 options)
```

Non-interactive (any arguments bypass the menu and pass through to `run_backtest.py`):

```bash
./run.sh --frequency annual --ranking pb --full
./run.sh --frequency weekly --max_positions 5 --pe_threshold 0.3
./run.sh --results_only           # Recompute performance from saved intermediate results
./run.sh --incremental            # Only run new cutoff dates since last backtest
./run.sh --update_price --update_only      # Incremental price update only
./run.sh --update_all --full --update_only # Full re-download only, no backtest
```

Direct execution (bypass `run.sh`):

```bash
../.venv/bin/python run_backtest.py --frequency annual --ranking pb
../.venv/bin/python next_rebalance.py
```

## Interactive Menu (`run.sh`)

```
Select backtest type:
  1) Single backtest — run one strategy (configurable filter, ranking, thresholds)
  2) Ranking comparison — 4 ranking methods (PE/PB/PR/ROE) with quarterly frequency
  3) Frequency comparison — annual vs annual+semi-annual, PB only
  4) Full matrix — 2 frequencies × 5 ranking methods (10 combinations)
  5) Selection analysis — how many stocks pass each filtering step
  6) Threshold sweep — test PE/PB/PR/ROE quantile combinations
  7) Data update only — download data without running backtest
  8) Next rebalance plan — calculate what to buy for the next trading day
  9) Report timing comparison — annual vs mid-year vs Q3 (1×/year each, PB only)
```

Option 1 walks through 12 configuration steps: data update mode → rebalance frequency → ranking method → Step 2 filter indicators → 4 quantile thresholds → max positions → winsorization → stop-loss → backtest mode → date range → summary → confirm.

Note: the menu's filter-indicator choices only cover PE/PB/PR combinations. Use `--filter_indicators pe,roe` on the command line for arbitrary combinations (e.g. the PE+ROE variant, see Research Notes).

Option 7 always exits after updating; none of its choices run a backtest. It offers:

- Financial only: refresh stocks due under the 30-day update interval.
- Price only incremental: refresh stocks due under the 1-day update interval.
- Price only full: ignore update timestamps and re-download all price history.
- All data incremental: apply the financial and price intervals independently.
- All data full: ignore update timestamps and re-download both datasets.

Backtesting has its own update metadata at `data/input/backtesting/query_metadata.json`. This keeps its refresh state independent from the `src/` pipeline.

## Strategy Logic

1. **Stock pool**: ~1050 stocks — each of the 7 index lists (HS300, ZZ500, Hongli, HongliDibo, GZ100, GZFC, ZZFC) maps to *all* its historical CSV files in `data/input/`, merged and deduplicated, so stocks that left an index stay in the pool (no survivorship bias).
2. **4-step filter** (at each cutoff date):
   - Step 1: Basic filter — exclude suspended stocks, missing financial data, negative valuations
   - Step 2: Valuation filter — PE/PB/PR below the 25th percentile (AND logic; indicator set configurable via `--filter_indicators`)
   - Step 3: ROE filter — ROE above the 75th percentile (computed on ALL candidates, not just Step 2 survivors)
   - Step 4: New stock filter — exclude stocks with < 120 trading days since listing
3. **Ranking**: when filtered stocks > `MAX_POSITIONS` (default 5), rank and take the top N. Options: `pb` (lowest), `pe`, `pr`, `roe` (highest), `pure_pb` (skip the 4-step filter, rank the whole pool by PB).
4. **Position sizing**: equal weight, full investment when N >= 5; 20% cap per stock when N < 5.
5. **Rebalance**: annual (after annual report, April cutoff), or weekly / monthly / quarterly / annual+Q3 / mid-year / Q3.

## CLI Reference (`run_backtest.py`)

| Flag | Description |
|------|-------------|
| `--frequency` | `weekly` \| `monthly` \| `quarterly` \| `annual` \| `annual_q3` \| `mid_year` \| `q3` |
| `--ranking` | `pb` (default) \| `pe` \| `pr` \| `roe` \| `pure_pb` |
| `--filter_indicators` | Comma-separated Step 2 indicators, e.g. `pe,pb`, `pe,roe` (default `pe,pb,pr`) |
| `--pe_threshold` / `--pb_threshold` / `--pr_threshold` | Quantile cutoff 0–1 (default 0.25) |
| `--roe_threshold` | Quantile cutoff 0–1 (default 0.75) |
| `--max_positions` | Max stocks per rebalance (default 5) |
| `--no_winsorize` | Disable 1%/99% extreme-value clipping |
| `--stop_loss` | Enable drawdown stop-loss (default 15% halve / 25% liquidate) |
| `--stop_loss_half` / `--stop_loss_full` | Custom stop-loss drawdowns |
| `--start_date` / `--end_date` | Backtest date range (default 2015-01-01 → latest) |
| `--results_only` | Recompute performance from existing `intermediate.pkl` |
| `--incremental` | Only run cutoff dates after the last saved one |
| `--full` | Bypass update timestamps and re-download selected data; if a backtest follows, it starts fresh |
| `--update_price` | Update price data; then backtest unless `--update_only` |
| `--update_financial` | Update financial data; then backtest unless `--update_only` |
| `--update_all` (alias `--fetch_data`) | Update price + financial data; then backtest unless `--update_only` |
| `--update_only` | Exit after data update without running a backtest |
| `--financial_season_end` | Latest report date to include (default: current year-end) |
| `--price_start` | Price download start date (default `20150101`) |

Incremental updates use per-stock timestamps. Financial data is due after 30 days and price data after 1 day. `--full` bypasses these timestamps.

`--update_financial` and `--update_all`/`--update_price` are mutually exclusive branches. To do a **full financial re-download without a backtest**, run:

```bash
./run.sh --update_financial --full --update_only
```

## Data Model

- **Price data**: per-stock CSVs in `data/input/backtesting/price/` with `trade_date`, `open`, `high`, `low`, `close` (HFQ/adjusted) + `close_na` (non-adjusted).
- **Financial data**: per-stock CSVs in `data/input/backtesting/financial/` with `report_date`, `ann_available_date`, `eps_ttm`, `bps_ttm`, `roe_ttm`.
- **Update metadata**: `data/input/backtesting/query_metadata.json` stores each stock's last successful financial/price refresh.
- **Valuation uses non-adjusted close** (`close_na`); **portfolio valuation uses HFQ close** (`close`).
- **Disclosure delay**: annual reports available end of April, semi-annual end of August, Q3 end of October (configurable in `REPORT_AVAILABLE_MONTHS`).

## Trading Costs

| Cost | Rate | Notes |
|------|------|-------|
| Commission | 0.03% | Min 5 RMB per trade |
| Stamp tax | 0.1% | Sell-side only |
| Slippage | 0.1% | Buy +0.1%, Sell −0.1% |
| Lot size | 100 shares | Floor-rounded |

## Key Config Defaults (`config.py`)

| Parameter | Default | Notes |
|-----------|---------|-------|
| `FILTER_INDICATORS` | `["pe", "pb", "pr"]` | Step 2 AND filter |
| `PE/PB/PR_THRESHOLD` | 0.25 | Keep lowest 25% |
| `ROE_THRESHOLD` | 0.75 | Keep highest 25% |
| `WINSORIZE_ENABLED` | True | 1%/99% clipping |
| `MAX_POSITIONS` | 5 | Max holdings |
| `NEW_STOCK_EXCLUDE_DAYS` | 120 | Min trading days since listing |
| `REBALANCE_FREQUENCY` | `"weekly"` | |
| `INITIAL_CAPITAL` | 1,000,000 RMB | |
| `MIN_FULL_POSITION_STOCKS` / `MAX_SINGLE_POSITION` | 5 / 0.20 | Full invest when N≥5, 20% cap otherwise |
| `STOP_LOSS_HALF/FULL_DRAWDOWN` | 0.15 / 0.25 | Disabled by default |

Limit up/down rules are also in `config.py` (`LIMIT_RATIO_RULES`): 10% main board, 20% ChiNext (after 2020-08-24) / STAR, 30% Beijing exchange.

## Outputs (`data/processed/backtesting/`)

- `holdings/` — per-rebalance portfolio holdings snapshots
- `trades/` — trade log with costs
- `performance/` — `equity_curve.csv`, `annual_returns.csv`, `performance_summary.csv`
- `charts/` — equity curve plot + annual returns heatmap
- `intermediate.pkl` — cached per-cutoff selection results (used by `--results_only` / `--incremental`)
- Experiment-specific subdirectories (`momentum_test/`, `pb_rank_1_10/`, `stop_loss_test/`, `pe_vs_pb_test/`, …)

## Next Rebalance Plan

```bash
./run.sh     # select option 8
```

`next_rebalance.py` finds the latest cutoff date, interactively configures frequency / thresholds / max positions / ranking / filter indicators, runs the 4-step selection, and outputs a buy plan (code, name, price, shares, amount) optionally saved as CSV. It is **pure local computation** — it never downloads data. Run an update first (`./run.sh --update_price`) if the local data is stale.

Note: its filter-indicator menu only offers PE/PB/PR combinations (no `pe,roe`).

## Analysis & Experiment Scripts

| Script | Purpose |
|--------|---------|
| `analyze_selection.py` | Per-step stock count analysis for each cutoff |
| `analyze_rebalance_cycles.py` | Post-rebalance rolling 252-day returns; feeds the monthly DCA simulation |
| `analyze_holding_returns.py` / `analyze_2018_returns.py` | Holding 1-year returns / 2018 bear-market per-stock returns |
| `analyze_pe_ratios.py` / `analyze_pe_thresholds.py` | PE_ratio of selected stocks vs subsequent 1-year price change |
| `generate_pe_history.py` | Daily per-stock PE time series → `pe_history/` |
| `compare_ranking_methods.py` | 4 ranking methods, quarterly |
| `compare_rebalance_frequency.py` | Annual vs annual+semi-annual, PB |
| `compare_frequency_ranking.py` | Full matrix: 2 frequencies × 5 rankings |
| `compare_pe_vs_pb_filter.py` | PE+ROE vs PB+ROE filter, PB rank top 5 |
| `compare_report_timing.py` | Annual vs mid-year vs Q3 report timing |
| `test_thresholds.py` | Parameter sweep of PE/PB/PR/ROE quantiles |
| `test_filter_combos.py` / `test_scoring.py` | Indicator-combination tests / score-based ranking |
| `test_stop_loss.py` | Drawdown stop-loss variants |
| `test_momentum_weighted.py` / `test_momentum_3x_yearly.py` | Momentum-based alternatives |
| `test_pb_rank_1_to_10.py` | PB rank top-N sweep (N=1..10) |
| `test_pe_trend_filter.py` / `test_pe_ge50_filter.py` | PE-based pre-filters |
| `test_dca_strategy.py` | Monthly 30k DCA + drawdown-triggered top-up |
| `simulate_survivorship.py` | Random pool-shrinkage to estimate survivorship bias |
| `debug_selection.py` | Trace how individual stocks pass the 4-step filter |
| `plot_drawdown_comparison.py` / `plot_equity_vs_drawdown.py` / `plot_pe_ratio_*.py` | Analysis plots |

## Research Notes

Findings from the comparison experiments are documented in `../doc/backtesting-issues.md`. Summary:

- The original strategy (PE+PB+PR+ROE hard thresholds + PB rank, annual, N=5) achieves ~11.37% annualized (2015–2026) with a −40% max drawdown.
- The only variant that beat it: **PE+ROE filter + PB rank** (~11.90%), run as `--filter_indicators pe,roe --ranking pb --frequency annual --no_winsorize`.
- Simplification: PB+ROE alone reproduces the original results exactly; PR and PE are redundant.
- Stop-loss, score-based ranking, momentum and PE-trend variants all underperformed in annual-rebalance mode.
- The 11.37% figure is likely inflated by survivorship bias; expected true range ~8–10%.
