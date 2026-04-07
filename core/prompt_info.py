"""System prompt component information for UI display.

This module provides functions to retrieve information about the system prompt
components, including token counts, for display in the Context tab's System
Prompt section.

The information is read-only - actual prompt building is done in runner_factory.py.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from tokenizer import count_tokens

if TYPE_CHECKING:
    from session import Session


# Prompt directories - for user prompt loading
_USER_PROMPTS_DIR = Path.home() / ".balloons" / "prompts"
_SOURCE_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


@dataclass
class PromptComponentInfo:
    """Information about a system prompt component."""
    id: str
    name: str
    description: str
    tokens: int
    enabled: bool = True
    content_preview: str = ""  # First 200 chars
    full_content: str = ""  # Full content for expandable preview


@dataclass
class DomainInfo:
    """Information about a domain plugin."""
    id: str
    name: str
    loaded: bool
    prompt_tokens: int
    context_tokens: int
    tools: list[str] = field(default_factory=list)
    prompt_content: str = ""  # Full prompt content for loaded domains


@dataclass
class SessionPromptFileInfo:
    """Information about a session-specific prompt file."""
    file_path: str
    filename: str  # Just the basename for display
    tokens: int
    exists: bool = True
    content_preview: str = ""  # First 200 chars
    full_content: str = ""  # Full content for expandable preview


@dataclass
class SystemPromptInfo:
    """Complete system prompt information for UI display."""
    components: list[PromptComponentInfo] = field(default_factory=list)
    domains: list[DomainInfo] = field(default_factory=list)
    session_prompt_files: list[SessionPromptFileInfo] = field(default_factory=list)
    total_tokens: int = 0
    context_window: int = 150000


def _get_prompt_path(filename: str) -> Path | None:
    """Get path to a prompt file, checking user dir first then source dir."""
    user_path = _USER_PROMPTS_DIR / filename
    if user_path.exists():
        return user_path
    source_path = _SOURCE_PROMPTS_DIR / filename
    if source_path.exists():
        return source_path
    return None


def _load_prompt_content(filename: str) -> str:
    """Load prompt file content."""
    path = _get_prompt_path(filename)
    if path:
        try:
            return path.read_text()
        except Exception:
            pass
    return ""


def get_user_prompt_info(backend_name: str = "") -> PromptComponentInfo:
    """Get information about the user's custom prompt (CLAUDE.md)."""
    from config import get_config

    config = get_config()
    # get_backend() accepts optional name, falls back to config.default_backend
    backend = config.get_backend(backend_name if backend_name else None)

    if backend:
        content = backend.load_system_prompt() or ""
        tokens = count_tokens(content) if content else 0
        preview = content[:200] if content else ""
    else:
        content = ""
        tokens = 0
        preview = ""

    return PromptComponentInfo(
        id="user-prompt",
        name="User Prompt",
        description="Your CLAUDE.md or custom system prompt",
        tokens=tokens,
        enabled=True,
        content_preview=preview,
        full_content=content,
    )


def get_tool_syntax_info(backend_type: str = "claude") -> PromptComponentInfo:
    """Get information about the tool syntax documentation.

    Uses the per-tool prompt builder to get the actual prompt content that
    will be sent to the LLM.
    """
    from .tool_prompts import build_tool_prompts

    name = "Claude Tool Syntax" if backend_type == "claude" else "OpenAI Tool Syntax"
    content = build_tool_prompts(backend_type=backend_type)
    tokens = count_tokens(content) if content else 0

    return PromptComponentInfo(
        id="tool-syntax",
        name=name,
        description="Balloons workflow tools documentation (fork, merge, etc.)",
        tokens=tokens,
        enabled=True,
        content_preview=content[:200] if content else "",
        full_content=content,
    )


def get_domain_infos() -> list[DomainInfo]:
    """Get information about available and loaded domains."""
    domains = []

    try:
        from plugins.registry import get_registry
        registry = get_registry()

        # Get available domains
        for domain_id in registry.available_domains:
            loaded = domain_id in registry.loaded_domains
            domain = registry.get_domain(domain_id) if loaded else None

            prompt_tokens = 0
            context_tokens = 0
            tools = []
            prompt_content = ""

            if domain:
                # Get prompt tokens
                prompt = domain.get_prompt()
                prompt_content = prompt or ""
                prompt_tokens = count_tokens(prompt) if prompt else 0

                # Get tools - domain.get_tools() returns list[ToolDef]
                domain_tools = domain.get_tools()
                tools = [t.name for t in domain_tools if hasattr(t, 'name')]

            domains.append(DomainInfo(
                id=domain_id,
                name=domain_id.title(),
                loaded=loaded,
                prompt_tokens=prompt_tokens,
                context_tokens=context_tokens,
                tools=tools,
                prompt_content=prompt_content,
            ))
    except ImportError:
        pass  # Plugin system not available

    return domains


def get_session_prompt_files_info(session: "Session | None") -> list[SessionPromptFileInfo]:
    """Get information about session-specific prompt files.

    Args:
        session: Session to get prompt files from

    Returns:
        List of SessionPromptFileInfo for each prompt file
    """
    if not session:
        return []

    files = []
    for file_path in session.get_prompt_files():
        path = Path(file_path)
        exists = path.exists()
        content = ""
        tokens = 0

        if exists:
            try:
                content = path.read_text()
                tokens = count_tokens(content)
            except Exception:
                exists = False

        files.append(SessionPromptFileInfo(
            file_path=file_path,
            filename=path.name,
            tokens=tokens,
            exists=exists,
            content_preview=content[:200] if content else "",
            full_content=content,
        ))

    return files


def get_system_prompt_info(
    session: "Session | None" = None,
    backend_name: str = "",
    backend_type: str = "claude",
) -> SystemPromptInfo:
    """Get complete system prompt information for UI display.

    Args:
        session: Optional session for context-specific info
        backend_name: Backend name to use for user prompt
        backend_type: "claude" or "openai" for tool syntax

    Returns:
        SystemPromptInfo with all component information
    """
    components = []
    total_tokens = 0

    # User prompt
    user_prompt = get_user_prompt_info(backend_name)
    components.append(user_prompt)
    total_tokens += user_prompt.tokens

    # Tool syntax
    tool_syntax = get_tool_syntax_info(backend_type)
    components.append(tool_syntax)
    total_tokens += tool_syntax.tokens

    # Domains placeholder - calculated from domain_infos
    domains = get_domain_infos()
    domain_tokens = sum(d.prompt_tokens + d.context_tokens for d in domains if d.loaded)

    components.append(PromptComponentInfo(
        id="domains",
        name="Domains",
        description="Loaded domain plugins",
        tokens=domain_tokens,
        enabled=True,
    ))
    total_tokens += domain_tokens

    # Session prompt files
    session_prompt_files = get_session_prompt_files_info(session)
    session_prompt_tokens = sum(f.tokens for f in session_prompt_files if f.exists)

    components.append(PromptComponentInfo(
        id="session-prompts",
        name="Session Prompts",
        description="Files added as prompts to this session",
        tokens=session_prompt_tokens,
        enabled=True,
    ))
    total_tokens += session_prompt_tokens

    # Session context (if available)
    session_context_tokens = 0
    if session:
        # TODO: Calculate actual session context tokens
        # This would include goals, bindings, etc.
        pass

    components.append(PromptComponentInfo(
        id="session-context",
        name="Session Context",
        description="Goals, bindings, and session state",
        tokens=session_context_tokens,
        enabled=True,
    ))
    total_tokens += session_context_tokens

    # Get context window from session or default
    context_window = session.context_window if session else 150000

    return SystemPromptInfo(
        components=components,
        domains=domains,
        session_prompt_files=session_prompt_files,
        total_tokens=total_tokens,
        context_window=context_window,
    )
