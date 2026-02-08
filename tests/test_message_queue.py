"""Tests for the MessageQueue class used for queuing messages during streaming."""

import pytest
from datetime import datetime

from session import MessageQueue, QueuedMessage


class TestQueuedMessage:
    """Tests for the QueuedMessage dataclass."""

    def test_create_queued_message(self):
        """Can create a QueuedMessage with required fields."""
        msg = QueuedMessage(
            id="test-id",
            content="Hello world",
            created=datetime.now(),
        )
        assert msg.id == "test-id"
        assert msg.content == "Hello world"
        assert not msg.paused  # Default is False

    def test_queued_message_paused_default(self):
        """QueuedMessage.paused defaults to False."""
        msg = QueuedMessage(
            id="test-id",
            content="test",
            created=datetime.now(),
        )
        assert msg.paused is False

    def test_queued_message_serialization(self):
        """QueuedMessage can be serialized and deserialized."""
        now = datetime.now()
        msg = QueuedMessage(
            id="test-id",
            content="Hello",
            created=now,
            paused=True,
        )

        data = msg.to_dict()
        assert data["id"] == "test-id"
        assert data["content"] == "Hello"
        assert data["paused"] is True
        assert "created" in data

        restored = QueuedMessage.from_dict(data)
        assert restored.id == msg.id
        assert restored.content == msg.content
        assert restored.paused == msg.paused


class TestMessageQueue:
    """Tests for the MessageQueue class."""

    def test_empty_queue(self):
        """Empty queue has correct initial state."""
        q = MessageQueue()
        assert len(q) == 0
        assert not q  # bool is False
        assert q.peek() is None
        assert q.pop() is None

    def test_add_message(self):
        """Adding messages increases queue size."""
        q = MessageQueue()
        msg = q.add("first message")

        assert len(q) == 1
        assert q  # bool is True
        assert msg.content == "first message"
        assert not msg.paused

    def test_fifo_order(self):
        """Messages are returned in FIFO order."""
        q = MessageQueue()
        q.add("first")
        q.add("second")
        q.add("third")

        assert q.pop().content == "first"
        assert q.pop().content == "second"
        assert q.pop().content == "third"
        assert q.pop() is None

    def test_peek_does_not_remove(self):
        """Peek returns message without removing it."""
        q = MessageQueue()
        q.add("test message")

        peeked = q.peek()
        assert peeked.content == "test message"
        assert len(q) == 1  # Still there

        popped = q.pop()
        assert popped.content == "test message"
        assert len(q) == 0

    def test_remove_by_id(self):
        """Can remove a specific message by ID."""
        q = MessageQueue()
        msg1 = q.add("first")
        msg2 = q.add("second")
        msg3 = q.add("third")

        assert q.remove(msg2.id) is True
        assert len(q) == 2
        assert q.pop().content == "first"
        assert q.pop().content == "third"

    def test_remove_nonexistent_id(self):
        """Removing nonexistent ID returns False."""
        q = MessageQueue()
        q.add("test")

        assert q.remove("nonexistent-id") is False
        assert len(q) == 1

    def test_toggle_pause(self):
        """Can toggle pause state on a message."""
        q = MessageQueue()
        msg = q.add("test")

        assert not msg.paused
        new_state = q.toggle_pause(msg.id)
        assert new_state is True
        assert msg.paused is True

        new_state = q.toggle_pause(msg.id)
        assert new_state is False
        assert msg.paused is False

    def test_is_blocked(self):
        """Queue is blocked when first message is paused."""
        q = MessageQueue()
        msg1 = q.add("first")
        q.add("second")

        assert not q.is_blocked()

        msg1.paused = True
        assert q.is_blocked()

    def test_first_pause_index(self):
        """first_pause_index returns correct index."""
        q = MessageQueue()
        q.add("first")
        msg2 = q.add("second")
        q.add("third")

        assert q.first_pause_index() == -1  # No paused messages

        msg2.paused = True
        assert q.first_pause_index() == 1

    def test_clear(self):
        """Clear removes all messages and returns count."""
        q = MessageQueue()
        q.add("first")
        q.add("second")
        q.add("third")

        count = q.clear()
        assert count == 3
        assert len(q) == 0
        assert not q

    def test_get_by_id(self):
        """Can retrieve message by ID without removing."""
        q = MessageQueue()
        msg = q.add("test")

        retrieved = q.get(msg.id)
        assert retrieved is msg
        assert len(q) == 1  # Still in queue

    def test_get_nonexistent_id(self):
        """Getting nonexistent ID returns None."""
        q = MessageQueue()
        q.add("test")

        assert q.get("nonexistent") is None

    def test_update_content(self):
        """Can update message content by ID."""
        q = MessageQueue()
        msg = q.add("original")

        assert q.update_content(msg.id, "updated")
        assert msg.content == "updated"

    def test_update_content_nonexistent(self):
        """Updating nonexistent ID returns False."""
        q = MessageQueue()
        q.add("test")

        assert not q.update_content("nonexistent", "new content")


class TestMessageQueueDrain:
    """Tests for the drain() method - critical for queue processing."""

    def test_drain_empty_queue(self):
        """Draining empty queue returns empty list."""
        q = MessageQueue()
        result = q.drain()
        assert result == []

    def test_drain_all_messages(self):
        """Drain returns all message contents when none paused."""
        q = MessageQueue()
        q.add("first")
        q.add("second")
        q.add("third")

        result = q.drain()
        assert result == ["first", "second", "third"]
        assert len(q) == 0

    def test_drain_stops_at_paused(self):
        """Drain stops at first paused message."""
        q = MessageQueue()
        q.add("first")
        msg2 = q.add("second")
        msg2.paused = True
        q.add("third")

        result = q.drain()
        assert result == ["first"]
        assert len(q) == 2  # second and third remain

    def test_drain_blocked_queue(self):
        """Drain returns empty when first message is paused (blocked)."""
        q = MessageQueue()
        msg = q.add("blocked")
        msg.paused = True
        q.add("also blocked")

        result = q.drain()
        assert result == []
        assert len(q) == 2  # Both still there

    def test_drain_removes_only_drained(self):
        """After drain, only non-drained messages remain."""
        q = MessageQueue()
        q.add("drain me")
        q.add("drain me too")
        msg3 = q.add("keep me")
        msg3.paused = True
        q.add("keep me too")

        result = q.drain()
        assert result == ["drain me", "drain me too"]

        # Check what remains
        assert len(q) == 2
        assert q.peek().content == "keep me"
        assert q.peek().paused is True


class TestMessageQueueSerialization:
    """Tests for MessageQueue serialization/deserialization."""

    def test_empty_queue_serialization(self):
        """Empty queue serializes correctly."""
        q = MessageQueue()
        data = q.to_dict()
        assert data == {"messages": []}

        restored = MessageQueue.from_dict(data)
        assert len(restored) == 0

    def test_queue_with_messages_serialization(self):
        """Queue with messages round-trips correctly."""
        q = MessageQueue()
        q.add("first")
        q.add("second")
        msg3 = q.add("third")
        msg3.paused = True

        data = q.to_dict()
        assert len(data["messages"]) == 3

        restored = MessageQueue.from_dict(data)
        assert len(restored) == 3
        assert restored.messages[0].content == "first"
        assert restored.messages[1].content == "second"
        assert restored.messages[2].content == "third"
        assert restored.messages[2].paused is True

    def test_from_dict_empty_data(self):
        """from_dict handles empty/missing data gracefully."""
        restored = MessageQueue.from_dict({})
        assert len(restored) == 0

        restored = MessageQueue.from_dict({"messages": []})
        assert len(restored) == 0
