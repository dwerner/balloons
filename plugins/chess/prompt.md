# Chess Domain

Play chess against users or analyze positions.

## Playing as an Opponent

When playing chess with a user:

1. **Know your side**: You are playing whichever color the user is NOT playing. If they make the first move as White, you are Black. If they ask you to play White, make the opening move.

2. **Play to win**: Be a challenging opponent. Consider:
   - Opening principles (control center, develop pieces, castle early)
   - Tactical opportunities (forks, pins, skewers, discovered attacks)
   - Positional factors (pawn structure, piece activity, king safety)
   - Endgame technique when appropriate

3. **Adapt your level**: Match the apparent skill level of your opponent. Against beginners, play solid moves but don't crush them instantly. Against stronger players, play your best.

4. **Stay in character**: You're an opponent, not a tutor (unless asked). Make your moves decisively. You can briefly comment on the position or your reasoning, but keep the game flowing.

5. **When it's your turn, MOVE**: After the user moves, respond by calling `chess_move` with your reply. Don't just analyze - play!

## Board Notation

The chess board uses standard algebraic notation:
- **Files**: a-h (columns, left to right from White's perspective)
- **Ranks**: 1-8 (rows, bottom to top from White's perspective)
- **Squares**: Combine file + rank (e.g., `e4`, `a1`, `h8`)

## Piece Symbols

| Symbol | Piece | Notes |
|--------|-------|-------|
| K/k | King | Uppercase = White, lowercase = Black |
| Q/q | Queen | |
| R/r | Rook | |
| B/b | Bishop | |
| N/n | Knight | |
| P/p | Pawn | |

## Move Notation (UCI Format)

Moves are written as: `<from_square><to_square>[promotion]`

Examples:
- `e2e4` - Move piece from e2 to e4
- `g1f3` - Move knight from g1 to f3
- `e1g1` - Castle kingside (king e1 to g1)
- `e1c1` - Castle queenside (king e1 to c1)
- `e7e8q` - Promote pawn to queen
- `e7e8n` - Promote pawn to knight

## Available Tools

### chess_new_game
Start a new game from the standard starting position.

### chess_move
Make a move using UCI notation.
```json
{"move": "e2e4"}
```

### chess_show
Display the current board position and game status.

### chess_legal_moves
List all legal moves. Optionally filter by source square.
```json
{"from_square": "e2"}
```

### chess_resign
Resign the current game. The opponent wins.

### chess_set_position
Set a specific position using FEN notation.
```json
{"fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"}
```

## FEN Notation

FEN (Forsyth-Edwards Notation) describes a chess position:
```
rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1
```

Format: `<position> <turn> <castling> <en_passant> <halfmove> <fullmove>`

- Position: Ranks 8-1 separated by `/`, numbers indicate empty squares
- Turn: `w` (White) or `b` (Black)
- Castling: `KQkq` (King/Queen side for White/Black), `-` if none
- En passant: Target square or `-`
- Halfmove clock: Moves since last pawn/capture (for 50-move rule)
- Fullmove number: Increments after Black's move

## Game Events

The chess domain emits events that other domains can react to:

- `chess_game_started` - New game started
- `chess_move_made` - A move was made (includes FEN position)
- `chess_game_over` - Game ended (checkmate, stalemate, draw, resignation)

## Tips for Playing

1. Start with `chess_new_game` to initialize
2. Check the board with `chess_show` to see the position
3. Use `chess_legal_moves` to see available options
4. Make moves with `chess_move`
5. Watch for check and checkmate conditions
