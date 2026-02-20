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
    Message, Turn, TextBlock, ToolUseBlock, ToolResultBlock,
    InterruptionBlock, ErrorBlock, LinkBlock, ForkBlock,
    MergeBlock, MergedToBlock, ArchiveBlock, ReviewBlock, Sentiment,
    ForkProposalBlock, MergeProposalBlock, ContextAssignmentData, ForkBindingData,
    ExchangeInfo
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
    sentiment: Sentiment | None = None  # User sentiment rating (assistant turns only)


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


@dataclass
class RenderReview(RenderInstruction):
    """Instruction to render a review marker."""
    child_session_id: str = ""
    model_under_review: str = ""
    status: str = "active"
    overall_score: float = 0.0
    task_category: str = ""
    task_description: str = ""


@dataclass
class RenderForkProposal(RenderInstruction):
    """Instruction to render a fork proposal with Accept/Reject buttons."""
    proposal_id: str = ""
    name: str = ""
    description: str = ""
    context_plan: list[ContextAssignmentData] = field(default_factory=list)
    initial_prompt: str = ""
    bind_to: ForkBindingData | None = None
    bind_to_inherit: bool = False
    status: str = "pending"  # "pending", "accepted", "rejected"
    all_exchanges: list[ExchangeInfo] = field(default_factory=list)  # All exchanges for interactive tree
    session_id: str = ""  # Session this proposal belongs to (for correct status updates)


@dataclass
class RenderMergeProposal(RenderInstruction):
    """Instruction to render a merge proposal with Accept/Reject buttons."""
    proposal_id: str = ""
    summary: str = ""
    reason: str = ""
    files_changed: list[str] = field(default_factory=list)
    key_accomplishments: list[str] = field(default_factory=list)
    status: str = "pending"  # "pending", "accepted", "rejected"


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
            session_loader: Optional async callable to load sessions by ID.
                           Defaults to Session.load. Can be replaced for testing.
        """
        self._session_loader = session_loader or Session.load

    async def load(
        self,
        messages: list[Message | Turn],
        session: Session | None = None,
        start_turn_id: int = 0
    ) -> HistoryLoadResult:
        """Transform messages/turns into render instructions.

        Args:
            messages: List of Message or Turn objects to transform
            session: Optional session for context (used for fork proposals to track session_id)
            start_turn_id: Starting turn counter (for appending to existing history)

        Returns:
            HistoryLoadResult with instructions and final turn ID
        """
        instructions: list[RenderInstruction] = []
        turn_counter = start_turn_id
        session_id = session.id if session else ""

        for turn_idx, msg in enumerate(messages):
            turn_counter += 1
            turn_id = turn_counter

            # Extract sentiment if this is a Turn object
            sentiment = getattr(msg, 'sentiment', None)

            # Process message content blocks
            if msg.content_blocks:
                for block_idx, block in enumerate(msg.content_blocks):
                    instr = await self._process_block(
                        block, msg.role, turn_id, block_idx, turn_idx, sentiment, session_id
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
                        block_idx=0,
                        sentiment=sentiment if msg.role == "assistant" else None
                    ))

        return HistoryLoadResult(
            instructions=instructions,
            final_turn_id=turn_counter
        )

    async def _process_block(
        self,
        block: Any,
        role: str,
        turn_id: int,
        block_idx: int,
        turn_idx: int,
        sentiment: Sentiment | None = None,
        session_id: str = ""
    ) -> RenderInstruction | None:
        """Process a single content block into a render instruction."""

        if isinstance(block, TextBlock):
            if block.text.strip():
                return RenderMessage(
                    turn_id=turn_id,
                    role=role,
                    text=block.text,
                    block_idx=block_idx,
                    sentiment=sentiment if role == "assistant" else None
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
            linked_session = await self._session_loader(block.linked_session_id)
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

        elif isinstance(block, ReviewBlock):
            return RenderReview(
                turn_id=turn_id,
                child_session_id=block.child_session_id,
                model_under_review=block.model_under_review,
                status=block.status,
                overall_score=block.overall_score,
                task_category=block.task_category,
                task_description=block.task_description,
            )

        elif isinstance(block, ForkProposalBlock):
            return RenderForkProposal(
                turn_id=turn_id,
                proposal_id=block.proposal_id,
                name=block.name,
                description=block.description,
                context_plan=block.context_plan,
                initial_prompt=block.initial_prompt,
                bind_to=block.bind_to,
                bind_to_inherit=block.bind_to_inherit,
                status=block.status,
                all_exchanges=block.all_exchanges,
                session_id=session_id,
            )

        elif isinstance(block, MergeProposalBlock):
            return RenderMergeProposal(
                turn_id=turn_id,
                proposal_id=block.proposal_id,
                summary=block.summary,
                reason=block.reason,
                files_changed=block.files_changed,
                key_accomplishments=block.key_accomplishments,
                status=block.status,
            )

        return None
