"""Tests for the chess engine."""

import pytest
from .engine import ChessEngine, Square, Move, Color, PieceType


class TestSquare:
    def test_from_str(self):
        sq = Square.from_str("e4")
        assert sq.file == 4
        assert sq.rank == 3

    def test_to_str(self):
        sq = Square(file=4, rank=3)
        assert str(sq) == "e4"

    def test_corners(self):
        assert str(Square.from_str("a1")) == "a1"
        assert str(Square.from_str("h8")) == "h8"
        assert str(Square.from_str("a8")) == "a8"
        assert str(Square.from_str("h1")) == "h1"


class TestMove:
    def test_from_str(self):
        move = Move.from_str("e2e4")
        assert str(move.from_sq) == "e2"
        assert str(move.to_sq) == "e4"
        assert move.promotion is None

    def test_promotion(self):
        move = Move.from_str("e7e8q")
        assert str(move.from_sq) == "e7"
        assert str(move.to_sq) == "e8"
        assert move.promotion == PieceType.QUEEN


class TestChessEngine:
    def test_new_game(self):
        engine = ChessEngine()
        assert engine.turn == Color.WHITE
        fen = engine.get_fen()
        assert fen.startswith("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR")

    def test_simple_move(self):
        engine = ChessEngine()
        error = engine.make_move("e2e4")
        assert error is None
        assert engine.turn == Color.BLACK

    def test_illegal_move_wrong_turn(self):
        engine = ChessEngine()
        error = engine.make_move("e7e5")  # Black's pawn, but White to move
        assert error is not None
        assert "White" in error or "turn" in error.lower()

    def test_illegal_move_no_piece(self):
        engine = ChessEngine()
        error = engine.make_move("e4e5")  # No piece on e4
        assert error is not None

    def test_scholar_mate(self):
        """Test scholar's mate (4-move checkmate)."""
        engine = ChessEngine()

        moves = ["e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6", "h5f7"]
        for move in moves:
            error = engine.make_move(move)
            assert error is None, f"Move {move} failed: {error}"

        assert engine.is_checkmate()
        assert engine.get_game_result() == "1-0"

    def test_castling_kingside(self):
        engine = ChessEngine()
        # Clear pieces between king and rook
        engine.state.set_piece(Square.from_str("f1"), None)
        engine.state.set_piece(Square.from_str("g1"), None)

        error = engine.make_move("e1g1")
        assert error is None

        # Check king and rook positions
        king = engine.state.get_piece(Square.from_str("g1"))
        rook = engine.state.get_piece(Square.from_str("f1"))
        assert king is not None and king.type == PieceType.KING
        assert rook is not None and rook.type == PieceType.ROOK

    def test_en_passant(self):
        engine = ChessEngine()
        moves = ["e2e4", "a7a6", "e4e5", "d7d5"]  # d5 creates en passant
        for move in moves:
            engine.make_move(move)

        # Now e5xd6 should be legal (en passant)
        error = engine.make_move("e5d6")
        assert error is None

        # Check that black pawn on d5 is captured
        assert engine.state.get_piece(Square.from_str("d5")) is None

    def test_promotion(self):
        # Set up a position with a pawn about to promote
        engine = ChessEngine()
        engine.set_position("8/P7/8/8/8/8/8/4K2k w - - 0 1")

        error = engine.make_move("a7a8q")
        assert error is None

        piece = engine.state.get_piece(Square.from_str("a8"))
        assert piece is not None
        assert piece.type == PieceType.QUEEN
        assert piece.color == Color.WHITE

    def test_stalemate(self):
        # Classic stalemate position
        engine = ChessEngine()
        engine.set_position("k7/8/1K6/8/8/8/8/7Q b - - 0 1")

        # Simulate position where black king has no moves
        engine.set_position("k7/2Q5/1K6/8/8/8/8/8 b - - 0 1")

        assert engine.is_stalemate()
        is_draw, reason = engine.is_draw()
        assert is_draw
        assert reason == "stalemate"

    def test_fen_round_trip(self):
        engine = ChessEngine()
        engine.make_move("e2e4")
        engine.make_move("e7e5")
        engine.make_move("g1f3")

        fen = engine.get_fen()
        engine2 = ChessEngine()
        engine2.set_position(fen)

        assert engine2.get_fen() == fen

    def test_legal_moves_from_square(self):
        engine = ChessEngine()
        moves = engine.get_legal_moves(Square.from_str("e2"))
        move_strs = [str(m) for m in moves]
        assert "e2e3" in move_strs
        assert "e2e4" in move_strs
        assert len(moves) == 2

    def test_render_board(self):
        engine = ChessEngine()
        board = engine.render_board()
        assert "r n b q k b n r" in board or "rnbqkbnr" in board.replace(" ", "").lower()
        assert "a b c d e f g h" in board


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
