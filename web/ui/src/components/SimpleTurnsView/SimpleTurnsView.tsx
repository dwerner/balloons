import React, { useState, useEffect, useRef } from 'react';
import type { BalloonsClient } from '../../../../generated/balloons-client';
import { MarkdownContent } from '../../MarkdownContent';
import './SimpleTurnsView.css';

// Debug logger that sends to server (v2 - focused on getTurns vs streaming reconciliation)
function debugLog(message: string, data?: Record<string, unknown>) {
  const logData = { message, ...data, timestamp: new Date().toISOString() };
  console.log('[SimpleTurnsView]', message, data);
  fetch('/debug-log', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(logData),
  }).catch(() => { /* ignore */ });
}

interface SimpleTurnsViewProps {
  sessionId: string | null;
  client: BalloonsClient;
}

interface StreamingTurn {
  idx: number;
  role: string;
  content: string;
  contentBlockType?: string;
  exchangeId?: string;
  streaming: boolean;
  toolUse?: {
    toolUseId: string;
    toolName: string;
    toolInput?: Record<string, unknown>;
  };
  toolResult?: {
    toolUseId: string;
    content: string;
    isError: boolean;
  };
}

/**
 * SimpleTurnsView - A fresh implementation of turns rendering
 *
 * Design principles:
 * 1. Load complete turn data from server on session change
 * 2. During streaming, only UPDATE existing turns or ADD new ones
 * 3. Never show incomplete/placeholder turns - wait for actual data
 * 4. Keep it simple - no complex filtering or transformation
 */
export function SimpleTurnsView({ sessionId, client }: SimpleTurnsViewProps) {
  // Turns loaded from server (source of truth)
  const [turns, setTurns] = useState<StreamingTurn[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Load turns from server when session changes
  useEffect(() => {
    if (!sessionId) {
      setTurns([]);
      return;
    }

    const loadTurns = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const serverTurns = await client.tree.getTurns(sessionId);
        // DEBUG: Log content lengths from server on initial load
        debugLog(`Initial load: ${serverTurns.length} turns`);
        serverTurns.forEach(t => {
          if (t.role === 'assistant' && t.content && t.content.length > 500) {
            debugLog(`INITIAL Turn ${t.idx}: ${t.content.length} chars`, {
              turnIdx: t.idx,
              contentLength: t.content.length,
              first100: t.content.slice(0, 100),
              last100: t.content.slice(-100),
            });
          }
        });
        const mapped: StreamingTurn[] = serverTurns.map(t => ({
          idx: t.idx,
          role: t.role,
          content: t.content || '',
          contentBlockType: t.contentBlockType,
          exchangeId: t.exchangeId ?? undefined,
          streaming: t.streaming || false,
          toolUse: t.toolUse ? {
            toolUseId: t.toolUse.toolUseId,
            toolName: t.toolUse.toolName,
            toolInput: t.toolUse.toolInput,
          } : undefined,
          toolResult: t.toolResult ? {
            toolUseId: t.toolResult.toolUseId,
            content: t.toolResult.content || '',
            isError: t.toolResult.isError || false,
          } : undefined,
        }));
        setTurns(mapped);
      } catch (err) {
        setError(`Failed to load turns: ${err}`);
      } finally {
        setIsLoading(false);
      }
    };

    loadTurns();
  }, [sessionId, client]);

  // Subscribe to streaming events
  useEffect(() => {
    if (!sessionId) return;

    const unsubscribers: (() => void)[] = [];

    // Turn started - create placeholder turn
    unsubscribers.push(
      client.tasks.onTurnStarted((data) => {
        if (data.sessionId !== sessionId) return;

        // Skip events with undefined turnIndex (server bug)
        if (data.turnIndex === undefined || data.turnIndex === null) {
          debugLog(`TURN_STARTED skipping undefined turnIndex`, {
            event: 'turn_started_skip',
            role: data.role,
            exchangeId: data.exchangeId,
            rawTurnIndex: String(data.turnIndex),
            typeofTurnIndex: typeof data.turnIndex,
          });
          return;
        }

        // Also skip if turnIndex is not a valid number
        if (typeof data.turnIndex !== 'number' || isNaN(data.turnIndex)) {
          debugLog(`TURN_STARTED skipping invalid turnIndex`, {
            event: 'turn_started_skip_invalid',
            role: data.role,
            rawTurnIndex: String(data.turnIndex),
            typeofTurnIndex: typeof data.turnIndex,
          });
          return;
        }

        debugLog(`TURN_STARTED turn ${data.turnIndex}`, {
          event: 'turn_started',
          turnIndex: data.turnIndex,
          role: data.role,
          turnType: data.turnType,
          exchangeId: data.exchangeId,
        });

        setTurns(prev => {
          const existing = prev.find(t => t.idx === data.turnIndex);
          if (existing) {
            debugLog(`TURN_STARTED turn ${data.turnIndex} already exists`, {
              turnIndex: data.turnIndex,
              existingRole: existing.role,
            });
            return prev;
          }

          const newTurn: StreamingTurn = {
            idx: data.turnIndex,
            role: data.role,
            content: '',
            contentBlockType: data.turnType ?? undefined,
            exchangeId: data.exchangeId,
            streaming: true,
          };
          debugLog(`TURN_STARTED creating turn ${data.turnIndex}`, {
            turnIndex: data.turnIndex,
            role: data.role,
            prevTurnCount: prev.length,
          });
          return [...prev, newTurn].sort((a, b) => a.idx - b.idx);
        });
      })
    );

    // Content delta - update turn content
    unsubscribers.push(
      client.tasks.onContentDelta((data) => {
        if (data.sessionId !== sessionId) return;

        setTurns(prev => {
          const turnIdx = prev.findIndex(t => t.idx === data.turnIndex);
          const existing = prev[turnIdx];
          if (turnIdx >= 0 && existing) {
            // Update existing turn
            debugLog(`DELTA update existing turn ${data.turnIndex}`, {
              event: 'content_delta',
              turnIndex: data.turnIndex,
              existingLen: existing.content.length,
              accumulatedLen: data.accumulated.length,
              delta: data.accumulated.length - existing.content.length,
              prevTurnCount: prev.length,
            });
            const updated = [...prev];
            updated[turnIdx] = {
              idx: existing.idx,
              role: existing.role,
              content: data.accumulated,
              contentBlockType: existing.contentBlockType,
              exchangeId: existing.exchangeId,
              streaming: true,
              toolUse: existing.toolUse,
              toolResult: existing.toolResult,
            };
            return updated;
          } else {
            // New turn - add it
            debugLog(`DELTA new turn ${data.turnIndex}`, {
              event: 'content_delta_new',
              turnIndex: data.turnIndex,
              accumulatedLen: data.accumulated.length,
              prevTurnCount: prev.length,
              existingIndices: prev.map(t => t.idx),
            });
            const newTurn: StreamingTurn = {
              idx: data.turnIndex,
              role: 'assistant',
              content: data.accumulated,
              contentBlockType: 'text',
              exchangeId: data.exchangeId,
              streaming: true,
            };
            return [...prev, newTurn].sort((a, b) => a.idx - b.idx);
          }
        });
      })
    );

    // Turn finished - finalize turn
    unsubscribers.push(
      client.tasks.onTurnFinished((data) => {
        if (data.sessionId !== sessionId) return;

        debugLog(`TURN_FINISHED turn ${data.turnIndex}`, {
          event: 'turn_finished',
          turnIndex: data.turnIndex,
          role: data.role,
          contentLen: data.content?.length ?? 0,
        });

        setTurns(prev => {
          const turnIdx = prev.findIndex(t => t.idx === data.turnIndex);
          const existing = prev[turnIdx];
          if (turnIdx >= 0 && existing) {
            debugLog(`TURN_FINISHED updating existing`, {
              turnIndex: data.turnIndex,
              existingLen: existing.content.length,
              newLen: data.content?.length ?? 0,
              diff: (data.content?.length ?? 0) - existing.content.length,
            });
            const updated = [...prev];
            updated[turnIdx] = {
              idx: existing.idx,
              role: data.role,
              content: data.content,
              contentBlockType: existing.contentBlockType,
              exchangeId: existing.exchangeId,
              streaming: false,
              toolUse: existing.toolUse,
              toolResult: existing.toolResult,
            };
            return updated;
          }
          debugLog(`TURN_FINISHED turn not found!`, {
            turnIndex: data.turnIndex,
            existingIndices: prev.map(t => t.idx),
          });
          return prev;
        });
      })
    );

    // Tool use started - add/update turn with tool info
    // NOTE: Don't overwrite existing turns with text content - tool_use events
    // may arrive with the same turnIndex as the main assistant text turn due to
    // server-side race conditions. Only create new turn if it doesn't exist.
    unsubscribers.push(
      client.tasks.onToolUseStarted((data) => {
        if (data.sessionId !== sessionId) return;

        debugLog(`TOOL_USE_STARTED ${data.toolName}`, {
          event: 'tool_use_started',
          turnIndex: data.turnIndex,
          toolName: data.toolName,
          toolUseId: data.toolUseId,
        });

        setTurns(prev => {
          // Check if we already have a tool use with this toolUseId
          const existingToolUse = prev.find(t => t.toolUse?.toolUseId === data.toolUseId);
          if (existingToolUse) {
            debugLog(`TOOL_USE_STARTED skipping - toolUseId ${data.toolUseId} already exists`, {
              turnIndex: data.turnIndex,
              existingIdx: existingToolUse.idx,
            });
            return prev;
          }

          // Check if the turnIndex already has content (text turn) - don't overwrite
          const existingTurn = prev.find(t => t.idx === data.turnIndex);
          if (existingTurn && (existingTurn.content || existingTurn.contentBlockType === 'text')) {
            debugLog(`TOOL_USE_STARTED skipping - turn ${data.turnIndex} is a text turn`, {
              turnIndex: data.turnIndex,
              existingContentLen: existingTurn.content?.length ?? 0,
              contentBlockType: existingTurn.contentBlockType,
            });
            return prev;
          }

          // Create or update the turn
          if (existingTurn) {
            const turnIdx = prev.findIndex(t => t.idx === data.turnIndex);
            const updated = [...prev];
            updated[turnIdx] = {
              idx: existingTurn.idx,
              role: existingTurn.role,
              content: existingTurn.content,
              contentBlockType: 'tool_use',
              exchangeId: existingTurn.exchangeId,
              streaming: true,
              toolUse: {
                toolUseId: data.toolUseId,
                toolName: data.toolName,
                toolInput: {},
              },
              toolResult: existingTurn.toolResult,
            };
            return updated;
          } else {
            // New tool use turn
            const newTurn: StreamingTurn = {
              idx: data.turnIndex,
              role: 'assistant',
              content: '',
              contentBlockType: 'tool_use',
              exchangeId: data.exchangeId,
              streaming: true,
              toolUse: {
                toolUseId: data.toolUseId,
                toolName: data.toolName,
                toolInput: {},
              },
            };
            return [...prev, newTurn].sort((a, b) => a.idx - b.idx);
          }
        });
      })
    );

    // Tool use complete - update with full input
    unsubscribers.push(
      client.tasks.onToolUse((data) => {
        if (data.sessionId !== sessionId) return;

        setTurns(prev => {
          const turnIdx = prev.findIndex(t =>
            t.toolUse?.toolUseId === data.toolUseId
          );
          const existing = prev[turnIdx];
          if (turnIdx >= 0 && existing && existing.toolUse) {
            const updated = [...prev];
            updated[turnIdx] = {
              idx: existing.idx,
              role: existing.role,
              content: existing.content,
              contentBlockType: existing.contentBlockType,
              exchangeId: existing.exchangeId,
              streaming: existing.streaming,
              toolUse: {
                toolUseId: existing.toolUse.toolUseId,
                toolName: existing.toolUse.toolName,
                toolInput: data.toolInput,
              },
              toolResult: existing.toolResult,
            };
            return updated;
          }
          return prev;
        });
      })
    );

    // Tool result - add result turn
    unsubscribers.push(
      client.tasks.onToolResult((data) => {
        if (data.sessionId !== sessionId) return;

        debugLog(`TOOL_RESULT turn ${data.turnIndex}`, {
          event: 'tool_result',
          turnIndex: data.turnIndex,
          toolUseId: data.toolUseId,
          resultLen: data.result?.length ?? 0,
          isError: data.isError,
        });

        setTurns(prev => {
          const turnIdx = prev.findIndex(t => t.idx === data.turnIndex);
          const existing = prev[turnIdx];
          if (turnIdx >= 0 && existing) {
            const updated = [...prev];
            updated[turnIdx] = {
              idx: existing.idx,
              role: 'tool',
              content: data.result,
              contentBlockType: 'tool_result',
              exchangeId: existing.exchangeId,
              streaming: false,
              toolUse: existing.toolUse,
              toolResult: {
                toolUseId: data.toolUseId,
                content: data.result,
                isError: data.isError,
              },
            };
            return updated;
          } else {
            const newTurn: StreamingTurn = {
              idx: data.turnIndex,
              role: 'tool',
              content: data.result,
              contentBlockType: 'tool_result',
              exchangeId: data.exchangeId,
              streaming: false,
              toolResult: {
                toolUseId: data.toolUseId,
                content: data.result,
                isError: data.isError,
              },
            };
            return [...prev, newTurn].sort((a, b) => a.idx - b.idx);
          }
        });
      })
    );

    // Task completed - reload turns to get final state
    unsubscribers.push(
      client.tasks.onTaskCompleted(async (data) => {
        if (data.sessionId !== sessionId) return;

        debugLog('TASK_COMPLETED reloading...', { event: 'task_completed' });

        // Capture current state for comparison
        setTurns(prev => {
          debugLog('TASK_COMPLETED current state before reload', {
            turnCount: prev.length,
            turns: prev.map(t => ({ idx: t.idx, role: t.role, len: t.content.length, streaming: t.streaming })),
          });
          return prev;
        });

        const serverTurns = await client.tree.getTurns(sessionId);
        // Log the last 10 turns with full details to debug missing turns
        const lastTurns = serverTurns.slice(-10);
        debugLog(`TASK_COMPLETED getTurns returned ${serverTurns.length} turns, last 10:`, {
          event: 'task_completed_reload',
          totalTurns: serverTurns.length,
          last10: lastTurns.map(t => ({
            idx: t.idx,
            role: t.role,
            contentBlockType: t.contentBlockType,
            len: t.content?.length ?? 0,
            contentPreview: t.content?.slice(0, 80) ?? '',
            hasToolUse: !!t.toolUse,
            hasToolResult: !!t.toolResult,
            toolName: t.toolUse?.toolName,
          })),
        });

        const mapped: StreamingTurn[] = serverTurns.map(t => ({
          idx: t.idx,
          role: t.role,
          content: t.content || '',
          contentBlockType: t.contentBlockType,
          exchangeId: t.exchangeId ?? undefined,
          streaming: false,
          toolUse: t.toolUse ? {
            toolUseId: t.toolUse.toolUseId,
            toolName: t.toolUse.toolName,
            toolInput: t.toolUse.toolInput,
          } : undefined,
          toolResult: t.toolResult ? {
            toolUseId: t.toolResult.toolUseId,
            content: t.toolResult.content || '',
            isError: t.toolResult.isError || false,
          } : undefined,
        }));
        setTurns(mapped);
      })
    );

    return () => {
      unsubscribers.forEach(unsub => unsub());
    };
  }, [sessionId, client]);

  // Auto-scroll to bottom when new content arrives
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [turns]);

  if (!sessionId) {
    return <div className="simple-turns-view empty">No session selected</div>;
  }

  if (isLoading) {
    return <div className="simple-turns-view loading">Loading turns...</div>;
  }

  if (error) {
    return <div className="simple-turns-view error">{error}</div>;
  }

  return (
    <div className="simple-turns-view" ref={scrollRef}>
      <div className="simple-turns-header">
        Simple Turns View ({turns.length} turns)
      </div>
      <div className="simple-turns-list">
        {turns.map(turn => (
          <TurnCard key={turn.idx} turn={turn} />
        ))}
      </div>
    </div>
  );
}

function TurnCard({ turn }: { turn: StreamingTurn }) {
  const { role, content, contentBlockType, streaming, toolUse, toolResult } = turn;

  // Determine display type
  const isToolUse = contentBlockType === 'tool_use' || toolUse;
  const isToolResult = contentBlockType === 'tool_result' || toolResult;

  if (isToolUse && toolUse) {
    return (
      <div className={`turn-card tool-use ${streaming ? 'streaming' : ''}`}>
        <div className="turn-card-header">
          <span className="turn-icon">🔧</span>
          <span className="turn-label">{toolUse.toolName}</span>
          {streaming && <span className="streaming-indicator">●</span>}
        </div>
        {toolUse.toolInput && Object.keys(toolUse.toolInput).length > 0 && (
          <div className="turn-card-body">
            <pre className="tool-input">{JSON.stringify(toolUse.toolInput, null, 2)}</pre>
          </div>
        )}
      </div>
    );
  }

  if (isToolResult && toolResult) {
    return (
      <div className={`turn-card tool-result ${toolResult.isError ? 'error' : ''}`}>
        <div className="turn-card-header">
          <span className="turn-icon">{toolResult.isError ? '❌' : '✓'}</span>
          <span className="turn-label">Result</span>
        </div>
        <div className="turn-card-body">
          <pre className="tool-result-content">
            {toolResult.content.slice(0, 500)}
            {toolResult.content.length > 500 && '...'}
          </pre>
        </div>
      </div>
    );
  }

  if (role === 'user') {
    return (
      <div className="turn-card user">
        <div className="turn-card-header">
          <span className="turn-icon">👤</span>
          <span className="turn-label">User</span>
        </div>
        <div className="turn-card-body">
          {content}
        </div>
      </div>
    );
  }

  if (role === 'assistant') {
    return (
      <div className={`turn-card assistant ${streaming ? 'streaming' : ''}`}>
        <div className="turn-card-header">
          <span className="turn-icon">🤖</span>
          <span className="turn-label">Assistant</span>
          {streaming && <span className="streaming-indicator">●</span>}
        </div>
        <div className="turn-card-body">
          {content ? (
            <MarkdownContent content={content} />
          ) : streaming ? (
            <span className="thinking">Thinking...</span>
          ) : null}
        </div>
      </div>
    );
  }

  // Fallback for other roles
  return (
    <div className="turn-card other">
      <div className="turn-card-header">
        <span className="turn-icon">📄</span>
        <span className="turn-label">{role}</span>
      </div>
      <div className="turn-card-body">
        {content}
      </div>
    </div>
  );
}

export default SimpleTurnsView;
