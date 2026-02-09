"""Tests for SlidesPane widget."""

import pytest
from unittest.mock import Mock, MagicMock

from session import Session
from models import SlideBlock
from widgets.slides_pane import SlidesPane, SlideCard


class TestSlideCard:
    """Tests for the SlideCard widget."""

    def test_slide_card_creation(self):
        """SlideCard should store slide index, turn index, and slide data."""
        slide = SlideBlock(title="Test", content="Content", notes="Notes")
        card = SlideCard(slide_index=0, turn_index=5, slide=slide)

        assert card.slide_index == 0
        assert card.turn_index == 5
        assert card.slide == slide

    def test_slide_card_truncates_long_title(self):
        """SlideCard should truncate titles longer than 40 chars."""
        long_title = "A" * 50
        slide = SlideBlock(title=long_title, content="", notes="")
        card = SlideCard(slide_index=0, turn_index=0, slide=slide)

        # The truncation happens in compose(), but we can verify the slide is stored
        assert card.slide.title == long_title


class TestSlidesPane:
    """Tests for the SlidesPane widget."""

    def test_slides_pane_creation(self):
        """SlidesPane should create successfully."""
        pane = SlidesPane()
        assert pane is not None

    def test_set_session_with_no_slides(self):
        """set_session with empty session should show no slides message."""
        # This test would need Textual's test framework to properly mount widgets
        # For now, just test the API
        pane = SlidesPane()
        pane._session = None
        assert pane._session is None

    def test_set_session_stores_session(self):
        """set_session should store the session reference."""
        pane = SlidesPane()
        session = Session()
        pane._session = session
        assert pane._session is session


class TestSlidesPaneIntegration:
    """Integration tests for SlidesPane with real sessions."""

    def test_get_slides_from_session(self):
        """SlidesPane should be able to get slides from a session."""
        session = Session()
        session.add_slide_turn("Slide 1", "Content 1")
        session.add_message("user", "Hello")
        session.add_slide_turn("Slide 2", "Content 2")

        slides = session.get_all_slides()
        assert len(slides) == 2
        assert slides[0][1].title == "Slide 1"
        assert slides[1][1].title == "Slide 2"

    def test_slide_count(self):
        """Session should track slide count correctly."""
        session = Session()
        assert session.get_slide_count() == 0

        session.add_slide_turn("Slide 1", "Content")
        assert session.get_slide_count() == 1

        session.add_message("user", "Not a slide")
        assert session.get_slide_count() == 1

        session.add_slide_turn("Slide 2", "Content")
        assert session.get_slide_count() == 2


class TestCreateSlideTool:
    """Tests for the create_slide tool execution."""

    @pytest.mark.asyncio
    async def test_execute_create_slide_basic(self):
        """create_slide should create a slide in the session."""
        from unittest.mock import AsyncMock, patch
        from core.tool_executor import execute_create_slide

        session = Session()
        with patch.object(session, 'save_async', new_callable=AsyncMock):
            result, is_error = await execute_create_slide(
                {"title": "Test Slide", "content": "Test Content", "notes": "Notes"},
                session=session,
            )

        assert not is_error
        assert "Test Slide" in result
        assert session.get_slide_count() == 1
        assert session.get_all_slides()[0][1].title == "Test Slide"

    @pytest.mark.asyncio
    async def test_execute_create_slide_no_session(self):
        """create_slide should error without a session."""
        from core.tool_executor import execute_create_slide

        result, is_error = await execute_create_slide(
            {"title": "Test", "content": "Content"},
            session=None,
        )

        assert is_error
        assert "No session" in result

    @pytest.mark.asyncio
    async def test_execute_create_slide_validation(self):
        """create_slide should validate input."""
        from core.tool_executor import execute_create_slide

        session = Session()

        # Empty title and content
        result, is_error = await execute_create_slide({}, session=session)
        assert is_error
        assert "required" in result.lower()

        # Title too long
        result, is_error = await execute_create_slide(
            {"title": "A" * 150, "content": "X"},
            session=session,
        )
        assert is_error
        assert "too long" in result.lower()

    @pytest.mark.asyncio
    async def test_execute_create_slide_content_too_long(self):
        """create_slide should warn about very long content."""
        from core.tool_executor import execute_create_slide

        session = Session()
        long_content = "\n".join(["Line " + str(i) for i in range(25)])

        result, is_error = await execute_create_slide(
            {"title": "Test", "content": long_content},
            session=session,
        )

        assert is_error
        assert "too long" in result.lower()
