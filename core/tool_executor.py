"""Tool execution for OpenAI-compatible backends.

Executes tools and returns results. Used by OpenAICompatibleRunner
to handle function calls from the model.
"""

import asyncio
import glob as glob_module
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import aiofiles

from .debug_log import debug_log
from .tools import BALLOON_TOOL_NAMES
from .link_tools import LINK_TOOL_NAMES, execute_link_tool
from .fork import ForkProposal, ContextAssignment, MergeProposal

if TYPE_CHECKING:
    from session import Session


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
    run_id: str = "",
    session: "Session | None" = None,
) -> tuple[str, bool]:
    """Execute a tool and return the result.

    Args:
        name: Tool name (Read, Write, Bash, list_links, etc.)
        args: Tool arguments from the model
        working_dir: Working directory for file operations
        run_id: Run ID for debug logging
        session: Session for link tools (required for list_links, follow_link, search_linked_session)

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
        # Link navigation tools
        if name in LINK_TOOL_NAMES:
            if session is None:
                return "Error: Link tools require a session context", True
            return execute_link_tool(name, args, session)

        # Standard file/shell tools
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
        elif name == "balloon":
            return execute_balloon(args)
        elif name == "propose_fork":
            return execute_propose_fork(args)
        elif name == "propose_merge":
            return execute_propose_merge(args)
        elif name == "create_slide":
            return execute_create_slide(args, session)
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
        async with aiofiles.open(path, encoding="utf-8", errors="replace") as f:
            content = await f.read()
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
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(content)
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


def execute_balloon(args: dict) -> tuple[str, bool]:
    """Handle a balloon tool call.

    The balloon tool is used by the model to send messages through the UI.
    The actual display is handled by the UI layer - this just validates
    the arguments and returns an acknowledgment.

    Args:
        args: Tool arguments containing 'message' and optional 'type'

    Returns:
        Tuple of (result_string, is_error)
    """
    message = args.get("message")
    if not message:
        return "Error: message is required", True

    msg_type = args.get("type", "info")
    valid_types = {"info", "warning", "error", "success", "question"}
    if msg_type not in valid_types:
        msg_type = "info"

    # The actual display happens in the UI layer via the tool events
    # We just acknowledge that the balloon was received
    return f"Balloon displayed: [{msg_type}] {message}", False


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


def execute_propose_fork(args: dict) -> tuple[str, bool]:
    """Handle a propose_fork tool call.

    This validates the proposal arguments and returns a structured result.
    The actual UI display and fork creation is handled by the app layer,
    which intercepts this tool and shows the ForkProposalModal.

    Args:
        args: Tool arguments containing name, description, context_plan, etc.

    Returns:
        Tuple of (result_string, is_error)
    """
    name = args.get("name")
    if not name:
        return "Error: name is required", True

    description = args.get("description")
    if not description:
        return "Error: description is required", True

    context_plan = args.get("context_plan", [])
    if not context_plan:
        return "Error: context_plan is required (list of context assignments)", True

    # Validate context_plan entries
    valid_modes = {"copy", "compress", "drop"}
    for i, assignment in enumerate(context_plan):
        if not isinstance(assignment, dict):
            return f"Error: context_plan[{i}] must be an object", True

        if "exchange_range" not in assignment:
            return f"Error: context_plan[{i}] missing exchange_range", True

        mode = assignment.get("mode", "").lower()
        if mode not in valid_modes:
            return f"Error: context_plan[{i}] has invalid mode '{mode}' (must be copy/compress/drop)", True

    # Build the proposal object for the UI layer to use
    # The actual result is intercepted by the app - this is just acknowledgment
    return "FORK_PROPOSAL_PENDING", False


def parse_fork_proposal(args: dict) -> ForkProposal | None:
    """Parse tool arguments into a ForkProposal object.

    Called by the app layer when it intercepts a propose_fork tool call.

    Args:
        args: Tool arguments from the model

    Returns:
        ForkProposal object, or None if parsing fails
    """
    try:
        debug_log.info(
            f"parse_fork_proposal received args",
            category="fork",
            details={"args_keys": list(args.keys()), "context_plan_len": len(args.get("context_plan", []))},
        )
        name = args.get("name", "")
        description = args.get("description", "")
        initial_prompt = args.get("initial_prompt", "")

        context_plan = []
        for assignment in args.get("context_plan", []):
            context_plan.append(ContextAssignment(
                exchange_range=assignment.get("exchange_range", ""),
                mode=assignment.get("mode", "drop").lower(),
                reason=assignment.get("reason", ""),
            ))

        return ForkProposal(
            name=name,
            description=description,
            context_plan=context_plan,
            initial_prompt=initial_prompt,
        )
    except Exception:
        return None


def execute_propose_merge(args: dict) -> tuple[str, bool]:
    """Handle a propose_merge tool call.

    This validates the proposal arguments and returns a structured result.
    The actual UI display and merge execution is handled by the app layer,
    which intercepts this tool and shows the MergeProposalModal.

    Args:
        args: Tool arguments containing summary, reason, files_changed, etc.

    Returns:
        Tuple of (result_string, is_error)
    """
    summary = args.get("summary")
    if not summary:
        return "Error: summary is required", True

    # Other fields are optional, just validate types
    files_changed = args.get("files_changed", [])
    if not isinstance(files_changed, list):
        return "Error: files_changed must be a list", True

    key_accomplishments = args.get("key_accomplishments", [])
    if not isinstance(key_accomplishments, list):
        return "Error: key_accomplishments must be a list", True

    # The actual result is intercepted by the app - this is just acknowledgment
    return "MERGE_PROPOSAL_PENDING", False


def parse_merge_proposal(args: dict) -> MergeProposal | None:
    """Parse tool arguments into a MergeProposal object.

    Called by the app layer when it intercepts a propose_merge tool call.

    Args:
        args: Tool arguments from the model

    Returns:
        MergeProposal object, or None if parsing fails
    """
    try:
        debug_log.info(
            f"parse_merge_proposal received args",
            category="merge",
            details={"args_keys": list(args.keys())},
        )
        summary = args.get("summary", "")
        reason = args.get("reason", "")
        files_changed = args.get("files_changed", [])
        key_accomplishments = args.get("key_accomplishments", [])

        # Ensure lists contain strings
        files_changed = [str(f) for f in files_changed if f]
        key_accomplishments = [str(a) for a in key_accomplishments if a]

        return MergeProposal(
            summary=summary,
            reason=reason,
            files_changed=files_changed,
            key_accomplishments=key_accomplishments,
        )
    except Exception:
        return None


def execute_create_slide(args: dict, session: "Session | None" = None) -> tuple[str, bool]:
    """Handle a create_slide tool call.

    Creates a slide turn in the session.

    Args:
        args: Tool arguments containing title, content, and optional notes
        session: The session to add the slide to

    Returns:
        Tuple of (result_string, is_error)
    """
    title = args.get("title", "")
    content = args.get("content", "")
    notes = args.get("notes", "")

    if not title and not content:
        return "Error: Either title or content is required", True

    # Validate title length (soft limit)
    if len(title) > 100:
        return f"Error: Title too long ({len(title)} chars). Max recommended: 50 chars", True

    # Validate content length (soft limit - ~10 lines)
    content_lines = content.count("\n") + 1 if content else 0
    if content_lines > 20:
        return f"Error: Content too long ({content_lines} lines). Max recommended: 10 lines for 1080p", True

    if not session:
        return "Error: No session available to create slide", True

    # Create the slide in the session
    session.add_slide_turn(
        title=title,
        content=content,
        notes=notes,
    )
    session.save()

    debug_log.info(f"Slide created in session {session.id[:8]}: '{title}' - session now has {session.get_slide_count()} slides", category="slides")

    return f"Slide created: {title or '(untitled)'}", False


@dataclass
class SlideData:
    """Parsed slide data from tool arguments."""
    title: str
    content: str
    notes: str


def parse_create_slide(args: dict) -> SlideData | None:
    """Parse tool arguments into SlideData.

    Called by the app layer when it intercepts a create_slide tool call.

    Args:
        args: Tool arguments from the model

    Returns:
        SlideData object, or None if parsing fails
    """
    try:
        title = args.get("title", "")
        content = args.get("content", "")
        notes = args.get("notes", "")

        if not title and not content:
            return None

        return SlideData(
            title=title,
            content=content,
            notes=notes,
        )
    except Exception:
        return None
