"""
Subscription Manager - Manages client subscriptions to session event layers.

This module implements a layered subscription system where clients can subscribe
to different levels of event granularity for each session:

- HEADER: Turn lifecycle events (created, completed, deleted) and stream status
- BODY: Full turn content blocks on completion
- DELTA: Live streaming events (text deltas, tool input deltas)
- HISTORY: One-time history loading (triggers historyChunk/historyComplete)

Example usage:
    manager = SubscriptionManager()

    # Tree view - subscribe to headers for all sessions
    manager.add_layers("session-1", "client-abc", {Layer.HEADER})
    manager.add_layers("session-2", "client-abc", {Layer.HEADER})

    # User selects session-1 - add full subscription
    manager.add_layers("session-1", "client-abc", {Layer.BODY, Layer.DELTA, Layer.HISTORY})

    # Route events efficiently
    clients = manager.get_clients_for_layer("session-1", Layer.DELTA)
    # Only clients subscribed to DELTA receive delta events
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Set, Dict


class Layer(str, Enum):
    """Subscription layers for session events.

    Each layer represents a category of events with different bandwidth costs:
    - HEADER: Low bandwidth, suitable for many sessions
    - BODY: Medium bandwidth, turn content on completion
    - DELTA: High bandwidth, only for actively viewed session
    - HISTORY: One-time load, oldest-first (chronological order)
    - HISTORY_REVERSE: One-time load, newest-first (fast time-to-bottom)
    - HISTORY_LAZY: On-demand loading via load_history_range() calls
    """
    HEADER = "header"
    BODY = "body"
    DELTA = "delta"
    HISTORY = "history"
    HISTORY_REVERSE = "history_reverse"
    HISTORY_LAZY = "history_lazy"


@dataclass
class SubscriptionManager:
    """Manages client subscriptions to session event layers.

    Thread-safe management of which clients receive which event types
    for each session. Supports efficient lookup in both directions:
    - Client → Sessions → Layers (for client state management)
    - Session → Layer → Clients (for event routing)

    Attributes:
        _subscriptions: Nested dict mapping client_id → session_id → set of Layers
    """

    # client_id -> session_id -> set of subscribed layers
    _subscriptions: Dict[str, Dict[str, Set[Layer]]] = field(default_factory=dict)

    def add_layers(
        self,
        session_id: str,
        client_id: str,
        layers: Set[Layer]
    ) -> bool:
        """Add subscription layers for a client/session pair.

        Creates the subscription if it doesn't exist, or adds to existing.

        Args:
            session_id: The session to subscribe to
            client_id: The client subscribing
            layers: Set of layers to add (e.g., {Layer.HEADER, Layer.BODY})

        Returns:
            True if any layers were added (subscription changed)
        """
        if not client_id or not session_id or not layers:
            return False

        # Ensure client entry exists
        if client_id not in self._subscriptions:
            self._subscriptions[client_id] = {}

        # Ensure session entry exists for this client
        if session_id not in self._subscriptions[client_id]:
            self._subscriptions[client_id][session_id] = set()

        # Track if we actually added anything
        before_count = len(self._subscriptions[client_id][session_id])
        self._subscriptions[client_id][session_id].update(layers)
        after_count = len(self._subscriptions[client_id][session_id])

        return after_count > before_count

    def remove_layers(
        self,
        session_id: str,
        client_id: str,
        layers: Set[Layer]
    ) -> bool:
        """Remove subscription layers for a client/session pair.

        If all layers are removed, the subscription is deleted entirely.

        Args:
            session_id: The session to modify
            client_id: The client to modify
            layers: Set of layers to remove

        Returns:
            True if any layers were removed (subscription changed)
        """
        if client_id not in self._subscriptions:
            return False

        if session_id not in self._subscriptions[client_id]:
            return False

        # Track if we actually removed anything
        before_count = len(self._subscriptions[client_id][session_id])
        self._subscriptions[client_id][session_id].difference_update(layers)
        after_count = len(self._subscriptions[client_id][session_id])

        # Clean up empty subscription
        if not self._subscriptions[client_id][session_id]:
            del self._subscriptions[client_id][session_id]

        # Clean up empty client entry
        if not self._subscriptions[client_id]:
            del self._subscriptions[client_id]

        return after_count < before_count

    def unsubscribe(self, session_id: str, client_id: str) -> bool:
        """Fully unsubscribe a client from a session.

        Removes all layers for this client/session pair.

        Args:
            session_id: The session to unsubscribe from
            client_id: The client to unsubscribe

        Returns:
            True if the client was subscribed (and is now unsubscribed)
        """
        if client_id not in self._subscriptions:
            return False

        if session_id not in self._subscriptions[client_id]:
            return False

        del self._subscriptions[client_id][session_id]

        # Clean up empty client entry
        if not self._subscriptions[client_id]:
            del self._subscriptions[client_id]

        return True

    def unsubscribe_client(self, client_id: str) -> int:
        """Unsubscribe a client from all sessions.

        Called when a client disconnects to clean up all subscriptions.

        Args:
            client_id: The client to fully unsubscribe

        Returns:
            Number of sessions the client was unsubscribed from
        """
        if client_id not in self._subscriptions:
            return 0

        session_count = len(self._subscriptions[client_id])
        del self._subscriptions[client_id]
        return session_count

    def get_clients_for_layer(
        self,
        session_id: str,
        layer: Layer
    ) -> Set[str]:
        """Get all clients subscribed to a specific layer for a session.

        Used for event routing - only send events to clients who want them.

        Args:
            session_id: The session generating the event
            layer: The layer the event belongs to

        Returns:
            Set of client_ids subscribed to this layer for this session
        """
        result = set()
        for client_id, sessions in self._subscriptions.items():
            if session_id in sessions:
                if layer in sessions[session_id]:
                    result.add(client_id)
        return result

    def get_client_layers(
        self,
        session_id: str,
        client_id: str
    ) -> Set[Layer]:
        """Get the layers a client is subscribed to for a session.

        Args:
            session_id: The session to check
            client_id: The client to check

        Returns:
            Set of subscribed layers (empty if not subscribed)
        """
        if client_id not in self._subscriptions:
            return set()
        if session_id not in self._subscriptions[client_id]:
            return set()
        return self._subscriptions[client_id][session_id].copy()

    def get_client_sessions(self, client_id: str) -> Dict[str, Set[Layer]]:
        """Get all sessions a client is subscribed to with their layers.

        Args:
            client_id: The client to query

        Returns:
            Dict mapping session_id → set of layers
        """
        if client_id not in self._subscriptions:
            return {}
        # Return a copy to prevent external mutation
        return {
            session_id: layers.copy()
            for session_id, layers in self._subscriptions[client_id].items()
        }

    def has_any_subscribers(self, session_id: str) -> bool:
        """Check if any client is subscribed to a session at any layer.

        Args:
            session_id: The session to check

        Returns:
            True if at least one client has any subscription to this session
        """
        for sessions in self._subscriptions.values():
            if session_id in sessions and sessions[session_id]:
                return True
        return False

    def get_subscriber_count(self, session_id: str) -> int:
        """Get the number of unique clients subscribed to a session.

        Args:
            session_id: The session to check

        Returns:
            Number of clients with any subscription to this session
        """
        count = 0
        for sessions in self._subscriptions.values():
            if session_id in sessions and sessions[session_id]:
                count += 1
        return count
