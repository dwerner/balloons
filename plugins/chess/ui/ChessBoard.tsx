/**
 * Chess Board Component
 *
 * Interactive chess board for playing against the LLM.
 * Supports click-to-move, drag-and-drop, and displays legal moves.
 */

import React, { useState, useCallback, useMemo } from 'react';

// Piece unicode characters
const PIECES: Record<string, string> = {
  K: '♔', Q: '♕', R: '♖', B: '♗', N: '♘', P: '♙',
  k: '♚', q: '♛', r: '♜', b: '♝', n: '♞', p: '♟',
};

// Square colors
const LIGHT_SQUARE = '#f0d9b5';
const DARK_SQUARE = '#b58863';
const SELECTED_SQUARE = '#829769';
const LEGAL_MOVE_DOT = 'rgba(0, 0, 0, 0.15)';
const CAPTURE_HIGHLIGHT = 'rgba(255, 0, 0, 0.3)';
const LAST_MOVE_HIGHLIGHT = 'rgba(255, 255, 0, 0.4)';

interface ChessBoardProps {
  /** FEN position string */
  fen?: string;
  /** Called when a move is made */
  onMove?: (move: string) => void;
  /** Board size in pixels */
  size?: number;
  /** Whether it's the player's turn */
  isPlayerTurn?: boolean;
  /** Legal moves in UCI format */
  legalMoves?: string[];
  /** Last move made */
  lastMove?: string;
  /** Whether the board is flipped (black at bottom) */
  flipped?: boolean;
  /** Show coordinates */
  showCoordinates?: boolean;
}

interface Position {
  board: (string | null)[][];
  turn: 'w' | 'b';
}

function parseFEN(fen: string): Position {
  const parts = fen.split(' ');
  const ranks = parts[0].split('/');
  const board: (string | null)[][] = [];

  for (const rank of ranks) {
    const row: (string | null)[] = [];
    for (const char of rank) {
      if (/\d/.test(char)) {
        for (let i = 0; i < parseInt(char); i++) {
          row.push(null);
        }
      } else {
        row.push(char);
      }
    }
    board.push(row);
  }

  return {
    board,
    turn: (parts[1] as 'w' | 'b') || 'w',
  };
}

function squareToNotation(file: number, rank: number): string {
  return String.fromCharCode(97 + file) + (8 - rank);
}

function notationToSquare(notation: string): { file: number; rank: number } {
  return {
    file: notation.charCodeAt(0) - 97,
    rank: 8 - parseInt(notation[1]),
  };
}

export const ChessBoard: React.FC<ChessBoardProps> = ({
  fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
  onMove,
  size = 400,
  isPlayerTurn = true,
  legalMoves = [],
  lastMove,
  flipped = false,
  showCoordinates = true,
}) => {
  const [selectedSquare, setSelectedSquare] = useState<string | null>(null);
  const [hoverSquare, setHoverSquare] = useState<string | null>(null);

  const position = useMemo(() => parseFEN(fen), [fen]);
  const squareSize = size / 8;

  // Get legal moves from selected square
  const legalFromSelected = useMemo(() => {
    if (!selectedSquare) return [];
    return legalMoves
      .filter(move => move.startsWith(selectedSquare))
      .map(move => move.slice(2, 4));
  }, [selectedSquare, legalMoves]);

  // Parse last move
  const lastMoveSquares = useMemo(() => {
    if (!lastMove) return { from: null, to: null };
    return {
      from: lastMove.slice(0, 2),
      to: lastMove.slice(2, 4),
    };
  }, [lastMove]);

  const handleSquareClick = useCallback((file: number, rank: number) => {
    if (!isPlayerTurn || !onMove) return;

    const notation = squareToNotation(file, rank);
    const piece = position.board[rank][file];

    if (selectedSquare) {
      // Check if this is a legal move
      if (legalFromSelected.includes(notation)) {
        // Check for promotion
        const fromSquare = notationToSquare(selectedSquare);
        const movingPiece = position.board[fromSquare.rank][fromSquare.file];
        const isPromotion =
          movingPiece?.toLowerCase() === 'p' &&
          ((position.turn === 'w' && rank === 0) ||
           (position.turn === 'b' && rank === 7));

        if (isPromotion) {
          // Default to queen promotion
          onMove(selectedSquare + notation + 'q');
        } else {
          onMove(selectedSquare + notation);
        }
        setSelectedSquare(null);
      } else if (piece && isOwnPiece(piece, position.turn)) {
        // Select a different piece
        setSelectedSquare(notation);
      } else {
        // Deselect
        setSelectedSquare(null);
      }
    } else {
      // Select a piece
      if (piece && isOwnPiece(piece, position.turn)) {
        setSelectedSquare(notation);
      }
    }
  }, [selectedSquare, legalFromSelected, position, isPlayerTurn, onMove]);

  const isOwnPiece = (piece: string, turn: 'w' | 'b'): boolean => {
    return turn === 'w' ? piece === piece.toUpperCase() : piece === piece.toLowerCase();
  };

  const getSquareColor = (file: number, rank: number): string => {
    const notation = squareToNotation(file, rank);
    const isLight = (file + rank) % 2 === 0;

    // Selected square
    if (notation === selectedSquare) {
      return SELECTED_SQUARE;
    }

    // Last move highlight
    if (notation === lastMoveSquares.from || notation === lastMoveSquares.to) {
      return isLight
        ? `color-mix(in srgb, ${LIGHT_SQUARE}, ${LAST_MOVE_HIGHLIGHT})`
        : `color-mix(in srgb, ${DARK_SQUARE}, ${LAST_MOVE_HIGHLIGHT})`;
    }

    return isLight ? LIGHT_SQUARE : DARK_SQUARE;
  };

  const renderSquare = (file: number, rank: number) => {
    const displayRank = flipped ? 7 - rank : rank;
    const displayFile = flipped ? 7 - file : file;
    const piece = position.board[displayRank][displayFile];
    const notation = squareToNotation(displayFile, displayRank);
    const isLegalTarget = legalFromSelected.includes(notation);
    const hasCapture = isLegalTarget && piece !== null;

    return (
      <div
        key={`${file}-${rank}`}
        onClick={() => handleSquareClick(displayFile, displayRank)}
        onMouseEnter={() => setHoverSquare(notation)}
        onMouseLeave={() => setHoverSquare(null)}
        style={{
          width: squareSize,
          height: squareSize,
          backgroundColor: getSquareColor(displayFile, displayRank),
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          position: 'relative',
          cursor: isPlayerTurn ? 'pointer' : 'default',
          fontSize: squareSize * 0.7,
          userSelect: 'none',
        }}
      >
        {/* Legal move indicator */}
        {isLegalTarget && !hasCapture && (
          <div
            style={{
              position: 'absolute',
              width: squareSize * 0.3,
              height: squareSize * 0.3,
              borderRadius: '50%',
              backgroundColor: LEGAL_MOVE_DOT,
            }}
          />
        )}

        {/* Capture indicator */}
        {hasCapture && (
          <div
            style={{
              position: 'absolute',
              width: '100%',
              height: '100%',
              borderRadius: '50%',
              border: `${squareSize * 0.08}px solid ${CAPTURE_HIGHLIGHT}`,
              boxSizing: 'border-box',
            }}
          />
        )}

        {/* Piece */}
        {piece && (
          <span
            style={{
              color: piece === piece.toUpperCase() ? '#fff' : '#000',
              textShadow: piece === piece.toUpperCase()
                ? '0 0 3px #000, 0 0 5px #000'
                : '0 0 3px #fff, 0 0 5px #fff',
              zIndex: 1,
            }}
          >
            {PIECES[piece]}
          </span>
        )}

        {/* Coordinates */}
        {showCoordinates && file === 0 && (
          <span
            style={{
              position: 'absolute',
              top: 2,
              left: 4,
              fontSize: squareSize * 0.18,
              color: (displayFile + displayRank) % 2 === 0 ? DARK_SQUARE : LIGHT_SQUARE,
              fontWeight: 'bold',
            }}
          >
            {8 - displayRank}
          </span>
        )}
        {showCoordinates && rank === 7 && (
          <span
            style={{
              position: 'absolute',
              bottom: 2,
              right: 4,
              fontSize: squareSize * 0.18,
              color: (displayFile + displayRank) % 2 === 0 ? DARK_SQUARE : LIGHT_SQUARE,
              fontWeight: 'bold',
            }}
          >
            {String.fromCharCode(97 + displayFile)}
          </span>
        )}
      </div>
    );
  };

  return (
    <div
      style={{
        width: size,
        height: size,
        display: 'grid',
        gridTemplateColumns: `repeat(8, ${squareSize}px)`,
        gridTemplateRows: `repeat(8, ${squareSize}px)`,
        border: '2px solid #333',
        boxShadow: '0 4px 8px rgba(0,0,0,0.3)',
      }}
    >
      {Array.from({ length: 8 }, (_, rank) =>
        Array.from({ length: 8 }, (_, file) => renderSquare(file, rank))
      )}
    </div>
  );
};

export default ChessBoard;
