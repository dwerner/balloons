"""Tests for typed chess events."""

import pytest
from dataclasses import asdict

from plugins.events import DomainEvent, payload_to_dict, RawPayload
from plugins.chess.events import (
    ChessGameStartedPayload,
    ChessMovePayload,
    ChessGameOverPayload,
    ChessStateSyncPayload,
)


class TestChessPayloads:
    """Test typed chess event payloads."""

    def test_game_started_payload(self):
        """Test ChessGameStartedPayload serialization."""
        payload = ChessGameStartedPayload(
            fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            legal_moves=["e2e4", "d2d4", "g1f3"],
        )
        d = asdict(payload)
        assert d["fen"].startswith("rnbqkbnr")
        assert "e2e4" in d["legal_moves"]

    def test_move_payload(self):
        """Test ChessMovePayload serialization."""
        payload = ChessMovePayload(
            move="e2e4",
            fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
            legal_moves=["e7e5", "e7e6"],
        )
        d = asdict(payload)
        assert d["move"] == "e2e4"
        assert "e7e5" in d["legal_moves"]

    def test_game_over_payload(self):
        """Test ChessGameOverPayload serialization."""
        payload = ChessGameOverPayload(
            result="1-0",
            reason="checkmate",
        )
        d = asdict(payload)
        assert d["result"] == "1-0"
        assert d["reason"] == "checkmate"

    def test_state_sync_payload(self):
        """Test ChessStateSyncPayload serialization."""
        payload = ChessStateSyncPayload(
            fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            legal_moves=["e2e4"],
            game_over=False,
            result=None,
        )
        d = asdict(payload)
        assert d["game_over"] is False
        assert d["result"] is None


class TestDomainEvent:
    """Test DomainEvent with typed payloads."""

    def test_event_with_typed_payload(self):
        """Test event creation with typed payload."""
        payload = ChessGameStartedPayload(
            fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            legal_moves=["e2e4"],
        )
        event = DomainEvent(
            type="chess_game_started",
            source_domain="chess",
            payload=payload,
            target_session="session-123",
        )

        d = event.to_dict()
        assert d["type"] == "chess_game_started"
        assert d["sourceDomain"] == "chess"
        assert d["payload"]["fen"].startswith("rnbqkbnr")
        assert d["targetSession"] == "session-123"

    def test_event_with_raw_payload(self):
        """Test backwards compatibility with RawPayload."""
        event = DomainEvent(
            type="custom_event",
            source_domain="test",
            payload=RawPayload(data={"key": "value"}),
        )

        d = event.to_dict()
        assert d["payload"] == {"key": "value"}

    def test_event_with_dict_payload(self):
        """Test backwards compatibility with dict payload."""
        event = DomainEvent(
            type="custom_event",
            source_domain="test",
            payload={"key": "value"},
        )

        d = event.to_dict()
        assert d["payload"] == {"key": "value"}

    def test_get_payload_dict(self):
        """Test get_payload_dict helper."""
        payload = ChessMovePayload(
            move="e2e4",
            fen="test",
            legal_moves=[],
        )
        event = DomainEvent(
            type="test",
            source_domain="test",
            payload=payload,
        )

        pd = event.get_payload_dict()
        assert pd["move"] == "e2e4"


class TestPayloadToDict:
    """Test payload_to_dict conversion function."""

    def test_dict_passthrough(self):
        """Test that dicts pass through unchanged."""
        d = {"key": "value"}
        assert payload_to_dict(d) == d

    def test_dataclass_conversion(self):
        """Test dataclass to dict conversion."""
        payload = ChessGameOverPayload(result="0-1", reason="resignation")
        d = payload_to_dict(payload)
        assert d["result"] == "0-1"
        assert d["reason"] == "resignation"

    def test_raw_payload_extraction(self):
        """Test RawPayload data extraction."""
        raw = RawPayload(data={"nested": {"data": 123}})
        d = payload_to_dict(raw)
        assert d["nested"]["data"] == 123

    def test_snake_to_camel_conversion(self):
        """Test snake_case keys are converted to camelCase."""
        payload = ChessStateSyncPayload(
            fen="test",
            legal_moves=["e2e4"],
            game_over=True,
            result="1-0",
        )
        d = payload_to_dict(payload)
        # Keys should be camelCase for JavaScript consumption
        assert "legalMoves" in d
        assert "gameOver" in d
        assert d["legalMoves"] == ["e2e4"]
        assert d["gameOver"] is True
        # Simple keys stay the same
        assert d["fen"] == "test"
        assert d["result"] == "1-0"

    def test_camel_case_disabled(self):
        """Test snake_case preserved when camel_case=False."""
        payload = ChessStateSyncPayload(
            fen="test",
            legal_moves=["e2e4"],
            game_over=False,
            result=None,
        )
        d = payload_to_dict(payload, camel_case=False)
        # Keys should remain snake_case
        assert "legal_moves" in d
        assert "game_over" in d
        assert "legalMoves" not in d
