"""Command execution with business logic separated from UI.

This module handles command operations, separating business logic from UI updates.
Operations return result dataclasses that the UI layer interprets to update widgets.

Pattern follows ForkManager: each command handler returns a result object describing
what happened, rather than directly manipulating UI components.

Commands handled:
- :archive - Archive selected turns with LLM-generated summary
- :rehydrate - Restore archived turns to session
- :link - Create bidirectional links between sessions
- :backend - Set or show the current backend

The app layer calls these methods, receives results, and updates UI accordingly.
"""

from dataclasses import dataclass, field
from typing import Optional
import uuid

from models import ArchiveBlock, LinkBlock
from session import Session, Turn


# =============================================================================
# Result Dataclasses - UI-agnostic operation results
# =============================================================================

@dataclass
class ArchiveResult:
    """Result of an archive operation."""
    success: bool
    error: Optional[str] = None

    # Archive info (on success)
    archive_block: Optional[ArchiveBlock] = None
    new_turns: list[Turn] = field(default_factory=list)
    archived_count: int = 0
    file_path: str = ""


@dataclass
class RehydrateResult:
    """Result of a rehydrate operation."""
    success: bool
    error: Optional[str] = None

    # Rehydration info (on success)
    new_turns: list[Turn] = field(default_factory=list)
    restored_count: int = 0


@dataclass
class LinkTarget:
    """Resolved link target with its session."""
    prefix: str
    session: Session
    summary: str = ""  # LLM-generated or existing


@dataclass
class LinkResult:
    """Result of a link operation."""
    success: bool
    error: Optional[str] = None

    # Link info (on success)
    linked_targets: list[LinkTarget] = field(default_factory=list)
    link_turns: list[Turn] = field(default_factory=list)  # Turns added to current session

    # Sessions that need saving (modified)
    sessions_to_save: list[Session] = field(default_factory=list)

    # Summaries that need generating (session_id -> session)
    needs_summary: list[Session] = field(default_factory=list)


@dataclass
class ShellResult:
    """Result of a shell command execution."""
    success: bool
    error: Optional[str] = None

    # Command info
    command: str = ""
    output: str = ""
    exit_code: int = 0
    was_cancelled: bool = False

    # Formatted prompt for Claude
    prompt: str = ""


@dataclass
class BackendInfo:
    """Information about current and available backends."""
    current: str
    available: list[str] = field(default_factory=list)
    is_missing: bool = False  # True if session's backend no longer exists


@dataclass
class BackendResult:
    """Result of a backend command."""
    success: bool
    error: Optional[str] = None

    # For show (no name provided)
    info: Optional[BackendInfo] = None

    # For set (name provided)
    new_backend: str = ""
    model: str = ""


# =============================================================================
# CommandExecutor - Handles command business logic
# =============================================================================

class CommandExecutor:
    """Executes commands without UI dependencies.

    This class handles the business logic of commands without directly
    interacting with UI widgets. Operations return result objects that
    describe what happened and what the UI should do.

    Usage:
        executor = CommandExecutor()

        # Archive command
        result = executor.prepare_archive(
            session=session,
            turn_indices=[5, 6, 7],
            summary="Work on feature X",
        )
        if result.success:
            session.turns = result.new_turns
            session.save()
            # Update UI with result.archive_block

        # Link command
        result = executor.prepare_link(
            current_session=session,
            target_prefixes=["abc123", "def456"],
        )
        if result.needs_summary:
            # Generate summaries for result.needs_summary
            pass
        if result.success:
            for session in result.sessions_to_save:
                session.save()
    """

    def __init__(self):
        """Initialize the command executor."""
        pass

    # =========================================================================
    # Archive Operations
    # =========================================================================

    def prepare_archive(
        self,
        session: Session,
        turn_indices: list[int],
        summary: str,
    ) -> ArchiveResult:
        """Prepare an archive operation.

        Validates the operation and performs the archive. Returns the result
        with the new turns list and archive block.

        Args:
            session: The session containing turns to archive
            turn_indices: Indices of turns to archive (contiguous range)
            summary: LLM-generated or user-provided summary

        Returns:
            ArchiveResult with success status and archive info
        """
        from core.archiver import Archiver, ArchiveError

        if not session:
            return ArchiveResult(success=False, error="No active session")

        if not turn_indices:
            return ArchiveResult(success=False, error="No turns selected to archive")

        # Calculate range (must be contiguous)
        turn_start = min(turn_indices)
        turn_end = max(turn_indices) + 1

        # Perform the archive
        archiver = Archiver()
        try:
            archive_block, new_turns = archiver.archive_turns(
                session.id,
                session.turns,
                turn_start,
                turn_end,
                summary,
            )

            return ArchiveResult(
                success=True,
                archive_block=archive_block,
                new_turns=new_turns,
                archived_count=archive_block.message_count,
                file_path=archive_block.file_path,
            )

        except ArchiveError as e:
            return ArchiveResult(success=False, error=str(e))

    def prepare_rehydrate(
        self,
        session: Session,
        turn_index: int,
    ) -> RehydrateResult:
        """Prepare a rehydrate operation.

        Validates and performs rehydration of an archive block back to
        original turns.

        Args:
            session: The session containing the archive block
            turn_index: Index of the turn containing the archive block

        Returns:
            RehydrateResult with success status and restored turns
        """
        from core.archiver import Archiver, ArchiveError

        if not session:
            return RehydrateResult(success=False, error="No active session")

        if turn_index < 0 or turn_index >= len(session.turns):
            return RehydrateResult(success=False, error="Invalid turn index")

        turn = session.turns[turn_index]

        # Verify it's an archive turn
        archive_block = None
        for block in turn.content_blocks:
            if isinstance(block, ArchiveBlock):
                archive_block = block
                break

        if not archive_block:
            return RehydrateResult(success=False, error="Selected turn is not an archive")

        # Perform rehydration
        archiver = Archiver()
        try:
            new_turns = archiver.rehydrate(session.turns, turn_index)

            return RehydrateResult(
                success=True,
                new_turns=new_turns,
                restored_count=archive_block.message_count,
            )

        except ArchiveError as e:
            return RehydrateResult(success=False, error=str(e))

    # =========================================================================
    # Link Operations
    # =========================================================================

    def resolve_link_targets(
        self,
        current_session: Session,
        target_prefixes: list[str],
    ) -> LinkResult:
        """Resolve link target prefixes to sessions.

        First phase of linking: validates prefixes and loads target sessions.
        Does not create links yet - call complete_link() after generating
        any needed summaries.

        Args:
            current_session: The session creating links
            target_prefixes: List of 8-char hash prefixes

        Returns:
            LinkResult with resolved targets and sessions needing summaries
        """
        if not current_session:
            return LinkResult(success=False, error="No active session")

        if not target_prefixes:
            return LinkResult(success=False, error="No target sessions specified")

        all_sessions = Session.list_sessions()
        resolved: list[LinkTarget] = []
        needs_summary: list[Session] = []

        for prefix in target_prefixes:
            matches = [s for s in all_sessions if s["id"].startswith(prefix)]

            if not matches:
                return LinkResult(success=False, error=f"No session found matching '{prefix}'")

            if len(matches) > 1:
                match_ids = [s["id"][:8] for s in matches[:5]]
                return LinkResult(
                    success=False,
                    error=f"Multiple sessions match '{prefix}': {', '.join(match_ids)}..."
                )

            target_id = matches[0]["id"]

            # Check not linking to self
            if target_id == current_session.id:
                return LinkResult(success=False, error="Cannot link session to itself")

            # Load target session
            target_session = Session.load(target_id)
            if not target_session:
                return LinkResult(success=False, error=f"Failed to load session {prefix}")

            resolved.append(LinkTarget(
                prefix=prefix,
                session=target_session,
                summary=target_session.summary or "",
            ))

            # Track sessions needing summary generation
            if not target_session.summary:
                needs_summary.append(target_session)

        # Check if current session needs summary
        if not current_session.summary:
            needs_summary.append(current_session)

        return LinkResult(
            success=True,
            linked_targets=resolved,
            needs_summary=needs_summary,
        )

    def complete_link(
        self,
        current_session: Session,
        targets: list[LinkTarget],
        current_summary: str,
    ) -> LinkResult:
        """Complete the link operation after summaries are generated.

        Second phase: creates bidirectional links and returns the turns
        to add to both sessions.

        Args:
            current_session: The session creating links
            targets: Resolved link targets (with summaries populated)
            current_summary: Summary of current session (for target's link)

        Returns:
            LinkResult with link turns and sessions to save
        """
        link_turns: list[Turn] = []
        sessions_to_save: list[Session] = []

        for target in targets:
            # Create unique link ID (same for both sides)
            link_id = str(uuid.uuid4())

            # Add link as a turn in current session with target's summary
            link_turn = current_session.add_link_turn(
                link_id=link_id,
                linked_session_id=target.session.id,
                summary=target.summary,
            )
            link_turns.append(link_turn)

            # Add link as a turn in target session with current session's summary
            target.session.add_link_turn(
                link_id=link_id,
                linked_session_id=current_session.id,
                summary=current_summary,
            )
            sessions_to_save.append(target.session)

        # Current session also needs saving
        sessions_to_save.append(current_session)

        return LinkResult(
            success=True,
            linked_targets=targets,
            link_turns=link_turns,
            sessions_to_save=sessions_to_save,
        )

    # =========================================================================
    # Backend Operations
    # =========================================================================

    def get_backend_info(
        self,
        session: Session,
        config,  # Type hint omitted to avoid circular import
    ) -> BackendResult:
        """Get information about current and available backends.

        Args:
            session: Current session
            config: Application config with backends dict

        Returns:
            BackendResult with backend info
        """
        current = session.backend_name or config.default_backend
        available = list(config.backends.keys())
        is_missing = session.backend_name and session.backend_name not in config.backends

        return BackendResult(
            success=True,
            info=BackendInfo(
                current=current,
                available=available,
                is_missing=is_missing,
            ),
        )

    def set_backend(
        self,
        session: Session,
        backend_name: str,
        config,  # Type hint omitted to avoid circular import
    ) -> BackendResult:
        """Set the backend for a session.

        Args:
            session: Session to update
            backend_name: Name of backend to use
            config: Application config with backends dict

        Returns:
            BackendResult with new backend info
        """
        if backend_name not in config.backends:
            available = list(config.backends.keys())
            return BackendResult(
                success=False,
                error=f"Unknown backend: {backend_name}. Available: {', '.join(available)}",
            )

        # Update session
        session.backend_name = backend_name

        # Get backend config for model info
        backend_config = config.get_backend(backend_name)

        return BackendResult(
            success=True,
            new_backend=backend_name,
            model=backend_config.model or "",
        )

    # =========================================================================
    # Shell Operations
    # =========================================================================

    async def execute_shell(
        self,
        command: str,
        working_directory: str | None = None,
    ) -> ShellResult:
        """Execute a shell command and capture output.

        Runs the command asynchronously with color output enabled.
        Returns the output formatted as a prompt for Claude.

        Args:
            command: Shell command to execute
            working_directory: Directory to run command in (None = current)

        Returns:
            ShellResult with command output and formatted prompt
        """
        import asyncio
        import os

        if not command:
            return ShellResult(success=False, error="No command specified")

        # Set up environment with color support
        env = os.environ.copy()
        env.update({
            "FORCE_COLOR": "1",
            "CLICOLOR_FORCE": "1",
            "TERM": "xterm-256color",
        })

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                cwd=working_directory,
            )
            stdout, _ = await process.communicate()
            output = stdout.decode("utf-8", errors="replace").rstrip()
            exit_code = process.returncode or 0

        except asyncio.CancelledError:
            return ShellResult(
                success=False,
                error="Command cancelled",
                command=command,
                was_cancelled=True,
            )
        except Exception as e:
            return ShellResult(
                success=False,
                error=str(e),
                command=command,
            )

        # Format output as prompt for Claude
        prompt = f"# User executed shell command:\n```bash\n$ {command}\n```\n# Output:\n```\n{output}\n```"

        return ShellResult(
            success=True,
            command=command,
            output=output,
            exit_code=exit_code,
            prompt=prompt,
        )
