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
    echo "  1) Single backtest — run one strategy (configurable)"
    echo "  2) Ranking comparison — 4 ranking methods (PE/PB/PR/ROE) with quarterly frequency"
    echo "  3) Frequency comparison — annual vs annual+semi-annual, PB only"
    echo "  4) Full matrix — 2 frequencies × 5 ranking methods (10 combinations)"
    echo "  5) Selection analysis — how many stocks pass each filtering step"
    echo "  6) Threshold sweep — test PE/PB/PR/ROE quantile combinations"
    echo "  7) Data update only — download data without running backtest"
    read -rp "Choose [1-7] (default 1): " TYPE_CHOICE
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
            echo "  1) Financial data only"
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
                    CMD="$VENV_PYTHON run_backtest.py --update_financial"
                    ;;
                2)
                    echo ">>> Updating price data (incremental)..."
                    CMD="$VENV_PYTHON run_backtest.py --update_price"
                    ;;
                3)
                    echo ">>> Updating price data (full re-download)..."
                    CMD="$VENV_PYTHON run_backtest.py --update_price --full"
                    ;;
                4)
                    echo ">>> Updating all data (incremental)..."
                    CMD="$VENV_PYTHON run_backtest.py --update_all"
                    ;;
                5)
                    echo ">>> Updating all data (full re-download)..."
                    CMD="$VENV_PYTHON run_backtest.py --update_all --full"
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
    read -rp "Choose [1-5] (default 1): " FREQ_CHOICE
    FREQ_CHOICE=${FREQ_CHOICE:-1}

    case $FREQ_CHOICE in
        2) FREQ_FLAG="--frequency monthly" ;;
        3) FREQ_FLAG="--frequency quarterly" ;;
        4) FREQ_FLAG="--frequency annual" ;;
        5) FREQ_FLAG="--frequency annual_q3" ;;
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

    # --- [4/10] Valuation thresholds ---
    echo "[4/10] Valuation thresholds (quantile cutoffs):"
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

    # --- [5/10] Max positions ---
    echo "[5/10] Max positions per rebalance:"
    read -rp "  Number [3-20] (default 10): " MAX_POS
    MAX_POS=${MAX_POS:-10}
    POS_FLAG="--max_positions $MAX_POS"

    echo ""

    # --- [6/10] Winsorization ---
    echo "[6/10] Extreme value handling (winsorization):"
    echo "  1) Enable 1%/99% clipping (default)"
    echo "  2) Disable (use raw quantiles)"
    read -rp "Choose [1-2] (default 1): " WIN_CHOICE
    WIN_CHOICE=${WIN_CHOICE:-1}

    case $WIN_CHOICE in
        2) WIN_FLAG="--no_winsorize" ;;
        *) WIN_FLAG="" ;;
    esac

    echo ""

    # --- [7/10] Run mode ---
    INTERMEDIATE="$SCRIPT_DIR/../data/processed/backtesting/intermediate.pkl"
    HAS_INTERMEDIATE=false
    if [ -f "$INTERMEDIATE" ]; then
        HAS_INTERMEDIATE=true
    fi

    echo "[7/10] Backtest mode:"
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

    # --- [8/10] Date range ---
    if [ "$RUN_FLAG" = "--results_only" ]; then
        echo "[8/10] Performance-only mode, no date range needed."
        START_DATE=""
        END_DATE=""
    else
        echo "[8/10] Backtest date range:"
        read -rp "  Start date (YYYY-MM-DD, default 2015-01-01): " START_DATE
        START_DATE=${START_DATE:-2015-01-01}
        read -rp "  End date (YYYY-MM-DD, leave empty for latest): " END_DATE
    fi

    echo ""

    # --- [9/10] Summary of config ---
    echo "[9/10] Configuration summary:"
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
        *) echo "  Rebalance frequency: Weekly" ;;
    esac
    case "$RANK_CHOICE" in
        2) echo "  Ranking method: PE lowest" ;;
        3) echo "  Ranking method: PR lowest" ;;
        4) echo "  Ranking method: ROE highest" ;;
        5) echo "  Ranking method: Pure PB lowest (no 4-step filter)" ;;
        *) echo "  Ranking method: PB lowest" ;;
    esac
    echo "  PE threshold: <= ${PE_INPUT}%"
    echo "  PB threshold: <= ${PB_INPUT}%"
    echo "  PR threshold: <= ${PR_INPUT}%"
    echo "  ROE threshold: > ${ROE_INPUT}% quantile"
    echo "  Max positions: $MAX_POS"
    if [ -n "$WIN_FLAG" ]; then
        echo "  Winsorization: Off (raw quantiles)"
    else
        echo "  Winsorization: On (1%/99% clipping)"
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

    # --- [10/10] Confirm ---
    echo "[10/10] Confirm?"
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
    if [ -n "$FREQ_FLAG" ]; then
        CMD="$CMD $FREQ_FLAG"
    fi
    if [ -n "$RANK_FLAG" ]; then
        CMD="$CMD $RANK_FLAG"
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
