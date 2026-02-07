#!/bin/bash
#
# Setup script for balloons development environment
# Usage: ./scripts/setup.sh
#
# Creates a virtual environment and installs dependencies.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$REPO_ROOT/.venv"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# Check Python version
check_python() {
    local python_cmd=""

    # Try python3 first, then python
    if command -v python3 &>/dev/null; then
        python_cmd="python3"
    elif command -v python &>/dev/null; then
        python_cmd="python"
    else
        log_error "Python not found. Please install Python 3.11+."
        exit 1
    fi

    # Check version
    local version
    version=$($python_cmd -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    local major minor
    major=$(echo "$version" | cut -d. -f1)
    minor=$(echo "$version" | cut -d. -f2)

    if [[ "$major" -lt 3 ]] || [[ "$major" -eq 3 && "$minor" -lt 11 ]]; then
        log_error "Python 3.11+ required, found $version"
        exit 1
    fi

    log_info "Found Python $version ($python_cmd)"
    echo "$python_cmd"
}

# Create virtual environment
create_venv() {
    local python_cmd="$1"

    if [[ -d "$VENV_DIR" ]]; then
        log_warn "Virtual environment already exists at $VENV_DIR"
        read -p "Recreate? [y/N] " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            log_info "Removing existing venv..."
            rm -rf "$VENV_DIR"
        else
            log_info "Using existing venv"
            return 0
        fi
    fi

    log_info "Creating virtual environment..."
    $python_cmd -m venv "$VENV_DIR"
    log_info "Virtual environment created at $VENV_DIR"
}

# Install dependencies
install_deps() {
    log_info "Installing dependencies..."

    # Activate and install
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip
    pip install -r "$REPO_ROOT/requirements.txt"

    # Install dev dependencies if present
    if [[ -f "$REPO_ROOT/requirements-dev.txt" ]]; then
        log_info "Installing dev dependencies..."
        pip install -r "$REPO_ROOT/requirements-dev.txt"
    fi

    log_info "Dependencies installed"
}

# Show activation instructions
show_instructions() {
    echo ""
    log_info "Setup complete!"
    echo ""
    echo "To activate the virtual environment:"
    echo "  source .venv/bin/activate"
    echo ""
    echo "To run balloons:"
    echo "  python main.py"
    echo ""
    echo "To run tests:"
    echo "  pytest"
}

# Main
main() {
    cd "$REPO_ROOT"

    log_info "Setting up balloons development environment..."
    echo ""

    local python_cmd
    python_cmd=$(check_python)

    create_venv "$python_cmd"
    install_deps
    show_instructions
}

main "$@"
