"""Chess domain plugin.

Provides chess playing capabilities to Balloons sessions.
"""

from typing import Any, TYPE_CHECKING

from ..base import DomainEvent, DecoratedStatefulDomain, ToolResult
from ..decorators import llm_callable, Param
from ..storage import JsonFileStorage
from .engine import ChessEngine, Color
from .events import (
    ChessGameStartedPayload,
    ChessMovePayload,
    ChessGameOverPayload,
    ChessStateSyncPayload,
)

if TYPE_CHECKING:
    from session import Session


# In-memory cache for active games (fast access)
_session_games: dict[str, ChessEngine] = {}

# Persistent storage for game state
_storage: JsonFileStorage | None = None


def _get_storage() -> JsonFileStorage:
    """Get the persistent storage instance."""
    global _storage
    if _storage is None:
        _storage = JsonFileStorage("chess")
    return _storage


class ChessDomain(DecoratedStatefulDomain):
    """Chess domain providing a complete chess playing experience.

    Tools:
        - chess_new_game: Start a new game
        - chess_move: Make a move
        - chess_show: Show the current board
        - chess_legal_moves: List legal moves
        - chess_resign: Resign the game
        - chess_set_position: Set position from FEN

    Events emitted:
        - chess_game_started: New game started
        - chess_move_made: A move was made
        - chess_game_over: Game ended (checkmate, stalemate, draw, resignation)
    """

    @property
    def id(self) -> str:
        return "chess"

    @property
    def name(self) -> str:
        return "Chess"

    @property
    def version(self) -> str:
        return "0.1.0"

    def get_prompt(self) -> str:
        """Load prompt from prompt.md file."""
        import os
        prompt_path = os.path.join(os.path.dirname(__file__), "prompt.md")
        try:
            with open(prompt_path, "r") as f:
                return f.read()
        except FileNotFoundError:
            # Fallback if file not found
            return """## Chess Domain

You can play chess using the chess_* tools. The board uses standard algebraic notation.
Use chess_new_game to start, chess_move to play, chess_show to see the board."""

    def get_ui_config(self) -> dict | None:
        """Return UI configuration for the chess domain.

        Registers the ChessBoard and ChessGame components that can be
        rendered in the Balloons UI.
        """
        return {
            "components": [
                {
                    "name": "ChessBoard",
                    "path": "plugins/chess/ui/ChessBoard.tsx",
                    "description": "Interactive chess board component",
                },
                {
                    "name": "ChessGame",
                    "path": "plugins/chess/ui/ChessGame.tsx",
                    "description": "Full chess game UI with controls",
                },
            ],
            "tabs": [
                {
                    "id": "chess",
                    "label": "Chess",
                    "icon": "♟",
                    "component": "ChessGame",
                },
            ],
        }

    # --- LLM-callable tools ---

    @llm_callable(description="Start a new chess game. Resets the board to the starting position.")
    async def chess_new_game(self, session: "Session" = None) -> ToolResult:
        """Start a new chess game."""
        engine = ChessEngine()
        _session_games[session.id] = engine

        board = engine.render_board()
        result = f"New chess game started!\n\n{board}\n\nWhite to move. Use chess_move with UCI notation (e.g., 'e2e4')."

        # Get legal moves in UCI format for the UI
        legal_moves = [m.to_uci() for m in engine.get_legal_moves()]

        event = DomainEvent(
            type="chess_game_started",
            source_domain=self.id,
            payload=ChessGameStartedPayload(
                fen=engine.get_fen(),
                legal_moves=legal_moves,
            ),
            target_session=session.id,
        )

        return ToolResult(result, events=[event])

    @llm_callable(
        description="""Make a chess move. Use UCI notation (e.g., 'e2e4', 'g1f3', 'e7e8q' for promotion).

Examples:
- 'e2e4' - Move pawn from e2 to e4
- 'g1f3' - Move knight from g1 to f3
- 'e1g1' - Castle kingside (move king from e1 to g1)
- 'e7e8q' - Promote pawn to queen""",
        params={
            "move": Param(str, "Move in UCI notation (e.g., 'e2e4', 'e7e8q')"),
        }
    )
    async def chess_move(self, move: str, session: "Session" = None) -> ToolResult:
        """Make a chess move."""
        engine = _session_games.get(session.id)
        if engine is None:
            return ToolResult(
                "No game in progress. Use chess_new_game to start a game.",
                is_error=True,
            )

        move_str = move.strip()
        if not move_str:
            return ToolResult("Move is required", is_error=True)

        # Check if game is already over
        result = engine.get_game_result()
        if result:
            return ToolResult(
                f"Game is already over: {result}. Use chess_new_game to start a new game.",
                is_error=True,
            )

        # Try to make the move
        result = engine.make_move(move_str)
        # Handle both old (str | None) and new (tuple) return formats
        if isinstance(result, tuple):
            error, captured = result
        else:
            error = result
            captured = None
        if error:
            return ToolResult(f"Invalid move: {error}", is_error=True)

        # Build response
        board = engine.render_board()
        events = []

        # Get legal moves for the next turn
        legal_moves = [m.to_uci() for m in engine.get_legal_moves()]

        # Emit move event
        events.append(DomainEvent(
            type="chess_move_made",
            source_domain=self.id,
            payload=ChessMovePayload(
                move=move_str,
                fen=engine.get_fen(),
                legal_moves=legal_moves,
                captured=captured,
            ),
            target_session=session.id,
        ))

        # Check for game end
        game_result = engine.get_game_result()
        if game_result:
            if engine.is_checkmate():
                winner = "White" if game_result == "1-0" else "Black"
                status = f"Checkmate! {winner} wins."
            else:
                is_draw, draw_reason = engine.is_draw()
                status = f"Draw by {draw_reason}." if draw_reason else "Draw."

            events.append(DomainEvent(
                type="chess_game_over",
                source_domain=self.id,
                payload=ChessGameOverPayload(
                    result=game_result,
                    reason="checkmate" if engine.is_checkmate() else draw_reason or "unknown",
                ),
                target_session=session.id,
            ))

            return ToolResult(
                f"Move: {move_str}\n\n{board}\n\n{status}",
                events=events,
            )

        # Game continues
        turn = "White" if engine.turn == Color.WHITE else "Black"
        check_str = " CHECK!" if engine.is_in_check() else ""

        return ToolResult(
            f"Move: {move_str}\n\n{board}\n\n{turn} to move.{check_str}",
            events=events,
        )

    @llm_callable(description="Show the current chess board position and game status.")
    async def chess_show(self, session: "Session" = None) -> ToolResult:
        """Show the current board."""
        engine = _session_games.get(session.id)
        if engine is None:
            return ToolResult(
                "No game in progress. Use chess_new_game to start a game.",
                is_error=True,
            )

        board = engine.render_board()
        fen = engine.get_fen()
        legal_moves = [m.to_uci() for m in engine.get_legal_moves()]

        result = engine.get_game_result()
        if result:
            status = f"Game over: {result}"
        else:
            turn = "White" if engine.turn == Color.WHITE else "Black"
            check_str = " (CHECK!)" if engine.is_in_check() else ""
            status = f"{turn} to move{check_str}"

        # Emit state event so UI can sync
        event = DomainEvent(
            type="chess_state_sync",
            source_domain=self.id,
            payload=ChessStateSyncPayload(
                fen=fen,
                legal_moves=legal_moves,
                game_over=result is not None,
                result=result,
            ),
            target_session=session.id,
        )

        return ToolResult(f"{board}\n\nFEN: {fen}\n{status}", events=[event])

    @llm_callable(
        description="List all legal moves in the current position.",
        params={
            "from_square": Param(str, "Optional: Only show moves from this square (e.g., 'e2')", required=False),
        }
    )
    async def chess_legal_moves(self, from_square: str | None = None, session: "Session" = None) -> ToolResult:
        """List legal moves."""
        engine = _session_games.get(session.id)
        if engine is None:
            return ToolResult(
                "No game in progress. Use chess_new_game to start a game.",
                is_error=True,
            )

        from_square_str = (from_square or "").strip()
        from_sq = None

        if from_square_str:
            from .engine import Square
            try:
                from_sq = Square.from_str(from_square_str)
            except ValueError:
                return ToolResult(f"Invalid square: {from_square_str}", is_error=True)

        moves = engine.get_legal_moves(from_sq)

        if not moves:
            if from_sq:
                return ToolResult(f"No legal moves from {from_square_str}")
            else:
                return ToolResult("No legal moves available")

        move_strs = [str(m) for m in moves]
        if from_sq:
            return ToolResult(f"Legal moves from {from_square_str}: {', '.join(move_strs)}")
        else:
            return ToolResult(f"Legal moves ({len(moves)}): {', '.join(move_strs)}")

    @llm_callable(description="Resign the current game. The opponent wins.")
    async def chess_resign(self, session: "Session" = None) -> ToolResult:
        """Resign the current game."""
        engine = _session_games.get(session.id)
        if engine is None:
            return ToolResult(
                "No game in progress. Use chess_new_game to start a game.",
                is_error=True,
            )

        result = engine.get_game_result()
        if result:
            return ToolResult(
                f"Game is already over: {result}",
                is_error=True,
            )

        # The side to move resigns
        winner = "Black" if engine.turn == Color.WHITE else "White"
        loser = "White" if engine.turn == Color.WHITE else "Black"
        game_result = "0-1" if engine.turn == Color.WHITE else "1-0"

        event = DomainEvent(
            type="chess_game_over",
            source_domain=self.id,
            payload=ChessGameOverPayload(
                result=game_result,
                reason="resignation",
            ),
            target_session=session.id,
        )

        return ToolResult(
            f"{loser} resigns. {winner} wins!",
            events=[event],
        )

    @llm_callable(
        description="Set the board to a specific position using FEN notation.",
        params={
            "fen": Param(str, "Position in FEN notation"),
        }
    )
    async def chess_set_position(self, fen: str, session: "Session" = None) -> ToolResult:
        """Set position from FEN."""
        fen = fen.strip()
        if not fen:
            return ToolResult("FEN is required", is_error=True)

        try:
            engine = ChessEngine()
            engine.set_position(fen)
            _session_games[session.id] = engine

            board = engine.render_board()
            turn = "White" if engine.turn == Color.WHITE else "Black"
            check_str = " (CHECK!)" if engine.is_in_check() else ""

            return ToolResult(
                f"Position set.\n\n{board}\n\n{turn} to move{check_str}"
            )
        except ValueError as e:
            return ToolResult(f"Invalid FEN: {e}", is_error=True)

    # --- StatefulDomain methods ---

    async def get_state(self, session: "Session") -> dict[str, Any] | None:
        """Return current chess game state.

        Called when a client requests a state sync (e.g., on reconnection).
        The service layer wraps this in a DomainEvent for WebSocket broadcast.
        """
        engine = _session_games.get(session.id)
        if engine is None:
            return None

        result = engine.get_game_result()

        return {
            "fen": engine.get_fen(),
            "legal_moves": [m.to_uci() for m in engine.get_legal_moves()],
            "game_over": result is not None,
            "result": result,
        }

    async def save_state(self, session: "Session") -> dict[str, Any]:
        """Save chess game state to memory and persistent storage."""
        engine = _session_games.get(session.id)
        if engine is None:
            return {}

        state = {
            "fen": engine.get_fen(),
            "move_history": engine.state.move_history,
        }

        # Also persist to JSON file
        await _get_storage().save(session.id, state)

        return state

    async def load_state(self, session: "Session", state: dict[str, Any]) -> None:
        """Load chess game state from memory or persistent storage."""
        # First try the provided state (from session)
        if not state:
            # Try loading from persistent storage
            state = await _get_storage().load(session.id)

        if not state:
            return

        fen = state.get("fen")
        if not fen:
            return

        engine = ChessEngine()
        engine.set_position(fen)
        engine.state.move_history = state.get("move_history", [])
        _session_games[session.id] = engine

    async def clear_state(self, session: "Session") -> None:
        """Clear chess game state from memory and persistent storage."""
        if session.id in _session_games:
            del _session_games[session.id]
        await _get_storage().delete(session.id)


# Factory function is defined in __init__.py to avoid circular imports
