"""Context grouping logic for fork/derive operations.

Handles separating messages by context mode and grouping contiguous
COMPRESS messages for efficient summarization.

Extracted from app.py to enable unit testing without the UI.
"""

from dataclasses import dataclass

from models import Message, ContextMode


@dataclass
class ContextGroups:
    """Result of grouping messages by context mode.

    Attributes:
        copy_items: List of (message, index) tuples to copy verbatim
        compress_groups: List of groups, where each group is [(message, index), ...]
                        containing contiguous COMPRESS messages
    """

    copy_items: list[tuple[Message, int]]
    compress_groups: list[list[tuple[Message, int]]]

    @property
    def needs_compression(self) -> bool:
        """Whether any compression is needed."""
        return len(self.compress_groups) > 0

    @property
    def compress_group_positions(self) -> list[int]:
        """Get the first index of each compress group (where summary will be inserted)."""
        return [group[0][1] for group in self.compress_groups]


def group_messages_by_context_mode(
    indexed_messages: list[tuple[Message, int]],
) -> ContextGroups:
    """Group messages by their context mode for fork/derive operations.

    Separates COPY and COMPRESS messages, then groups contiguous COMPRESS
    messages together. Two COMPRESS messages are in the same group if there
    are no COPY messages between them.

    Args:
        indexed_messages: List of (Message, original_index) tuples

    Returns:
        ContextGroups with copy_items and compress_groups
    """
    copy_items: list[tuple[Message, int]] = []
    compress_items: list[tuple[Message, int]] = []

    for msg, idx in indexed_messages:
        if msg.context_mode == ContextMode.COPY:
            copy_items.append((msg, idx))
        elif msg.context_mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
            compress_items.append((msg, idx))
        # DROP messages are ignored

    # Group contiguous COMPRESS messages
    compress_groups: list[list[tuple[Message, int]]] = []

    if compress_items:
        compress_items.sort(key=lambda x: x[1])
        current_group = [compress_items[0]]

        for i in range(1, len(compress_items)):
            msg, idx = compress_items[i]
            _, prev_idx = current_group[-1]

            # Check if contiguous (no COPY messages between them)
            copy_indices = {i for _, i in copy_items}
            has_copy_between = any(prev_idx < ci < idx for ci in copy_indices)

            if has_copy_between:
                # Start new group
                compress_groups.append(current_group)
                current_group = [(msg, idx)]
            else:
                # Continue current group
                current_group.append((msg, idx))

        compress_groups.append(current_group)

    return ContextGroups(copy_items=copy_items, compress_groups=compress_groups)


def build_context_messages(
    copy_items: list[tuple[Message, int]],
    summary_items: list[tuple[Message, int]],
) -> list[Message]:
    """Combine copy and summary messages, sorted by original index.

    Args:
        copy_items: List of (message, index) tuples to include verbatim
        summary_items: List of (summary_message, index) tuples from compression

    Returns:
        List of Message objects in correct order
    """
    all_items = copy_items + summary_items
    all_items.sort(key=lambda x: x[1])
    return [msg for msg, _ in all_items]
