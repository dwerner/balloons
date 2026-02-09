"""Shared session/turn rendering utilities for tree views.

This module provides reusable components for rendering sessions and turns
in both context_tree.py and nested_tree.py. The goal is to maintain
consistent formatting across different tree views while allowing
customization where needed.

Usage:
    from widgets.session_rendering import (
        SessionLabelRenderer,
        TurnLabelRenderer,
        format_kt,
        get_model_icon,
        CLAUDE_SYSTEM_OVERHEAD,
        SESSION_COLORS,
    )
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import TYPE_CHECKING

from rich.markup import escape as escape_markup
from rich.style import Style
from rich.text import Text

from models import (
    ContextMode,
    ArchiveBlock,
    ForkBlock,
    MergeBlock,
    MergedToBlock,
    LinkBlock,
    ToolUseBlock,
    ToolResultBlock,
    ErrorBlock,
    InterruptionBlock,
    ReviewBlock,
)

if TYPE_CHECKING:
    from core.tree_state import SessionData, TurnData


# Claude CLI system overhead: ~19.3k tokens for built-in tools and system prompt
CLAUDE_SYSTEM_OVERHEAD = 19300

# Colors for session grouping (cycling through these for visual distinction)
SESSION_COLORS = [
    "blue",
    "magenta",
    "cyan",
    "green",
    "yellow",
    "red",
]

# Spinner animation characters
SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def format_kt(tokens: int) -> str:
    """Format tokens as kt, rounding up to nearest 0.1kt, dropping leading zero.

    Examples:
        200 -> ".2kt"
        1500 -> "1.5kt"
        0 -> ""
    """
    if tokens <= 0:
        return ""
    kt = math.ceil(tokens / 100) / 10  # Round up to nearest 0.1
    if kt < 1:
        return f".{int(kt * 10)}kt"  # e.g., ".2kt" for 200 tokens
    return f"{kt:.1f}kt"


def token_color(tokens: int, min_tokens: int = 0, max_tokens: int = 50000) -> str:
    """Get a Rich color for token count, lerping green → yellow → bright red.

    Args:
        tokens: The token count to color
        min_tokens: Tokens at or below this are fully green (default 0)
        max_tokens: Tokens at or above this are fully red (default 50k)

    Returns:
        A Rich color string like "rgb(r,g,b)"

    Color progression:
        0 tokens: bright green (0, 255, 0)
        25k tokens: bright yellow (255, 255, 0)
        50k+ tokens: bright red (255, 50, 50)
    """
    if tokens <= min_tokens:
        return "green"
    if tokens >= max_tokens:
        return "rgb(255,50,50)"  # Bright red

    # Two-phase lerp: green → yellow → bright red
    t = (tokens - min_tokens) / (max_tokens - min_tokens)
    mid_point = 0.5

    if t <= mid_point:
        # Phase 1: green (0, 255, 0) → yellow (255, 255, 0)
        phase_t = t / mid_point
        r = int(255 * phase_t)
        g = 255
        b = 0
    else:
        # Phase 2: yellow (255, 255, 0) → bright red (255, 50, 50)
        phase_t = (t - mid_point) / (1 - mid_point)
        r = 255
        g = int(255 * (1 - phase_t) + 50 * phase_t)  # 255 → 50
        b = int(50 * phase_t)  # 0 → 50

    return f"rgb({r},{g},{b})"


def token_style(tokens: int, pulse_frame: int = 0, pulse_threshold: int = 10000) -> str:
    """Get a Rich style string for token count, with animated pulsing.

    Args:
        tokens: The token count to style
        pulse_frame: Animation frame (0-9) for pulsing effect
        pulse_threshold: Tokens above this will pulse (default 10k)

    Returns:
        A Rich style string like "[rgb(r,g,b)]"

    The pulse effect smoothly varies brightness using a sine wave pattern.
    Call this with incrementing pulse_frame values (0-9) to animate.
    """
    color = token_color(tokens)
    if tokens >= pulse_threshold:
        # Pulse by varying the color intensity using sine wave
        # pulse_frame goes 0-9, we want a smooth sine wave
        import math
        # Map frame to 0-2π for full sine cycle
        angle = (pulse_frame / 10) * 2 * math.pi
        # Sine gives -1 to 1, map to 0.5 to 1.0 for brightness multiplier
        brightness = 0.75 + 0.25 * math.sin(angle)

        # Parse the color and apply brightness
        if color == "green":
            r, g, b = 0, 255, 0
        elif color.startswith("rgb("):
            # Parse rgb(r,g,b)
            parts = color[4:-1].split(",")
            r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
        else:
            # Fallback
            r, g, b = 255, 255, 255

        # Apply brightness (keep minimum so it doesn't go too dark)
        r = int(r * brightness)
        g = int(g * brightness)
        b = int(b * brightness)
        return f"[rgb({r},{g},{b})]"
    return f"[{color}]"


def get_model_icon(model: str, backend_name: str) -> str:
    """Get a visual icon for a model/backend combination.

    Icons help users quickly identify which model a session uses.
    Uses unicode symbols that render well in terminals.

    Args:
        model: Model identifier (e.g., "claude-opus-4-5-20251101", "gpt-4")
        backend_name: Backend name (e.g., "claude", "openrouter", "ollama")

    Returns:
        A short icon string with Rich markup for coloring.
    """
    model_lower = model.lower() if model else ""
    backend_lower = backend_name.lower() if backend_name else ""

    # Claude models - use different icons for different tiers
    if "opus" in model_lower or "opus" in backend_lower:
        return "[bold magenta]◆[/]"  # Diamond for Opus (premium)
    elif "sonnet" in model_lower:
        return "[cyan]◇[/]"  # Hollow diamond for Sonnet (balanced)
    elif "haiku" in model_lower:
        return "[green]○[/]"  # Circle for Haiku (fast/cheap)
    elif "claude" in model_lower or backend_lower == "claude":
        return "[blue]●[/]"  # Filled circle for generic Claude

    # OpenAI models
    if "gpt-4" in model_lower or "gpt4" in model_lower:
        return "[yellow]★[/]"  # Star for GPT-4
    elif "gpt-3" in model_lower or "gpt3" in model_lower:
        return "[yellow]☆[/]"  # Hollow star for GPT-3.5
    elif "o1" in model_lower or "o3" in model_lower:
        return "[red]✦[/]"  # Four-pointed star for reasoning models

    # Local/open models
    if "llama" in model_lower:
        return "[orange1]▲[/]"  # Triangle for Llama
    elif "qwen" in model_lower:
        return "[bright_blue]◈[/]"  # Diamond with dot for Qwen
    elif "mistral" in model_lower:
        return "[bright_cyan]◎[/]"  # Bullseye for Mistral
    elif "deepseek" in model_lower:
        return "[bright_green]◉[/]"  # Fisheye for DeepSeek
    elif "gemma" in model_lower:
        return "[bright_magenta]❖[/]"  # Diamond for Gemma

    # Backend-based fallbacks
    if backend_lower in ("ollama", "llamacpp"):
        return "[dim]▪[/]"  # Small square for local models
    elif backend_lower == "openrouter":
        return "[dim]◦[/]"  # Small circle for OpenRouter

    # Default - no icon if we can't identify the model
    return ""


class SessionLabelRenderer:
    """Renders session node labels with consistent formatting.

    Supports:
    - Fork status indicators (↳ for active forks, ✓ for merged)
    - Streaming spinner animation
    - Unviewed turn counts
    - Model icons
    - Session ID prefix
    - Name/title display
    - Message and token counts
    - Active session highlighting
    """

    def __init__(
        self,
        spinner_chars: str = SPINNER_CHARS,
        include_model_icon: bool = True,
        include_tokens: bool = True,
    ):
        """Initialize the renderer.

        Args:
            spinner_chars: Characters to use for spinner animation
            include_model_icon: Whether to show model icons
            include_tokens: Whether to show token counts
        """
        self._spinner_chars = spinner_chars
        self._include_model_icon = include_model_icon
        self._include_tokens = include_tokens

    def render(
        self,
        session_data: SessionData,
        is_active: bool,
        spinner_frame: int = 0,
        is_streaming: bool = False,
        unviewed_count: int = 0,
    ) -> str:
        """Render a session label.

        Args:
            session_data: The session data to render
            is_active: Whether this is the currently active session
            spinner_frame: Current frame of spinner animation (0-9)
            is_streaming: Whether the session is currently streaming
            unviewed_count: Number of unviewed turns in this session

        Returns:
            Rich markup string for the session label
        """
        # Parse date
        try:
            dt = datetime.fromisoformat(session_data.created)
            date_str = dt.strftime("%b %d %H:%M")
        except Exception:
            date_str = session_data.created[:16] if session_data.created else ""

        msg_count = session_data.message_count
        session_id = session_data.id

        # Calculate token count with backend overhead
        session_tokens = session_data.cached_context_tokens if self._include_tokens else 0
        if self._include_tokens:
            if session_data.backend_name == "claude" or (
                not session_data.backend_name and "claude" in (session_data.model or "").lower()
            ):
                session_tokens += CLAUDE_SYSTEM_OVERHEAD

        # Fork status indicator
        is_fork = session_data.parent_id is not None
        fork_status = session_data.fork_status
        if is_fork:
            if fork_status == "merged":
                prefix = "[green]✓[/] "
                status = "[dim][merged][/]"
            else:
                prefix = "[magenta]↳[/] "
                status = ""
        else:
            prefix = ""
            status = ""

        # Animated streaming indicator
        if is_streaming:
            spinner = self._spinner_chars[spinner_frame % len(self._spinner_chars)]
            streaming_indicator = f"[yellow]{spinner}[/] "
        else:
            streaming_indicator = ""

        # Unviewed turns indicator (hidden for now, tracking logic preserved)
        unviewed_indicator = ""

        # Model icon for visual differentiation
        if self._include_model_icon:
            model_icon = get_model_icon(session_data.model, session_data.backend_name)
            model_indicator = f"{model_icon} " if model_icon else ""
        else:
            model_indicator = ""

        # Name display: fork name > title > date
        fork_name = session_data.fork_name
        title = session_data.title
        if fork_name:
            name_part = escape_markup(fork_name)
        elif title:
            truncated = title[:25] + "..." if len(title) > 25 else title
            name_part = escape_markup(truncated)
        else:
            name_part = None

        # Session ID prefix
        id_prefix = f"[dim]{session_id[:8]}[/] "

        # Token count
        if self._include_tokens:
            token_str = format_kt(session_tokens)
            stats = f"[dim]({msg_count}msg {token_str})[/]" if token_str else f"[dim]({msg_count}msg)[/]"
        else:
            stats = f"[dim]({msg_count}msg)[/]"

        # Build the label
        if name_part:
            label = f"{model_indicator}{id_prefix}{name_part} {stats}{unviewed_indicator} {status}"
        else:
            label = f"{model_indicator}{id_prefix}{date_str} {stats}{unviewed_indicator} {status}"

        # Highlight active session
        if is_active:
            return f"{prefix}{streaming_indicator}[bold cyan]{label}[/]"
        else:
            return f"{prefix}{streaming_indicator}{label}"


class TurnLabelRenderer:
    """Renders turn node labels with consistent formatting.

    Supports:
    - Unviewed indicator (blue dot)
    - Context mode indicator (☑/Σ/☐)
    - Content block type detection and icons
    - Role-based icons (👤/🤖)
    - Token counts
    - Content preview with truncation
    """

    def __init__(self, include_tokens: bool = True):
        """Initialize the renderer.

        Args:
            include_tokens: Whether to show token counts
        """
        self._include_tokens = include_tokens

    def render(
        self,
        role: str,
        content: str,
        mode: ContextMode,
        content_block=None,
        tokens: int = 0,
        viewed: bool = True,
    ) -> str:
        """Render a turn label.

        Args:
            role: The turn's role (user, assistant, system, tool)
            content: Display text for the turn
            mode: Context mode (COPY, COMPRESS, DROP)
            content_block: Single content block (TextBlock, ForkBlock, etc.)
            tokens: Token count for this turn
            viewed: Whether this turn has been viewed

        Returns:
            Rich markup string for the turn label
        """
        # Unviewed indicator (hidden for now, tracking logic preserved)
        unviewed_indicator = ""

        # Mode indicator: copy=green check, compress=yellow Σ, drop=empty box
        if mode == ContextMode.COPY:
            indicator = "[green]☑[/]"
        elif mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
            indicator = "[yellow]Σ[/]"
        else:  # DROP
            indicator = "☐"

        # Handle special content block types
        if isinstance(content_block, ArchiveBlock):
            summary = (
                content_block.structured_summary.work_done
                if content_block.structured_summary
                else content_block.summary
            )
            preview = summary[:40] + "..." if len(summary) > 40 else summary
            preview = preview.replace("\n", " ")
            return f"{unviewed_indicator}{indicator} 📦 {escape_markup(preview)}"

        if isinstance(content_block, ForkBlock):
            preview = f"{content_block.fork_name}"
            if content_block.status == "merged":
                return f"{unviewed_indicator}{indicator} [green]🔀 Fork: {escape_markup(preview)} [merged][/]"
            return f"{unviewed_indicator}{indicator} [bold]🔀 Fork: {escape_markup(preview)}[/]"

        if isinstance(content_block, MergeBlock):
            msg_preview = (
                content_block.message[:40] + "..."
                if len(content_block.message) > 40
                else content_block.message
            )
            msg_preview = msg_preview.replace("\n", " ")
            return f"{unviewed_indicator}{indicator} [green]⬅️ Merged: {escape_markup(content_block.fork_name)}[/] {escape_markup(msg_preview)}"

        if isinstance(content_block, MergedToBlock):
            msg_preview = (
                content_block.message[:40] + "..."
                if len(content_block.message) > 40
                else content_block.message
            )
            msg_preview = msg_preview.replace("\n", " ")
            return f"{unviewed_indicator}{indicator} [green]➡️ Merged to parent[/] {escape_markup(msg_preview)}"

        if isinstance(content_block, ReviewBlock):
            status_str = ""
            if content_block.status == "completed":
                score_str = f" {content_block.overall_score:.1f}" if content_block.overall_score > 0 else ""
                status_str = f" [green][completed{score_str}][/]"
            elif content_block.status == "abandoned":
                status_str = " [red][abandoned][/]"
            return f"{unviewed_indicator}{indicator} [magenta]📋 Review: {escape_markup(content_block.model_under_review)}{status_str}[/]"

        if isinstance(content_block, LinkBlock):
            preview = (
                content_block.summary[:40] + "..."
                if len(content_block.summary) > 40
                else content_block.summary
            )
            preview = preview.replace("\n", " ")
            return f"{unviewed_indicator}{indicator} [magenta]🔗 Link:[/] {escape_markup(preview)}"

        if isinstance(content_block, ToolUseBlock):
            if self._include_tokens and tokens > 0:
                kt_str = format_kt(tokens)
                token_str = f"[cyan]({kt_str})[/]" if kt_str else ""
            else:
                token_str = ""
            return f"{unviewed_indicator}{indicator} 🤖 [cyan]🔧 {escape_markup(content_block.name)}[/]{token_str}"

        if isinstance(content_block, ToolResultBlock):
            result_preview = content[:30] + "..." if len(content) > 30 else content
            result_preview = result_preview.replace("\n", " ")
            error_indicator = "[red]❌[/] " if content_block.is_error else ""
            return f"{unviewed_indicator}{indicator} {error_indicator}📋 {escape_markup(result_preview)}"

        if isinstance(content_block, ErrorBlock):
            return f"{unviewed_indicator}{indicator} [yellow]⚠ Error:[/] {escape_markup(content_block.reason)}"

        if isinstance(content_block, InterruptionBlock):
            return f"{unviewed_indicator}{indicator} [red]⚠ Interrupted:[/] {escape_markup(content_block.reason)}"

        # Default: text turn (user or assistant message)
        icon = "👤" if role == "user" else "🤖"

        preview = content[:30] + "..." if len(content) > 30 else content
        preview = preview.replace("\n", " ")

        # Token count
        if self._include_tokens and tokens > 0:
            kt_str = format_kt(tokens)
            token_str = f"[cyan]({kt_str})[/]" if kt_str else ""
        else:
            token_str = ""

        return f"{unviewed_indicator}{indicator} {icon}{token_str} {escape_markup(preview)}"
