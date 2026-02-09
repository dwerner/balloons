"""Tests for the EntityPane widget."""

import pytest
from widgets.entity_pane import EntityPane
from core.async_storage import is_rust_storage_available


class TestEntityPane:
    """Test EntityPane widget creation and basic functionality."""

    def test_entity_pane_creation(self):
        """Test that EntityPane can be created."""
        pane = EntityPane()
        assert pane is not None

    def test_entity_pane_has_show_hide_methods(self):
        """Test that EntityPane has show/hide methods."""
        pane = EntityPane()
        assert hasattr(pane, 'show')
        assert hasattr(pane, 'hide')
        assert callable(pane.show)
        assert callable(pane.hide)

    def test_content_preview_text(self):
        """Test content preview extraction for text blocks."""
        pane = EntityPane()

        # Short text
        preview = pane._get_content_preview({"type": "text", "text": "Hello world"})
        assert preview == "Hello world"

        # Long text gets truncated
        long_text = "A" * 100
        preview = pane._get_content_preview({"type": "text", "text": long_text})
        assert len(preview) <= 43  # 40 chars + "..."
        assert preview.endswith("...")

        # Multiline uses first line
        preview = pane._get_content_preview({"type": "text", "text": "Line 1\nLine 2"})
        assert preview == "Line 1"

    def test_content_preview_tool_use(self):
        """Test content preview extraction for tool use blocks."""
        pane = EntityPane()

        preview = pane._get_content_preview({
            "type": "tool_use",
            "name": "read_file",
            "id": "123",
            "input": {"path": "/some/file"}
        })
        assert preview == "tool: read_file"

    def test_content_preview_tool_result(self):
        """Test content preview extraction for tool result blocks."""
        pane = EntityPane()

        # Success result
        preview = pane._get_content_preview({
            "type": "tool_result",
            "tool_use_id": "123",
            "content": "Some output",
            "is_error": False
        })
        assert preview == "result"

        # Error result
        preview = pane._get_content_preview({
            "type": "tool_result",
            "tool_use_id": "123",
            "content": "Error message",
            "is_error": True
        })
        assert preview == "error result"

    def test_content_preview_slide(self):
        """Test content preview extraction for slide blocks."""
        pane = EntityPane()

        preview = pane._get_content_preview({
            "type": "slide",
            "title": "My Slide Title",
            "content": "Some content"
        })
        assert preview == "slide: My Slide Title"

        # Empty title
        preview = pane._get_content_preview({
            "type": "slide",
            "title": "",
            "content": "Some content"
        })
        assert preview == "slide"

    def test_content_preview_fork_merge(self):
        """Test content preview extraction for fork/merge blocks."""
        pane = EntityPane()

        preview = pane._get_content_preview({
            "type": "fork",
            "fork_name": "feature-branch"
        })
        assert preview == "fork: feature-branch"

        preview = pane._get_content_preview({
            "type": "merge",
            "fork_name": "feature-branch"
        })
        assert preview == "merge: feature-branch"

    def test_content_preview_unknown(self):
        """Test content preview for unknown block types."""
        pane = EntityPane()

        preview = pane._get_content_preview({"type": "unknown_type"})
        assert preview == ""

    def test_rust_storage_availability_check(self):
        """Test that we can check Rust storage availability."""
        # Just check that the function exists and returns a boolean
        result = is_rust_storage_available()
        assert isinstance(result, bool)
