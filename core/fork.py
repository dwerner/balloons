"""Fork, merge, and derive operations for Balloons.

This module handles session branching operations, separating business logic
from UI updates. Operations return result dataclasses that the UI layer
interprets to update widgets.

Terminology:
- Fork: Create child session linked to parent (can merge back)
- Merge: Complete fork and return to parent with summary
- Derive: Create independent session with selected context (no merge)
"""

import uuid
from dataclasses import dataclass, field
from typing import Optional, Any

from models import Message, TextBlock, ContextMode
from session import Session
from .context_grouper import group_messages_by_context_mode, ContextGroups


# =============================================================================
# Result Dataclasses - UI-agnostic operation results
# =============================================================================

@dataclass
class ContextAssignment:
    """A context mode assignment for a range of exchanges.

    Used by LLM to propose which exchanges should be COPY/COMPRESS/DROP.
    """
    exchange_range: str  # e.g., "0-2", "5", "last", "all"
    mode: str  # "copy", "compress", "drop"
    reason: str = ""  # Why this mode for these exchanges


@dataclass
class ForkProposal:
    """A proposed fork with curated context, suggested by the LLM.

    When an LLM wants to suggest starting an implementation task with
    optimized context, it can call the propose_fork tool to create this
    proposal. The user sees a visual representation and can accept,
    modify, or reject it.
    """
    name: str  # Short fork name (e.g., "implement-cache-layer")
    description: str  # What this fork will accomplish
    context_plan: list[ContextAssignment] = field(default_factory=list)
    initial_prompt: str = ""  # Optional starting prompt

    def resolve_exchange_indices(self, total_exchanges: int) -> dict[int, ContextMode]:
        """Convert exchange_range strings to actual indices with modes.

        Args:
            total_exchanges: Total number of exchanges in the session

        Returns:
            Dict mapping exchange index -> ContextMode
        """
        result: dict[int, ContextMode] = {}

        for assignment in self.context_plan:
            mode = ContextMode(assignment.mode)
            indices = self._parse_range(assignment.exchange_range, total_exchanges)
            for idx in indices:
                result[idx] = mode

        return result

    def _parse_range(self, range_str: str, total: int) -> list[int]:
        """Parse an exchange range string into indices.

        Supports:
        - "0-2": indices 0, 1, 2
        - "5": just index 5
        - "last": last exchange
        - "last-2": last 3 exchanges
        - "all": all exchanges
        - "-3": last 3 (negative indexing)
        """
        range_str = range_str.strip().lower()

        if range_str == "all":
            return list(range(total))

        if range_str == "last":
            return [total - 1] if total > 0 else []

        # Handle "last-N" format (e.g., "last-2" means last 3 exchanges)
        if range_str.startswith("last-"):
            try:
                n = int(range_str[5:])
                start = max(0, total - n - 1)
                return list(range(start, total))
            except ValueError:
                return []

        # Handle negative index (e.g., "-3" means last 3)
        if range_str.startswith("-") and range_str[1:].isdigit():
            try:
                n = int(range_str[1:])
                start = max(0, total - n)
                return list(range(start, total))
            except ValueError:
                return []

        # Handle range "X-Y"
        if "-" in range_str and not range_str.startswith("-"):
            parts = range_str.split("-")
            if len(parts) == 2:
                try:
                    start = int(parts[0])
                    end = int(parts[1])
                    return list(range(max(0, start), min(total, end + 1)))
                except ValueError:
                    return []

        # Single index
        try:
            idx = int(range_str)
            if 0 <= idx < total:
                return [idx]
        except ValueError:
            pass

        return []


@dataclass
class MergeProposal:
    """A proposed merge back to parent, suggested by the LLM.

    When an LLM believes work in a fork is complete and ready to merge,
    it can call the propose_merge tool. This generates a summary preview
    and presents it to the user for approval before merging.
    """
    summary: str  # Preview of the merge summary
    reason: str = ""  # Why the LLM thinks merge is appropriate now
    files_changed: list[str] = field(default_factory=list)  # Key files modified
    key_accomplishments: list[str] = field(default_factory=list)  # What was done


@dataclass
class ForkResult:
    """Result of a fork operation."""
    success: bool
    error: Optional[str] = None

    # Session info (on success)
    child_session: Optional[Session] = None
    parent_session: Optional[Session] = None
    fork_point: int = 0

    # Execution mode
    background: bool = False
    needs_compression: bool = False

    # For compression: helper context data
    helper_id: Optional[str] = None
    compression_prompt: Optional[str] = None
    fork_data: dict = field(default_factory=dict)

    # For immediate execution (no compression)
    prompt: str = ""
    name: str = ""
    allowed_tools: list = field(default_factory=list)


@dataclass
class MergeResult:
    """Result of a merge operation."""
    success: bool
    error: Optional[str] = None

    # Session info (on success)
    fork_session: Optional[Session] = None
    parent_session: Optional[Session] = None
    fork_name: str = ""
    merge_message: str = ""


@dataclass
class DeriveResult:
    """Result of a derive operation."""
    success: bool
    error: Optional[str] = None

    # Session info (on success)
    new_session: Optional[Session] = None

    # Execution mode
    needs_compression: bool = False

    # For compression: helper context data
    helper_id: Optional[str] = None
    compression_prompt: Optional[str] = None
    derive_data: dict = field(default_factory=dict)

    # For immediate execution
    prompt: str = ""
    allowed_tools: list = field(default_factory=list)


@dataclass
class SwitchResult:
    """Result of a session switch operation."""
    success: bool
    error: Optional[str] = None
    target_session: Optional[Session] = None
    available_forks: list = field(default_factory=list)


# =============================================================================
# ForkManager - Handles fork/merge/derive business logic
# =============================================================================

class ForkManager:
    """Manages fork, merge, and derive operations.

    This class handles the business logic of session branching without
    directly interacting with UI widgets. Operations return result objects
    that describe what happened and what the UI should do.

    Usage:
        manager = ForkManager(context_builder)
        result = manager.prepare_fork(
            current_session=session,
            indexed_messages=messages,
            prompt="Do X",
            allowed_tools=tools,
        )
        if result.success:
            if result.needs_compression:
                # Start helper runner with result.compression_prompt
                pass
            else:
                # Switch to result.child_session and start streaming
                pass
    """

    def __init__(self, context_builder):
        """Initialize the fork manager.

        Args:
            context_builder: ContextBuilder for generating compression prompts
        """
        self._context_builder = context_builder

    def prepare_fork(
        self,
        current_session: Session,
        indexed_messages: list[tuple[Message, int]],
        prompt: str,
        allowed_tools: list[str],
        name: str = "",
        background: bool = False,
    ) -> ForkResult:
        """Prepare a fork operation.

        Validates the operation and creates the child session. If compression
        is needed, returns the compression prompt without completing the fork.

        Args:
            current_session: The session to fork from
            indexed_messages: Selected messages with their indices
            prompt: Initial prompt for the fork
            allowed_tools: Tools enabled for the fork
            name: Optional name for the fork
            background: Whether to run in background

        Returns:
            ForkResult with session info and next steps
        """
        # Validate
        if current_session.is_read_only():
            return ForkResult(success=False, error="Cannot fork from a merged session")

        # Track fork point
        fork_point = len(current_session.turns)

        # Group messages by context mode
        groups = group_messages_by_context_mode(indexed_messages)

        # Create child session with fork metadata
        child_session = Session()
        child_session.parent_id = current_session.id
        child_session.fork_name = name
        child_session.fork_status = "active"
        child_session.fork_point_turn = fork_point

        if not groups.needs_compression:
            # No compression - populate child immediately
            for msg, _ in sorted(groups.copy_items, key=lambda x: x[1]):
                child_session.add_message(msg.role, msg.content, content_blocks=msg.content_blocks)

            child_session.save()

            # Register child in parent
            current_session.add_child(
                child_session.id,
                prompt,
                name=name,
                fork_point=fork_point,
            )

            # Add fork turn marker to parent session
            current_session.add_fork_turn(
                fork_id=str(uuid.uuid4()),
                child_session_id=child_session.id,
                fork_name=name or "fork",
                prompt=prompt,
            )
            current_session.save()

            return ForkResult(
                success=True,
                child_session=child_session,
                parent_session=current_session,
                fork_point=fork_point,
                background=background,
                needs_compression=False,
                prompt=prompt,
                name=name,
                allowed_tools=allowed_tools,
            )
        else:
            # Compression needed - return prompt and data for helper
            helper_id = f"compress-{uuid.uuid4().hex[:8]}"

            group = groups.compress_groups[0]
            group_messages = [msg for msg, _ in group]
            compression_prompt = self._context_builder.build_context_summary_prompt(group_messages)

            return ForkResult(
                success=True,
                child_session=child_session,
                parent_session=current_session,
                fork_point=fork_point,
                background=background,
                needs_compression=True,
                helper_id=helper_id,
                compression_prompt=compression_prompt,
                fork_data={
                    "child_session": child_session,
                    "parent_session": current_session,
                    "prompt": prompt,
                    "name": name,
                    "background": background,
                    "allowed_tools": allowed_tools,
                    "copy_items": groups.copy_items,
                    "compress_group_positions": groups.compress_group_positions[:1],
                    "fork_point": fork_point,
                },
                prompt=prompt,
                name=name,
                allowed_tools=allowed_tools,
            )

    def complete_fork_after_compression(
        self,
        fork_data: dict,
        compressed_summary: str,
    ) -> ForkResult:
        """Complete a fork after context compression.

        Called after the compression helper finishes. Inserts the summary
        at the correct position and finalizes the fork.

        Args:
            fork_data: Data from the original prepare_fork call
            compressed_summary: LLM-generated summary of compressed context

        Returns:
            ForkResult ready for UI updates
        """
        child_session = fork_data["child_session"]
        parent_session = fork_data["parent_session"]
        copy_items = fork_data["copy_items"]
        compress_positions = fork_data["compress_group_positions"]
        prompt = fork_data["prompt"]
        name = fork_data["name"]
        background = fork_data["background"]
        allowed_tools = fork_data["allowed_tools"]
        fork_point = fork_data["fork_point"]

        # Build messages with summary inserted at correct position
        all_items = []

        # Add copy items
        for msg, idx in copy_items:
            all_items.append((msg, idx, "copy"))

        # Add summary at first compress group position
        if compress_positions:
            summary_pos = compress_positions[0]
            summary_msg = Message(
                role="user",
                content=f"[Context Summary]\n{compressed_summary}",
                content_blocks=[TextBlock(text=f"[Context Summary]\n{compressed_summary}")],
            )
            all_items.append((summary_msg, summary_pos, "summary"))

        # Sort by position and add to child
        all_items.sort(key=lambda x: x[1])
        for msg, _, _ in all_items:
            child_session.add_message(msg.role, msg.content, content_blocks=msg.content_blocks)

        child_session.save()

        # Register child in parent
        parent_session.add_child(
            child_session.id,
            prompt,
            name=name,
            fork_point=fork_point,
        )

        # Add fork turn marker to parent session
        parent_session.add_fork_turn(
            fork_id=str(uuid.uuid4()),
            child_session_id=child_session.id,
            fork_name=name or "fork",
            prompt=prompt,
        )
        parent_session.save()

        return ForkResult(
            success=True,
            child_session=child_session,
            parent_session=parent_session,
            fork_point=fork_point,
            background=background,
            needs_compression=False,
            prompt=prompt,
            name=name,
            allowed_tools=allowed_tools,
        )

    def prepare_merge(self, fork_session: Session) -> MergeResult:
        """Validate and prepare a merge operation.

        Does not generate the merge summary - that's done separately
        via LLM streaming.

        Args:
            fork_session: The fork to merge

        Returns:
            MergeResult with validation status
        """
        if not fork_session.is_fork():
            return MergeResult(
                success=False,
                error="Not in a fork - use :new for blank session",
            )

        if fork_session.is_merged():
            return MergeResult(
                success=False,
                error="This fork is already merged",
            )

        parent = fork_session.get_parent()
        if not parent:
            return MergeResult(
                success=False,
                error="Parent session not found",
            )

        return MergeResult(
            success=True,
            fork_session=fork_session,
            parent_session=parent,
            fork_name=fork_session.get_fork_display_name(),
        )

    def complete_merge(
        self,
        fork_session: Session,
        parent_session: Session,
        merge_message: str,
    ) -> MergeResult:
        """Complete a merge after summary generation.

        Args:
            fork_session: The fork being merged
            parent_session: The parent session
            merge_message: LLM-generated merge summary

        Returns:
            MergeResult ready for UI updates
        """
        merge_point = len(parent_session.turns)

        # Mark fork as merged
        fork_session.mark_merged(merge_message, merge_point)
        fork_session.save()

        # Update parent's child record
        parent_session.mark_child_merged(fork_session.id, merge_point)

        # Update the ForkBlock status to merged (if it exists)
        parent_session.update_fork_status(fork_session.id, "merged")

        # Add merge turn marker to parent session
        parent_session.add_merge_turn(
            merge_id=str(uuid.uuid4()),
            child_session_id=fork_session.id,
            fork_name=fork_session.get_fork_display_name(),
            message=merge_message,
        )
        parent_session.save()

        return MergeResult(
            success=True,
            fork_session=fork_session,
            parent_session=parent_session,
            fork_name=fork_session.get_fork_display_name(),
            merge_message=merge_message,
        )

    def prepare_derive(
        self,
        indexed_messages: list[tuple[Message, int]],
        prompt: str,
        allowed_tools: list[str],
    ) -> DeriveResult:
        """Prepare a derive operation.

        Creates a new independent session (no parent relationship).

        Args:
            indexed_messages: Selected messages with their indices
            prompt: Initial prompt for the new session
            allowed_tools: Tools enabled for the session

        Returns:
            DeriveResult with session info and next steps
        """
        # Group messages by context mode
        groups = group_messages_by_context_mode(indexed_messages)

        # Create new independent session
        new_session = Session()

        if not groups.needs_compression:
            # No compression - populate immediately
            for msg, _ in sorted(groups.copy_items, key=lambda x: x[1]):
                new_session.add_message(msg.role, msg.content, content_blocks=msg.content_blocks)

            new_session.save()

            return DeriveResult(
                success=True,
                new_session=new_session,
                needs_compression=False,
                prompt=prompt,
                allowed_tools=allowed_tools,
            )
        else:
            # Compression needed
            helper_id = f"derive-compress-{uuid.uuid4().hex[:8]}"

            group = groups.compress_groups[0]
            group_messages = [msg for msg, _ in group]
            compression_prompt = self._context_builder.build_context_summary_prompt(group_messages)

            return DeriveResult(
                success=True,
                new_session=new_session,
                needs_compression=True,
                helper_id=helper_id,
                compression_prompt=compression_prompt,
                derive_data={
                    "new_session": new_session,
                    "prompt": prompt,
                    "allowed_tools": allowed_tools,
                    "copy_items": groups.copy_items,
                    "compress_group_positions": groups.compress_group_positions[:1],
                },
                prompt=prompt,
                allowed_tools=allowed_tools,
            )

    def complete_derive_after_compression(
        self,
        derive_data: dict,
        compressed_summary: str,
    ) -> DeriveResult:
        """Complete a derive after context compression.

        Args:
            derive_data: Data from the original prepare_derive call
            compressed_summary: LLM-generated summary

        Returns:
            DeriveResult ready for UI updates
        """
        new_session = derive_data["new_session"]
        copy_items = derive_data["copy_items"]
        compress_positions = derive_data["compress_group_positions"]
        prompt = derive_data["prompt"]
        allowed_tools = derive_data["allowed_tools"]

        # Build messages with summary
        all_items = []

        for msg, idx in copy_items:
            all_items.append((msg, idx, "copy"))

        if compress_positions:
            summary_pos = compress_positions[0]
            summary_msg = Message(
                role="user",
                content=f"[Context Summary]\n{compressed_summary}",
                content_blocks=[TextBlock(text=f"[Context Summary]\n{compressed_summary}")],
            )
            all_items.append((summary_msg, summary_pos, "summary"))

        all_items.sort(key=lambda x: x[1])
        for msg, _, _ in all_items:
            new_session.add_message(msg.role, msg.content, content_blocks=msg.content_blocks)

        new_session.save()

        return DeriveResult(
            success=True,
            new_session=new_session,
            needs_compression=False,
            prompt=prompt,
            allowed_tools=allowed_tools,
        )

    def find_switch_target(
        self,
        current_session: Session,
        name: str,
    ) -> SwitchResult:
        """Find a session to switch to.

        Searches forks of current session, then parent's forks if in a fork.

        Args:
            current_session: The current session
            name: Fork name or session ID prefix, or "parent"/".."

        Returns:
            SwitchResult with target session or error
        """
        if not name:
            # Return available forks
            forks = current_session.get_all_forks()
            return SwitchResult(
                success=False,
                available_forks=forks,
            )

        target_session = None

        # Check current session's forks
        for fork in current_session.get_all_forks():
            fork_name = fork.get("name", "")
            fork_id = fork.get("session_id", "")
            if fork_name == name or fork_id.startswith(name):
                target_session = Session.load(fork_id)
                break

        # If not found and in a fork, check parent's forks
        if not target_session and current_session.is_fork():
            parent = current_session.get_parent()
            if parent:
                for fork in parent.get_all_forks():
                    fork_name = fork.get("name", "")
                    fork_id = fork.get("session_id", "")
                    if fork_name == name or fork_id.startswith(name):
                        target_session = Session.load(fork_id)
                        break

        # Check for parent request
        if not target_session and name in ("parent", ".."):
            if current_session.is_fork():
                target_session = current_session.get_parent()

        if target_session:
            return SwitchResult(success=True, target_session=target_session)
        else:
            return SwitchResult(
                success=False,
                error=f"No fork found matching '{name}'",
            )
