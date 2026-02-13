"""Tests for MarkdownViewerModal widget."""

import pytest
import tempfile
from pathlib import Path

from widgets.markdown_viewer import MarkdownViewerModal


class TestMarkdownViewerModal:
    """Tests for the MarkdownViewerModal widget."""

    def test_modal_creation_with_content(self):
        """Modal should accept content directly."""
        content = "# Test Header\n\nSome **bold** text."
        modal = MarkdownViewerModal(content=content, title="Test")

        assert modal._content == content
        assert modal._title == "Test"
        assert modal._file_path is None

    def test_modal_creation_with_file_path(self):
        """Modal should load content from file path."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write("# From File\n\nLoaded from disk.")
            temp_path = Path(f.name)

        try:
            modal = MarkdownViewerModal(file_path=temp_path)

            assert modal._content == "# From File\n\nLoaded from disk."
            assert modal._file_path == temp_path
        finally:
            temp_path.unlink()

    def test_modal_creation_with_string_path(self):
        """Modal should accept file path as string."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write("# String Path")
            temp_path = f.name

        try:
            modal = MarkdownViewerModal(file_path=temp_path)

            assert modal._content == "# String Path"
            assert modal._file_path == Path(temp_path)
        finally:
            Path(temp_path).unlink()

    def test_modal_content_takes_priority_over_file(self):
        """Content parameter should take priority over file_path."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write("# From File")
            temp_path = Path(f.name)

        try:
            modal = MarkdownViewerModal(
                content="# Direct Content",
                file_path=temp_path,
            )

            # Content should be the direct content, not file contents
            assert modal._content == "# Direct Content"
        finally:
            temp_path.unlink()

    def test_modal_default_content_when_empty(self):
        """Modal should show placeholder when no content provided."""
        modal = MarkdownViewerModal()

        assert modal._content == "*No content to display*"

    def test_modal_default_title(self):
        """Modal should have default title."""
        modal = MarkdownViewerModal(content="test")

        assert modal._title == "Markdown Viewer"

    def test_modal_bindings(self):
        """Modal should have escape and q bindings to close."""
        modal = MarkdownViewerModal(content="test")

        bindings = {b[0] for b in modal.BINDINGS}
        assert "escape" in bindings
        assert "q" in bindings


class TestMarkdownViewerModalIntegration:
    """Integration tests that require the Textual test framework."""

    @pytest.mark.skip(reason="Requires Textual test framework for widget mounting")
    async def test_modal_displays_markdown(self):
        """Modal should render markdown content correctly."""
        # This would need async_pilot from textual.testing
        pass

    @pytest.mark.skip(reason="Requires Textual test framework for widget mounting")
    async def test_modal_close_button(self):
        """Modal should close when Close button is pressed."""
        pass

    @pytest.mark.skip(reason="Requires Textual test framework for widget mounting")
    async def test_modal_escape_key(self):
        """Modal should close when Escape is pressed."""
        pass
