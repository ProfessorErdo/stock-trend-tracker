#!/bin/bash

# ============================================================
# Stock Trend Tracker Startup Script
# ============================================================
#
# Usage:
#   ./stock-trend-tracker.sh [options]
#
# Options:
#   -p <port>    Specify port number (default: 8082)
#   -h           Show this help message
#
# Examples:
#   ./stock-trend-tracker.sh           # Start on default port 8082
#   ./stock-trend-tracker.sh -p 9000   # Start on port 9000
#
# Features:
#   - Auto-detects and handles port conflicts
#   - Starts FastAPI backend (serves both API and frontend)
#   - Auto-opens browser when server is ready
#   - Creates log file for debugging
#
# ============================================================

# Default configuration
DEFAULT_PORT=8082
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="${PROJECT_DIR}/server.log"
PID_FILE="${PROJECT_DIR}/server.pid"

# Parse command line arguments
PORT=$DEFAULT_PORT
while getopts "p:h" opt; do
    case $opt in
        p) PORT="$OPTARG" ;;
        h) echo "Usage: $0 [-p <port>] [-h]" && exit 0 ;;
        *) echo "Invalid option" && exit 1 ;;
    esac
done

# Color output helpers
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo "${BLUE}[INFO]${NC} $1"; }
log_success() { echo "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo "${RED}[ERROR]${NC} $1"; }

# Function: Check if port is in use
check_port() {
    local port=$1
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
        return 0  # Port is in use
    else
        return 1  # Port is free
    fi
}

# Function: Kill process on specific port
kill_port_process() {
    local port=$1
    local pid=$(lsof -Pi :$port -sTCP:LISTEN -t 2>/dev/null | head -1)

    if [ -n "$pid" ]; then
        log_warning "Found process $pid using port $port"
        log_info "Attempting to kill process $pid..."
        kill -9 $pid 2>/dev/null
        sleep 1

        if check_port $port; then
            log_error "Failed to free port $port"
            return 1
        else
            log_success "Port $port is now free"
            return 0
        fi
    fi
    return 0
}

# Function: Find next available port
find_available_port() {
    local start_port=$1
    local max_attempts=10
    local current_port=$start_port

    for i in $(seq 1 $max_attempts); do
        if ! check_port $current_port; then
            echo $current_port
            return 0
        fi
        log_warning "Port $current_port is in use, trying next..."
        current_port=$((current_port + 1))
    done

    log_error "No available port found after $max_attempts attempts"
    return 1
}

# Function: Wait for server to be ready
wait_for_server() {
    local port=$1
    local max_attempts=30
    local url="http://localhost:$port/api/health"

    log_info "Waiting for server to be ready..."

    for i in $(seq 1 $max_attempts); do
        if curl -s "$url" >/dev/null 2>&1; then
            log_success "Server is ready!"
            return 0
        fi
        sleep 1
    done

    log_error "Server failed to start after $max_attempts seconds"
    return 1
}

# Function: Open browser
open_browser() {
    local url=$1

    log_info "Opening browser..."

    # Detect OS and use appropriate command
    if [[ "$OSTYPE" == "darwin"* ]]; then
        open "$url" 2>/dev/null
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        xdg-open "$url" 2>/dev/null || firefox "$url" 2>/dev/null
    else
        log_warning "Cannot auto-open browser on this OS"
    fi
}

# Function: Cleanup on exit
cleanup() {
    log_info "Shutting down server..."

    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if [ -n "$pid" ] && kill -0 $pid 2>/dev/null; then
            kill $pid 2>/dev/null
            log_success "Server process $pid stopped"
        fi
        rm -f "$PID_FILE"
    fi

    exit 0
}

# Register cleanup on script exit
trap cleanup SIGINT SIGTERM

# ============================================================
# Main Script
# ============================================================

log_info "Stock Trend Tracker Startup Script"
log_info "Project directory: $PROJECT_DIR"

# Change to project directory
cd "$PROJECT_DIR" || {
    log_error "Failed to change to project directory"
    exit 1
}

# Check Python environment
if [ ! -d ".venv" ]; then
    log_error "Virtual environment not found. Please run: uv venv && uv sync"
    exit 1
fi

# Handle port conflicts
if check_port $PORT; then
    log_warning "Port $PORT is already in use"

    # Ask user what to do
    echo ""
    echo "Options:"
    echo "  1) Kill existing process and use port $PORT"
    echo "  2) Find next available port"
    echo "  3) Exit"
    echo ""
    read -p "Select option [1/2/3]: " choice

    case $choice in
        1)
            kill_port_process $PORT || exit 1
            ;;
        2)
            PORT=$(find_available_port $((PORT + 1)))
            if [ -z "$PORT" ]; then
                exit 1
            fi
            log_info "Will use port $PORT"
            ;;
        3)
            log_info "Exiting..."
            exit 0
            ;;
        *)
            log_error "Invalid choice"
            exit 1
            ;;
    esac
fi

# Clear old log file
rm -f "$LOG_FILE"

# Start server
log_info "Starting server on port $PORT..."
log_info "Log file: $LOG_FILE"

source .venv/bin/activate && nohup uvicorn src.api:app --host 0.0.0.0 --port $PORT --reload > "$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo $SERVER_PID > "$PID_FILE"

log_info "Server PID: $SERVER_PID"

# Wait for server to be ready
if wait_for_server $PORT; then
    URL="http://localhost:$PORT"
    log_success "Server is running at $URL"
    log_info "Press Ctrl+C to stop the server"

    # Open browser
    open_browser "$URL"

    # Keep script running to maintain server process
    log_info "Server is running in background. Logs available at $LOG_FILE"

    # Tail log file for debugging
    tail -f "$LOG_FILE" &
    TAIL_PID=$!

    # Wait for server process
    wait $SERVER_PID 2>/dev/null

    # Cleanup tail process
    kill $TAIL_PID 2>/dev/null
else
    log_error "Server failed to start. Check $LOG_FILE for details"
    cleanup
    exit 1
fi