# Chess Domain Plugin

Play chess against the LLM or analyze positions within Balloons.

## Quick Start

Once the chess domain is loaded, you can start a game:

```
You: Let's play chess!
LLM: [calls chess_new_game]

  +-----------------+
8 | r n b q k b n r |
7 | p p p p p p p p |
6 | . . . . . . . . |
5 | . . . . . . . . |
4 | . . . . . . . . |
3 | . . . . . . . . |
2 | P P P P P P P P |
1 | R N B Q K B N R |
  +-----------------+
    a b c d e f g h

White to move. Your move!
```

## Available Commands

### Start a New Game
```
chess_new_game
```
Resets the board to the standard starting position.

### Make a Move
```
chess_move(move="e2e4")
```
Uses UCI notation: source square + destination square.

Examples:
- `e2e4` - Move piece from e2 to e4
- `g1f3` - Move knight from g1 to f3
- `e1g1` - Castle kingside
- `e7e8q` - Promote pawn to queen

### Show the Board
```
chess_show
```
Displays the current position and game status.

### List Legal Moves
```
chess_legal_moves
chess_legal_moves(from_square="e2")
```
Shows all legal moves, optionally filtered by source square.

### Resign
```
chess_resign
```
Resign the current game.

### Set Position
```
chess_set_position(fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1")
```
Set up a specific position using FEN notation.

## Board Notation

The board uses standard algebraic notation:

```
  +-----------------+
8 | r n b q k b n r |  ← Black's back rank
7 | p p p p p p p p |  ← Black's pawns
6 | . . . . . . . . |
5 | . . . . . . . . |
4 | . . . . . . . . |
3 | . . . . . . . . |
2 | P P P P P P P P |  ← White's pawns
1 | R N B Q K B N R |  ← White's back rank
  +-----------------+
    a b c d e f g h
    ↑
    Files (columns)
```

**Piece symbols:**
- `K/k` = King
- `Q/q` = Queen
- `R/r` = Rook
- `B/b` = Bishop
- `N/n` = Knight
- `P/p` = Pawn

Uppercase = White, lowercase = Black

## FEN Notation

FEN (Forsyth-Edwards Notation) describes a complete position:

```
rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1
```

Format: `<position> <turn> <castling> <en_passant> <halfmove> <fullmove>`

- **Position**: Ranks 8-1, separated by `/`. Numbers indicate empty squares.
- **Turn**: `w` (White) or `b` (Black)
- **Castling**: `K`=White kingside, `Q`=White queenside, `k`/`q`=Black
- **En passant**: Target square or `-`
- **Halfmove clock**: Moves since last pawn move/capture (50-move rule)
- **Fullmove number**: Increments after Black's move

## Playing Against the LLM

The LLM can play as either color. For a game where you play White:

```
You: Let's play chess. I'll play white, you play black. I'll start with e4.

LLM: [calls chess_new_game, then chess_move("e2e4")]
     Great! I'll respond with the Sicilian Defense.
     [calls chess_move("c7c5")]
```

For analysis, you can set up any position:

```
You: Let's analyze this endgame position: 8/8/8/8/8/5K2/8/4k2R w - - 0 1

LLM: [calls chess_set_position]
     This is a basic King + Rook vs King endgame. White should...
```

## Game State Persistence

Games are automatically saved and can be resumed across sessions. The position is stored in `~/.balloons/plugins/chess/`.

## Events

The chess domain emits events that other domains can react to:

| Event | Payload | Description |
|-------|---------|-------------|
| `chess_game_started` | `{fen}` | New game started |
| `chess_move_made` | `{move, fen}` | A move was made |
| `chess_game_over` | `{result, reason}` | Game ended |

Results: `"1-0"` (White wins), `"0-1"` (Black wins), `"1/2-1/2"` (Draw)

Reasons: `"checkmate"`, `"stalemate"`, `"resignation"`, `"50-move rule"`, etc.
