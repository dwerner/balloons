"""Tests for session review tools."""

import pytest
import uuid
from datetime import datetime
from pathlib import Path

from core.tools import REVIEW_TOOLS, REVIEW_TOOL_NAMES, get_tools_for_request
from core.tool_executor import execute_save_review


class TestReviewTools:
    """Tests for review tool definitions."""

    def test_review_tool_names(self):
        """Review tool names set contains save_review."""
        assert "save_review" in REVIEW_TOOL_NAMES

    def test_review_tools_definition(self):
        """Review tools list has save_review with correct structure."""
        assert len(REVIEW_TOOLS) == 1
        tool = REVIEW_TOOLS[0]
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "save_review"

    def test_get_tools_includes_review_when_enabled(self):
        """get_tools_for_request includes review tools when flag is True."""
        tools = get_tools_for_request(include_review_tools=True)
        tool_names = [t["function"]["name"] for t in tools]
        assert "save_review" in tool_names

    def test_get_tools_excludes_review_by_default(self):
        """get_tools_for_request excludes review tools by default."""
        tools = get_tools_for_request()
        tool_names = [t["function"]["name"] for t in tools]
        assert "save_review" not in tool_names


class TestSaveReviewTool:
    """Tests for save_review tool execution."""

    @pytest.fixture
    def mock_session(self, tmp_path):
        """Create a mock session for testing."""
        from session import Session
        from models import TextBlock

        session = Session()
        session.id = str(uuid.uuid4())
        session.backend_name = "test-backend"
        session.add_message("user", "Test message", content_blocks=[TextBlock(text="Test message")])
        return session

    @pytest.fixture
    def valid_args(self):
        """Valid arguments for save_review tool."""
        return {
            "session_id": str(uuid.uuid4()),
            "model_under_review": "claude-sonnet-4",
            "scores": {
                "correctness": 4,
                "efficiency": 3,
                "instruction_following": 5,
                "recovery": 4,
                "autonomy": 3,
                "judgment": 4,
                "communication": 5,
            },
            "task_category": "feature",
            "task_description": "Implemented a session review system",
            "user_summary": "Great session overall, minor issues with efficiency",
            "llm_commentary": "The session showed good code quality with room for optimization",
        }

    @pytest.mark.asyncio
    async def test_save_review_missing_session_id(self, mock_session):
        """save_review fails without session_id."""
        args = {"model_under_review": "test"}
        result, is_error = await execute_save_review(args, mock_session)
        assert is_error
        assert "session_id" in result.lower()

    @pytest.mark.asyncio
    async def test_save_review_missing_model(self, mock_session):
        """save_review fails without model_under_review."""
        args = {"session_id": str(uuid.uuid4())}
        result, is_error = await execute_save_review(args, mock_session)
        assert is_error
        assert "model_under_review" in result.lower()

    @pytest.mark.asyncio
    async def test_save_review_missing_scores(self, mock_session, valid_args):
        """save_review fails without required scores."""
        del valid_args["scores"]["correctness"]
        result, is_error = await execute_save_review(valid_args, mock_session)
        assert is_error
        assert "correctness" in result.lower()

    @pytest.mark.asyncio
    async def test_save_review_invalid_score_value(self, mock_session, valid_args):
        """save_review fails with invalid score value."""
        valid_args["scores"]["correctness"] = 10  # Invalid: must be 0-5
        result, is_error = await execute_save_review(valid_args, mock_session)
        assert is_error
        assert "0-5" in result or "correctness" in result.lower()

    @pytest.mark.asyncio
    async def test_save_review_invalid_category(self, mock_session, valid_args):
        """save_review fails with invalid task category."""
        valid_args["task_category"] = "invalid_category"
        result, is_error = await execute_save_review(valid_args, mock_session)
        assert is_error
        assert "task_category" in result.lower()

    @pytest.mark.asyncio
    async def test_save_review_success(self, mock_session, valid_args, tmp_path, monkeypatch):
        """save_review succeeds with valid arguments."""
        # Redirect home directory to tmp_path for file-based storage
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        # Mock Session.load to avoid needing real storage
        async def mock_load(session_id):
            return None  # Session doesn't exist, but that's ok

        from session import Session
        monkeypatch.setattr(Session, "load", staticmethod(mock_load))

        reviews_dir = tmp_path / ".balloons" / "reviews"

        result, is_error = await execute_save_review(valid_args, mock_session)
        assert not is_error, f"Expected success but got error: {result}"
        assert "saved successfully" in result.lower()

        # Verify file was created
        saved_files = list(reviews_dir.glob("*.json"))
        assert len(saved_files) == 1
