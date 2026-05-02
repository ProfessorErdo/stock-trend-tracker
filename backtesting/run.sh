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

    # 1. Data download mode
    echo "[1/5] Data download mode:"
    echo "  1) Skip (use existing data)"
    echo "  2) Update price data only (skip already downloaded)"
    echo "  3) Update all data (price + financial)"
    read -rp "Choose [1-3] (default 1): " DATA_CHOICE
    DATA_CHOICE=${DATA_CHOICE:-1}

    case $DATA_CHOICE in
        2) DATA_FLAG="--update_price" ;;
        3) DATA_FLAG="--update_all" ;;
        *) DATA_FLAG="" ;;
    esac

    echo ""

    # 2. Rebalance frequency
    echo "[2/6] Rebalance frequency:"
    echo "  1) Weekly (current default)"
    echo "  2) Monthly"
    echo "  3) Quarterly (3 times/year: after annual, semi-annual, and Q3 reports)"
    read -rp "Choose [1-3] (default 1): " FREQ_CHOICE
    FREQ_CHOICE=${FREQ_CHOICE:-1}

    case $FREQ_CHOICE in
        2) FREQ_FLAG="--frequency monthly" ;;
        3) FREQ_FLAG="--frequency quarterly" ;;
        *) FREQ_FLAG="" ;;
    esac

    echo ""

    # 3. Winsorization
    echo "[3/6] Extreme value handling (winsorization):"
    echo "  1) Enable 1%/99% clipping (default, filters extreme outliers)"
    echo "  2) Disable (use raw quantiles, recommended if stock pool is pre-filtered)"
    read -rp "Choose [1-2] (default 1): " WIN_CHOICE
    WIN_CHOICE=${WIN_CHOICE:-1}

    case $WIN_CHOICE in
        2) WIN_FLAG="--no_winsorize" ;;
        *) WIN_FLAG="" ;;
    esac

    echo ""

    # 4. Run mode
    INTERMEDIATE="$SCRIPT_DIR/../data/processed/backtesting/intermediate.pkl"
    HAS_INTERMEDIATE=false
    if [ -f "$INTERMEDIATE" ]; then
        HAS_INTERMEDIATE=true
    fi

    echo "[4/6] Backtest mode:"
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
                # Incremental mode: no extra flag, main program auto-detects
                RUN_FLAG=""
            else
                echo "Error: No intermediate results found, cannot run incremental backtest."
                exit 1
            fi
            ;;
        *) RUN_FLAG="" ;;
    esac

    echo ""

    # 4. Date range
    if [ "$RUN_FLAG" = "--results_only" ]; then
        echo "[5/6] Performance-only mode, no date range needed."
        START_DATE=""
        END_DATE=""
    else
        echo "[5/6] Backtest date range:"
        read -rp "  Start date (YYYY-MM-DD, default 2015-01-01): " START_DATE
        START_DATE=${START_DATE:-2015-01-01}
        read -rp "  End date (YYYY-MM-DD, leave empty for latest): " END_DATE
    fi

    echo ""

    # 5. Confirm
    echo "[6/6] Confirm parameters:"
    if [ -n "$DATA_FLAG" ]; then
        echo "  Data download: $DATA_FLAG"
    else
        echo "  Data download: Skip"
    fi
    if [ "$FREQ_FLAG" = "--frequency monthly" ]; then
        echo "  Rebalance frequency: Monthly"
    elif [ "$FREQ_FLAG" = "--frequency quarterly" ]; then
        echo "  Rebalance frequency: Quarterly"
    else
        echo "  Rebalance frequency: Weekly"
    fi
    if [ -n "$WIN_FLAG" ]; then
        echo "  Winsorization: Off (raw quantiles)"
    else
        echo "  Winsorization: On (1%/99% clipping)"
    fi
    if [ -n "$RUN_FLAG" ]; then
        echo "  Backtest mode: $RUN_FLAG"
    elif $HAS_INTERMEDIATE && [ "$RUN_CHOICE" = "3" ]; then
        echo "  Backtest mode: Incremental (auto-detect intermediate results)"
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
    read -rp "Confirm? [Y/n] " CONFIRM
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
