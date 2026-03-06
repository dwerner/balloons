"""Debug logging tools for LLM self-debugging.

These tools allow the LLM to query logs, configure logging, and
check server identity. Essential for debugging issues during development.
"""

import json
from typing import TYPE_CHECKING

from .debug_log import debug_log, Category, LogLevel
from .server_identity import get_identity, identity_to_dict

if TYPE_CHECKING:
    from session import Session


DEBUG_TOOL_NAMES = frozenset([
    "debug_log_query",
    "debug_log_config",
    "debug_log_tail",
])


async def execute_debug_tool(
    name: str,
    args: dict,
    session: "Session | None" = None,
) -> tuple[str, bool]:
    """Execute a debug logging tool.

    Args:
        name: Tool name
        args: Tool arguments
        session: Session context (optional)

    Returns:
        Tuple of (result_string, is_error)
    """
    if name == "debug_log_query":
        return _query_logs(args)
    elif name == "debug_log_config":
        return _config_logs(args)
    elif name == "debug_log_tail":
        return await _tail_logs(args)
    else:
        return f"Unknown debug tool: {name}", True


def _query_logs(args: dict) -> tuple[str, bool]:
    """Query log entries from in-memory buffer.

    Args:
        category: Category to query (required)
        limit: Max entries to return (default 10)
        offset: Skip first N entries for pagination (default 0)
        level: Filter by level (optional)
        run_id: Filter by run (optional)
        session_id: Filter by session (optional)
        verbose: Include full details JSON (default False - shows truncated summary)
    """
    category = args.get("category")
    if not category:
        return "Error: 'category' is required", True

    limit = args.get("limit", 10)
    offset = args.get("offset", 0)
    level_str = args.get("level")
    run_id = args.get("run_id")
    session_id = args.get("session_id")
    verbose = args.get("verbose", False)

    # Convert level string to enum
    level_enum = None
    if level_str:
        level_map = {
            "error": LogLevel.ERROR,
            "warning": LogLevel.WARNING,
            "info": LogLevel.INFO,
            "perf": LogLevel.PERF,
            "debug": LogLevel.DEBUG,
            "trace": LogLevel.TRACE,
        }
        level_enum = level_map.get(level_str.lower())

    # Query with offset + limit to support pagination
    # We fetch more than needed to know if there are more entries
    entries = debug_log.query(
        category=category,
        limit=offset + limit + 1,  # +1 to detect if more exist
        level=level_enum,
        session_id=session_id,
        run_id=run_id,
    )

    if not entries:
        return f"No entries found in category '{category}'", False

    # Apply offset and check for more
    total_available = len(entries)
    entries = entries[offset:offset + limit]
    has_more = total_available > offset + limit

    if not entries:
        return f"No entries at offset {offset} in category '{category}'", False

    # Format entries for LLM - compact by default
    header = f"Showing {len(entries)} entries from '{category}'"
    if offset > 0:
        header += f" (offset {offset})"
    if has_more:
        header += f" [more available, use offset={offset + limit}]"
    header += ":"

    lines = [header]
    for entry in entries:
        level_prefix = entry.level.value.upper()[:3]
        lines.append(f"[{entry.seq}] {entry.timestamp} {level_prefix}: {entry.message}")
        if entry.details:
            if verbose:
                # Full details in verbose mode
                details_str = json.dumps(entry.details, indent=2)
                lines.append("  " + details_str.replace("\n", "\n  "))
            else:
                # Compact: show truncated one-liner
                details_str = json.dumps(entry.details, separators=(",", ":"))
                if len(details_str) > 100:
                    details_str = details_str[:97] + "..."
                lines.append(f"  {details_str}")

    return "\n".join(lines), False


def _config_logs(args: dict) -> tuple[str, bool]:
    """Query or modify log configuration.

    Args:
        action: "list", "enable", "disable", "identity", "categories", "stats"
        category: Category name (for enable/disable)
    """
    action = args.get("action", "list")

    if action == "list":
        enabled = debug_log.get_categories()
        if enabled:
            return f"Enabled categories: {', '.join(enabled)}", False
        return "All categories enabled (no filter)", False

    elif action == "enable":
        category = args.get("category")
        if not category:
            return "Error: 'category' required for enable action", True
        debug_log.enable_category(category)
        return f"Enabled category: {category}", False

    elif action == "disable":
        category = args.get("category")
        if not category:
            return "Error: 'category' required for disable action", True
        debug_log.disable_category(category)
        return f"Disabled category: {category}", False

    elif action == "identity":
        identity = get_identity()
        if identity is None:
            return "Server identity not captured (server may not have started with capture_identity)", False
        info = identity_to_dict()
        lines = [
            "Server Identity:",
            f"  Git commit: {info['git_commit_short']} ({'dirty' if info['git_dirty'] else 'clean'})",
            f"  Branch: {info['git_branch']}",
        ]
        if info['git_dirty']:
            lines.append(f"  Diff hash: {info['git_diff_hash']}")
        lines.extend([
            f"  Slot: {info['slot']}",
            f"  Port: {info['port']}",
            f"  PID: {info['pid']}",
            f"  Started: {info['start_time']}",
        ])
        return "\n".join(lines), False

    elif action == "categories":
        return f"Available categories: {', '.join(Category.all())}", False

    elif action == "stats":
        stats = debug_log.get_buffer_stats()
        lines = ["Buffer Statistics:"]
        for cat, s in sorted(stats.items()):
            lines.append(f"  {cat}: {s['count']}/{s['maxsize']} entries")
        return "\n".join(lines), False

    else:
        return f"Unknown action: {action}. Valid actions: list, enable, disable, identity, categories, stats", True


async def _tail_logs(args: dict) -> tuple[str, bool]:
    """Tail a log file for historical debugging.

    Args:
        category: Category to tail (required)
        lines: Number of lines (default 20)
        offset: Skip last N lines, for pagination (default 0)
        grep: Optional filter pattern
        verbose: Include details in output (default False)
    """
    import aiofiles
    from pathlib import Path

    category = args.get("category")
    if not category:
        return "Error: 'category' is required", True

    num_lines = args.get("lines", 20)
    offset = args.get("offset", 0)
    grep_pattern = args.get("grep")
    verbose = args.get("verbose", False)

    log_path = Path.home() / ".balloons" / "logs" / f"{category}.log"

    if not log_path.exists():
        return f"Log file not found: {log_path}\n(Category may not have been enabled for file logging)", False

    try:
        async with aiofiles.open(log_path, "r") as f:
            all_lines = await f.readlines()
    except Exception as e:
        return f"Error reading log file: {e}", True

    # Apply grep filter if specified
    if grep_pattern:
        all_lines = [line for line in all_lines if grep_pattern.lower() in line.lower()]

    total_lines = len(all_lines)

    # Apply offset from end, then take N lines
    # offset=0 means last N lines, offset=20 means skip last 20, take N before that
    if offset > 0:
        all_lines = all_lines[:-offset] if offset < len(all_lines) else []

    tail_lines = all_lines[-num_lines:] if all_lines else []
    has_more = len(all_lines) > num_lines

    if not tail_lines:
        if grep_pattern:
            return f"No lines matching '{grep_pattern}' in {log_path}", False
        if offset > 0:
            return f"No lines at offset {offset} in {log_path}", False
        return f"Log file is empty: {log_path}", False

    # Parse and format entries - compact by default
    header = f"Showing {len(tail_lines)} of {total_lines} entries from {log_path}"
    if grep_pattern:
        header += f" (grep: '{grep_pattern}')"
    if offset > 0:
        header += f" (offset {offset} from end)"
    if has_more:
        header += f" [more available, use offset={offset + num_lines}]"
    header += ":"

    result_lines = [header]

    for line in tail_lines:
        line = line.strip()
        try:
            entry = json.loads(line)
            level = entry.get("level", "?").upper()[:3]
            ts = entry.get("timestamp", "")
            msg = entry.get("message", "")
            result_lines.append(f"[{entry.get('seq', '?')}] {ts} {level}: {msg}")
            if verbose and entry.get("details"):
                details_str = json.dumps(entry["details"], indent=2)
                result_lines.append("  " + details_str.replace("\n", "\n  "))
        except json.JSONDecodeError:
            # Not valid JSON, output as-is
            result_lines.append(line)

    return "\n".join(result_lines), False
