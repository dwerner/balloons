/**
 * Chess Game Component
 *
 * Integrates ChessBoard with Balloons for player vs LLM games.
 * Handles move sending, game state, and turn management.
 */

import React, { useState, useCallback, useEffect } from 'react';
import ChessBoard from './ChessBoard';

interface ChessGameProps {
  /** WebSocket send function */
  sendMessage?: (message: string) => void;
  /** Current session ID */
  sessionId?: string;
  /** Initial FEN position */
  initialFen?: string;
  /** Player color ('w' or 'b') */
  playerColor?: 'w' | 'b';
  /** Callback when game state updates */
  onGameUpdate?: (state: ChessGameState) => void;
}

interface ChessGameState {
  fen: string;
  turn: 'w' | 'b';
  lastMove?: string;
  legalMoves: string[];
  gameOver: boolean;
  result?: string;
  reason?: string;
  moveHistory: string[];
}

const DEFAULT_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

// Calculate legal moves from FEN (simplified - in production, use a chess library)
function calculateLegalMoves(fen: string): string[] {
  // This is a placeholder - the actual legal moves should come from the server
  // In a real implementation, you'd either:
  // 1. Use a client-side chess library like chess.js
  // 2. Request legal moves from the server
  return [];
}

export const ChessGame: React.FC<ChessGameProps> = ({
  sendMessage,
  sessionId,
  initialFen = DEFAULT_FEN,
  playerColor = 'w',
  onGameUpdate,
}) => {
  const [gameState, setGameState] = useState<ChessGameState>({
    fen: initialFen,
    turn: 'w',
    legalMoves: [],
    gameOver: false,
    moveHistory: [],
  });

  const [isWaitingForLLM, setIsWaitingForLLM] = useState(false);
  const [status, setStatus] = useState('');

  // Determine if it's the player's turn
  const isPlayerTurn = gameState.turn === playerColor && !gameState.gameOver && !isWaitingForLLM;

  // Handle player move
  const handleMove = useCallback((move: string) => {
    if (!sendMessage) {
      console.warn('No sendMessage function provided');
      return;
    }

    // Send move to LLM via Balloons
    const message = `[Player move: ${move}]\n\nI played ${move}. Your turn!`;
    sendMessage(message);

    // Update local state optimistically
    setGameState(prev => ({
      ...prev,
      lastMove: move,
      moveHistory: [...prev.moveHistory, move],
    }));
    setIsWaitingForLLM(true);
    setStatus('Waiting for opponent...');
  }, [sendMessage]);

  // Start a new game
  const handleNewGame = useCallback(() => {
    if (!sendMessage) return;

    const colorText = playerColor === 'w' ? "I'll play White" : "I'll play Black";
    sendMessage(`Let's play chess! ${colorText}, you play the other color.`);

    setGameState({
      fen: DEFAULT_FEN,
      turn: 'w',
      legalMoves: [],
      gameOver: false,
      moveHistory: [],
    });
    setIsWaitingForLLM(playerColor === 'b'); // Wait if LLM plays White
    setStatus(playerColor === 'w' ? 'Your turn (White)' : 'Waiting for White to move...');
  }, [sendMessage, playerColor]);

  // Request current position
  const handleShowBoard = useCallback(() => {
    if (!sendMessage) return;
    sendMessage('Show me the current chess position.');
  }, [sendMessage]);

  // Resign
  const handleResign = useCallback(() => {
    if (!sendMessage || gameState.gameOver) return;
    if (window.confirm('Are you sure you want to resign?')) {
      sendMessage('I resign.');
      setGameState(prev => ({
        ...prev,
        gameOver: true,
        result: playerColor === 'w' ? '0-1' : '1-0',
        reason: 'resignation',
      }));
      setStatus('You resigned');
    }
  }, [sendMessage, gameState.gameOver, playerColor]);

  // Update status based on game state
  useEffect(() => {
    if (gameState.gameOver) {
      setStatus(`Game over: ${gameState.result} (${gameState.reason})`);
    } else if (isWaitingForLLM) {
      setStatus('Waiting for opponent...');
    } else if (isPlayerTurn) {
      setStatus('Your turn');
    }
  }, [gameState, isWaitingForLLM, isPlayerTurn]);

  // Notify parent of state changes
  useEffect(() => {
    onGameUpdate?.(gameState);
  }, [gameState, onGameUpdate]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, alignItems: 'center' }}>
      {/* Game info */}
      <div style={{
        display: 'flex',
        gap: 16,
        alignItems: 'center',
        padding: '8px 16px',
        backgroundColor: '#2a2a2a',
        borderRadius: 8,
        color: '#fff',
        fontFamily: 'system-ui, sans-serif',
      }}>
        <span style={{ fontWeight: 'bold' }}>
          {playerColor === 'w' ? '⬜' : '⬛'} You
        </span>
        <span>vs</span>
        <span style={{ fontWeight: 'bold' }}>
          {playerColor === 'w' ? '⬛' : '⬜'} LLM
        </span>
        <span style={{ color: '#888', marginLeft: 8 }}>
          {status}
        </span>
      </div>

      {/* Chess board */}
      <ChessBoard
        fen={gameState.fen}
        onMove={handleMove}
        size={400}
        isPlayerTurn={isPlayerTurn}
        legalMoves={gameState.legalMoves}
        lastMove={gameState.lastMove}
        flipped={playerColor === 'b'}
        showCoordinates={true}
      />

      {/* Controls */}
      <div style={{ display: 'flex', gap: 8 }}>
        <button
          onClick={handleNewGame}
          style={{
            padding: '8px 16px',
            backgroundColor: '#4a9c4a',
            color: '#fff',
            border: 'none',
            borderRadius: 4,
            cursor: 'pointer',
            fontWeight: 'bold',
          }}
        >
          New Game
        </button>
        <button
          onClick={handleShowBoard}
          style={{
            padding: '8px 16px',
            backgroundColor: '#4a7c9c',
            color: '#fff',
            border: 'none',
            borderRadius: 4,
            cursor: 'pointer',
          }}
        >
          Show Board
        </button>
        <button
          onClick={handleResign}
          disabled={gameState.gameOver}
          style={{
            padding: '8px 16px',
            backgroundColor: gameState.gameOver ? '#666' : '#9c4a4a',
            color: '#fff',
            border: 'none',
            borderRadius: 4,
            cursor: gameState.gameOver ? 'not-allowed' : 'pointer',
          }}
        >
          Resign
        </button>
      </div>

      {/* Move history */}
      {gameState.moveHistory.length > 0 && (
        <div style={{
          maxWidth: 400,
          padding: 12,
          backgroundColor: '#1a1a1a',
          borderRadius: 8,
          color: '#ccc',
          fontSize: 12,
          fontFamily: 'monospace',
        }}>
          <div style={{ marginBottom: 8, color: '#888' }}>Move History:</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {gameState.moveHistory.map((move, i) => (
              <span key={i} style={{
                backgroundColor: i % 2 === 0 ? '#333' : '#444',
                padding: '2px 6px',
                borderRadius: 2,
              }}>
                {Math.floor(i / 2) + 1}{i % 2 === 0 ? '.' : '...'}{move}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default ChessGame;
