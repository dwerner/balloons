/**
 * ChessTab - Interactive chess board for playing against the LLM
 *
 * This is a plugin-ready version that can be dynamically loaded.
 * It receives its dependencies via props (sendMessage, sessionDataClient, etc.)
 * rather than importing from the main app.
 *
 * Features:
 * - Visual chess board with piece animations
 * - Click-to-move interaction
 * - Legal move highlighting
 * - Game state synchronization with chess domain
 * - Automatic board updates from LLM moves
 */

import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import './ChessTab.css';

// Piece unicode characters with better styling
const PIECES: Record<string, string> = {
  K: '♔', Q: '♕', R: '♖', B: '♗', N: '♘', P: '♙',
  k: '♚', q: '♛', r: '♜', b: '♝', n: '♞', p: '♟',
};

// Plugin context provided by the host app
export interface PluginContext {
  /** Send a message to the LLM */
  sendMessage?: (message: string) => void;
  /** Current session ID */
  sessionId?: string;
  /** Subscribe to domain events, returns unsubscribe function */
  subscribeToDomainEvents?: (
    domainId: string,
    callback: (event: DomainEventData) => void
  ) => () => void;
  /** Request current domain state */
  requestDomainState?: (domainId: string) => Promise<boolean>;
  /** Whether the LLM is currently responding (streaming) */
  isLLMResponding?: boolean;
}

// Domain event structure
export interface DomainEventData {
  sessionId: string;
  domainId: string;
  eventType: string;
  data: Record<string, unknown>;
}

interface Position {
  board: (string | null)[][];
  turn: 'w' | 'b';
}

interface AnimatedPiece {
  piece: string;
  fromFile: number;
  fromRank: number;
  toFile: number;
  toRank: number;
  startTime: number;
}

const DEFAULT_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
const ANIMATION_DURATION = 200; // ms

function parseFEN(fen: string): Position {
  const parts = fen.split(' ');
  const ranksPart = parts[0];
  if (!ranksPart) {
    return { board: Array(8).fill(null).map(() => Array(8).fill(null)), turn: 'w' };
  }
  const ranks = ranksPart.split('/');
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
  const rankChar = notation[1] || '1';
  return {
    file: notation.charCodeAt(0) - 97,
    rank: 8 - parseInt(rankChar),
  };
}

export function ChessTab({ sendMessage, sessionId, subscribeToDomainEvents, requestDomainState, isLLMResponding = false }: PluginContext) {
  const [localFen, setLocalFen] = useState<string>(DEFAULT_FEN);
  const [selectedSquare, setSelectedSquare] = useState<string | null>(null);
  const [legalMoves, setLegalMoves] = useState<string[]>([]);
  const [lastMove, setLastMove] = useState<string | null>(null);
  const [animatingPiece, setAnimatingPiece] = useState<AnimatedPiece | null>(null);
  const [playerColor, setPlayerColor] = useState<'w' | 'b'>('w');
  const [gameStarted, setGameStarted] = useState(false);
  const [isPendingStart, setIsPendingStart] = useState(false);  // Waiting for game to start
  const [isThinking, setIsThinking] = useState(false);
  const [moveHistory, setMoveHistory] = useState<string[]>([]);
  const [gameOver, setGameOver] = useState(false);
  const [gameResult, setGameResult] = useState<string | null>(null);
  const [capturedByWhite, setCapturedByWhite] = useState<string[]>([]);  // Pieces white captured
  const [capturedByBlack, setCapturedByBlack] = useState<string[]>([]);  // Pieces black captured
  const boardRef = useRef<HTMLDivElement>(null);

  // Subscribe to domain events
  useEffect(() => {
    if (!subscribeToDomainEvents || !sessionId) return;

    console.log('[ChessTab] Subscribing to domain events for session:', sessionId);

    const unsubscribe = subscribeToDomainEvents('chess', (event) => {
      console.log('[ChessTab] Received domain event:', event);
      // Only process events for our session
      if (event.sessionId !== sessionId) return;

      console.log('[ChessTab] Processing chess event:', event.eventType);
      const data = event.data;

      switch (event.eventType) {
        case 'chess_game_started':
          console.log('[ChessTab] Game started, legal moves:', data.legalMoves);
          setLocalFen(data.fen as string || DEFAULT_FEN);
          setLegalMoves((data.legalMoves as string[]) || []);
          setMoveHistory([]);
          setGameOver(false);
          setGameResult(null);
          setLastMove(null);
          setSelectedSquare(null);
          setIsThinking(false);
          setIsPendingStart(false);  // Clear pending state
          setGameStarted(true);       // NOW enable the board
          setCapturedByWhite([]);
          setCapturedByBlack([]);
          break;

        case 'chess_move_made': {
          const moveStr = data.move as string;
          const newFen = data.fen as string;
          const capturedPiece = data.captured as string | null;

          // Track captured piece from server (authoritative source)
          if (capturedPiece) {
            // Determine who captured based on piece color
            if (capturedPiece === capturedPiece.toUpperCase()) {
              // White piece was captured (by black)
              setCapturedByBlack(prev => [...prev, capturedPiece]);
            } else {
              // Black piece was captured (by white)
              setCapturedByWhite(prev => [...prev, capturedPiece]);
            }
          }

          // Animate opponent's move (if it wasn't our optimistic move)
          if (moveStr && moveStr.length >= 4) {
            const fromSq = moveStr.slice(0, 2);
            const toSq = moveStr.slice(2, 4);
            const from = notationToSquare(fromSq);
            const to = notationToSquare(toSq);

            // Get the piece that moved from current (pre-update) position
            const oldPosition = parseFEN(localFen);
            const fromRow = oldPosition.board[from.rank];
            const movedPiece = fromRow ? fromRow[from.file] : null;

            // Animate if this is opponent's move (not our optimistic move)
            // We know it's opponent's move if current turn matches our color
            if (movedPiece && oldPosition.turn !== playerColor) {
              setAnimatingPiece({
                piece: movedPiece,
                fromFile: from.file,
                fromRank: from.rank,
                toFile: to.file,
                toRank: to.rank,
                startTime: Date.now(),
              });
              setTimeout(() => setAnimatingPiece(null), ANIMATION_DURATION);
            }
          }

          setLocalFen(newFen);
          setLegalMoves((data.legalMoves as string[]) || []);
          setLastMove(moveStr);
          setSelectedSquare(null);
          if (moveStr) {
            setMoveHistory(prev => [...prev, moveStr]);
          }
          setIsThinking(false);
          break;
        }

        case 'chess_game_over':
          setGameOver(true);
          setGameResult(data.result as string);
          setLegalMoves([]);
          setIsThinking(false);
          break;

        case 'chess_state_sync':
          // Sync state on chess_show or page reload
          console.log('[ChessTab] State sync:', data);
          setLocalFen(data.fen as string || DEFAULT_FEN);
          setLegalMoves((data.legalMoves as string[]) || []);
          setGameOver(data.gameOver as boolean || false);
          setGameResult(data.result as string | null);
          setGameStarted(true);
          setIsThinking(false);
          break;
      }
    });

    return unsubscribe;
  }, [subscribeToDomainEvents, sessionId, localFen, playerColor]);

  // Request current chess state on mount (for tab switching / page reload)
  useEffect(() => {
    if (!requestDomainState || !sessionId) return;

    // Request domain state - the server will emit a chess_state_sync event if a game exists
    console.log('[ChessTab] Requesting chess state for session:', sessionId);
    requestDomainState('chess').then((hasState) => {
      console.log('[ChessTab] State request result:', hasState);
    }).catch((err) => {
      console.warn('[ChessTab] Failed to request domain state:', err);
    });
  }, [requestDomainState, sessionId]);

  // Use chess state from events
  const fen = localFen;
  const position = useMemo(() => parseFEN(fen), [fen]);
  // Only enable interaction when:
  // 1. It's our turn (based on FEN)
  // 2. Game isn't over
  // 3. We have legal moves loaded (server confirmed position)
  // 4. LLM is not currently streaming a response
  const isPlayerTurn = position.turn === playerColor && !gameOver && legalMoves.length > 0 && !isLLMResponding;

  // Parse last move for highlighting
  const lastMoveSquares = useMemo(() => {
    if (!lastMove) return { from: null, to: null };
    return {
      from: lastMove.slice(0, 2),
      to: lastMove.slice(2, 4),
    };
  }, [lastMove]);

  // Get legal moves from selected square
  const legalFromSelected = useMemo(() => {
    if (!selectedSquare) return [];
    return legalMoves
      .filter(move => move.startsWith(selectedSquare))
      .map(move => move.slice(2, 4));
  }, [selectedSquare, legalMoves]);

  // Handle square click
  const handleSquareClick = useCallback((file: number, rank: number) => {
    console.log('[ChessTab] Click:', { file, rank, isPlayerTurn, gameStarted, selectedSquare, legalMoves: legalMoves.length });
    if (!isPlayerTurn || !sendMessage || !gameStarted) {
      console.log('[ChessTab] Click ignored:', { isPlayerTurn, sendMessage: !!sendMessage, gameStarted });
      return;
    }

    const notation = squareToNotation(file, rank);
    const boardRow = position.board[rank];
    const piece = boardRow ? boardRow[file] : null;

    if (selectedSquare) {
      // If clicking on own piece, select it instead
      if (piece && isOwnPiece(piece, position.turn)) {
        setSelectedSquare(notation);
        return;
      }

      // Check if this is a legal move (if we have legal moves from backend)
      const isLegalMove = legalFromSelected.length === 0 || legalFromSelected.includes(notation);
      console.log('[ChessTab] Move check:', { from: selectedSquare, to: notation, isLegalMove, legalFromSelected });

      // If clicking on a different square that's legal, try to make a move
      if (notation !== selectedSquare && isLegalMove) {
        const move = selectedSquare + notation;

        // Animate the piece
        const from = notationToSquare(selectedSquare);
        const fromRow = position.board[from.rank];
        const movingPiece = fromRow ? fromRow[from.file] : null;
        if (movingPiece) {
          setAnimatingPiece({
            piece: movingPiece,
            fromFile: from.file,
            fromRank: from.rank,
            toFile: file,
            toRank: rank,
            startTime: Date.now(),
          });

          // Optimistically update board state immediately
          // This prevents the "bounce back" visual glitch
          const toSquare = notationToSquare(notation);
          const newBoard = position.board.map(row => [...row]);
          const fromBoardRow = newBoard[from.rank];
          const toBoardRow = newBoard[toSquare.rank];
          if (fromBoardRow) fromBoardRow[from.file] = null;
          if (toBoardRow) toBoardRow[toSquare.file] = movingPiece;
          // Reconstruct FEN from board (simplified - just pieces, turn flips)
          const fenRows = newBoard.map(row =>
            row.reduce((acc, piece) => {
              if (piece === null) {
                const last = acc[acc.length - 1];
                if (last && /\d/.test(last)) {
                  acc[acc.length - 1] = String(parseInt(last) + 1);
                } else {
                  acc.push('1');
                }
              } else {
                acc.push(piece);
              }
              return acc;
            }, [] as string[]).join('')
          ).join('/');
          const newTurn = position.turn === 'w' ? 'b' : 'w';
          setLocalFen(`${fenRows} ${newTurn} - - 0 1`);
        }

        // Send move to LLM via chat
        setLastMove(move);
        setSelectedSquare(null);
        setIsThinking(true);
        setLegalMoves([]); // Clear legal moves until next event
        sendMessage(`chess_move ${move}`);

        // Clear animation after duration
        setTimeout(() => {
          setAnimatingPiece(null);
        }, ANIMATION_DURATION);
      } else if (notation === selectedSquare) {
        // Clicking same square - deselect
        setSelectedSquare(null);
      }
      // If not legal, just ignore the click
    } else {
      // Select a piece
      if (piece && isOwnPiece(piece, position.turn)) {
        setSelectedSquare(notation);
      }
    }
  }, [selectedSquare, legalFromSelected, position, isPlayerTurn, sendMessage, gameStarted]);

  const isOwnPiece = (piece: string, turn: 'w' | 'b'): boolean => {
    return turn === 'w' ? piece === piece.toUpperCase() : piece === piece.toLowerCase();
  };

  // Start a new game
  const handleNewGame = useCallback((color: 'w' | 'b') => {
    if (!sendMessage) return;

    setPlayerColor(color);
    setIsPendingStart(true);  // Show pending state until we receive game_started event
    setGameStarted(false);    // Don't enable board yet
    setSelectedSquare(null);
    setLastMove(null);
    setLocalFen(DEFAULT_FEN);
    setLegalMoves([]);

    const colorText = color === 'w' ? "I'll play White" : "I'll play Black";
    sendMessage(`Let's play chess! ${colorText}, you play the other color. Start by calling chess_new_game.`);

    if (color === 'b') {
      setIsThinking(true);
    }
  }, [sendMessage]);

  // Update thinking state when turn changes
  useEffect(() => {
    // We're thinking when it's not our turn and game isn't over
    const currentTurn = position.turn;
    setIsThinking(currentTurn !== playerColor && !gameOver);
  }, [position.turn, playerColor, gameOver]);

  // Render a square
  const renderSquare = (file: number, rank: number) => {
    const displayRank = playerColor === 'b' ? 7 - rank : rank;
    const displayFile = playerColor === 'b' ? 7 - file : file;
    const displayRow = position.board[displayRank];
    const piece = displayRow ? displayRow[displayFile] : null;
    const notation = squareToNotation(displayFile, displayRank);
    const isLight = (displayFile + displayRank) % 2 === 0;
    const isSelected = notation === selectedSquare;
    const isLegalTarget = legalFromSelected.includes(notation);
    const isLastMoveSquare = notation === lastMoveSquares.from || notation === lastMoveSquares.to;
    const hasCapture = isLegalTarget && piece !== null;

    // Check if this piece is currently animating (hide it)
    const isAnimating = animatingPiece &&
      displayFile === animatingPiece.fromFile &&
      displayRank === animatingPiece.fromRank;

    return (
      <div
        key={`${file}-${rank}`}
        className={`chess-square ${isLight ? 'chess-square--light' : 'chess-square--dark'} ${isSelected ? 'chess-square--selected' : ''} ${isLastMoveSquare ? 'chess-square--last-move' : ''}`}
        onClick={() => handleSquareClick(displayFile, displayRank)}
      >
        {/* Legal move indicator */}
        {isLegalTarget && !hasCapture && (
          <div className="chess-legal-move-dot" />
        )}

        {/* Capture indicator */}
        {hasCapture && (
          <div className="chess-capture-ring" />
        )}

        {/* Piece */}
        {piece && !isAnimating && (
          <span className={`chess-piece ${piece === piece.toUpperCase() ? 'chess-piece--white' : 'chess-piece--black'}`}>
            {PIECES[piece]}
          </span>
        )}

        {/* Coordinates */}
        {file === 0 && (
          <span className="chess-coord chess-coord--rank">
            {8 - displayRank}
          </span>
        )}
        {rank === 7 && (
          <span className="chess-coord chess-coord--file">
            {String.fromCharCode(97 + displayFile)}
          </span>
        )}
      </div>
    );
  };

  // Render animated piece overlay
  const renderAnimatedPiece = () => {
    if (!animatingPiece || !boardRef.current) return null;

    const squareSize = boardRef.current.offsetWidth / 8;
    const elapsed = Date.now() - animatingPiece.startTime;
    const progress = Math.min(elapsed / ANIMATION_DURATION, 1);
    const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic

    // Convert to display coordinates
    const fromFile = playerColor === 'b' ? 7 - animatingPiece.fromFile : animatingPiece.fromFile;
    const fromRank = playerColor === 'b' ? 7 - animatingPiece.fromRank : animatingPiece.fromRank;
    const toFile = playerColor === 'b' ? 7 - animatingPiece.toFile : animatingPiece.toFile;
    const toRank = playerColor === 'b' ? 7 - animatingPiece.toRank : animatingPiece.toRank;

    const x = fromFile * squareSize + (toFile - fromFile) * squareSize * eased;
    const y = fromRank * squareSize + (toRank - fromRank) * squareSize * eased;

    return (
      <div
        className="chess-animated-piece"
        style={{
          left: x,
          top: y,
          width: squareSize,
          height: squareSize,
          fontSize: squareSize * 0.7,
        }}
      >
        <span className={`chess-piece ${animatingPiece.piece === animatingPiece.piece.toUpperCase() ? 'chess-piece--white' : 'chess-piece--black'}`}>
          {PIECES[animatingPiece.piece]}
        </span>
      </div>
    );
  };

  return (
    <div className="chess-tab">
      {!gameStarted && !isPendingStart ? (
        <div className="chess-start-screen">
          <h2>♟️ Chess vs LLM</h2>
          <p>Choose your color to start a new game:</p>
          <div className="chess-color-buttons">
            <button
              className="chess-color-button chess-color-button--white"
              onClick={() => handleNewGame('w')}
            >
              ♔ Play as White
            </button>
            <button
              className="chess-color-button chess-color-button--black"
              onClick={() => handleNewGame('b')}
            >
              ♚ Play as Black
            </button>
          </div>
        </div>
      ) : isPendingStart && !gameStarted ? (
        <div className="chess-start-screen">
          <h2>♟️ Starting Game...</h2>
          <p className="chess-thinking">Waiting for the LLM to set up the board...</p>
          <div className="chess-board-preview">
            <div className="chess-board">
              {Array.from({ length: 8 }, (_, rank) =>
                Array.from({ length: 8 }, (_, file) => {
                  const isLight = (file + rank) % 2 === 0;
                  return (
                    <div
                      key={`${file}-${rank}`}
                      className={`chess-square ${isLight ? 'chess-square--light' : 'chess-square--dark'}`}
                      style={{ opacity: 0.5 }}
                    />
                  );
                })
              )}
            </div>
          </div>
        </div>
      ) : (
        <>
          {/* Game info bar */}
          <div className="chess-info-bar">
            <span className="chess-player">
              {playerColor === 'w' ? '♔' : '♚'} You
            </span>
            <span className="chess-vs">vs</span>
            <span className="chess-player">
              {playerColor === 'w' ? '♚' : '♔'} LLM
            </span>
            <span className="chess-status">
              {gameOver ? (
                `Game over: ${gameResult}`
              ) : isLLMResponding ? (
                <span className="chess-thinking">LLM responding...</span>
              ) : isThinking ? (
                <span className="chess-thinking">Thinking...</span>
              ) : isPlayerTurn ? (
                `Your turn (${legalMoves.length} moves)${selectedSquare ? ` [${selectedSquare}→${legalFromSelected.length}]` : ''}`
              ) : (
                "Opponent's turn"
              )}
            </span>
          </div>

          {/* Captured pieces - opponent's captures (pieces you lost) */}
          <div className="chess-captured">
            <span className="chess-captured-label">
              {playerColor === 'w' ? 'Lost:' : 'Won:'}
            </span>
            <span className="chess-captured-pieces">
              {(playerColor === 'w' ? capturedByBlack : capturedByWhite).map((piece, i) => (
                <span key={i} className="chess-captured-piece">{PIECES[piece]}</span>
              ))}
            </span>
          </div>

          {/* Chess board */}
          <div className={`chess-board-container ${!isPlayerTurn ? 'chess-board-container--disabled' : ''} ${gameOver ? 'chess-board-container--game-over' : ''}`}>
            <div className={`chess-board ${!isPlayerTurn ? 'chess-board--disabled' : ''}`} ref={boardRef}>
              {Array.from({ length: 8 }, (_, rank) =>
                Array.from({ length: 8 }, (_, file) => renderSquare(file, rank))
              )}
              {renderAnimatedPiece()}
            </div>
          </div>

          {/* Captured pieces - your captures (pieces you took) */}
          <div className="chess-captured">
            <span className="chess-captured-label">
              {playerColor === 'w' ? 'Won:' : 'Lost:'}
            </span>
            <span className="chess-captured-pieces">
              {(playerColor === 'w' ? capturedByWhite : capturedByBlack).map((piece, i) => (
                <span key={i} className="chess-captured-piece">{PIECES[piece]}</span>
              ))}
            </span>
          </div>

          {/* Controls */}
          <div className="chess-controls">
            <button
              className="chess-button chess-button--new"
              onClick={() => setGameStarted(false)}
            >
              New Game
            </button>
            <button
              className="chess-button chess-button--resign"
              onClick={() => sendMessage?.('I resign.')}
              disabled={gameOver}
            >
              Resign
            </button>
          </div>

          {/* Move history */}
          {moveHistory.length > 0 && (
            <div className="chess-history">
              <div className="chess-history-label">Moves:</div>
              <div className="chess-history-moves">
                {moveHistory.map((move, i) => (
                  <span key={i} className="chess-move">
                    {i % 2 === 0 && <span className="chess-move-number">{Math.floor(i / 2) + 1}.</span>}
                    {move}
                  </span>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default ChessTab;
