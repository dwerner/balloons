"""Server identity capture for debug logging.

Captures git state and server metadata at startup for debugging and
correlating logs with code versions.
"""

import hashlib
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ServerIdentity:
    """Server identity captured at startup."""

    git_commit: str  # Full commit hash
    git_commit_short: str  # Short hash for display
    git_branch: str  # Current branch name
    git_dirty: bool  # Whether working tree has changes
    git_diff_hash: str  # Hash of current diff (fingerprint of local changes)
    slot: str  # A or B
    port: int
    pid: int
    start_time: str  # ISO format


_identity: ServerIdentity | None = None


def _run_git_command(args: list[str], default: str = "") -> str:
    """Run a git command and return output, or default on failure."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            timeout=5,
            cwd=os.path.dirname(__file__) or ".",
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return default
    except Exception:
        return default


def _compute_diff_hash() -> str:
    """Compute a hash of the current git diff.

    This creates a fingerprint of uncommitted changes, useful for
    identifying when two dirty repos have the same local modifications.
    """
    diff = _run_git_command(["diff", "HEAD"])
    if not diff:
        return ""
    return hashlib.sha256(diff.encode()).hexdigest()[:12]


def capture_identity(port: int, slot: str = "A") -> ServerIdentity:
    """Capture server identity at startup.

    Call this once when the server starts. The identity is cached
    and can be retrieved via get_identity().

    Args:
        port: The port the server is listening on
        slot: The server slot (A or B)

    Returns:
        ServerIdentity with git state and server metadata
    """
    global _identity

    git_commit = _run_git_command(["rev-parse", "HEAD"])
    git_commit_short = git_commit[:8] if git_commit else ""
    git_branch = _run_git_command(["branch", "--show-current"])
    git_status = _run_git_command(["status", "--porcelain"])
    git_dirty = bool(git_status)
    git_diff_hash = _compute_diff_hash() if git_dirty else ""

    _identity = ServerIdentity(
        git_commit=git_commit,
        git_commit_short=git_commit_short,
        git_branch=git_branch,
        git_dirty=git_dirty,
        git_diff_hash=git_diff_hash,
        slot=slot,
        port=port,
        pid=os.getpid(),
        start_time=datetime.utcnow().isoformat() + "Z",
    )

    return _identity


def get_identity() -> ServerIdentity | None:
    """Get the cached server identity.

    Returns None if capture_identity() hasn't been called yet.
    """
    return _identity


def identity_to_dict() -> dict:
    """Get identity as a dict for logging/serialization."""
    if _identity is None:
        return {}
    return {
        "git_commit": _identity.git_commit,
        "git_commit_short": _identity.git_commit_short,
        "git_branch": _identity.git_branch,
        "git_dirty": _identity.git_dirty,
        "git_diff_hash": _identity.git_diff_hash,
        "slot": _identity.slot,
        "port": _identity.port,
        "pid": _identity.pid,
        "start_time": _identity.start_time,
    }
