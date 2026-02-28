"""Tests for the SubscriptionManager class."""

import pytest
from service.subscription_manager import SubscriptionManager, Layer


class TestSubscriptionManager:
    """Test suite for SubscriptionManager."""

    @pytest.fixture
    def manager(self):
        """Create a fresh SubscriptionManager for each test."""
        return SubscriptionManager()

    # --- add_layers tests ---

    def test_add_layers_creates_subscription(self, manager):
        """Adding layers to non-existent subscription creates it."""
        result = manager.add_layers("session-1", "client-a", {Layer.HEADER})
        assert result is True
        assert manager.get_client_layers("session-1", "client-a") == {Layer.HEADER}

    def test_add_layers_extends_existing(self, manager):
        """Adding more layers extends existing subscription."""
        manager.add_layers("session-1", "client-a", {Layer.HEADER})
        result = manager.add_layers("session-1", "client-a", {Layer.BODY, Layer.DELTA})

        assert result is True
        assert manager.get_client_layers("session-1", "client-a") == {
            Layer.HEADER, Layer.BODY, Layer.DELTA
        }

    def test_add_layers_idempotent(self, manager):
        """Adding already-subscribed layers returns False (no change)."""
        manager.add_layers("session-1", "client-a", {Layer.HEADER, Layer.BODY})
        result = manager.add_layers("session-1", "client-a", {Layer.HEADER})

        assert result is False  # No new layers added
        assert manager.get_client_layers("session-1", "client-a") == {Layer.HEADER, Layer.BODY}

    def test_add_layers_empty_set_returns_false(self, manager):
        """Adding empty set of layers returns False."""
        result = manager.add_layers("session-1", "client-a", set())
        assert result is False

    def test_add_layers_empty_client_id_returns_false(self, manager):
        """Adding layers with empty client_id returns False."""
        result = manager.add_layers("session-1", "", {Layer.HEADER})
        assert result is False

    def test_add_layers_empty_session_id_returns_false(self, manager):
        """Adding layers with empty session_id returns False."""
        result = manager.add_layers("", "client-a", {Layer.HEADER})
        assert result is False

    # --- remove_layers tests ---

    def test_remove_layers_removes_subset(self, manager):
        """Removing some layers keeps others."""
        manager.add_layers("session-1", "client-a", {Layer.HEADER, Layer.BODY, Layer.DELTA})
        result = manager.remove_layers("session-1", "client-a", {Layer.DELTA})

        assert result is True
        assert manager.get_client_layers("session-1", "client-a") == {Layer.HEADER, Layer.BODY}

    def test_remove_layers_all_cleans_up(self, manager):
        """Removing all layers cleans up subscription entirely."""
        manager.add_layers("session-1", "client-a", {Layer.HEADER})
        result = manager.remove_layers("session-1", "client-a", {Layer.HEADER})

        assert result is True
        assert manager.get_client_layers("session-1", "client-a") == set()
        assert not manager.has_any_subscribers("session-1")

    def test_remove_layers_nonexistent_returns_false(self, manager):
        """Removing from non-existent subscription returns False."""
        result = manager.remove_layers("session-1", "client-a", {Layer.HEADER})
        assert result is False

    def test_remove_layers_not_subscribed_returns_false(self, manager):
        """Removing layers not in subscription returns False."""
        manager.add_layers("session-1", "client-a", {Layer.HEADER})
        result = manager.remove_layers("session-1", "client-a", {Layer.DELTA})

        assert result is False
        assert manager.get_client_layers("session-1", "client-a") == {Layer.HEADER}

    # --- unsubscribe tests ---

    def test_unsubscribe_removes_all_layers(self, manager):
        """Unsubscribe removes all layers for session."""
        manager.add_layers("session-1", "client-a", {Layer.HEADER, Layer.BODY, Layer.DELTA})
        result = manager.unsubscribe("session-1", "client-a")

        assert result is True
        assert manager.get_client_layers("session-1", "client-a") == set()

    def test_unsubscribe_keeps_other_sessions(self, manager):
        """Unsubscribe from one session keeps other subscriptions."""
        manager.add_layers("session-1", "client-a", {Layer.HEADER})
        manager.add_layers("session-2", "client-a", {Layer.HEADER, Layer.BODY})

        manager.unsubscribe("session-1", "client-a")

        assert manager.get_client_layers("session-1", "client-a") == set()
        assert manager.get_client_layers("session-2", "client-a") == {Layer.HEADER, Layer.BODY}

    def test_unsubscribe_nonexistent_returns_false(self, manager):
        """Unsubscribe from non-existent subscription returns False."""
        result = manager.unsubscribe("session-1", "client-a")
        assert result is False

    # --- unsubscribe_client tests ---

    def test_unsubscribe_client_removes_all(self, manager):
        """Unsubscribe client removes all session subscriptions."""
        manager.add_layers("session-1", "client-a", {Layer.HEADER})
        manager.add_layers("session-2", "client-a", {Layer.HEADER, Layer.BODY})
        manager.add_layers("session-3", "client-a", {Layer.DELTA})

        count = manager.unsubscribe_client("client-a")

        assert count == 3
        assert manager.get_client_sessions("client-a") == {}

    def test_unsubscribe_client_keeps_other_clients(self, manager):
        """Unsubscribe client keeps other clients' subscriptions."""
        manager.add_layers("session-1", "client-a", {Layer.HEADER})
        manager.add_layers("session-1", "client-b", {Layer.HEADER, Layer.BODY})

        manager.unsubscribe_client("client-a")

        assert manager.get_client_layers("session-1", "client-b") == {Layer.HEADER, Layer.BODY}

    def test_unsubscribe_client_nonexistent_returns_zero(self, manager):
        """Unsubscribe non-existent client returns 0."""
        count = manager.unsubscribe_client("nonexistent")
        assert count == 0

    # --- get_clients_for_layer tests ---

    def test_get_clients_for_layer_returns_matching(self, manager):
        """Get clients returns only those subscribed to the layer."""
        manager.add_layers("session-1", "client-a", {Layer.HEADER, Layer.BODY})
        manager.add_layers("session-1", "client-b", {Layer.HEADER})
        manager.add_layers("session-1", "client-c", {Layer.HEADER, Layer.DELTA})

        # All three have HEADER
        assert manager.get_clients_for_layer("session-1", Layer.HEADER) == {
            "client-a", "client-b", "client-c"
        }

        # Only client-a has BODY
        assert manager.get_clients_for_layer("session-1", Layer.BODY) == {"client-a"}

        # Only client-c has DELTA
        assert manager.get_clients_for_layer("session-1", Layer.DELTA) == {"client-c"}

        # No one has HISTORY
        assert manager.get_clients_for_layer("session-1", Layer.HISTORY) == set()

    def test_get_clients_for_layer_session_isolation(self, manager):
        """Get clients only returns clients for the specific session."""
        manager.add_layers("session-1", "client-a", {Layer.HEADER})
        manager.add_layers("session-2", "client-b", {Layer.HEADER})

        assert manager.get_clients_for_layer("session-1", Layer.HEADER) == {"client-a"}
        assert manager.get_clients_for_layer("session-2", Layer.HEADER) == {"client-b"}

    # --- get_client_sessions tests ---

    def test_get_client_sessions_returns_all(self, manager):
        """Get client sessions returns all subscribed sessions."""
        manager.add_layers("session-1", "client-a", {Layer.HEADER})
        manager.add_layers("session-2", "client-a", {Layer.HEADER, Layer.BODY})
        manager.add_layers("session-3", "client-a", {Layer.DELTA})

        sessions = manager.get_client_sessions("client-a")

        assert sessions == {
            "session-1": {Layer.HEADER},
            "session-2": {Layer.HEADER, Layer.BODY},
            "session-3": {Layer.DELTA},
        }

    def test_get_client_sessions_returns_copy(self, manager):
        """Get client sessions returns a copy, not the internal state."""
        manager.add_layers("session-1", "client-a", {Layer.HEADER})

        sessions = manager.get_client_sessions("client-a")
        sessions["session-1"].add(Layer.DELTA)  # Modify returned value

        # Internal state should be unchanged
        assert manager.get_client_layers("session-1", "client-a") == {Layer.HEADER}

    # --- has_any_subscribers tests ---

    def test_has_any_subscribers_true(self, manager):
        """Has subscribers returns True when subscribed."""
        manager.add_layers("session-1", "client-a", {Layer.HEADER})
        assert manager.has_any_subscribers("session-1") is True

    def test_has_any_subscribers_false(self, manager):
        """Has subscribers returns False when not subscribed."""
        assert manager.has_any_subscribers("session-1") is False

    def test_has_any_subscribers_after_unsubscribe(self, manager):
        """Has subscribers returns False after full unsubscribe."""
        manager.add_layers("session-1", "client-a", {Layer.HEADER})
        manager.unsubscribe("session-1", "client-a")
        assert manager.has_any_subscribers("session-1") is False

    # --- get_subscriber_count tests ---

    def test_get_subscriber_count(self, manager):
        """Get subscriber count returns unique client count."""
        manager.add_layers("session-1", "client-a", {Layer.HEADER})
        manager.add_layers("session-1", "client-b", {Layer.HEADER, Layer.BODY})
        manager.add_layers("session-1", "client-c", {Layer.DELTA})

        assert manager.get_subscriber_count("session-1") == 3

    def test_get_subscriber_count_zero(self, manager):
        """Get subscriber count returns 0 for no subscribers."""
        assert manager.get_subscriber_count("session-1") == 0

    # --- Integration scenarios ---

    def test_typical_session_selection_workflow(self, manager):
        """Test typical workflow: tree view → select → switch sessions."""
        # User loads tree view - subscribe HEADER to all visible sessions
        manager.add_layers("session-1", "client-a", {Layer.HEADER})
        manager.add_layers("session-2", "client-a", {Layer.HEADER})
        manager.add_layers("session-3", "client-a", {Layer.HEADER})

        # User selects session-1 - upgrade to full
        manager.add_layers("session-1", "client-a", {Layer.BODY, Layer.DELTA, Layer.HISTORY})

        assert manager.get_client_layers("session-1", "client-a") == {
            Layer.HEADER, Layer.BODY, Layer.DELTA, Layer.HISTORY
        }

        # User switches to session-2 - downgrade session-1, upgrade session-2
        manager.remove_layers("session-1", "client-a", {Layer.DELTA})
        manager.add_layers("session-2", "client-a", {Layer.BODY, Layer.DELTA, Layer.HISTORY})

        # session-1 keeps HEADER+BODY for preview, loses DELTA
        assert manager.get_client_layers("session-1", "client-a") == {
            Layer.HEADER, Layer.BODY, Layer.HISTORY
        }
        # session-2 now has full subscription
        assert manager.get_client_layers("session-2", "client-a") == {
            Layer.HEADER, Layer.BODY, Layer.DELTA, Layer.HISTORY
        }

    def test_multiple_clients_same_session(self, manager):
        """Multiple clients can have different subscriptions to same session."""
        manager.add_layers("session-1", "client-a", {Layer.HEADER})  # Tree viewer
        manager.add_layers("session-1", "client-b", {Layer.HEADER, Layer.BODY, Layer.DELTA})  # Active viewer

        # Event routing should work correctly
        assert manager.get_clients_for_layer("session-1", Layer.HEADER) == {"client-a", "client-b"}
        assert manager.get_clients_for_layer("session-1", Layer.DELTA) == {"client-b"}

    def test_client_disconnect_cleanup(self, manager):
        """Client disconnect cleans up all subscriptions."""
        # Client subscribes to multiple sessions
        manager.add_layers("session-1", "client-a", {Layer.HEADER, Layer.BODY, Layer.DELTA})
        manager.add_layers("session-2", "client-a", {Layer.HEADER})
        manager.add_layers("session-3", "client-a", {Layer.HEADER})

        # Other client also subscribed
        manager.add_layers("session-1", "client-b", {Layer.HEADER})

        # Client disconnects
        manager.unsubscribe_client("client-a")

        # session-1 still has client-b
        assert manager.has_any_subscribers("session-1") is True
        assert manager.get_clients_for_layer("session-1", Layer.HEADER) == {"client-b"}

        # Other sessions have no subscribers
        assert manager.has_any_subscribers("session-2") is False
        assert manager.has_any_subscribers("session-3") is False
