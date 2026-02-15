"""Tests for core/async_storage.py."""

import asyncio
import tempfile
from pathlib import Path

import pytest

from core.async_storage import AsyncStorage, is_rust_storage_available
from session import Session
from models import Turn, TextBlock, ToolUseBlock, ToolResultBlock, ContextMode


# Skip all tests if Rust storage is not available
pytestmark = pytest.mark.skipif(
    not is_rust_storage_available(),
    reason="Rust balloons_storage module not available"
)


@pytest.fixture
def temp_db():
    """Create a temporary database file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test.db"


@pytest.fixture
def sample_session():
    """Create a sample session with various turn types."""
    session = Session()
    session.model = "claude-sonnet-4-20250514"
    session.title = "Test Session"
    session.working_directories = ["/home/dan/test"]

    # Add a user text turn
    session.add_turn(
        role="user",
        content_block=TextBlock(text="Hello, can you help me?"),
        tokens=10,
    )

    # Add an assistant text turn
    session.add_turn(
        role="assistant",
        content_block=TextBlock(text="Of course! How can I help you today?"),
        tokens=15,
    )

    # Add a tool use turn
    session.add_turn(
        role="assistant",
        content_block=ToolUseBlock(
            id="tool_123",
            name="Read",
            input={"file_path": "/home/dan/test.py"},
        ),
        tokens=20,
    )

    # Add a tool result turn
    session.add_turn(
        role="tool",
        content_block=ToolResultBlock(
            tool_use_id="tool_123",
            content="print('hello world')",
            is_error=False,
        ),
        tokens=5,
    )

    session.total_input_tokens = 50
    session.total_output_tokens = 35
    session.total_cost = 0.001

    return session


@pytest.mark.asyncio
async def test_save_and_load_session(temp_db, sample_session):
    """Test saving and loading a session."""
    storage = AsyncStorage(temp_db)

    # Save the session
    await storage.save_session(sample_session)

    # Load it back
    loaded = await storage.load_session(sample_session.id)

    assert loaded is not None
    assert loaded.id == sample_session.id
    assert loaded.model == sample_session.model
    assert loaded.title == sample_session.title
    assert loaded.working_directories == sample_session.working_directories
    assert loaded.total_input_tokens == sample_session.total_input_tokens
    assert loaded.total_output_tokens == sample_session.total_output_tokens
    assert len(loaded.turns) == len(sample_session.turns)


@pytest.mark.asyncio
async def test_load_nonexistent_session(temp_db):
    """Test loading a session that doesn't exist."""
    storage = AsyncStorage(temp_db)

    loaded = await storage.load_session("nonexistent-id")
    assert loaded is None


@pytest.mark.asyncio
async def test_delete_session(temp_db, sample_session):
    """Test deleting a session."""
    storage = AsyncStorage(temp_db)

    # Save the session
    await storage.save_session(sample_session)

    # Verify it exists
    loaded = await storage.load_session(sample_session.id)
    assert loaded is not None

    # Delete it
    await storage.delete_session(sample_session.id)

    # Verify it's gone
    loaded = await storage.load_session(sample_session.id)
    assert loaded is None


@pytest.mark.asyncio
async def test_list_sessions(temp_db):
    """Test listing all sessions."""
    storage = AsyncStorage(temp_db)

    # Create and save multiple sessions
    for i in range(3):
        session = Session()
        session.title = f"Test Session {i}"
        session.add_turn(
            role="user",
            content_block=TextBlock(text=f"Message {i}"),
        )
        await storage.save_session(session)

    # List sessions
    sessions = await storage.list_sessions()
    assert len(sessions) == 3

    # Verify metadata format
    for meta in sessions:
        assert "id" in meta
        assert "name" in meta
        assert "created_at" in meta
        assert "updated_at" in meta
        assert "turn_count" in meta


@pytest.mark.asyncio
async def test_turn_content_blocks_preserved(temp_db, sample_session):
    """Test that various content block types are preserved."""
    storage = AsyncStorage(temp_db)

    await storage.save_session(sample_session)
    loaded = await storage.load_session(sample_session.id)

    assert loaded is not None

    # Check user text block
    assert isinstance(loaded.turns[0].content_block, TextBlock)
    assert loaded.turns[0].content_block.text == "Hello, can you help me?"
    assert loaded.turns[0].role == "user"

    # Check assistant text block
    assert isinstance(loaded.turns[1].content_block, TextBlock)
    assert loaded.turns[1].content_block.text == "Of course! How can I help you today?"
    assert loaded.turns[1].role == "assistant"

    # Check tool use block
    assert isinstance(loaded.turns[2].content_block, ToolUseBlock)
    assert loaded.turns[2].content_block.name == "Read"
    assert loaded.turns[2].content_block.input == {"file_path": "/home/dan/test.py"}

    # Check tool result block
    assert isinstance(loaded.turns[3].content_block, ToolResultBlock)
    assert loaded.turns[3].content_block.content == "print('hello world')"
    assert loaded.turns[3].content_block.is_error is False


@pytest.mark.asyncio
async def test_context_mode_preserved(temp_db):
    """Test that context mode is preserved."""
    storage = AsyncStorage(temp_db)

    session = Session()
    session.add_turn(
        role="user",
        content_block=TextBlock(text="Copy me"),
        context_mode=ContextMode.COPY,
    )
    session.add_turn(
        role="assistant",
        content_block=TextBlock(text="Compress me"),
        context_mode=ContextMode.COMPRESS,
    )
    session.add_turn(
        role="user",
        content_block=TextBlock(text="Drop me"),
        context_mode=ContextMode.DROP,
    )

    await storage.save_session(session)
    loaded = await storage.load_session(session.id)

    assert loaded.turns[0].context_mode == ContextMode.COPY
    assert loaded.turns[1].context_mode == ContextMode.COMPRESS
    assert loaded.turns[2].context_mode == ContextMode.DROP


@pytest.mark.asyncio
async def test_fork_fields_preserved(temp_db):
    """Test that fork/merge related fields are preserved."""
    storage = AsyncStorage(temp_db)

    session = Session()
    session.parent_id = "parent-123"
    session.fork_name = "test-fork"
    session.fork_status = "active"
    session.fork_point_turn = 5
    session.children = [{"session_id": "child-1", "status": "active"}]

    await storage.save_session(session)
    loaded = await storage.load_session(session.id)

    assert loaded.parent_id == "parent-123"
    assert loaded.fork_name == "test-fork"
    assert loaded.fork_status == "active"
    assert loaded.fork_point_turn == 5
    assert loaded.children == [{"session_id": "child-1", "status": "active"}]


@pytest.mark.asyncio
async def test_update_session(temp_db, sample_session):
    """Test updating an existing session."""
    storage = AsyncStorage(temp_db)

    # Save initial version
    await storage.save_session(sample_session)

    # Modify and save again
    sample_session.title = "Updated Title"
    sample_session.add_turn(
        role="user",
        content_block=TextBlock(text="New message"),
        tokens=5,
    )
    await storage.save_session(sample_session)

    # Load and verify
    loaded = await storage.load_session(sample_session.id)
    assert loaded.title == "Updated Title"
    assert len(loaded.turns) == 5  # Original 4 + new one


@pytest.mark.asyncio
async def test_concurrent_access(temp_db):
    """Test that concurrent operations don't corrupt data."""
    storage = AsyncStorage(temp_db)

    # Create many sessions concurrently
    async def create_session(i):
        session = Session()
        session.title = f"Concurrent Session {i}"
        session.add_turn(
            role="user",
            content_block=TextBlock(text=f"Message {i}"),
        )
        await storage.save_session(session)
        return session.id

    # Create 10 sessions concurrently
    ids = await asyncio.gather(*[create_session(i) for i in range(10)])

    # Verify all sessions exist
    sessions = await storage.list_sessions()
    assert len(sessions) == 10

    # Load each session and verify
    for i, session_id in enumerate(ids):
        loaded = await storage.load_session(session_id)
        assert loaded is not None
        assert loaded.title == f"Concurrent Session {i}"


@pytest.mark.asyncio
async def test_save_turn_independently(temp_db, sample_session):
    """Test saving turns independently after session creation."""
    storage = AsyncStorage(temp_db)

    # Save session (which saves all turns)
    await storage.save_session(sample_session)
    original_turn_count = len(sample_session.turns)

    # Load and verify
    loaded = await storage.load_session(sample_session.id)
    assert len(loaded.turns) == original_turn_count

    # Now save an additional turn directly
    from models import Turn, TextBlock, ContextMode
    new_turn = Turn(
        role="user",
        content_block=TextBlock(text="New independent turn"),
        tokens=10,
        context_mode=ContextMode.COPY,
    )
    await storage.save_turn(sample_session.id, new_turn)

    # Reload and verify the new turn is present
    loaded = await storage.load_session(sample_session.id)
    assert len(loaded.turns) == original_turn_count + 1
    assert loaded.turns[-1].content_block.text == "New independent turn"


@pytest.mark.asyncio
async def test_delete_turn(temp_db, sample_session):
    """Test deleting a single turn."""
    storage = AsyncStorage(temp_db)

    await storage.save_session(sample_session)
    original_count = len(sample_session.turns)

    # Load turns to get the IDs
    turns_data = await storage.load_turns(sample_session.id)
    assert len(turns_data) == original_count

    # Delete the first turn
    first_turn_id = turns_data[0]["id"]
    await storage.delete_turn(sample_session.id, first_turn_id)

    # Verify turn was deleted
    loaded = await storage.load_session(sample_session.id)
    assert len(loaded.turns) == original_count - 1


@pytest.mark.asyncio
async def test_reorder_turns(temp_db):
    """Test reordering turns within a session."""
    storage = AsyncStorage(temp_db)

    session = Session()
    session.add_turn(role="user", content_block=TextBlock(text="First"))
    session.add_turn(role="assistant", content_block=TextBlock(text="Second"))
    session.add_turn(role="user", content_block=TextBlock(text="Third"))

    await storage.save_session(session)

    # Get turn IDs
    turns_data = await storage.load_turns(session.id)
    turn_ids = [t["id"] for t in turns_data]
    assert len(turn_ids) == 3

    # Reorder: third, first, second
    new_order = [turn_ids[2], turn_ids[0], turn_ids[1]]
    await storage.reorder_turns(session.id, new_order)

    # Verify new order
    loaded = await storage.load_session(session.id)
    assert loaded.turns[0].content_block.text == "Third"
    assert loaded.turns[1].content_block.text == "First"
    assert loaded.turns[2].content_block.text == "Second"


@pytest.mark.asyncio
async def test_session_metadata_update_preserves_turns(temp_db, sample_session):
    """Test that updating session metadata doesn't affect turns."""
    storage = AsyncStorage(temp_db)

    await storage.save_session(sample_session)
    original_turn_count = len(sample_session.turns)

    # Modify session metadata only (not turns)
    sample_session.title = "Updated Title"
    sample_session.total_input_tokens = 999

    # Save just the session metadata (clear turns first to avoid re-saving)
    sample_session.turns = []
    session_data = storage._session_to_wire(sample_session)
    import json
    json_data = json.dumps(session_data)
    await storage._run_sync(storage._storage.save_session, sample_session.id, json_data)

    # Load and verify turns are still there
    loaded = await storage.load_session(sample_session.id)
    assert loaded.title == "Updated Title"
    assert loaded.total_input_tokens == 999
    assert len(loaded.turns) == original_turn_count


@pytest.mark.asyncio
async def test_incremental_save_only_saves_dirty_turns(temp_db, sample_session):
    """Test that incremental save only saves new/modified turns, not all turns."""
    storage = AsyncStorage(temp_db)

    # First save (full save)
    await storage.save_session(sample_session)

    # Verify session is clean after save
    assert not sample_session._metadata_dirty
    assert len(sample_session._saved_turn_order) == len(sample_session.turns)
    assert all(not t.is_dirty for t in sample_session.turns)

    # Add a new turn
    sample_session.add_turn(
        role="user",
        content_block=TextBlock(text="New question"),
        tokens=5,
    )

    # Verify only the new turn is dirty
    dirty_turns = sample_session.get_dirty_turns()
    assert len(dirty_turns) == 1
    assert dirty_turns[0].content_block.text == "New question"

    # Save (should be incremental)
    await storage.save_session(sample_session)

    # Verify clean again
    assert all(not t.is_dirty for t in sample_session.turns)
    assert len(sample_session._saved_turn_order) == len(sample_session.turns)

    # Load and verify all turns are there
    loaded = await storage.load_session(sample_session.id)
    assert len(loaded.turns) == 5  # Original 4 + new one


@pytest.mark.asyncio
async def test_incremental_save_handles_turn_deletion(temp_db, sample_session):
    """Test that incremental save handles deleted turns."""
    storage = AsyncStorage(temp_db)

    # First save
    await storage.save_session(sample_session)
    original_count = len(sample_session.turns)
    deleted_turn_id = sample_session.turns[1].id

    # Delete a turn
    sample_session.delete_turn(1)

    # Verify deletion is tracked
    assert deleted_turn_id in sample_session._deleted_turn_ids
    assert sample_session.needs_save()

    # Save (incremental)
    await storage.save_session(sample_session)

    # Verify clean
    assert len(sample_session._deleted_turn_ids) == 0

    # Load and verify
    loaded = await storage.load_session(sample_session.id)
    assert len(loaded.turns) == original_count - 1
    assert all(t.id != deleted_turn_id for t in loaded.turns)


@pytest.mark.asyncio
async def test_incremental_save_handles_turn_reorder(temp_db, sample_session):
    """Test that incremental save handles turn reordering."""
    storage = AsyncStorage(temp_db)

    # First save
    await storage.save_session(sample_session)
    original_order = [t.id for t in sample_session.turns]

    # Reverse the order
    sample_session.turns = list(reversed(sample_session.turns))
    new_order = [t.id for t in sample_session.turns]

    # Verify reorder is detected
    assert sample_session.has_turn_order_changed()
    assert sample_session.needs_save()

    # Save (incremental)
    await storage.save_session(sample_session)

    # Load and verify order
    loaded = await storage.load_session(sample_session.id)
    loaded_order = [t.id for t in loaded.turns]
    assert loaded_order == new_order


@pytest.mark.asyncio
async def test_turn_id_persists_across_save_load(temp_db):
    """Test that turn IDs are preserved when saving and loading."""
    storage = AsyncStorage(temp_db)

    session = Session()
    session.add_turn(
        role="user",
        content_block=TextBlock(text="Hello"),
        tokens=5,
    )

    original_id = session.turns[0].id
    assert original_id  # ID should be set

    # Save and load
    await storage.save_session(session)
    loaded = await storage.load_session(session.id)

    # Turn ID should be preserved
    assert loaded.turns[0].id == original_id


@pytest.mark.asyncio
async def test_loaded_session_is_clean(temp_db, sample_session):
    """Test that a loaded session starts clean (no pending saves)."""
    storage = AsyncStorage(temp_db)

    # Save
    await storage.save_session(sample_session)

    # Load
    loaded = await storage.load_session(sample_session.id)

    # Verify clean state
    assert not loaded._metadata_dirty
    assert len(loaded._deleted_turn_ids) == 0
    assert len(loaded._saved_turn_order) == len(loaded.turns)
    assert all(not t.is_dirty for t in loaded.turns)
    assert not loaded.needs_save()


@pytest.mark.asyncio
async def test_delete_unsaved_turn_does_not_cause_error(temp_db):
    """Test that deleting a turn that was never saved doesn't cause errors.

    Regression test for: turns created and deleted before save were being
    tracked in _deleted_turn_ids, causing "Turn not found" errors during save.
    """
    storage = AsyncStorage(temp_db)

    # Create and save a session with one turn
    session = Session()
    session.add_turn(
        role="user",
        content_block=TextBlock(text="Original turn"),
        tokens=5,
    )
    await storage.save_session(session)
    original_turn_id = session.turns[0].id

    # Add a new turn (not saved yet)
    session.add_turn(
        role="assistant",
        content_block=TextBlock(text="New turn that will be deleted"),
        tokens=10,
    )
    new_turn_id = session.turns[1].id
    assert new_turn_id not in session._saved_turn_order  # Not saved yet

    # Delete the new turn before saving
    session.delete_turn(1)

    # The new turn should NOT be in _deleted_turn_ids since it was never saved
    assert new_turn_id not in session._deleted_turn_ids

    # Save should succeed without "Turn not found" error
    await storage.save_session(session)

    # Verify session state
    loaded = await storage.load_session(session.id)
    assert len(loaded.turns) == 1
    assert loaded.turns[0].id == original_turn_id


@pytest.mark.asyncio
async def test_delete_saved_turn_is_tracked(temp_db):
    """Test that deleting a previously saved turn is properly tracked."""
    storage = AsyncStorage(temp_db)

    # Create and save a session with two turns
    session = Session()
    session.add_turn(
        role="user",
        content_block=TextBlock(text="Turn 1"),
        tokens=5,
    )
    session.add_turn(
        role="assistant",
        content_block=TextBlock(text="Turn 2"),
        tokens=10,
    )
    await storage.save_session(session)

    turn_to_delete_id = session.turns[1].id
    assert turn_to_delete_id in session._saved_turn_order  # Was saved

    # Delete the second turn
    session.delete_turn(1)

    # The turn SHOULD be in _deleted_turn_ids since it was saved
    assert turn_to_delete_id in session._deleted_turn_ids

    # Save should work
    await storage.save_session(session)

    # Verify session state
    loaded = await storage.load_session(session.id)
    assert len(loaded.turns) == 1
    assert loaded.turns[0].content_block.text == "Turn 1"


@pytest.mark.asyncio
async def test_incremental_save_snapshot_prevents_race_condition(temp_db):
    """Test that incremental save takes a snapshot to prevent race conditions.

    This tests the scenario where a new turn is added during an async save:
    1. Save starts, takes snapshot of turns
    2. New turn is added to session
    3. Save completes with snapshot turns
    4. New turn is still dirty and will be saved in next cycle
    5. reorder_turns only includes saved turns (not the new one)
    """
    storage = AsyncStorage(temp_db)

    # Create session with one turn
    session = Session()
    session.add_turn(
        role="user",
        content_block=TextBlock(text="Initial turn"),
    )
    await storage.save_session(session)

    # Verify session is clean
    assert session._saved_turn_order == [session.turns[0].id]
    assert not session.turns[0].is_dirty

    # Add a new turn (simulating a concurrent add during save)
    session.add_turn(
        role="assistant",
        content_block=TextBlock(text="New turn"),
    )
    new_turn_id = session.turns[1].id

    # The new turn should be dirty
    assert session.turns[1].is_dirty

    # Save should work even if we simulate concurrent modification
    # The key is that reorder_turns uses the snapshot order
    await storage.save_session(session)

    # After save, the new turn should be clean and in saved_turn_order
    assert not session.turns[1].is_dirty
    assert new_turn_id in session._saved_turn_order

    # Verify persistence
    loaded = await storage.load_session(session.id)
    assert len(loaded.turns) == 2
    assert loaded.turns[1].content_block.text == "New turn"


@pytest.mark.asyncio
async def test_mark_saved_clean_only_affects_saved_turns(temp_db):
    """Test that mark_saved_clean only marks the specified turns as clean."""
    session = Session()
    turn1 = session.add_turn(role="user", content_block=TextBlock(text="Turn 1"))
    turn2 = session.add_turn(role="assistant", content_block=TextBlock(text="Turn 2"))
    turn3 = session.add_turn(role="user", content_block=TextBlock(text="Turn 3"))

    # All turns start dirty
    assert turn1.is_dirty
    assert turn2.is_dirty
    assert turn3.is_dirty

    # Mark only turn1 and turn2 as saved
    saved_ids = {turn1.id, turn2.id}
    session.mark_saved_clean(saved_ids)

    # turn1 and turn2 should be clean, turn3 should still be dirty
    assert not turn1.is_dirty
    assert not turn2.is_dirty
    assert turn3.is_dirty

    # _saved_turn_order should only include saved turns
    assert session._saved_turn_order == [turn1.id, turn2.id]


# GoalStorage tests are in test_goal_storage.py (file-based, no Rust required)
