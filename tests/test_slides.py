"""Tests for slide turn type and SlideBlock functionality."""

import json
import pytest
from unittest.mock import patch

from session import Session, Turn
from models import SlideBlock, TextBlock


class TestSlideBlock:
    """Tests for the SlideBlock data model."""

    def test_slide_block_defaults(self):
        """SlideBlock should have correct default values."""
        slide = SlideBlock()
        assert slide.type == "slide"
        assert slide.title == ""
        assert slide.content == ""
        assert slide.notes == ""

    def test_slide_block_with_values(self):
        """SlideBlock should store provided values."""
        slide = SlideBlock(
            title="Introduction",
            content="# Hello World\n\n- Point 1\n- Point 2",
            notes="Remember to mention the demo",
        )
        assert slide.type == "slide"
        assert slide.title == "Introduction"
        assert slide.content == "# Hello World\n\n- Point 1\n- Point 2"
        assert slide.notes == "Remember to mention the demo"


class TestSessionSlides:
    """Tests for Session slide methods."""

    def test_add_slide_turn(self):
        """add_slide_turn should create a slide turn."""
        session = Session()
        turn = session.add_slide_turn(
            title="Test Slide",
            content="Some content",
            notes="Speaker notes",
        )

        assert turn.role == "slide"
        assert isinstance(turn.content_block, SlideBlock)
        assert turn.content_block.title == "Test Slide"
        assert turn.content_block.content == "Some content"
        assert turn.content_block.notes == "Speaker notes"

    def test_add_slide_turn_no_notes(self):
        """add_slide_turn should work without notes."""
        session = Session()
        turn = session.add_slide_turn(
            title="Slide",
            content="Content",
        )

        assert turn.content_block.notes == ""

    def test_get_all_slides(self):
        """get_all_slides should return all slides with indices."""
        session = Session()
        session.add_message("user", "Hello")  # index 0
        session.add_slide_turn("Slide 1", "Content 1")  # index 1
        session.add_message("assistant", "Response")  # index 2
        session.add_slide_turn("Slide 2", "Content 2")  # index 3
        session.add_slide_turn("Slide 3", "Content 3")  # index 4

        slides = session.get_all_slides()

        assert len(slides) == 3
        assert slides[0] == (1, session.turns[1].content_block)
        assert slides[1] == (3, session.turns[3].content_block)
        assert slides[2] == (4, session.turns[4].content_block)
        assert slides[0][1].title == "Slide 1"
        assert slides[1][1].title == "Slide 2"
        assert slides[2][1].title == "Slide 3"

    def test_get_all_slides_empty(self):
        """get_all_slides should return empty list when no slides."""
        session = Session()
        session.add_message("user", "Hello")
        session.add_message("assistant", "Hi")

        slides = session.get_all_slides()

        assert slides == []

    def test_get_slide_count(self):
        """get_slide_count should return correct count."""
        session = Session()
        assert session.get_slide_count() == 0

        session.add_slide_turn("Slide 1", "Content")
        assert session.get_slide_count() == 1

        session.add_message("user", "Hello")
        assert session.get_slide_count() == 1

        session.add_slide_turn("Slide 2", "Content")
        session.add_slide_turn("Slide 3", "Content")
        assert session.get_slide_count() == 3

    def test_has_slides(self):
        """has_slides should return correct boolean."""
        session = Session()
        assert session.has_slides() is False

        session.add_message("user", "Hello")
        assert session.has_slides() is False

        session.add_slide_turn("Slide", "Content")
        assert session.has_slides() is True

    def test_update_slide_title(self):
        """update_slide should update title."""
        session = Session()
        session.add_slide_turn("Original", "Content", "Notes")

        result = session.update_slide(0, title="Updated Title")

        assert result is True
        assert session.turns[0].content_block.title == "Updated Title"
        assert session.turns[0].content_block.content == "Content"
        assert session.turns[0].content_block.notes == "Notes"

    def test_update_slide_content(self):
        """update_slide should update content."""
        session = Session()
        session.add_slide_turn("Title", "Original content", "Notes")

        result = session.update_slide(0, content="New content")

        assert result is True
        assert session.turns[0].content_block.title == "Title"
        assert session.turns[0].content_block.content == "New content"
        assert session.turns[0].content_block.notes == "Notes"

    def test_update_slide_notes(self):
        """update_slide should update notes."""
        session = Session()
        session.add_slide_turn("Title", "Content", "Original notes")

        result = session.update_slide(0, notes="New notes")

        assert result is True
        assert session.turns[0].content_block.title == "Title"
        assert session.turns[0].content_block.content == "Content"
        assert session.turns[0].content_block.notes == "New notes"

    def test_update_slide_multiple_fields(self):
        """update_slide should update multiple fields at once."""
        session = Session()
        session.add_slide_turn("Title", "Content", "Notes")

        result = session.update_slide(0, title="New Title", content="New Content")

        assert result is True
        assert session.turns[0].content_block.title == "New Title"
        assert session.turns[0].content_block.content == "New Content"
        assert session.turns[0].content_block.notes == "Notes"  # unchanged

    def test_update_slide_invalid_index(self):
        """update_slide should return False for invalid index."""
        session = Session()
        session.add_slide_turn("Slide", "Content")

        assert session.update_slide(-1, title="X") is False
        assert session.update_slide(1, title="X") is False
        assert session.update_slide(100, title="X") is False

    def test_update_slide_non_slide_turn(self):
        """update_slide should return False for non-slide turns."""
        session = Session()
        session.add_message("user", "Hello")

        result = session.update_slide(0, title="X")

        assert result is False
        assert isinstance(session.turns[0].content_block, TextBlock)

    def test_delete_slide_turn(self):
        """Slides can be deleted like other turns."""
        session = Session()
        session.add_slide_turn("Slide 1", "Content 1")
        session.add_slide_turn("Slide 2", "Content 2")

        session.delete_turn(0)

        assert len(session.turns) == 1
        assert session.turns[0].content_block.title == "Slide 2"


class TestSlideSerialization:
    """Tests for slide serialization and deserialization."""

    def test_serialize_slide_block(self):
        """SlideBlock should serialize correctly."""
        session = Session()
        session.add_slide_turn("Title", "Content", "Notes")

        data = session._build_save_data()

        slide_data = data["turns"][0]["content_block"]
        assert slide_data["type"] == "slide"
        assert slide_data["title"] == "Title"
        assert slide_data["content"] == "Content"
        assert slide_data["notes"] == "Notes"

    def test_deserialize_slide_block(self):
        """SlideBlock should deserialize correctly."""
        slide_data = {
            "type": "slide",
            "title": "Test Title",
            "content": "# Markdown\n\n- Item",
            "notes": "Remember this",
        }

        block = Session._deserialize_content_block(slide_data)

        assert isinstance(block, SlideBlock)
        assert block.title == "Test Title"
        assert block.content == "# Markdown\n\n- Item"
        assert block.notes == "Remember this"

    def test_deserialize_slide_block_missing_fields(self):
        """SlideBlock should deserialize with default values for missing fields."""
        slide_data = {"type": "slide"}

        block = Session._deserialize_content_block(slide_data)

        assert isinstance(block, SlideBlock)
        assert block.title == ""
        assert block.content == ""
        assert block.notes == ""


class TestSlideSaveLoad:
    """Tests for slide save/load (requires Rust storage)."""

    @pytest.fixture
    def temp_storage(self, tmp_path):
        """Create temp storage for tests."""
        from core.async_storage import AsyncStorage, is_rust_storage_available
        import session as session_module

        if not is_rust_storage_available():
            pytest.skip("Rust balloons_py module not available")

        db_path = tmp_path / "test_sessions.db"
        temp_storage = AsyncStorage(db_path)

        old_storage = session_module._rust_storage
        session_module._rust_storage = temp_storage

        yield tmp_path

        session_module._rust_storage = old_storage

    async def test_save_load_roundtrip(self, temp_storage):
        """Slides should survive save/load roundtrip."""
        session = Session()
        session.add_message("user", "Let's make a presentation")
        session.add_slide_turn(
            title="Introduction",
            content="# Welcome\n\n- Point 1\n- Point 2",
            notes="Start with energy!",
        )
        session.add_slide_turn(
            title="Main Content",
            content="Details here",
            notes="",
        )
        session.add_message("assistant", "I created the slides")
        await session.save()

        # Load fresh
        loaded = await Session.load(session.id)

        assert len(loaded.turns) == 4
        assert loaded.get_slide_count() == 2

        slides = loaded.get_all_slides()
        assert slides[0][1].title == "Introduction"
        assert slides[0][1].content == "# Welcome\n\n- Point 1\n- Point 2"
        assert slides[0][1].notes == "Start with energy!"
        assert slides[1][1].title == "Main Content"
        assert slides[1][1].content == "Details here"
        assert slides[1][1].notes == ""

    async def test_slide_turn_role(self, temp_storage):
        """Slide turns should have role='slide'."""
        session = Session()
        session.add_slide_turn("Slide", "Content")
        await session.save()

        loaded = await Session.load(session.id)

        assert loaded.turns[0].role == "slide"

    async def test_mixed_content_save_load(self, temp_storage):
        """Mixed slides and messages should serialize correctly."""
        session = Session()
        session.add_message("user", "Hello")
        session.add_slide_turn("Slide 1", "Content 1")
        session.add_message("assistant", "Done")
        session.add_slide_turn("Slide 2", "Content 2")
        await session.save()

        loaded = await Session.load(session.id)

        assert len(loaded.turns) == 4
        assert loaded.turns[0].role == "user"
        assert loaded.turns[1].role == "slide"
        assert loaded.turns[2].role == "assistant"
        assert loaded.turns[3].role == "slide"

        assert isinstance(loaded.turns[0].content_block, TextBlock)
        assert isinstance(loaded.turns[1].content_block, SlideBlock)
        assert isinstance(loaded.turns[2].content_block, TextBlock)
        assert isinstance(loaded.turns[3].content_block, SlideBlock)


class TestSlideContextMode:
    """Tests for slide context modes."""

    def test_slide_default_context_mode(self):
        """Slides should default to COMPRESS context mode."""
        from models import ContextMode

        session = Session()
        turn = session.add_slide_turn("Title", "Content")

        # Compare by value to avoid module reloading identity issues
        assert turn.context_mode.value == ContextMode.COMPRESS.value

    def test_slide_context_mode_can_be_changed(self):
        """Slide context mode can be changed like other turns."""
        from models import ContextMode

        session = Session()
        session.add_slide_turn("Title", "Content")

        session.turns[0].context_mode = ContextMode.DROP
        # Compare by value to avoid module reloading identity issues
        assert session.turns[0].context_mode.value == ContextMode.DROP.value


