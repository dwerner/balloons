"""Tool execution for OpenAI-compatible backends.

Executes tools and returns results. Used by OpenAICompatibleRunner
to handle function calls from the model.
"""

import asyncio
import glob as glob_module
import os
import re
from pathlib import Path

from .debug_log import debug_log


# Maximum output size before truncation
MAX_OUTPUT_SIZE = 50000
MAX_LINES = 2000


def truncate_output(output: str, max_size: int = MAX_OUTPUT_SIZE) -> str:
    """Truncate output if it exceeds max size."""
    if len(output) <= max_size:
        return output
    half = max_size // 2
    return (
        output[:half] +
        f"\n\n... [truncated {len(output) - max_size} characters] ...\n\n" +
        output[-half:]
    )


def resolve_path(file_path: str, working_dir: str) -> Path:
    """Resolve a file path relative to working directory.

    Args:
        file_path: Path from tool input (absolute or relative)
        working_dir: Working directory for relative paths

    Returns:
        Resolved absolute Path
    """
    path = Path(file_path)
    if not path.is_absolute():
        path = Path(working_dir) / path
    return path.resolve()


async def execute_tool(
    name: str,
    args: dict,
    working_dir: str,
    run_id: str = ""
) -> tuple[str, bool]:
    """Execute a tool and return the result.

    Args:
        name: Tool name (Read, Write, Bash, etc.)
        args: Tool arguments from the model
        working_dir: Working directory for file operations
        run_id: Run ID for debug logging

    Returns:
        Tuple of (result_string, is_error)
    """
    debug_log.info(
        f"Executing tool: {name}",
        category="tool",
        details={"args": args},
        run_id=run_id,
    )

    try:
        if name == "Read":
            return await execute_read(args, working_dir)
        elif name == "Write":
            return await execute_write(args, working_dir)
        elif name == "Bash":
            return await execute_bash(args, working_dir)
        elif name == "Glob":
            return await execute_glob(args, working_dir)
        elif name == "Grep":
            return await execute_grep(args, working_dir)
        elif name == "List":
            return await execute_list(args, working_dir)
        else:
            return f"Unknown tool: {name}", True

    except Exception as e:
        debug_log.error(
            f"Tool execution error: {e}",
            category="tool",
            run_id=run_id,
        )
        return f"Error: {str(e)}", True


async def execute_read(args: dict, working_dir: str) -> tuple[str, bool]:
    """Read file contents."""
    file_path = args.get("file_path")
    if not file_path:
        return "Error: file_path is required", True

    path = resolve_path(file_path, working_dir)

    if not path.exists():
        return f"Error: File not found: {path}", True

    if path.is_dir():
        return f"Error: {path} is a directory, not a file", True

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Error reading file: {e}", True

    # Handle offset and limit
    offset = args.get("offset", 1)
    limit = args.get("limit")

    lines = content.splitlines(keepends=True)
    total_lines = len(lines)

    # Apply offset (1-indexed)
    start_idx = max(0, offset - 1)
    lines = lines[start_idx:]

    # Apply limit
    if limit:
        lines = lines[:limit]

    # Truncate long lines
    result_lines = []
    for i, line in enumerate(lines):
        line_num = start_idx + i + 1
        if len(line) > 2000:
            line = line[:2000] + "...[truncated]\n"
        result_lines.append(f"{line_num:6}\t{line}")

    # Limit total lines
    if len(result_lines) > MAX_LINES:
        result_lines = result_lines[:MAX_LINES]
        result_lines.append(f"\n... [truncated, showing {MAX_LINES} of {total_lines} lines]")

    result = "".join(result_lines)
    return truncate_output(result), False


async def execute_write(args: dict, working_dir: str) -> tuple[str, bool]:
    """Write content to a file."""
    file_path = args.get("file_path")
    content = args.get("content")

    if not file_path:
        return "Error: file_path is required", True
    if content is None:
        return "Error: content is required", True

    path = resolve_path(file_path, working_dir)

    # Create parent directories if needed
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        path.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} bytes to {path}", False
    except Exception as e:
        return f"Error writing file: {e}", True


async def execute_bash(args: dict, working_dir: str) -> tuple[str, bool]:
    """Execute a bash command."""
    command = args.get("command")
    if not command:
        return "Error: command is required", True

    timeout = min(args.get("timeout", 120), 600)  # Max 10 minutes

    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return f"Error: Command timed out after {timeout} seconds", True

        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")

        result_parts = []
        if stdout_text:
            result_parts.append(stdout_text)
        if stderr_text:
            result_parts.append(f"[stderr]\n{stderr_text}")
        if process.returncode != 0:
            result_parts.append(f"[exit code: {process.returncode}]")

        result = "\n".join(result_parts) if result_parts else "(no output)"
        return truncate_output(result), process.returncode != 0

    except Exception as e:
        return f"Error executing command: {e}", True


async def execute_glob(args: dict, working_dir: str) -> tuple[str, bool]:
    """Find files matching a glob pattern."""
    pattern = args.get("pattern")
    if not pattern:
        return "Error: pattern is required", True

    search_path = args.get("path", working_dir)
    if not Path(search_path).is_absolute():
        search_path = str(Path(working_dir) / search_path)

    try:
        # Use recursive glob
        full_pattern = str(Path(search_path) / pattern)
        matches = sorted(glob_module.glob(full_pattern, recursive=True))

        # Limit results
        if len(matches) > 1000:
            matches = matches[:1000]
            truncated = True
        else:
            truncated = False

        if not matches:
            return "No files found matching pattern", False

        result = "\n".join(matches)
        if truncated:
            result += "\n\n... [truncated, showing first 1000 matches]"

        return result, False

    except Exception as e:
        return f"Error: {e}", True


async def execute_grep(args: dict, working_dir: str) -> tuple[str, bool]:
    """Search for a pattern in files using ripgrep or grep."""
    pattern = args.get("pattern")
    if not pattern:
        return "Error: pattern is required", True

    search_path = args.get("path", working_dir)
    if not Path(search_path).is_absolute():
        search_path = str(Path(working_dir) / search_path)

    glob_pattern = args.get("glob")
    case_insensitive = args.get("case_insensitive", False)

    # Build command - prefer ripgrep if available
    cmd_parts = ["rg", "--line-number", "--no-heading"]

    if case_insensitive:
        cmd_parts.append("-i")

    if glob_pattern:
        cmd_parts.extend(["--glob", glob_pattern])

    cmd_parts.append("--")
    cmd_parts.append(pattern)
    cmd_parts.append(search_path)

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd_parts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir,
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=60
        )

        stdout_text = stdout.decode("utf-8", errors="replace")

        if process.returncode == 0:
            return truncate_output(stdout_text), False
        elif process.returncode == 1:
            # No matches
            return "No matches found", False
        else:
            # Error - try fallback to grep
            return await _grep_fallback(pattern, search_path, glob_pattern, case_insensitive, working_dir)

    except FileNotFoundError:
        # ripgrep not installed, use grep
        return await _grep_fallback(pattern, search_path, glob_pattern, case_insensitive, working_dir)
    except asyncio.TimeoutError:
        return "Error: Search timed out", True
    except Exception as e:
        return f"Error: {e}", True


async def _grep_fallback(
    pattern: str,
    search_path: str,
    glob_pattern: str | None,
    case_insensitive: bool,
    working_dir: str
) -> tuple[str, bool]:
    """Fallback grep implementation using standard grep."""
    cmd_parts = ["grep", "-r", "-n"]

    if case_insensitive:
        cmd_parts.append("-i")

    if glob_pattern:
        cmd_parts.extend(["--include", glob_pattern])

    cmd_parts.append(pattern)
    cmd_parts.append(search_path)

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd_parts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir,
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=60
        )

        stdout_text = stdout.decode("utf-8", errors="replace")

        if process.returncode == 0:
            return truncate_output(stdout_text), False
        elif process.returncode == 1:
            return "No matches found", False
        else:
            stderr_text = stderr.decode("utf-8", errors="replace")
            return f"Error: {stderr_text}", True

    except Exception as e:
        return f"Error: {e}", True


async def execute_list(args: dict, working_dir: str) -> tuple[str, bool]:
    """List files in a directory."""
    list_path = args.get("path", working_dir)
    if not Path(list_path).is_absolute():
        list_path = str(Path(working_dir) / list_path)

    path = Path(list_path)

    if not path.exists():
        return f"Error: Path not found: {path}", True

    if not path.is_dir():
        return f"Error: {path} is not a directory", True

    try:
        entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))

        lines = []
        for entry in entries[:500]:  # Limit to 500 entries
            if entry.is_dir():
                lines.append(f"  {entry.name}/")
            else:
                try:
                    size = entry.stat().st_size
                    lines.append(f"  {entry.name} ({size} bytes)")
                except OSError:
                    lines.append(f"  {entry.name}")

        if len(entries) > 500:
            lines.append(f"\n... [truncated, showing 500 of {len(entries)} entries]")

        return "\n".join(lines) if lines else "(empty directory)", False

    except Exception as e:
        return f"Error: {e}", True
