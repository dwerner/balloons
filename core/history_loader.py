"""History loader - transforms messages into render instructions.

This module separates the "what to render" from "how to render" by converting
a list of Message objects into RenderInstruction dataclasses. The ChatLog
widget then interprets these instructions to create widgets.

This enables:
- Unit testing without Textual dependencies
- Clear separation of data transformation from UI concerns
- Easier reasoning about history loading logic
"""

from dataclasses import dataclass, field
from typing import Any

from models import (
    Message, TextBlock, ToolUseBlock, ToolResultBlock,
    InterruptionBlock, ErrorBlock, LinkBlock, ForkBlock,
    MergeBlock, MergedToBlock, ArchiveBlock
)
from session import Session


# =============================================================================
# Render Instructions (what to render, not how)
# =============================================================================

@dataclass
class RenderInstruction:
    """Base class for all render instructions."""
    turn_id: int = 0


@dataclass
class RenderMessage(RenderInstruction):
    """Instruction to render a message bubble."""
    role: str = ""  # "user" or "assistant"
    text: str = ""
    block_idx: int = 0


@dataclass
class RenderToolUse(RenderInstruction):
    """Instruction to render a tool use block."""
    tool_name: str = ""
    tool_use_id: str = ""
    tool_input: dict = field(default_factory=dict)


@dataclass
class RenderToolResult(RenderInstruction):
    """Instruction to render a tool result block."""
    tool_use_id: str = ""
    content: str = ""
    is_error: bool = False


@dataclass
class RenderInterruption(RenderInstruction):
    """Instruction to render an interruption marker."""
    reason: str = ""


@dataclass
class RenderError(RenderInstruction):
    """Instruction to render an error marker."""
    reason: str = ""
    partial_tool_name: str = ""
    details: str = ""
    dump_file: str = ""


@dataclass
class RenderLink(RenderInstruction):
    """Instruction to render a link marker."""
    link_id: str = ""
    linked_session_id: str = ""
    linked_session_name: str = ""
    summary: str = ""
    link_point: int = 0  # Turn index where link exists
    is_orphaned: bool = False


@dataclass
class RenderArchive(RenderInstruction):
    """Instruction to render an archive marker."""
    archive_block: ArchiveBlock = None
    turn_index: int = 0


@dataclass
class RenderFork(RenderInstruction):
    """Instruction to render a fork marker."""
    prompt: str = ""
    child_session_id: str = ""
    fork_name: str = ""
    status: str = "active"


@dataclass
class RenderMerge(RenderInstruction):
    """Instruction to render a merge marker."""
    message: str = ""
    child_session_id: str = ""
    fork_name: str = ""
    files_changed: list[str] = field(default_factory=list)
    key_accomplishments: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class RenderMergedTo(RenderInstruction):
    """Instruction to render a 'merged to parent' marker."""
    message: str = ""
    parent_session_id: str = ""
    parent_name: str = ""
    parent_turn: int = 0
    merge_id: str = ""
    files_changed: list[str] = field(default_factory=list)
    key_accomplishments: list[str] = field(default_factory=list)
    reason: str = ""


# =============================================================================
# History Loader
# =============================================================================

@dataclass
class HistoryLoadResult:
    """Result of loading history - instructions plus metadata."""
    instructions: list[RenderInstruction] = field(default_factory=list)
    final_turn_id: int = 0


class HistoryLoader:
    """Transforms messages into render instructions.

    This class encapsulates the logic of iterating through messages and their
    content blocks, building fork/merge point maps from session metadata, and
    producing a flat list of render instructions.
    """

    def __init__(self, session_loader: callable = None):
        """Initialize the history loader.

        Args:
            session_loader: Optional callable to load sessions by ID.
                           Defaults to Session.load. Can be replaced for testing.
        """
        self._session_loader = session_loader or Session.load

    def load(
        self,
        messages: list[Message],
        session: Session | None = None,
        start_turn_id: int = 0
    ) -> HistoryLoadResult:
        """Transform messages into render instructions.

        Args:
            messages: List of Message objects to transform
            session: Optional session (unused, kept for API compatibility)
            start_turn_id: Starting turn counter (for appending to existing history)

        Returns:
            HistoryLoadResult with instructions and final turn ID
        """
        instructions: list[RenderInstruction] = []
        turn_counter = start_turn_id

        for turn_idx, msg in enumerate(messages):
            turn_counter += 1
            turn_id = turn_counter

            # Process message content blocks
            if msg.content_blocks:
                for block_idx, block in enumerate(msg.content_blocks):
                    instr = self._process_block(
                        block, msg.role, turn_id, block_idx, turn_idx
                    )
                    if instr:
                        instructions.append(instr)
            else:
                # Fallback: just use msg.content
                if msg.content.strip():
                    instructions.append(RenderMessage(
                        turn_id=turn_id,
                        role=msg.role,
                        text=msg.content,
                        block_idx=0
                    ))

        return HistoryLoadResult(
            instructions=instructions,
            final_turn_id=turn_counter
        )

    def _process_block(
        self,
        block: Any,
        role: str,
        turn_id: int,
        block_idx: int,
        turn_idx: int
    ) -> RenderInstruction | None:
        """Process a single content block into a render instruction."""

        if isinstance(block, TextBlock):
            if block.text.strip():
                return RenderMessage(
                    turn_id=turn_id,
                    role=role,
                    text=block.text,
                    block_idx=block_idx
                )

        elif isinstance(block, ToolUseBlock):
            return RenderToolUse(
                turn_id=turn_id,
                tool_name=block.name,
                tool_use_id=block.id,
                tool_input=block.input
            )

        elif isinstance(block, ToolResultBlock):
            return RenderToolResult(
                turn_id=turn_id,
                tool_use_id=block.tool_use_id,
                content=block.content,
                is_error=block.is_error
            )

        elif isinstance(block, InterruptionBlock):
            return RenderInterruption(
                turn_id=turn_id,
                reason=block.reason
            )

        elif isinstance(block, ErrorBlock):
            return RenderError(
                turn_id=turn_id,
                reason=block.reason,
                partial_tool_name=block.partial_tool_name,
                details=block.details,
                dump_file=block.dump_file
            )

        elif isinstance(block, LinkBlock):
            # Look up linked session for display name
            linked_session = self._session_loader(block.linked_session_id)
            is_orphaned = block.is_orphaned

            if linked_session:
                linked_name = (
                    linked_session.title or
                    linked_session.fork_name or
                    block.linked_session_id[:8]
                )
            else:
                linked_name = (
                    block.linked_session_id[:8]
                    if block.linked_session_id
                    else "[unknown]"
                )
                is_orphaned = True

            return RenderLink(
                turn_id=turn_id,
                link_id=block.link_id,
                linked_session_id=block.linked_session_id,
                linked_session_name=linked_name,
                summary=block.summary,
                link_point=turn_idx,
                is_orphaned=is_orphaned
            )

        elif isinstance(block, ArchiveBlock):
            return RenderArchive(
                turn_id=turn_id,
                archive_block=block,
                turn_index=turn_idx
            )

        elif isinstance(block, ForkBlock):
            return RenderFork(
                turn_id=turn_id,
                prompt=block.prompt,
                child_session_id=block.child_session_id,
                fork_name=block.fork_name,
                status=block.status
            )

        elif isinstance(block, MergeBlock):
            return RenderMerge(
                turn_id=turn_id,
                message=block.message,
                child_session_id=block.child_session_id,
                fork_name=block.fork_name,
                files_changed=block.files_changed,
                key_accomplishments=block.key_accomplishments,
                reason=block.reason,
            )

        elif isinstance(block, MergedToBlock):
            return RenderMergedTo(
                turn_id=turn_id,
                message=block.message,
                parent_session_id=block.parent_session_id,
                parent_name=block.parent_name,
                parent_turn=block.parent_turn,
                merge_id=block.merge_id,
                files_changed=block.files_changed,
                key_accomplishments=block.key_accomplishments,
                reason=block.reason,
            )

        return None
