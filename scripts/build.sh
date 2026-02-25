#!/bin/bash
#
# Unified build script for balloons
# Usage: ./scripts/build.sh [OPTIONS]
#
# Options:
#   --all         Full build: venv + codegen + rust (default if no options)
#   --venv        Create/update virtual environment
#   --codegen     Generate TypeScript and Rust code
#   --rust        Build Rust extension with maturin
#   --release     Build Rust in release mode (default: develop mode)
#   --check       Check if generated code is up-to-date (for CI)
#   --clean       Clean build artifacts
#   -h, --help    Show this help
#
# Examples:
#   ./scripts/build.sh              # Full dev build
#   ./scripts/build.sh --codegen    # Just regenerate TS/Rust
#   ./scripts/build.sh --rust --release  # Release build of Rust
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$REPO_ROOT/.venv"
RUST_DIR="$REPO_ROOT/balloons-rs"
MATURIN_CRATE="$RUST_DIR/crates/balloons-py"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
log_step() { echo -e "${BLUE}[STEP]${NC} $*"; }

# Track what to build
DO_VENV=false
DO_CODEGEN=false
DO_RUST=false
DO_CHECK=false
DO_CLEAN=false
RELEASE_MODE=false

# Parse arguments
parse_args() {
    if [[ $# -eq 0 ]]; then
        # Default: full build
        DO_VENV=true
        DO_CODEGEN=true
        DO_RUST=true
        return
    fi

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --all)
                DO_VENV=true
                DO_CODEGEN=true
                DO_RUST=true
                ;;
            --venv)
                DO_VENV=true
                ;;
            --codegen)
                DO_CODEGEN=true
                ;;
            --rust)
                DO_RUST=true
                ;;
            --release)
                RELEASE_MODE=true
                ;;
            --check)
                DO_CHECK=true
                DO_CODEGEN=true
                ;;
            --clean)
                DO_CLEAN=true
                ;;
            -h|--help)
                sed -n '2,20p' "$0" | sed 's/^# \?//'
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                exit 1
                ;;
        esac
        shift
    done
}

# Check Python version
check_python() {
    local python_cmd=""

    if command -v python3 &>/dev/null; then
        python_cmd="python3"
    elif command -v python &>/dev/null; then
        python_cmd="python"
    else
        log_error "Python not found. Please install Python 3.11+."
        exit 1
    fi

    local version
    version=$($python_cmd -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    local major minor
    major=$(echo "$version" | cut -d. -f1)
    minor=$(echo "$version" | cut -d. -f2)

    if [[ "$major" -lt 3 ]] || [[ "$major" -eq 3 && "$minor" -lt 11 ]]; then
        log_error "Python 3.11+ required, found $version"
        exit 1
    fi

    echo "$python_cmd"
}

# Create/ensure venv exists
ensure_venv() {
    log_step "Setting up virtual environment..."

    local python_cmd
    python_cmd=$(check_python)

    if [[ ! -d "$VENV_DIR" ]]; then
        log_info "Creating virtual environment..."
        $python_cmd -m venv "$VENV_DIR"
    fi

    # Activate venv
    source "$VENV_DIR/bin/activate"

    # Upgrade pip and install deps
    log_info "Installing dependencies..."
    pip install --upgrade pip -q
    pip install -r "$REPO_ROOT/requirements.txt" -q

    if [[ -f "$REPO_ROOT/requirements-dev.txt" ]]; then
        pip install -r "$REPO_ROOT/requirements-dev.txt" -q
    fi

    # Ensure maturin is available
    if ! command -v maturin &>/dev/null; then
        log_info "Installing maturin..."
        pip install maturin -q
    fi

    log_info "Virtual environment ready"
}

# Activate existing venv (assumes it exists)
activate_venv() {
    if [[ ! -d "$VENV_DIR" ]]; then
        log_error "Virtual environment not found at $VENV_DIR"
        log_error "Run with --venv or --all to create it"
        exit 1
    fi
    source "$VENV_DIR/bin/activate"
}

# Strip timestamp lines from generated files for comparison
# (timestamps change on every generation but aren't meaningful differences)
strip_timestamps() {
    grep -v "Generated:" | grep -v "//! Generated:"
}

# Generate TypeScript and Rust code
run_codegen() {
    log_step "Running code generation..."

    # Save current state if checking (without timestamps)
    local ts_before=""
    local rust_before=""
    if [[ "$DO_CHECK" == "true" ]]; then
        ts_before=$(find "$REPO_ROOT/web/generated" -name "*.ts" -exec cat {} \; 2>/dev/null | strip_timestamps || echo "")
        rust_before=$(find "$RUST_DIR/crates/balloons-core/src/generated" -name "*.rs" -exec cat {} \; 2>/dev/null | strip_timestamps || echo "")
    fi

    # Generate TypeScript
    log_info "Generating TypeScript types..."
    python -m codegen.generate_typescript

    # Generate Rust
    log_info "Generating Rust structs..."
    python -m codegen.generate_rust

    # Check if anything changed (for CI)
    if [[ "$DO_CHECK" == "true" ]]; then
        local ts_after
        local rust_after
        ts_after=$(find "$REPO_ROOT/web/generated" -name "*.ts" -exec cat {} \; 2>/dev/null | strip_timestamps || echo "")
        rust_after=$(find "$RUST_DIR/crates/balloons-core/src/generated" -name "*.rs" -exec cat {} \; 2>/dev/null | strip_timestamps || echo "")

        if [[ "$ts_before" != "$ts_after" ]] || [[ "$rust_before" != "$rust_after" ]]; then
            log_error "Generated code is out of date!"
            log_error "Run './scripts/build.sh --codegen' and commit the changes"
            exit 1
        fi
        log_info "Generated code is up-to-date"
    else
        log_info "Code generation complete"
    fi
}

# Build Rust extension
build_rust() {
    log_step "Building Rust extension..."

    # Check cargo
    if ! command -v cargo &>/dev/null; then
        log_error "Cargo not found. Please install Rust: https://rustup.rs"
        exit 1
    fi

    # Check maturin
    if ! command -v maturin &>/dev/null; then
        log_error "Maturin not found. Run with --venv to install it."
        exit 1
    fi

    cd "$MATURIN_CRATE"

    if [[ "$RELEASE_MODE" == "true" ]]; then
        log_info "Building in release mode..."
        maturin develop --release
    else
        log_info "Building in develop mode..."
        maturin develop
    fi

    cd "$REPO_ROOT"
    log_info "Rust extension built and installed to venv"
}

# Clean build artifacts
clean_artifacts() {
    log_step "Cleaning build artifacts..."

    # Rust target
    if [[ -d "$RUST_DIR/target" ]]; then
        log_info "Removing Rust target directory..."
        rm -rf "$RUST_DIR/target"
    fi

    # Python bytecode
    log_info "Removing Python bytecode..."
    find "$REPO_ROOT" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find "$REPO_ROOT" -type f -name "*.pyc" -delete 2>/dev/null || true

    # Maturin artifacts
    if [[ -d "$MATURIN_CRATE/target" ]]; then
        rm -rf "$MATURIN_CRATE/target"
    fi

    log_info "Clean complete"
}

# Main
main() {
    cd "$REPO_ROOT"
    parse_args "$@"

    echo ""
    log_info "Balloons Build Script"
    echo ""

    # Handle clean first
    if [[ "$DO_CLEAN" == "true" ]]; then
        clean_artifacts
        if [[ "$DO_VENV" == "false" && "$DO_CODEGEN" == "false" && "$DO_RUST" == "false" ]]; then
            exit 0
        fi
    fi

    # Ensure venv if building venv or if we need it for codegen/rust
    if [[ "$DO_VENV" == "true" ]]; then
        ensure_venv
    elif [[ "$DO_CODEGEN" == "true" || "$DO_RUST" == "true" ]]; then
        activate_venv
    fi

    # Run codegen
    if [[ "$DO_CODEGEN" == "true" ]]; then
        run_codegen
    fi

    # Build rust
    if [[ "$DO_RUST" == "true" ]]; then
        build_rust
    fi

    echo ""
    log_info "Build complete!"

    # Show what was built
    if [[ "$DO_RUST" == "true" ]]; then
        echo ""
        echo "To verify the Rust extension:"
        echo "  source .venv/bin/activate"
        echo "  python -c 'import balloons_storage; print(balloons_storage.__doc__)'"
    fi
}

main "$@"
