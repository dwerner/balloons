"""Pure chess engine with full rules validation.

This module contains the core chess logic, independent of the domain system.
It handles:
- Board representation
- Move validation (including castling, en passant, promotion)
- Check/checkmate/stalemate detection
- Move history
- FEN/PGN parsing
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator


class PieceType(Enum):
    PAWN = "p"
    KNIGHT = "n"
    BISHOP = "b"
    ROOK = "r"
    QUEEN = "q"
    KING = "k"


class Color(Enum):
    WHITE = "w"
    BLACK = "b"

    def opposite(self) -> "Color":
        return Color.BLACK if self == Color.WHITE else Color.WHITE


@dataclass
class Piece:
    type: PieceType
    color: Color

    def __str__(self) -> str:
        char = self.type.value
        return char.upper() if self.color == Color.WHITE else char

    @classmethod
    def from_char(cls, char: str) -> "Piece":
        color = Color.WHITE if char.isupper() else Color.BLACK
        piece_type = PieceType(char.lower())
        return cls(type=piece_type, color=color)


@dataclass
class Square:
    """Chess square represented as file (a-h) and rank (1-8)."""

    file: int  # 0-7 (a-h)
    rank: int  # 0-7 (1-8)

    def __str__(self) -> str:
        return f"{chr(ord('a') + self.file)}{self.rank + 1}"

    @classmethod
    def from_str(cls, s: str) -> "Square":
        """Parse square from algebraic notation (e.g., 'e4')."""
        if len(s) != 2:
            raise ValueError(f"Invalid square: {s}")
        file = ord(s[0].lower()) - ord("a")
        rank = int(s[1]) - 1
        if not (0 <= file <= 7 and 0 <= rank <= 7):
            raise ValueError(f"Invalid square: {s}")
        return cls(file=file, rank=rank)

    def __hash__(self) -> int:
        return hash((self.file, self.rank))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Square):
            return False
        return self.file == other.file and self.rank == other.rank


@dataclass
class Move:
    """A chess move."""

    from_sq: Square
    to_sq: Square
    promotion: PieceType | None = None  # For pawn promotion

    def __str__(self) -> str:
        promo = self.promotion.value if self.promotion else ""
        return f"{self.from_sq}{self.to_sq}{promo}"

    def to_uci(self) -> str:
        """Return move in UCI notation (e.g., 'e2e4', 'e7e8q')."""
        return str(self)

    @classmethod
    def from_str(cls, s: str) -> "Move":
        """Parse move from UCI notation (e.g., 'e2e4', 'e7e8q')."""
        s = s.lower().strip()
        if len(s) < 4 or len(s) > 5:
            raise ValueError(f"Invalid move: {s}")

        from_sq = Square.from_str(s[0:2])
        to_sq = Square.from_str(s[2:4])
        promotion = None
        if len(s) == 5:
            promotion = PieceType(s[4])

        return cls(from_sq=from_sq, to_sq=to_sq, promotion=promotion)


@dataclass
class GameState:
    """Complete chess game state."""

    board: list[list[Piece | None]]  # 8x8 board, [rank][file]
    turn: Color = Color.WHITE
    castling_rights: dict[Color, dict[str, bool]] = field(default_factory=dict)
    en_passant_target: Square | None = None
    halfmove_clock: int = 0  # For 50-move rule
    fullmove_number: int = 1
    move_history: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.castling_rights:
            self.castling_rights = {
                Color.WHITE: {"K": True, "Q": True},
                Color.BLACK: {"K": True, "Q": True},
            }

    @classmethod
    def new_game(cls) -> "GameState":
        """Create a new game with standard starting position."""
        board = [[None] * 8 for _ in range(8)]

        # Set up pawns
        for file in range(8):
            board[1][file] = Piece(PieceType.PAWN, Color.WHITE)
            board[6][file] = Piece(PieceType.PAWN, Color.BLACK)

        # Set up pieces
        back_rank = [
            PieceType.ROOK,
            PieceType.KNIGHT,
            PieceType.BISHOP,
            PieceType.QUEEN,
            PieceType.KING,
            PieceType.BISHOP,
            PieceType.KNIGHT,
            PieceType.ROOK,
        ]
        for file, piece_type in enumerate(back_rank):
            board[0][file] = Piece(piece_type, Color.WHITE)
            board[7][file] = Piece(piece_type, Color.BLACK)

        return cls(board=board)

    @classmethod
    def from_fen(cls, fen: str) -> "GameState":
        """Parse a FEN string into a game state."""
        parts = fen.split()
        if len(parts) < 4:
            raise ValueError(f"Invalid FEN: {fen}")

        # Parse board
        board = [[None] * 8 for _ in range(8)]
        ranks = parts[0].split("/")
        if len(ranks) != 8:
            raise ValueError(f"Invalid FEN board: {parts[0]}")

        for rank_idx, rank_str in enumerate(reversed(ranks)):
            file_idx = 0
            for char in rank_str:
                if char.isdigit():
                    file_idx += int(char)
                else:
                    board[rank_idx][file_idx] = Piece.from_char(char)
                    file_idx += 1

        # Parse turn
        turn = Color.WHITE if parts[1] == "w" else Color.BLACK

        # Parse castling rights
        castling_rights = {
            Color.WHITE: {"K": "K" in parts[2], "Q": "Q" in parts[2]},
            Color.BLACK: {"K": "k" in parts[2], "Q": "q" in parts[2]},
        }

        # Parse en passant
        en_passant = None
        if parts[3] != "-":
            en_passant = Square.from_str(parts[3])

        # Parse clocks
        halfmove = int(parts[4]) if len(parts) > 4 else 0
        fullmove = int(parts[5]) if len(parts) > 5 else 1

        return cls(
            board=board,
            turn=turn,
            castling_rights=castling_rights,
            en_passant_target=en_passant,
            halfmove_clock=halfmove,
            fullmove_number=fullmove,
        )

    def to_fen(self) -> str:
        """Convert game state to FEN string."""
        # Board
        ranks = []
        for rank_idx in range(7, -1, -1):
            rank_str = ""
            empty_count = 0
            for file_idx in range(8):
                piece = self.board[rank_idx][file_idx]
                if piece is None:
                    empty_count += 1
                else:
                    if empty_count > 0:
                        rank_str += str(empty_count)
                        empty_count = 0
                    rank_str += str(piece)
            if empty_count > 0:
                rank_str += str(empty_count)
            ranks.append(rank_str)
        board_str = "/".join(ranks)

        # Turn
        turn_str = "w" if self.turn == Color.WHITE else "b"

        # Castling
        castling = ""
        if self.castling_rights[Color.WHITE]["K"]:
            castling += "K"
        if self.castling_rights[Color.WHITE]["Q"]:
            castling += "Q"
        if self.castling_rights[Color.BLACK]["K"]:
            castling += "k"
        if self.castling_rights[Color.BLACK]["Q"]:
            castling += "q"
        if not castling:
            castling = "-"

        # En passant
        ep_str = str(self.en_passant_target) if self.en_passant_target else "-"

        return f"{board_str} {turn_str} {castling} {ep_str} {self.halfmove_clock} {self.fullmove_number}"

    def get_piece(self, sq: Square) -> Piece | None:
        """Get piece at a square."""
        return self.board[sq.rank][sq.file]

    def set_piece(self, sq: Square, piece: Piece | None) -> None:
        """Set piece at a square."""
        self.board[sq.rank][sq.file] = piece

    def copy(self) -> "GameState":
        """Create a deep copy of the game state."""
        board_copy = [[p for p in rank] for rank in self.board]
        castling_copy = {
            color: dict(rights) for color, rights in self.castling_rights.items()
        }
        return GameState(
            board=board_copy,
            turn=self.turn,
            castling_rights=castling_copy,
            en_passant_target=self.en_passant_target,
            halfmove_clock=self.halfmove_clock,
            fullmove_number=self.fullmove_number,
            move_history=list(self.move_history),
        )


class ChessEngine:
    """Chess engine with full rules validation."""

    def __init__(self, state: GameState | None = None):
        self.state = state or GameState.new_game()

    @property
    def turn(self) -> Color:
        return self.state.turn

    def get_fen(self) -> str:
        return self.state.to_fen()

    def set_position(self, fen: str) -> None:
        """Set position from FEN string."""
        self.state = GameState.from_fen(fen)

    def new_game(self) -> None:
        """Start a new game."""
        self.state = GameState.new_game()

    def _iter_squares(self) -> Iterator[Square]:
        """Iterate over all squares."""
        for rank in range(8):
            for file in range(8):
                yield Square(file=file, rank=rank)

    def _find_king(self, color: Color) -> Square | None:
        """Find the king of the given color."""
        for sq in self._iter_squares():
            piece = self.state.get_piece(sq)
            if piece and piece.type == PieceType.KING and piece.color == color:
                return sq
        return None

    def _is_attacked(self, sq: Square, by_color: Color) -> bool:
        """Check if a square is attacked by the given color."""
        # Check for pawn attacks
        pawn_dir = -1 if by_color == Color.WHITE else 1
        for df in [-1, 1]:
            attack_sq = Square(sq.file + df, sq.rank + pawn_dir)
            if 0 <= attack_sq.file <= 7 and 0 <= attack_sq.rank <= 7:
                piece = self.state.get_piece(attack_sq)
                if piece and piece.type == PieceType.PAWN and piece.color == by_color:
                    return True

        # Check for knight attacks
        knight_moves = [
            (-2, -1), (-2, 1), (-1, -2), (-1, 2),
            (1, -2), (1, 2), (2, -1), (2, 1),
        ]
        for df, dr in knight_moves:
            attack_sq = Square(sq.file + df, sq.rank + dr)
            if 0 <= attack_sq.file <= 7 and 0 <= attack_sq.rank <= 7:
                piece = self.state.get_piece(attack_sq)
                if piece and piece.type == PieceType.KNIGHT and piece.color == by_color:
                    return True

        # Check for king attacks
        for df in [-1, 0, 1]:
            for dr in [-1, 0, 1]:
                if df == 0 and dr == 0:
                    continue
                attack_sq = Square(sq.file + df, sq.rank + dr)
                if 0 <= attack_sq.file <= 7 and 0 <= attack_sq.rank <= 7:
                    piece = self.state.get_piece(attack_sq)
                    if piece and piece.type == PieceType.KING and piece.color == by_color:
                        return True

        # Check for sliding piece attacks (bishop, rook, queen)
        directions = [
            (0, 1), (0, -1), (1, 0), (-1, 0),  # Rook directions
            (1, 1), (1, -1), (-1, 1), (-1, -1),  # Bishop directions
        ]
        for df, dr in directions:
            is_diagonal = df != 0 and dr != 0
            current_sq = Square(sq.file + df, sq.rank + dr)
            while 0 <= current_sq.file <= 7 and 0 <= current_sq.rank <= 7:
                piece = self.state.get_piece(current_sq)
                if piece:
                    if piece.color == by_color:
                        if piece.type == PieceType.QUEEN:
                            return True
                        if is_diagonal and piece.type == PieceType.BISHOP:
                            return True
                        if not is_diagonal and piece.type == PieceType.ROOK:
                            return True
                    break
                current_sq = Square(current_sq.file + df, current_sq.rank + dr)

        return False

    def is_in_check(self, color: Color | None = None) -> bool:
        """Check if the given color's king is in check."""
        if color is None:
            color = self.state.turn
        king_sq = self._find_king(color)
        if king_sq is None:
            return False
        return self._is_attacked(king_sq, color.opposite())

    def _is_legal_move(self, move: Move) -> bool:
        """Check if a move is legal (doesn't leave king in check)."""
        # Make the move on a copy
        old_state = self.state
        self.state = self.state.copy()

        self._apply_move_unchecked(move)

        # Check if the moving side's king is in check
        in_check = self.is_in_check(old_state.turn)

        # Restore state
        self.state = old_state

        return not in_check

    def _apply_move_unchecked(self, move: Move) -> None:
        """Apply a move without checking legality."""
        piece = self.state.get_piece(move.from_sq)
        if piece is None:
            return

        captured = self.state.get_piece(move.to_sq)

        # Handle en passant capture
        if piece.type == PieceType.PAWN and move.to_sq == self.state.en_passant_target:
            capture_rank = move.from_sq.rank
            self.state.set_piece(Square(move.to_sq.file, capture_rank), None)

        # Handle castling
        if piece.type == PieceType.KING and abs(move.from_sq.file - move.to_sq.file) == 2:
            if move.to_sq.file > move.from_sq.file:  # Kingside
                rook_from = Square(7, move.from_sq.rank)
                rook_to = Square(5, move.from_sq.rank)
            else:  # Queenside
                rook_from = Square(0, move.from_sq.rank)
                rook_to = Square(3, move.from_sq.rank)
            rook = self.state.get_piece(rook_from)
            self.state.set_piece(rook_from, None)
            self.state.set_piece(rook_to, rook)

        # Move the piece
        self.state.set_piece(move.from_sq, None)
        if move.promotion:
            self.state.set_piece(move.to_sq, Piece(move.promotion, piece.color))
        else:
            self.state.set_piece(move.to_sq, piece)

        # Update en passant target
        if piece.type == PieceType.PAWN and abs(move.to_sq.rank - move.from_sq.rank) == 2:
            ep_rank = (move.from_sq.rank + move.to_sq.rank) // 2
            self.state.en_passant_target = Square(move.from_sq.file, ep_rank)
        else:
            self.state.en_passant_target = None

        # Update castling rights
        if piece.type == PieceType.KING:
            self.state.castling_rights[piece.color] = {"K": False, "Q": False}
        if piece.type == PieceType.ROOK:
            if move.from_sq.file == 0:
                self.state.castling_rights[piece.color]["Q"] = False
            elif move.from_sq.file == 7:
                self.state.castling_rights[piece.color]["K"] = False

        # Update clocks
        if piece.type == PieceType.PAWN or captured is not None:
            self.state.halfmove_clock = 0
        else:
            self.state.halfmove_clock += 1

        if self.state.turn == Color.BLACK:
            self.state.fullmove_number += 1

        self.state.turn = self.state.turn.opposite()

    def get_legal_moves(self, from_sq: Square | None = None) -> list[Move]:
        """Get all legal moves, optionally from a specific square."""
        moves = []

        for sq in self._iter_squares():
            if from_sq is not None and sq != from_sq:
                continue

            piece = self.state.get_piece(sq)
            if piece is None or piece.color != self.state.turn:
                continue

            # Generate pseudo-legal moves
            pseudo_moves = self._get_pseudo_moves(sq, piece)

            # Filter to legal moves
            for move in pseudo_moves:
                if self._is_legal_move(move):
                    moves.append(move)

        return moves

    def _get_pseudo_moves(self, sq: Square, piece: Piece) -> list[Move]:
        """Get pseudo-legal moves for a piece (may leave king in check)."""
        moves = []

        if piece.type == PieceType.PAWN:
            moves.extend(self._get_pawn_moves(sq, piece.color))
        elif piece.type == PieceType.KNIGHT:
            moves.extend(self._get_knight_moves(sq, piece.color))
        elif piece.type == PieceType.BISHOP:
            moves.extend(self._get_sliding_moves(sq, piece.color, [(1, 1), (1, -1), (-1, 1), (-1, -1)]))
        elif piece.type == PieceType.ROOK:
            moves.extend(self._get_sliding_moves(sq, piece.color, [(0, 1), (0, -1), (1, 0), (-1, 0)]))
        elif piece.type == PieceType.QUEEN:
            moves.extend(self._get_sliding_moves(sq, piece.color, [(0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)]))
        elif piece.type == PieceType.KING:
            moves.extend(self._get_king_moves(sq, piece.color))

        return moves

    def _get_pawn_moves(self, sq: Square, color: Color) -> list[Move]:
        moves = []
        direction = 1 if color == Color.WHITE else -1
        start_rank = 1 if color == Color.WHITE else 6
        promo_rank = 7 if color == Color.WHITE else 0

        # Single push
        to_sq = Square(sq.file, sq.rank + direction)
        if 0 <= to_sq.rank <= 7 and self.state.get_piece(to_sq) is None:
            if to_sq.rank == promo_rank:
                for promo in [PieceType.QUEEN, PieceType.ROOK, PieceType.BISHOP, PieceType.KNIGHT]:
                    moves.append(Move(sq, to_sq, promo))
            else:
                moves.append(Move(sq, to_sq))

                # Double push
                if sq.rank == start_rank:
                    to_sq2 = Square(sq.file, sq.rank + 2 * direction)
                    if self.state.get_piece(to_sq2) is None:
                        moves.append(Move(sq, to_sq2))

        # Captures
        for df in [-1, 1]:
            to_sq = Square(sq.file + df, sq.rank + direction)
            if not (0 <= to_sq.file <= 7 and 0 <= to_sq.rank <= 7):
                continue

            target = self.state.get_piece(to_sq)
            is_ep = to_sq == self.state.en_passant_target

            if (target is not None and target.color != color) or is_ep:
                if to_sq.rank == promo_rank:
                    for promo in [PieceType.QUEEN, PieceType.ROOK, PieceType.BISHOP, PieceType.KNIGHT]:
                        moves.append(Move(sq, to_sq, promo))
                else:
                    moves.append(Move(sq, to_sq))

        return moves

    def _get_knight_moves(self, sq: Square, color: Color) -> list[Move]:
        moves = []
        deltas = [(-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)]

        for df, dr in deltas:
            to_sq = Square(sq.file + df, sq.rank + dr)
            if not (0 <= to_sq.file <= 7 and 0 <= to_sq.rank <= 7):
                continue

            target = self.state.get_piece(to_sq)
            if target is None or target.color != color:
                moves.append(Move(sq, to_sq))

        return moves

    def _get_sliding_moves(self, sq: Square, color: Color, directions: list[tuple[int, int]]) -> list[Move]:
        moves = []

        for df, dr in directions:
            current = Square(sq.file + df, sq.rank + dr)
            while 0 <= current.file <= 7 and 0 <= current.rank <= 7:
                target = self.state.get_piece(current)
                if target is None:
                    moves.append(Move(sq, current))
                elif target.color != color:
                    moves.append(Move(sq, current))
                    break
                else:
                    break
                current = Square(current.file + df, current.rank + dr)

        return moves

    def _get_king_moves(self, sq: Square, color: Color) -> list[Move]:
        moves = []

        # Normal king moves
        for df in [-1, 0, 1]:
            for dr in [-1, 0, 1]:
                if df == 0 and dr == 0:
                    continue
                to_sq = Square(sq.file + df, sq.rank + dr)
                if not (0 <= to_sq.file <= 7 and 0 <= to_sq.rank <= 7):
                    continue
                target = self.state.get_piece(to_sq)
                if target is None or target.color != color:
                    moves.append(Move(sq, to_sq))

        # Castling
        if not self.is_in_check(color):
            base_rank = 0 if color == Color.WHITE else 7

            # Kingside
            if self.state.castling_rights[color]["K"]:
                if (self.state.get_piece(Square(5, base_rank)) is None and
                    self.state.get_piece(Square(6, base_rank)) is None and
                    not self._is_attacked(Square(5, base_rank), color.opposite()) and
                    not self._is_attacked(Square(6, base_rank), color.opposite())):
                    moves.append(Move(sq, Square(6, base_rank)))

            # Queenside
            if self.state.castling_rights[color]["Q"]:
                if (self.state.get_piece(Square(3, base_rank)) is None and
                    self.state.get_piece(Square(2, base_rank)) is None and
                    self.state.get_piece(Square(1, base_rank)) is None and
                    not self._is_attacked(Square(3, base_rank), color.opposite()) and
                    not self._is_attacked(Square(2, base_rank), color.opposite())):
                    moves.append(Move(sq, Square(2, base_rank)))

        return moves

    def make_move(self, move_str: str) -> tuple[str | None, str | None]:
        """Make a move and return (error, captured_piece).

        Args:
            move_str: Move in UCI notation (e.g., 'e2e4', 'e7e8q')

        Returns:
            Tuple of (error_message, captured_piece_symbol)
            - On error: (error_msg, None)
            - On success: (None, captured_piece or None if no capture)
        """
        try:
            move = Move.from_str(move_str)
        except ValueError as e:
            return str(e), None

        # Check if the move is legal
        legal_moves = self.get_legal_moves(move.from_sq)
        matching_move = None
        for legal in legal_moves:
            if legal.to_sq == move.to_sq:
                if move.promotion is None and legal.promotion is not None:
                    # Default to queen promotion
                    move.promotion = PieceType.QUEEN
                if legal.promotion == move.promotion:
                    matching_move = legal
                    break

        if matching_move is None:
            piece = self.state.get_piece(move.from_sq)
            if piece is None:
                return f"No piece at {move.from_sq}", None
            if piece.color != self.state.turn:
                return f"It's {self.state.turn.value}'s turn", None
            return f"Illegal move: {move}", None

        # Get captured piece BEFORE applying move
        captured = self.state.get_piece(matching_move.to_sq)

        # Handle en passant capture (captured piece is on different square)
        moving_piece = self.state.get_piece(matching_move.from_sq)
        if (moving_piece and moving_piece.type == PieceType.PAWN and
            matching_move.to_sq == self.state.en_passant_target):
            captured = self.state.get_piece(Square(matching_move.to_sq.file, matching_move.from_sq.rank))

        captured_symbol = str(captured) if captured else None

        # Apply the move
        self._apply_move_unchecked(matching_move)
        self.state.move_history.append(str(matching_move))

        return None, captured_symbol

    def is_checkmate(self) -> bool:
        """Check if the current side is in checkmate."""
        if not self.is_in_check():
            return False
        return len(self.get_legal_moves()) == 0

    def is_stalemate(self) -> bool:
        """Check if the current side is in stalemate."""
        if self.is_in_check():
            return False
        return len(self.get_legal_moves()) == 0

    def is_draw(self) -> tuple[bool, str | None]:
        """Check if the game is a draw.

        Returns:
            Tuple of (is_draw, reason)
        """
        if self.is_stalemate():
            return True, "stalemate"

        if self.state.halfmove_clock >= 100:
            return True, "50-move rule"

        # Check for insufficient material
        pieces = []
        for sq in self._iter_squares():
            piece = self.state.get_piece(sq)
            if piece and piece.type != PieceType.KING:
                pieces.append(piece)

        if len(pieces) == 0:
            return True, "insufficient material (K vs K)"

        if len(pieces) == 1:
            if pieces[0].type in [PieceType.BISHOP, PieceType.KNIGHT]:
                return True, "insufficient material"

        # TODO: Add more draw conditions (repetition)

        return False, None

    def get_game_result(self) -> str | None:
        """Get the game result.

        Returns:
            "1-0" for white win, "0-1" for black win, "1/2-1/2" for draw,
            or None if the game is ongoing.
        """
        if self.is_checkmate():
            # The side to move is in checkmate, so the other side wins
            if self.state.turn == Color.WHITE:
                return "0-1"
            else:
                return "1-0"

        is_draw, _ = self.is_draw()
        if is_draw:
            return "1/2-1/2"

        return None

    def render_board(self) -> str:
        """Render the board as ASCII art."""
        lines = []
        lines.append("  +-----------------+")
        for rank in range(7, -1, -1):
            row = f"{rank + 1} |"
            for file in range(8):
                piece = self.state.get_piece(Square(file, rank))
                if piece:
                    row += f" {piece}"
                else:
                    row += " ."
            row += " |"
            lines.append(row)
        lines.append("  +-----------------+")
        lines.append("    a b c d e f g h")
        return "\n".join(lines)
