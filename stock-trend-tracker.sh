#!/bin/bash

# ============================================================
# Stock Trend Tracker Startup Script
# ============================================================
#
# Usage:
#   ./stock-trend-tracker.sh [command] [options]
#
# Commands:
#   start        Start the server (default)
#   stop         Stop the server
#   status       Check server status
#   logs         View server logs
#   restart      Restart the server
#
# Options:
#   -p <port>    Specify port number (default: 8082)
#   -h           Show this help message
#
# Examples:
#   ./stock-trend-tracker.sh              # Start on default port 8082
#   ./stock-trend-tracker.sh start        # Start server
#   ./stock-trend-tracker.sh start -p 9000   # Start on port 9000
#   ./stock-trend-tracker.sh stop         # Stop server
#   ./stock-trend-tracker.sh status       # Check if server is running
#   ./stock-trend-tracker.sh logs         # View logs (tail -f)
#   ./stock-trend-tracker.sh restart      # Restart server
#
# Features:
#   - Auto-installs dependencies using uv (if not installed)
#   - Auto-detects and handles port conflicts
#   - Runs server in background (detached from terminal)
#   - Server continues running after terminal closes
#   - Creates log file for debugging
#
# ============================================================

# Default configuration
DEFAULT_PORT=8082
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="${PROJECT_DIR}/server.log"
PID_FILE="${PROJECT_DIR}/server.pid"

# Parse command (first argument)
COMMAND="start"
if [ $# -gt 0 ] && [[ ! "$1" =~ ^- ]]; then
    COMMAND="$1"
    shift
fi

# Parse command line arguments
PORT=$DEFAULT_PORT
while getopts "p:h" opt; do
    case $opt in
        p) PORT="$OPTARG" ;;
        h)
            echo "Usage: $0 [command] [options]"
            echo ""
            echo "Commands: start, stop, status, logs, restart"
            echo "Options:  -p <port>  Specify port (default: 8082)"
            exit 0
            ;;
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

# Function: Check Python version (let uv handle version management)
check_python() {
    log_info "Checking Python..."

    # Check if uv can manage Python versions
    # uv will automatically install required Python version from .python-version
    if command -v python3 &> /dev/null; then
        local python_version=$(python3 --version 2>&1)
        log_info "System Python: $python_version"
    else
        log_warning "System Python not found"
    fi

    # Check .python-version file
    if [ -f ".python-version" ]; then
        local required_version=$(cat .python-version)
        log_info "Required Python version (from .python-version): $required_version"
        log_info "uv will automatically install/manage Python $required_version if needed"
    fi

    log_success "Python check passed (uv will handle version management)"
}

# Function: Check and install uv package manager
setup_uv() {
    log_info "Checking uv package manager..."

    if command -v uv &> /dev/null; then
        local uv_version=$(uv --version 2>&1)
        log_success "uv is installed: $uv_version"
        return 0
    fi

    log_warning "uv is not installed"
    log_info "Installing uv package manager..."

    # Install uv using the official installer
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # Add uv to PATH for current session
    export PATH="$HOME/.local/bin:$PATH"

    # Verify installation
    if command -v uv &> /dev/null; then
        log_success "uv installed successfully: $(uv --version)"
    else
        log_error "Failed to install uv"
        log_info "Please install uv manually: curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi
}

# Function: Setup Python environment and install dependencies
setup_environment() {
    log_info "Setting up Python environment..."

    cd "$PROJECT_DIR" || {
        log_error "Failed to change to project directory"
        exit 1
    }

    # Check if .venv exists and has dependencies installed
    local needs_sync=false

    if [ ! -d ".venv" ]; then
        log_warning "Virtual environment not found"
        needs_sync=true
    elif [ ! -f ".venv/bin/python" ]; then
        log_warning "Virtual environment is incomplete"
        needs_sync=true
    elif [ ! -f "uv.lock" ]; then
        log_warning "Lock file not found, need to sync dependencies"
        needs_sync=true
    else
        # Check if dependencies are installed by testing import
        if ! .venv/bin/python -c "import fastapi" 2>/dev/null; then
            log_warning "Dependencies not fully installed"
            needs_sync=true
        fi
    fi

    if [ "$needs_sync" = true ]; then
        log_info "Installing dependencies with uv sync..."
        uv sync

        if [ $? -eq 0 ]; then
            log_success "Dependencies installed successfully"
        else
            log_error "Failed to install dependencies"
            log_info "Check pyproject.toml and uv.lock for issues"
            exit 1
        fi
    else
        log_success "Environment already set up"
    fi
}

# Function: Stop server
stop_server() {
    log_info "Stopping server..."

    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if [ -n "$pid" ] && kill -0 $pid 2>/dev/null; then
            # Kill the main process and any child processes
            kill -TERM $pid 2>/dev/null
            sleep 2
            # Force kill if still running
            if kill -0 $pid 2>/dev/null; then
                kill -9 $pid 2>/dev/null
            fi
            log_success "Server stopped (PID: $pid)"
        else
            log_warning "Server process not running"
        fi
        rm -f "$PID_FILE"
    else
        log_warning "No PID file found"

        # Try to find and kill by port
        if check_port $PORT; then
            local port_pid=$(lsof -Pi :$PORT -sTCP:LISTEN -t 2>/dev/null | head -1)
            if [ -n "$port_pid" ]; then
                kill -9 $port_pid 2>/dev/null
                log_success "Killed process $port_pid on port $PORT"
            fi
        fi
    fi
}

# Function: Show server status
show_status() {
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if kill -0 $pid 2>/dev/null; then
            log_success "Server is running (PID: $pid)"
            log_info "Port: $PORT"
            log_info "URL: http://localhost:$PORT"
            log_info "Log file: $LOG_FILE"
            return 0
        else
            log_warning "Server PID file exists but process is not running"
            return 1
        fi
    else
        log_warning "Server is not running"
        return 1
    fi
}

# Function: Cleanup on exit (for start command failure)
cleanup() {
    log_info "Cleaning up..."

    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if [ -n "$pid" ] && kill -0 $pid 2>/dev/null; then
            kill -TERM $pid 2>/dev/null
            sleep 1
            kill -9 $pid 2>/dev/null
        fi
        rm -f "$PID_FILE"
    fi

    exit 1
}

# ============================================================
# Main Script
# ============================================================

log_info "Stock Trend Tracker - $COMMAND"
log_info "Project directory: $PROJECT_DIR"

# Change to project directory
cd "$PROJECT_DIR" || {
    log_error "Failed to change to project directory"
    exit 1
}

# Handle different commands
case $COMMAND in
    stop)
        stop_server
        exit 0
        ;;
    status)
        show_status
        exit $?
        ;;
    logs)
        if [ -f "$LOG_FILE" ]; then
            log_info "Showing logs from $LOG_FILE (Ctrl+C to exit)"
            tail -f "$LOG_FILE"
        else
            log_warning "No log file found at $LOG_FILE"
            exit 1
        fi
        ;;
    restart)
        log_info "Restarting server..."
        stop_server
        sleep 2
        # Continue to start logic below
        ;;
    start)
        # Continue to start logic below
        ;;
    *)
        log_error "Unknown command: $COMMAND"
        log_info "Available commands: start, stop, status, logs, restart"
        exit 1
        ;;
esac

# Step 1: Check Python version
check_python

# Step 2: Setup uv package manager
setup_uv

# Step 3: Setup environment and install dependencies
setup_environment

# Handle port conflicts (for start/restart)
if check_port $PORT; then
    log_warning "Port $PORT is already in use"

    # Check if it's our server
    if [ -f "$PID_FILE" ]; then
        old_pid=$(cat "$PID_FILE")
        if kill -0 $old_pid 2>/dev/null; then
            log_warning "Server appears to be already running (PID: $old_pid)"
            log_info "Use './stock-trend-tracker.sh restart' to restart, or './stock-trend-tracker.sh stop' to stop"
            exit 1
        fi
    fi

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

# Start server in background (detached from terminal)
log_info "Starting server on port $PORT..."
log_info "Log file: $LOG_FILE"

# Use nohup to keep server running after terminal closes
nohup uv run uvicorn src.api:app --host 0.0.0.0 --port $PORT --reload > "$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo $SERVER_PID > "$PID_FILE"
echo $PORT > "${PROJECT_DIR}/server.port"

log_info "Server PID: $SERVER_PID"

# Wait for server to be ready (with timeout)
if wait_for_server $PORT; then
    URL="http://localhost:$PORT"
    log_success "Server is running at $URL"
    log_success "Server is running in background (detached from terminal)"
    log_info ""
    log_info "Useful commands:"
    log_info "  ./stock-trend-tracker.sh status  - Check server status"
    log_info "  ./stock-trend-tracker.sh logs    - View server logs"
    log_info "  ./stock-trend-tracker.sh stop    - Stop server"
    log_info ""

    # Open browser (only on local machine, not remote server)
    if [[ "$OSTYPE" == "darwin"* ]]; then
        open_browser "$URL"
    fi

    # Exit successfully - server continues running
    exit 0
else
    log_error "Server failed to start. Check $LOG_FILE for details"
    cleanup
fi