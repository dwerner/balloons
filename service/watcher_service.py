"""Watcher mode service for cross-session observation.

This service manages the watcher mode functionality:
1. Listens for StreamDoneEvent from target sessions
2. Generates LLM summaries of completed exchanges using the watcher's backend
3. Injects WatchSummaryBlock turns into watcher sessions
4. Triggers watcher LLM responses to summaries

The service implements SessionEventObserver to receive stream events.
"""

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Callable

from config import get_config
from core.debug_log import debug_log, Category
from core.runner_factory import create_runner
from models import TextDelta
from service.session_events import (
    SessionEventObserver,
    StreamDoneEvent,
    TurnCreatedEvent,
    TurnFinishedEvent,
)
from models import WatchStartBlock, WatchStopBlock, WatchSummaryBlock

if TYPE_CHECKING:
    from core.manager import SessionManager
    from session import Session


# Prompt for generating watcher summaries
_WATCHER_SUMMARY_PROMPT = """Summarize this exchange from a session you're watching.
Be concise (2-4 sentences). Focus on what was accomplished or decided.
Include any key code changes, decisions, or blockers.

Session: {target_name}
Exchange #{exchange_index}:

{exchange_content}

Summary:"""


@dataclass
class WatcherRelation:
    """Tracks a watcher session observing a target session."""

    watcher_session_id: str
    target_session_id: str
    target_session_name: str


class WatcherService(SessionEventObserver):
    """Service that manages watcher mode functionality.

    Responsibilities:
    - Track which sessions are watching which targets
    - Generate LLM summaries when target exchanges complete
    - Inject summaries into watcher sessions
    - Queue watcher LLM responses
    """

    def __init__(self, session_manager: "SessionManager"):
        self._manager = session_manager
        # Map of target_session_id -> list of watcher_session_ids
        self._watchers: dict[str, list[str]] = {}
        # Map of watcher_session_id -> list of target_session_ids
        self._watching: dict[str, list[str]] = {}
        # Lock for concurrent access to watcher maps
        self._lock = asyncio.Lock()
        # Pending summaries queue (for when watcher is mid-exchange)
        self._pending_summaries: dict[str, list[tuple[str, int, str]]] = {}  # watcher_id -> [(target_id, exchange_idx, summary)]
        # Event handler for notifying about summary injection
        self._event_handler: Optional[Callable] = None

    def set_event_handler(self, handler: Callable) -> None:
        """Set the event handler for turn events."""
        self._event_handler = handler

    async def register_watcher(
        self,
        watcher_session_id: str,
        target_session_id: str,
        target_session_name: str,
    ) -> None:
        """Register a watcher session to observe a target.

        Called when a watcher session is created or a WatchStartBlock is added.
        """
        async with self._lock:
            # Add to target -> watchers map
            if target_session_id not in self._watchers:
                self._watchers[target_session_id] = []
            if watcher_session_id not in self._watchers[target_session_id]:
                self._watchers[target_session_id].append(watcher_session_id)

            # Add to watcher -> targets map
            if watcher_session_id not in self._watching:
                self._watching[watcher_session_id] = []
            if target_session_id not in self._watching[watcher_session_id]:
                self._watching[watcher_session_id].append(target_session_id)

        debug_log.info(
            f"Registered watcher: {watcher_session_id[:8]} -> {target_session_id[:8]}",
            category=Category.SESSION,
        )

    async def unregister_watcher(
        self,
        watcher_session_id: str,
        target_session_id: Optional[str] = None,
    ) -> None:
        """Unregister a watcher from observing a target (or all targets).

        Called when a WatchStopBlock is added or watcher session is deleted.
        """
        async with self._lock:
            if target_session_id:
                # Remove specific target
                if target_session_id in self._watchers:
                    if watcher_session_id in self._watchers[target_session_id]:
                        self._watchers[target_session_id].remove(watcher_session_id)
                if watcher_session_id in self._watching:
                    if target_session_id in self._watching[watcher_session_id]:
                        self._watching[watcher_session_id].remove(target_session_id)
            else:
                # Remove all targets for this watcher
                for target_id in list(self._watching.get(watcher_session_id, [])):
                    if target_id in self._watchers:
                        if watcher_session_id in self._watchers[target_id]:
                            self._watchers[target_id].remove(watcher_session_id)
                self._watching.pop(watcher_session_id, None)

        debug_log.info(
            f"Unregistered watcher: {watcher_session_id[:8]} from {target_session_id[:8] if target_session_id else 'all'}",
            category=Category.SESSION,
        )

    def get_watchers_for_session(self, session_id: str) -> list[str]:
        """Get list of watcher session IDs observing a session."""
        return self._watchers.get(session_id, []).copy()

    def get_targets_for_watcher(self, watcher_session_id: str) -> list[str]:
        """Get list of target session IDs a watcher is observing."""
        return self._watching.get(watcher_session_id, []).copy()

    async def on_stream_done(self, event: StreamDoneEvent) -> None:
        """Handle stream done event - generate summaries for watchers.

        Called when a session completes an exchange. If any watchers are
        observing this session, generate and inject summaries.
        """
        target_session_id = event.session_id
        exchange_id = event.exchange_id

        # Get watchers for this session
        watchers = self.get_watchers_for_session(target_session_id)
        if not watchers:
            return  # No watchers, nothing to do

        debug_log.info(
            f"Target {target_session_id[:8]} completed exchange {exchange_id[:8]}, notifying {len(watchers)} watchers",
            category=Category.SESSION,
        )

        # Load target session to get exchange content
        target_session = self._manager.get_session(target_session_id)
        if not target_session:
            target_session = await self._manager.load_session(target_session_id)
            if not target_session:
                debug_log.error(
                    f"Could not load target session {target_session_id} for watcher summary",
                    category=Category.SESSION,
                )
                return

        # Get target name
        target_name = target_session.title or target_session.fork_name or target_session_id[:8]

        # Find the exchange index and content
        exchange_turns = [t for t in target_session.turns if t.exchange_id == exchange_id]
        if not exchange_turns:
            debug_log.warning(
                f"No turns found for exchange {exchange_id} in target {target_session_id[:8]}",
                category=Category.SESSION,
            )
            return

        # Calculate exchange index (count exchanges before this one)
        exchange_ids = []
        for turn in target_session.turns:
            if turn.exchange_id and turn.exchange_id not in exchange_ids:
                exchange_ids.append(turn.exchange_id)
        exchange_index = exchange_ids.index(exchange_id) if exchange_id in exchange_ids else len(exchange_ids)

        # Generate summary for each watcher
        for watcher_session_id in watchers:
            try:
                await self._generate_and_inject_summary(
                    watcher_session_id=watcher_session_id,
                    target_session_id=target_session_id,
                    target_session_name=target_name,
                    exchange_index=exchange_index,
                    exchange_turns=exchange_turns,
                )
            except Exception as e:
                debug_log.error(
                    f"Error generating summary for watcher {watcher_session_id[:8]}: {e}",
                    category=Category.SESSION,
                )

    def _format_exchange_content(self, exchange_turns: list) -> str:
        """Format exchange turns into text for summarization."""
        parts = []
        for turn in exchange_turns:
            role = turn.role.capitalize()

            # Extract text content
            if hasattr(turn.content_block, 'text') and turn.content_block.text:
                content = turn.content_block.text
                # Truncate very long content
                if len(content) > 2000:
                    content = content[:2000] + "\n[...truncated...]"
                parts.append(f"{role}:\n{content}")
            elif hasattr(turn.content_block, 'name'):
                # Tool use
                tool_name = turn.content_block.name
                parts.append(f"{role}: [Tool: {tool_name}]")
            elif hasattr(turn.content_block, 'tool_use_id'):
                # Tool result
                result = getattr(turn.content_block, 'content', '[result]')
                if len(str(result)) > 500:
                    result = str(result)[:500] + "..."
                parts.append(f"{role}: [Tool result: {result}]")

        return "\n\n".join(parts)

    async def _generate_llm_summary(
        self,
        watcher_session: "Session",
        target_name: str,
        exchange_index: int,
        exchange_content: str,
    ) -> str:
        """Generate an LLM summary using the watcher session's backend."""
        config = get_config()

        # Get the watcher session's backend (or default)
        backend_name = watcher_session.backend_name or config.default_backend
        backend = config.get_backend(backend_name)
        if not backend:
            backend = config.get_backend(config.default_backend)

        runner = create_runner(backend)

        # Build the prompt
        prompt = _WATCHER_SUMMARY_PROMPT.format(
            target_name=target_name,
            exchange_index=exchange_index,
            exchange_content=exchange_content,
        )

        # Stream the response
        summary_parts = []
        try:
            async for event in runner.stream_response([], prompt, disable_tools=True):
                if isinstance(event, TextDelta):
                    summary_parts.append(event.text)
        except Exception as e:
            debug_log.error(
                f"LLM summary generation failed: {e}",
                category=Category.RUNNER,
            )
            # Fall back to basic extraction
            return self._generate_fallback_summary(exchange_content)

        return "".join(summary_parts).strip() if summary_parts else self._generate_fallback_summary(exchange_content)

    def _generate_fallback_summary(self, exchange_content: str) -> str:
        """Generate a basic summary when LLM fails."""
        # Just return first 300 chars as a fallback
        if len(exchange_content) > 300:
            return exchange_content[:300] + "..."
        return exchange_content

    async def _generate_and_inject_summary(
        self,
        watcher_session_id: str,
        target_session_id: str,
        target_session_name: str,
        exchange_index: int,
        exchange_turns: list,
    ) -> None:
        """Generate an LLM summary and inject it into the watcher session.

        Uses the watcher session's configured backend for summary generation.
        """
        # Load watcher session
        watcher_session = self._manager.get_session(watcher_session_id)
        if not watcher_session:
            watcher_session = await self._manager.load_session(watcher_session_id)
            if not watcher_session:
                debug_log.error(
                    f"Could not load watcher session {watcher_session_id}",
                    category=Category.SESSION,
                )
                return

        # Format the exchange content
        exchange_content = self._format_exchange_content(exchange_turns)

        # Generate LLM summary using watcher's backend
        summary = await self._generate_llm_summary(
            watcher_session=watcher_session,
            target_name=target_session_name,
            exchange_index=exchange_index,
            exchange_content=exchange_content,
        )

        # Add the summary turn to watcher session
        summary_turn = watcher_session.add_watch_summary_turn(
            target_session_id=target_session_id,
            target_session_name=target_session_name,
            exchange_index=exchange_index,
            summary=summary,
        )

        await watcher_session.save()

        debug_log.info(
            f"Injected LLM summary for exchange {exchange_index} into watcher {watcher_session_id[:8]}",
            category=Category.SESSION,
            details={"summary_preview": summary[:100]},
        )

        # Emit turn event so UI updates
        if self._event_handler:
            self._event_handler(
                "watchSummaryInjected",
                {
                    "session_id": watcher_session_id,
                    "target_session_id": target_session_id,
                    "exchange_index": exchange_index,
                    "turn_index": len(watcher_session.turns) - 1,
                },
            )

    # --- SessionEventObserver Protocol Implementation ---
    # Most methods are no-ops; we only care about stream_done

    async def on_turn_created(self, event: TurnCreatedEvent) -> None:
        """Check for WatchStartBlock/WatchStopBlock turns to update registrations."""
        # This could be used to auto-register watchers when turns are created
        # For now, registration happens explicitly via create_watcher_session
        pass

    async def on_turn_delta(self, event) -> None:
        pass

    async def on_turn_finished(self, event: TurnFinishedEvent) -> None:
        pass

    async def on_stream_started(self, event) -> None:
        pass

    async def on_stream_progress(self, event) -> None:
        pass

    async def on_stream_error(self, event) -> None:
        pass

    async def on_tool_use_started(self, event) -> None:
        pass

    async def on_tool_input_delta(self, event) -> None:
        pass

    async def on_tool_use(self, event) -> None:
        pass

    async def on_tool_result(self, event) -> None:
        pass

    async def on_helper_started(self, event) -> None:
        pass

    async def on_helper_delta(self, event) -> None:
        pass

    async def on_helper_done(self, event) -> None:
        pass

    async def on_helper_error(self, event) -> None:
        pass
