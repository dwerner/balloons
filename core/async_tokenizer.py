"""Async token counting utilities.

Provides non-blocking token counting that integrates with asyncio.
Uses a dedicated ThreadPoolExecutor so token counting doesn't block
the Textual UI event loop.

Usage:
    tokenizer = AsyncTokenizer()

    # Count tokens asynchronously
    count = await tokenizer.count_tokens(text)

    # Or use callback pattern for fire-and-forget
    tokenizer.count_tokens_deferred(text, callback=lambda count: ...)
"""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Callable, Optional, Any

from models import TextBlock, ToolUseBlock, ToolResultBlock, ArchiveBlock


# Dedicated thread pool for token counting (CPU-bound work)
# Using 4 threads to match the Rust tokenizer's pool size
_token_executor: Optional[ThreadPoolExecutor] = None


def _get_token_executor() -> ThreadPoolExecutor:
    """Get or create the token counting thread pool."""
    global _token_executor
    if _token_executor is None:
        _token_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tokenizer")
    return _token_executor


def _count_tokens_sync(text: str) -> int:
    """Synchronous token counting - runs in thread pool."""
    from tokenizer import count_tokens
    return count_tokens(text)


def _format_turn_content(role: str, content_blocks: list) -> str:
    """Format turn content for token counting.

    Uses the same formatting as ContextBuilder.count_turn_tokens()
    for consistency.
    """
    if not content_blocks:
        return ""

    prefix = "User" if role == "user" else "Assistant"
    block_parts = []

    for block in content_blocks:
        # Use type attribute for duck-typing compatibility
        block_type = getattr(block, 'type', None)
        if block_type == 'text' or isinstance(block, TextBlock):
            if block.text:
                block_parts.append(block.text)
        elif block_type == 'tool_use' or isinstance(block, ToolUseBlock):
            input_str = json.dumps(block.input, indent=2)
            block_parts.append(f"[Tool Use: {block.name}]\n{input_str}")
        elif block_type == 'tool_result' or isinstance(block, ToolResultBlock):
            error_prefix = "[Error] " if getattr(block, 'is_error', False) else ""
            block_parts.append(f"[Tool Result]{error_prefix}\n{block.content}")
        elif block_type == 'archive' or isinstance(block, ArchiveBlock):
            block_parts.append(
                f"[Archived {block.message_count} turns: {block.summary}]\n"
                f"(Archive ID: {block.archive_id}, JSON path: {block.file_path})"
            )

    if not block_parts:
        return ""

    return f"{prefix}: " + "\n\n".join(block_parts)


class AsyncTokenizer:
    """Async wrapper for token counting.

    Provides async methods that run token counting in a thread pool,
    preventing UI blocking during large content token counting.
    """

    def __init__(self):
        self._executor = _get_token_executor()

    async def count_tokens(self, text: str) -> int:
        """Count tokens asynchronously.

        Runs in thread pool to avoid blocking the event loop.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, _count_tokens_sync, text)

    async def count_turn_tokens(self, role: str, content_blocks: list) -> int:
        """Count tokens for a turn's content blocks asynchronously."""
        text = _format_turn_content(role, content_blocks)
        if not text:
            return 0
        return await self.count_tokens(text)

    def count_tokens_deferred(
        self,
        text: str,
        callback: Callable[[int], Any],
    ) -> Future:
        """Count tokens in background and call callback with result.

        This is a fire-and-forget pattern - submits work to thread pool
        and returns immediately. The callback is called from the thread pool
        thread when counting is complete.

        Returns the Future for optional cancellation.
        """
        def work():
            count = _count_tokens_sync(text)
            callback(count)
            return count

        return self._executor.submit(work)

    def count_turn_tokens_deferred(
        self,
        role: str,
        content_blocks: list,
        callback: Callable[[int], Any],
    ) -> Future:
        """Count turn tokens in background and call callback with result."""
        text = _format_turn_content(role, content_blocks)
        if not text:
            # No content, call callback immediately with 0
            callback(0)
            # Return a completed future
            future = Future()
            future.set_result(0)
            return future
        return self.count_tokens_deferred(text, callback)


# Module-level singleton for convenience
_shared_tokenizer: Optional[AsyncTokenizer] = None


def get_async_tokenizer() -> AsyncTokenizer:
    """Get the shared async tokenizer instance."""
    global _shared_tokenizer
    if _shared_tokenizer is None:
        _shared_tokenizer = AsyncTokenizer()
    return _shared_tokenizer


def wait_for_pending_token_counts(timeout: float = 5.0) -> None:
    """Wait for all pending token counting tasks to complete.

    Useful in tests to ensure async token counting has finished
    before checking results.

    Args:
        timeout: Maximum time to wait in seconds
    """
    executor = _get_token_executor()
    # Submit a no-op task and wait for it - this ensures all previously
    # submitted tasks have completed since ThreadPoolExecutor processes
    # tasks in FIFO order
    future = executor.submit(lambda: None)
    future.result(timeout=timeout)
