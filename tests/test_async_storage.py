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
        yield Path(tmpdir) / "test.redb"


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
