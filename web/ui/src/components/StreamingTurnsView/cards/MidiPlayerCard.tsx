/**
 * MidiPlayerCard - Audio player for MIDI note sequences
 *
 * Renders a playable interface for the play_midi tool with:
 * - Note sequence display
 * - Play/Stop controls
 * - Progress indicator during playback
 * - BPM and waveform info
 */

import React, { useState, useRef, useCallback, useEffect } from 'react';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
import type { ToolUseBlock, ToolResultBlock } from '../../../../../generated/types';
import { BaseToolCard, calculateToolPhase } from './BaseToolCard';
import {
  getMidiSynth,
  parseNoteSequence,
  calculateDuration,
  type ParsedNote,
  type OscillatorType,
} from '../../../utils/midiPlayer';
import './cards.css';

interface MidiPlayerCardProps {
  turn: SessionDataTurn;
  result?: SessionDataTurn | null;
}

type PlaybackStatus = 'ready' | 'playing' | 'done' | 'error';

// Check if tool input is still streaming
function isStreamingInput(input: Record<string, unknown>): boolean {
  return typeof input._streaming === 'string';
}

export function MidiPlayerCard({ turn, result }: MidiPlayerCardProps) {
  const { contentBlock, streaming, tokens } = turn;

  // Playback state
  const [status, setStatus] = useState<PlaybackStatus>('ready');
  const [playError, setPlayError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [parsedNotes, setParsedNotes] = useState<ParsedNote[] | null>(null);
  const [duration, setDuration] = useState<number>(0);
  const synthRef = useRef(getMidiSynth());

  // Extract tool info
  const toolUseBlock = contentBlock?.type === 'tool_use'
    ? (contentBlock as ToolUseBlock)
    : null;

  const toolInput = toolUseBlock?.input || {};
  const inputIsStreaming = isStreamingInput(toolInput);

  // Extract play_midi-specific inputs
  const notes = (toolInput.notes || '') as string;
  const bpm = (toolInput.bpm || 120) as number;
  const waveform = ((toolInput.waveform || 'sine') as string) as OscillatorType;
  const volume = (toolInput.volume !== undefined ? toolInput.volume : 0.5) as number;

  // Get result info
  const resultBlock = result?.contentBlock?.type === 'tool_result'
    ? (result.contentBlock as ToolResultBlock)
    : null;
  const hasResult = !!resultBlock;
  const resultContent = resultBlock?.content || '';
  const isError = resultBlock?.isError || false;

  // Calculate phase
  const hasInput = !inputIsStreaming && notes.length > 0;
  const phase = calculateToolPhase(streaming, hasInput, inputIsStreaming, hasResult, isError);

  // Parse notes when input changes
  useEffect(() => {
    if (!notes) {
      setParsedNotes(null);
      setDuration(0);
      return;
    }

    try {
      const parsed = parseNoteSequence(notes);
      setParsedNotes(parsed);
      setDuration(calculateDuration(parsed, bpm));
      setPlayError(null);
    } catch (e) {
      setPlayError(e instanceof Error ? e.message : 'Failed to parse notes');
      setParsedNotes(null);
    }
  }, [notes, bpm]);

  const handlePlay = useCallback(async () => {
    if (!parsedNotes) return;

    try {
      setStatus('playing');
      setPlayError(null);
      setProgress(0);

      await synthRef.current.playSequence(
        parsedNotes,
        bpm,
        waveform,
        volume,
        (index, total) => {
          setProgress((index / total) * 100);
        }
      );

      setProgress(100);
      setStatus('done');

      // Reset to ready after a short delay
      setTimeout(() => {
        setStatus('ready');
        setProgress(0);
      }, 2000);
    } catch (e) {
      setPlayError(e instanceof Error ? e.message : 'Playback failed');
      setStatus('error');
    }
  }, [parsedNotes, bpm, waveform, volume]);

  const handleStop = useCallback(() => {
    synthRef.current.stop();
    setStatus('ready');
    setProgress(0);
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      synthRef.current.stop();
    };
  }, []);

  const formatDuration = (seconds: number): string => {
    if (seconds < 60) {
      return `${seconds.toFixed(1)}s`;
    }
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const waveformIcon: Record<OscillatorType, string> = {
    sine: '~',
    square: '#',
    sawtooth: '/',
    triangle: '^',
  };

  // Build header info
  const headerInfo = [
    `${bpm} BPM`,
    `${waveformIcon[waveform]} ${waveform}`,
    parsedNotes ? `${parsedNotes.length} notes` : null,
    duration > 0 ? formatDuration(duration) : null,
  ].filter(Boolean).join(' | ');

  // Raw data for debugging mode
  const rawData = { turn, result };

  return (
    <BaseToolCard
      toolName="play_midi"
      phase={phase}
      tokens={tokens}
      order={turn.order}
      orderEnd={result?.order}
      className="midi-player-card"
      rawData={rawData}
    >
      {/* Header with playback info */}
      <div className="midi-header-info">
        <span className="midi-icon">♪</span>
        <span className="midi-header-text">{headerInfo}</span>
      </div>

      {/* Note sequence display */}
      {hasInput && (
        <div className="midi-notes-display">
          <code>{notes}</code>
        </div>
      )}

      {/* Streaming indicator */}
      {inputIsStreaming && (
        <div className="tool-building-content">
          <span className="streaming-dots">
            <span className="dot">●</span>
            <span className="dot">●</span>
            <span className="dot">●</span>
          </span>
          <span>Building input...</span>
        </div>
      )}

      {/* Progress bar during playback */}
      {status === 'playing' && (
        <div className="midi-progress-container">
          <div
            className="midi-progress-bar"
            style={{ width: `${progress}%` }}
          />
        </div>
      )}

      {/* Playback controls */}
      {hasInput && parsedNotes && (
        <div className="midi-controls">
          {status === 'playing' ? (
            <button
              className="midi-button midi-stop"
              onClick={handleStop}
              title="Stop playback"
              type="button"
            >
              ■ Stop
            </button>
          ) : (
            <button
              className="midi-button midi-play"
              onClick={handlePlay}
              disabled={!parsedNotes || playError !== null}
              title="Play (requires user interaction)"
              type="button"
            >
              ▶ Play
            </button>
          )}

          {status === 'done' && (
            <span className="midi-status midi-done">✓ Done</span>
          )}

          {playError && (
            <span className="midi-status midi-error" title={playError}>
              ✕ {playError}
            </span>
          )}
        </div>
      )}

      {/* Result from backend (validation info) */}
      {hasResult && !isError && (
        <div className="midi-result">
          {resultContent}
        </div>
      )}

      {/* Error from backend */}
      {isError && (
        <div className="tool-output error">
          <code>{resultContent}</code>
        </div>
      )}

      {/* Executing state */}
      {!hasResult && phase === 'executing' && (
        <div className="tool-executing">Validating notes...</div>
      )}

      <style>{`
        .midi-player-card .midi-header-info {
          display: flex;
          align-items: center;
          gap: 8px;
          color: #9ca3af;
          font-size: 13px;
          margin-bottom: 8px;
        }

        .midi-player-card .midi-icon {
          font-size: 16px;
          color: #60a5fa;
        }

        .midi-player-card .midi-header-text {
          opacity: 0.9;
        }

        .midi-player-card .midi-notes-display {
          background: #0d1117;
          border-radius: 4px;
          padding: 8px 12px;
          margin-bottom: 10px;
          overflow-x: auto;
        }

        .midi-player-card .midi-notes-display code {
          font-family: 'Fira Code', 'Monaco', 'Consolas', monospace;
          font-size: 13px;
          color: #e5c07b;
          white-space: pre-wrap;
          word-break: break-word;
        }

        .midi-player-card .midi-progress-container {
          height: 4px;
          background: #374151;
          border-radius: 2px;
          margin-bottom: 10px;
          overflow: hidden;
        }

        .midi-player-card .midi-progress-bar {
          height: 100%;
          background: linear-gradient(90deg, #60a5fa, #818cf8);
          border-radius: 2px;
          transition: width 0.1s linear;
        }

        .midi-player-card .midi-controls {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 8px;
        }

        .midi-player-card .midi-button {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 6px 14px;
          border: none;
          border-radius: 6px;
          font-size: 13px;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.15s ease;
        }

        .midi-player-card .midi-button:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .midi-player-card .midi-play {
          background: #22c55e;
          color: white;
        }

        .midi-player-card .midi-play:hover:not(:disabled) {
          background: #16a34a;
        }

        .midi-player-card .midi-stop {
          background: #ef4444;
          color: white;
        }

        .midi-player-card .midi-stop:hover {
          background: #dc2626;
        }

        .midi-player-card .midi-status {
          font-size: 13px;
          font-weight: 500;
        }

        .midi-player-card .midi-done {
          color: #22c55e;
        }

        .midi-player-card .midi-error {
          color: #ef4444;
          max-width: 200px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .midi-player-card .midi-result {
          font-size: 12px;
          color: #9ca3af;
          padding: 4px 0;
        }
      `}</style>
    </BaseToolCard>
  );
}

export default MidiPlayerCard;
