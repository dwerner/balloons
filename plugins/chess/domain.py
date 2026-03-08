"""Chess domain plugin.

Provides chess playing capabilities to Balloons sessions.
"""

from typing import Any, TYPE_CHECKING

from ..base import Domain, DomainEvent, StatefulDomain, ToolDef, ToolResult
from ..storage import JsonFileStorage, InMemoryStorage, CompositeStorage
from .engine import ChessEngine, Color

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


class ChessDomain(StatefulDomain):
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

    def get_tools(self) -> list[ToolDef]:
        return [
            ToolDef(
                name="chess_new_game",
                description="Start a new chess game. Resets the board to the starting position.",
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
            ToolDef(
                name="chess_move",
                description="""Make a chess move. Use UCI notation (e.g., 'e2e4', 'g1f3', 'e7e8q' for promotion).

Examples:
- 'e2e4' - Move pawn from e2 to e4
- 'g1f3' - Move knight from g1 to f3
- 'e1g1' - Castle kingside (move king from e1 to g1)
- 'e7e8q' - Promote pawn to queen""",
                parameters={
                    "type": "object",
                    "properties": {
                        "move": {
                            "type": "string",
                            "description": "Move in UCI notation (e.g., 'e2e4', 'e7e8q')",
                        },
                    },
                    "required": ["move"],
                },
            ),
            ToolDef(
                name="chess_show",
                description="Show the current chess board position and game status.",
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
            ToolDef(
                name="chess_legal_moves",
                description="List all legal moves in the current position.",
                parameters={
                    "type": "object",
                    "properties": {
                        "from_square": {
                            "type": "string",
                            "description": "Optional: Only show moves from this square (e.g., 'e2')",
                        },
                    },
                    "required": [],
                },
            ),
            ToolDef(
                name="chess_resign",
                description="Resign the current game. The opponent wins.",
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
            ToolDef(
                name="chess_set_position",
                description="Set the board to a specific position using FEN notation.",
                parameters={
                    "type": "object",
                    "properties": {
                        "fen": {
                            "type": "string",
                            "description": "Position in FEN notation",
                        },
                    },
                    "required": ["fen"],
                },
            ),
        ]

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

    def get_context(self, session: "Session") -> str | None:
        """Return current game state if a game is in progress."""
        engine = _session_games.get(session.id)
        if engine is None:
            return None

        result = engine.get_game_result()
        if result:
            return f"[Chess game over: {result}]"

        turn = "White" if engine.turn == Color.WHITE else "Black"
        check_str = " (CHECK!)" if engine.is_in_check() else ""
        return f"[Chess: {turn} to move{check_str}]"

    async def handle_tool(
        self,
        tool_name: str,
        params: dict[str, Any],
        session: "Session",
    ) -> ToolResult:
        """Execute a chess tool."""

        if tool_name == "chess_new_game":
            return await self._handle_new_game(session)
        elif tool_name == "chess_move":
            return await self._handle_move(params, session)
        elif tool_name == "chess_show":
            return await self._handle_show(session)
        elif tool_name == "chess_legal_moves":
            return await self._handle_legal_moves(params, session)
        elif tool_name == "chess_resign":
            return await self._handle_resign(session)
        elif tool_name == "chess_set_position":
            return await self._handle_set_position(params, session)
        else:
            return ToolResult(f"Unknown chess tool: {tool_name}", is_error=True)

    async def _handle_new_game(self, session: "Session") -> ToolResult:
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
            payload={
                "fen": engine.get_fen(),
                "legalMoves": legal_moves,
            },
            target_session=session.id,
        )

        return ToolResult(result, events=[event])

    async def _handle_move(self, params: dict[str, Any], session: "Session") -> ToolResult:
        """Make a chess move."""
        engine = _session_games.get(session.id)
        if engine is None:
            return ToolResult(
                "No game in progress. Use chess_new_game to start a game.",
                is_error=True,
            )

        move_str = params.get("move", "").strip()
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
        error = engine.make_move(move_str)
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
            payload={
                "move": move_str,
                "fen": engine.get_fen(),
                "legalMoves": legal_moves,
            },
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
                payload={
                    "result": game_result,
                    "reason": "checkmate" if engine.is_checkmate() else draw_reason or "unknown",
                },
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

    async def _handle_show(self, session: "Session") -> ToolResult:
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
            payload={
                "fen": fen,
                "legalMoves": legal_moves,
                "gameOver": result is not None,
                "result": result,
            },
            target_session=session.id,
        )

        return ToolResult(f"{board}\n\nFEN: {fen}\n{status}", events=[event])

    async def _handle_legal_moves(self, params: dict[str, Any], session: "Session") -> ToolResult:
        """List legal moves."""
        engine = _session_games.get(session.id)
        if engine is None:
            return ToolResult(
                "No game in progress. Use chess_new_game to start a game.",
                is_error=True,
            )

        from_square_str = params.get("from_square", "").strip()
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

    async def _handle_resign(self, session: "Session") -> ToolResult:
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
            payload={
                "result": game_result,
                "reason": "resignation",
            },
            target_session=session.id,
        )

        return ToolResult(
            f"{loser} resigns. {winner} wins!",
            events=[event],
        )

    async def _handle_set_position(self, params: dict[str, Any], session: "Session") -> ToolResult:
        """Set position from FEN."""
        fen = params.get("fen", "").strip()
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

    # StatefulDomain methods

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
