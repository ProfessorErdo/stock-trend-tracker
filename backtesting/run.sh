#!/bin/bash
# Interactive run script for backtesting using project .venv
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "Error: .venv Python not found at $VENV_PYTHON"
    exit 1
fi

cd "$SCRIPT_DIR"

# --- Interactive Mode (default) ---
INTERACTIVE=true

# If any arguments are passed, skip interactive mode
if [ $# -gt 0 ]; then
    INTERACTIVE=false
fi

if $INTERACTIVE; then
    echo "=========================================="
    echo "  Stock Selection Strategy Backtest"
    echo "=========================================="
    echo ""

    # ============================================================
    # Main menu: choose backtest type
    # ============================================================
    echo "Select backtest type:"
    echo "  1) Single backtest — run one strategy (configurable filter, ranking, thresholds)"
    echo "  2) Ranking comparison — 4 ranking methods (PE/PB/PR/ROE) with quarterly frequency"
    echo "  3) Frequency comparison — annual vs annual+semi-annual, PB only"
    echo "  4) Full matrix — 2 frequencies × 5 ranking methods (10 combinations)"
    echo "  5) Selection analysis — how many stocks pass each filtering step"
    echo "  6) Threshold sweep — test PE/PB/PR/ROE quantile combinations"
    echo "  7) Data update only — download data without running backtest"
    echo "  8) Next rebalance plan — calculate what to buy for the next trading day"
    echo "  9) Report timing comparison — annual vs mid-year vs Q3 (1×/year each, PB only)"
    read -rp "Choose [1-9] (default 1): " TYPE_CHOICE
    TYPE_CHOICE=${TYPE_CHOICE:-1}

    # ============================================================
    # Mode 2-6: direct scripts
    # ============================================================
    case $TYPE_CHOICE in
        2)
            echo ""
            echo ">>> Running ranking comparison (PE/PB/PR/ROE, quarterly)..."
            exec $VENV_PYTHON compare_ranking_methods.py
            ;;
        3)
            echo ""
            echo ">>> Running frequency comparison (annual vs annual+semi-annual, PB only)..."
            exec $VENV_PYTHON compare_rebalance_frequency.py
            ;;
        4)
            echo ""
            echo ">>> Running full matrix (2 frequencies × 5 ranking methods)..."
            exec $VENV_PYTHON compare_frequency_ranking.py
            ;;
        5)
            echo ""
            echo "Select analysis frequency:"
            echo "  1) Weekly"
            echo "  2) Monthly"
            echo "  3) Quarterly"
            read -rp "Choose [1-3] (default 3): " SEL_FREQ
            case $SEL_FREQ in
                2) FREQ_ARG="monthly" ;;
                1) FREQ_ARG="weekly" ;;
                *) FREQ_ARG="quarterly" ;;
            esac
            echo ""
            echo ">>> Running selection analysis ($FREQ_ARG)..."
            exec $VENV_PYTHON analyze_selection.py "$FREQ_ARG"
            ;;
        6)
            echo ""
            echo ">>> Running threshold sweep..."
            exec $VENV_PYTHON test_thresholds.py
            ;;
        7)
            echo ""
            echo "[Data Update Only] Choose data type:"
            echo "  1) Financial data only (due per 30-day update metadata)"
            echo "  2) Price data only (incremental — new days)"
            echo "  3) Price data only (full — re-download all)"
            echo "  4) All data (incremental — price + financial)"
            echo "  5) All data (full — re-download everything)"
            read -rp "Choose [1-5] (default 1): " DU_CHOICE
            DU_CHOICE=${DU_CHOICE:-1}

            echo ""
            echo "[2/2] Confirm data update?"
            read -rp "Proceed? [Y/n] " DU_CONFIRM
            DU_CONFIRM=${DU_CONFIRM:-Y}
            if [[ "$DU_CONFIRM" =~ ^[Nn] ]]; then
                echo "Cancelled."
                exit 0
            fi

            echo ""
            case $DU_CHOICE in
                1)
                    echo ">>> Updating financial data only..."
                    CMD="$VENV_PYTHON run_backtest.py --update_financial --update_only"
                    ;;
                2)
                    echo ">>> Updating price data (incremental)..."
                    CMD="$VENV_PYTHON run_backtest.py --update_price --update_only"
                    ;;
                3)
                    echo ">>> Updating price data (full re-download)..."
                    CMD="$VENV_PYTHON run_backtest.py --update_price --full --update_only"
                    ;;
                4)
                    echo ">>> Updating all data (incremental)..."
                    CMD="$VENV_PYTHON run_backtest.py --update_all --update_only"
                    ;;
                5)
                    echo ">>> Updating all data (full re-download)..."
                    CMD="$VENV_PYTHON run_backtest.py --update_all --full --update_only"
                    ;;
                *)
                    echo "Invalid choice, exiting."
                    exit 1
                    ;;
            esac
            echo ">>> Running: $CMD"
            echo ""
            exec $CMD
            ;;
        8)
            echo ""
            echo ">>> Running next rebalance plan calculator..."
            exec $VENV_PYTHON next_rebalance.py
            ;;
        9)
            echo ""
            echo ">>> Running report timing comparison (annual vs mid-year vs Q3, 1×/year each, PB only)..."
            exec $VENV_PYTHON compare_report_timing.py
            ;;
    esac

    # ============================================================
    # Mode 1: Single backtest — full interactive config
    # ============================================================

    # --- [1/10] Data update mode ---
    echo ""
    echo "[1/10] Data update mode:"
    echo "  1) Skip (use existing data)"
    echo "  2) Incremental price update (only download new days)"
    echo "  3) Full price update (re-download all price data)"
    echo "  4) Financial data only (skip already downloaded)"
    echo "  5) Incremental price + financial data"
    echo "  6) Full price + financial data (re-download everything)"
    read -rp "Choose [1-6] (default 1): " DATA_CHOICE
    DATA_CHOICE=${DATA_CHOICE:-1}

    case $DATA_CHOICE in
        2) DATA_FLAG="--update_price" ;;
        3) DATA_FLAG="--update_price --full" ;;
        4) DATA_FLAG="--update_financial" ;;
        5) DATA_FLAG="--update_all" ;;
        6) DATA_FLAG="--update_all --full" ;;
        *) DATA_FLAG="" ;;
    esac

    echo ""

    # --- [2/10] Rebalance frequency ---
    echo "[2/10] Rebalance frequency:"
    echo "  1) Weekly (default)"
    echo "  2) Monthly"
    echo "  3) Quarterly (3×/year: after annual, semi-annual, Q3 reports)"
    echo "  4) Annual only (1×/year: after annual report)"
    echo "  5) Annual + Q3 (2×/year: after annual + Q3 reports)"
    echo "  6) Mid-Year only (1×/year: after mid-year report, Aug cutoff/Sep rebalance)"
    echo "  7) Q3 only (1×/year: after Q3 report, Oct cutoff/Nov rebalance)"
    read -rp "Choose [1-7] (default 1): " FREQ_CHOICE
    FREQ_CHOICE=${FREQ_CHOICE:-1}

    case $FREQ_CHOICE in
        2) FREQ_FLAG="--frequency monthly" ;;
        3) FREQ_FLAG="--frequency quarterly" ;;
        4) FREQ_FLAG="--frequency annual" ;;
        5) FREQ_FLAG="--frequency annual_q3" ;;
        6) FREQ_FLAG="--frequency mid_year" ;;
        7) FREQ_FLAG="--frequency q3" ;;
        *) FREQ_FLAG="" ;;
    esac

    echo ""

    # --- [3/10] Ranking method ---
    echo "[3/10] Ranking method (when filtered stocks > max positions):"
    echo "  1) PB lowest (default)"
    echo "  2) PE lowest"
    echo "  3) PR lowest"
    echo "  4) ROE highest"
    echo "  5) Pure PB lowest (skip 4-step filter, only basic filter + PB rank)"
    read -rp "Choose [1-5] (default 1): " RANK_CHOICE
    RANK_CHOICE=${RANK_CHOICE:-1}

    case $RANK_CHOICE in
        2) RANK_FLAG="--ranking pe" ;;
        3) RANK_FLAG="--ranking pr" ;;
        4) RANK_FLAG="--ranking roe" ;;
        5) RANK_FLAG="--ranking pure_pb" ;;
        *) RANK_FLAG="--ranking pb" ;;
    esac

    echo ""

    # --- [4/11] Step 2 filter indicators ---
    echo "[4/11] Step 2 valuation filter indicators (lower-is-better, AND logic):"
    echo "  1) PE + PB + PR (default, all three AND)"
    echo "  2) PE only"
    echo "  3) PB only"
    echo "  4) PR only"
    echo "  5) PE + PB"
    echo "  6) PE + PR"
    echo "  7) PB + PR"
    echo "  8) Custom (enter your own: pe, pb, pr)"
    read -rp "Choose [1-8] (default 1): " FILTER_CHOICE
    FILTER_CHOICE=${FILTER_CHOICE:-1}

    FILTER_FLAG=""
    case $FILTER_CHOICE in
        2) FILTER_FLAG="--filter_indicators pe" ;;
        3) FILTER_FLAG="--filter_indicators pb" ;;
        4) FILTER_FLAG="--filter_indicators pr" ;;
        5) FILTER_FLAG="--filter_indicators pe,pb" ;;
        6) FILTER_FLAG="--filter_indicators pe,pr" ;;
        7) FILTER_FLAG="--filter_indicators pb,pr" ;;
        8)
            read -rp "  Enter indicators (comma-separated, e.g. pe,pb): " CUSTOM_FILTER
            CUSTOM_FILTER=${CUSTOM_FILTER:-pe,pb,pr}
            FILTER_FLAG="--filter_indicators $CUSTOM_FILTER"
            ;;
        *) FILTER_FLAG="" ;;
    esac

    echo ""

    # --- [5/11] Valuation thresholds ---
    echo "[5/11] Valuation thresholds (quantile cutoffs):"
    read -rp "  PE threshold [1-50] (default 25): " PE_INPUT
    PE_INPUT=${PE_INPUT:-25}
    read -rp "  PB threshold [1-50] (default 25): " PB_INPUT
    PB_INPUT=${PB_INPUT:-25}
    read -rp "  PR threshold [1-50] (default 25): " PR_INPUT
    PR_INPUT=${PR_INPUT:-25}
    read -rp "  ROE threshold [50-99] (default 75): " ROE_INPUT
    ROE_INPUT=${ROE_INPUT:-75}

    THRESH_FLAGS="--pe_threshold 0.$(printf '%02d' $PE_INPUT) --pb_threshold 0.$(printf '%02d' $PB_INPUT) --pr_threshold 0.$(printf '%02d' $PR_INPUT) --roe_threshold 0.$(printf '%02d' $ROE_INPUT)"

    echo ""

    # --- [6/11] Max positions ---
    echo "[6/11] Max positions per rebalance:"
    read -rp "  Number [3-20] (default 5): " MAX_POS
    MAX_POS=${MAX_POS:-5}
    POS_FLAG="--max_positions $MAX_POS"

    echo ""

    # --- [7/11] Threshold tail trimming ---
    echo "[7/11] Quantile threshold tail trimming:"
    echo "  1) Trim adverse 1% tail before quantiles (default)"
    echo "  2) Disable (use raw quantiles)"
    read -rp "Choose [1-2] (default 1): " WIN_CHOICE
    WIN_CHOICE=${WIN_CHOICE:-1}

    case $WIN_CHOICE in
        2) WIN_FLAG="--no_winsorize" ;;
        *) WIN_FLAG="" ;;
    esac

    echo ""

    # --- [8/11] Stop-loss ---
    echo "[8/11] Stop-loss (drawdown-based risk control):"
    echo "  1) Disabled (default)"
    echo "  2) Enable — halve at 15% drawdown, liquidate at 25%"
    echo "  3) Custom thresholds"
    read -rp "Choose [1-3] (default 1): " SL_CHOICE
    SL_CHOICE=${SL_CHOICE:-1}
    SL_FLAG=""

    case $SL_CHOICE in
        2) SL_FLAG="--stop_loss" ;;
        3)
            read -rp "  Half stop-loss drawdown [5-40] (default 15): " SL_HALF
            SL_HALF=${SL_HALF:-15}
            read -rp "  Full stop-loss drawdown [10-50] (default 25): " SL_FULL
            SL_FULL=${SL_FULL:-25}
            SL_FLAG="--stop_loss --stop_loss_half 0.$(printf '%02d' $SL_HALF) --stop_loss_full 0.$(printf '%02d' $SL_FULL)"
            ;;
    esac

    echo ""

    # --- [8/11] Run mode ---
    INTERMEDIATE="$SCRIPT_DIR/../data/processed/backtesting/intermediate.pkl"
    HAS_INTERMEDIATE=false
    if [ -f "$INTERMEDIATE" ]; then
        HAS_INTERMEDIATE=true
    fi

    echo "[9/11] Backtest mode:"
    echo "  1) Full backtest (run everything from scratch)"
    if $HAS_INTERMEDIATE; then
        echo "  2) Performance only (use existing intermediate results)"
        echo "  3) Incremental (only run new dates)"
        read -rp "Choose [1-3] (default 1): " RUN_CHOICE
        RUN_CHOICE=${RUN_CHOICE:-1}
    else
        echo "  2) Performance only (no intermediate results available)"
        read -rp "Choose [1-2] (default 1): " RUN_CHOICE
        RUN_CHOICE=${RUN_CHOICE:-1}
    fi

    case $RUN_CHOICE in
        2)
            if $HAS_INTERMEDIATE; then
                RUN_FLAG="--results_only"
            else
                echo "Error: No intermediate results found, cannot compute performance only."
                exit 1
            fi
            ;;
        3)
            if $HAS_INTERMEDIATE; then
                RUN_FLAG="--incremental"
            else
                echo "Error: No intermediate results found, cannot run incremental backtest."
                exit 1
            fi
            ;;
        *) RUN_FLAG="" ;;
    esac

    echo ""

    # --- [9/11] Date range ---
    if [ "$RUN_FLAG" = "--results_only" ]; then
        echo "[10/11] Performance-only mode, no date range needed."
        START_DATE=""
        END_DATE=""
    else
        echo "[10/11] Backtest date range:"
        read -rp "  Start date (YYYY-MM-DD, default 2015-01-01): " START_DATE
        START_DATE=${START_DATE:-2015-01-01}
        read -rp "  End date (YYYY-MM-DD, leave empty for latest): " END_DATE
    fi

    echo ""

    # --- [11/11] Summary of config ---
    echo "[11/11] Configuration summary:"
    if [ -n "$DATA_FLAG" ]; then
        case "$DATA_CHOICE" in
            2) echo "  Data update: Incremental price" ;;
            3) echo "  Data update: Full price re-download" ;;
            4) echo "  Data update: Financial only" ;;
            5) echo "  Data update: Incremental price + financial" ;;
            6) echo "  Data update: Full price + financial re-download" ;;
            *) echo "  Data update: $DATA_FLAG" ;;
        esac
    else
        echo "  Data update: Skip"
    fi
    case "$FREQ_CHOICE" in
        2) echo "  Rebalance frequency: Monthly" ;;
        3) echo "  Rebalance frequency: Quarterly" ;;
        4) echo "  Rebalance frequency: Annual" ;;
        5) echo "  Rebalance frequency: Annual + Q3" ;;
        6) echo "  Rebalance frequency: Mid-Year only (Aug/Sep)" ;;
        7) echo "  Rebalance frequency: Q3 only (Oct/Nov)" ;;
        *) echo "  Rebalance frequency: Weekly" ;;
    esac
    case "$RANK_CHOICE" in
        2) echo "  Ranking method: PE lowest" ;;
        3) echo "  Ranking method: PR lowest" ;;
        4) echo "  Ranking method: ROE highest" ;;
        5) echo "  Ranking method: Pure PB lowest (no 4-step filter)" ;;
        *) echo "  Ranking method: PB lowest" ;;
    esac
    case "$FILTER_CHOICE" in
        2) echo "  Step 2 filter: PE only" ;;
        3) echo "  Step 2 filter: PB only" ;;
        4) echo "  Step 2 filter: PR only" ;;
        5) echo "  Step 2 filter: PE + PB" ;;
        6) echo "  Step 2 filter: PE + PR" ;;
        7) echo "  Step 2 filter: PB + PR" ;;
        8) echo "  Step 2 filter: ${CUSTOM_FILTER:-pe,pb,pr}" ;;
        *) echo "  Step 2 filter: PE + PB + PR" ;;
    esac
    echo "  PE threshold: <= ${PE_INPUT}%"
    echo "  PB threshold: <= ${PB_INPUT}%"
    echo "  PR threshold: <= ${PR_INPUT}%"
    echo "  ROE threshold: > ${ROE_INPUT}% quantile"
    echo "  Max positions: $MAX_POS"
    if [ -n "$WIN_FLAG" ]; then
        echo "  Threshold trimming: Off (raw quantiles)"
    else
        echo "  Threshold trimming: On (PE/PB/PR low 1%, ROE high 1%)"
    fi
    if [ -n "$SL_FLAG" ]; then
        echo "  Stop-loss: $SL_FLAG"
    else
        echo "  Stop-loss: Off"
    fi
    if [ -n "$RUN_FLAG" ]; then
        echo "  Backtest mode: $RUN_FLAG"
    else
        echo "  Backtest mode: Full backtest"
    fi
    if [ -n "$START_DATE" ]; then
        echo "  Start date: $START_DATE"
    fi
    if [ -n "$END_DATE" ]; then
        echo "  End date: $END_DATE"
    fi
    echo ""

    # --- [12/12] Confirm ---
    echo "[12/12] Confirm?"
    read -rp "Proceed? [Y/n] " CONFIRM
    CONFIRM=${CONFIRM:-Y}
    if [[ "$CONFIRM" =~ ^[Nn] ]]; then
        echo "Cancelled."
        exit 0
    fi

    # Build command
    echo ""
    CMD="$VENV_PYTHON run_backtest.py"
    if [ -n "$DATA_FLAG" ]; then
        CMD="$CMD $DATA_FLAG"
    fi
    if [ -n "$RUN_FLAG" ]; then
        CMD="$CMD $RUN_FLAG"
    fi
    if [ -n "$WIN_FLAG" ]; then
        CMD="$CMD $WIN_FLAG"
    fi
    if [ -n "$SL_FLAG" ]; then
        CMD="$CMD $SL_FLAG"
    fi
    if [ -n "$FREQ_FLAG" ]; then
        CMD="$CMD $FREQ_FLAG"
    fi
    if [ -n "$RANK_FLAG" ]; then
        CMD="$CMD $RANK_FLAG"
    fi
    if [ -n "$FILTER_FLAG" ]; then
        CMD="$CMD $FILTER_FLAG"
    fi
    if [ -n "$THRESH_FLAGS" ]; then
        CMD="$CMD $THRESH_FLAGS"
    fi
    if [ -n "$POS_FLAG" ]; then
        CMD="$CMD $POS_FLAG"
    fi
    if [ -n "$START_DATE" ]; then
        CMD="$CMD --start_date $START_DATE"
    fi
    if [ -n "$END_DATE" ]; then
        CMD="$CMD --end_date $END_DATE"
    fi

    echo ">>> Running: $CMD"
    echo ""
    exec $CMD
else
    # Pass-through mode
    exec "$VENV_PYTHON" run_backtest.py "$@"
fi
