#!/bin/bash
#
# Release script for balloons
# Usage: ./scripts/release.sh [VERSION]
#
# If VERSION is provided, creates a new release with that version.
# If no VERSION, shows current version and available commands.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VERSION_FILE="$REPO_ROOT/VERSION"
DIST_DIR="$REPO_ROOT/dist"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# Get current version from VERSION file
get_version() {
    if [[ -f "$VERSION_FILE" ]]; then
        cat "$VERSION_FILE" | tr -d '[:space:]'
    else
        echo "0.0.0"
    fi
}

# Validate semver format
validate_version() {
    local version="$1"
    if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?$ ]]; then
        log_error "Invalid version format: $version"
        log_error "Expected: MAJOR.MINOR.PATCH or MAJOR.MINOR.PATCH-prerelease"
        exit 1
    fi
}

# Check for uncommitted changes
check_clean_tree() {
    if ! git -C "$REPO_ROOT" diff --quiet HEAD 2>/dev/null; then
        log_error "Working tree has uncommitted changes. Commit or stash them first."
        exit 1
    fi
}

# Create tarball without git history
# Sets DIST_FILE to the created tarball path
create_tarball() {
    local version="$1"
    local tarball_name="balloons-v${version}.tar.gz"

    mkdir -p "$DIST_DIR"

    log_info "Creating tarball: $tarball_name"
    git -C "$REPO_ROOT" archive \
        --format=tar.gz \
        --prefix="balloons-v${version}/" \
        --output="$DIST_DIR/$tarball_name" \
        HEAD

    DIST_FILE="$DIST_DIR/$tarball_name"
    log_info "Tarball created: $DIST_FILE"
    ls -lh "$DIST_FILE"
}

# Push to all configured remotes
sync_remotes() {
    local tag="$1"
    local remotes
    remotes=$(git -C "$REPO_ROOT" remote)

    if [[ -z "$remotes" ]]; then
        log_warn "No git remotes configured. Skipping remote sync."
        return 0
    fi

    for remote in $remotes; do
        log_info "Pushing to remote: $remote"
        git -C "$REPO_ROOT" push "$remote" HEAD --tags || {
            log_warn "Failed to push to $remote (continuing...)"
        }
    done
}

# Show usage/status
show_status() {
    local current_version
    current_version=$(get_version)

    echo "Balloons Release Tool"
    echo "====================="
    echo ""
    echo "Current version: $current_version"
    echo ""
    echo "Usage:"
    echo "  ./scripts/release.sh VERSION    Create release (e.g., 0.2.0)"
    echo "  ./scripts/release.sh --tarball  Create tarball for current version"
    echo "  ./scripts/release.sh --sync     Push current state to all remotes"
    echo ""
    echo "Configured remotes:"
    git -C "$REPO_ROOT" remote -v 2>/dev/null || echo "  (none)"
    echo ""
    echo "Recent tags:"
    git -C "$REPO_ROOT" tag -l --sort=-v:refname | head -5 || echo "  (none)"
}

# Main release flow
do_release() {
    local new_version="$1"
    local current_version
    current_version=$(get_version)

    validate_version "$new_version"
    check_clean_tree

    log_info "Releasing: $current_version -> $new_version"

    # Update VERSION file
    echo "$new_version" > "$VERSION_FILE"

    # Commit the version bump
    git -C "$REPO_ROOT" add "$VERSION_FILE"
    git -C "$REPO_ROOT" commit -m "Release v${new_version}"

    # Create annotated tag
    git -C "$REPO_ROOT" tag -a "v${new_version}" -m "Release v${new_version}"

    log_info "Created tag: v${new_version}"

    # Create tarball
    create_tarball "$new_version"

    # Sync to remotes
    sync_remotes "v${new_version}"

    echo ""
    log_info "Release v${new_version} complete!"

    # Output dist file path for scripting (last line of stdout)
    echo ""
    echo "DIST_FILE=$DIST_FILE"
}

# Entry point
main() {
    cd "$REPO_ROOT"

    case "${1:-}" in
        "")
            show_status
            ;;
        --tarball)
            create_tarball "$(get_version)"
            # Output dist file path for scripting
            echo ""
            echo "DIST_FILE=$DIST_FILE"
            ;;
        --sync)
            sync_remotes ""
            ;;
        -h|--help)
            show_status
            ;;
        *)
            do_release "$1"
            ;;
    esac
}

main "$@"
