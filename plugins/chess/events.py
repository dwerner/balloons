"""Typed event payloads for the Chess domain.

Defines structured event data for type-safe event handling.
"""

from dataclasses import dataclass


@dataclass
class ChessGameStartedPayload:
    """Payload for chess_game_started event.

    Emitted when a new game is started via chess_new_game.
    """
    fen: str
    legal_moves: list[str]  # UCI format moves


@dataclass
class ChessMovePayload:
    """Payload for chess_move_made event.

    Emitted when a move is successfully made via chess_move.
    """
    move: str  # UCI format (e.g., "e2e4")
    fen: str  # Position after the move
    legal_moves: list[str]  # Available moves for the next player
    captured: str | None = None  # Captured piece symbol (e.g., "P", "n") or None


@dataclass
class ChessGameOverPayload:
    """Payload for chess_game_over event.

    Emitted when the game ends (checkmate, stalemate, draw, resignation).
    """
    result: str  # "1-0" (white wins), "0-1" (black wins), "1/2-1/2" (draw)
    reason: str  # "checkmate", "stalemate", "resignation", "insufficient_material", etc.


@dataclass
class ChessStateSyncPayload:
    """Payload for chess_state_sync event.

    Emitted when the UI requests current state (e.g., on reconnection)
    or when chess_show is called.
    """
    fen: str
    legal_moves: list[str]
    game_over: bool
    result: str | None  # Only set if game_over is True


# Map event types to their payload classes for validation/parsing
EVENT_PAYLOADS = {
    "chess_game_started": ChessGameStartedPayload,
    "chess_move_made": ChessMovePayload,
    "chess_game_over": ChessGameOverPayload,
    "chess_state_sync": ChessStateSyncPayload,
}
