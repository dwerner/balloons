import React, { useState, useEffect } from 'react';
import type { BalloonsClient, TurnSnapshot, SessionHistoryChunkEvent, SessionHistoryCompleteEvent, Unsubscribe } from '../../../../generated/balloons-client';
import { MarkdownContent } from '../../MarkdownContent';
import { useAutoScroll } from '../../hooks';
import { ScrollToBottom } from '../ScrollToBottom';
import './SimpleTurnsView.css';

// Create a debug logger that uses the client's WebSocket connection
function createDebugLogger(client: BalloonsClient) {
  return (message: string, data?: Record<string, unknown>) => {
    console.log('[SimpleTurnsView]', message, data);
    if (client.isConnected) {
      client.debugLog.info(message, 'web.SimpleTurnsView', '', data ?? null).catch(() => {});
    }
  };
}

interface SimpleTurnsViewProps {
  sessionId: string | null;
  client: BalloonsClient;
}

// Helper to load turns via subscription API
async function loadTurnsViaSubscription(
  client: BalloonsClient,
  sessionId: string,
  clientId: string
): Promise<StreamingTurn[]> {
  return new Promise((resolve, reject) => {
    const collectedTurns: Map<string, TurnSnapshot> = new Map();
    const handlers: Unsubscribe[] = [];
    let timeoutId: ReturnType<typeof setTimeout>;

    const cleanup = () => {
      handlers.forEach(h => h());
      clearTimeout(timeoutId);
    };

    handlers.push(
      client.sessionData.sessionDataHistoryChunk((event: SessionHistoryChunkEvent) => {
        if (event.sessionId !== sessionId) return;
        for (const turn of event.turns || []) {
          if (turn.turnId) {
            collectedTurns.set(turn.turnId, turn);
          }
        }
      })
    );

    handlers.push(
      client.sessionData.sessionDataHistoryComplete((event: SessionHistoryCompleteEvent) => {
        if (event.sessionId !== sessionId) return;
        cleanup();

        const snapshots = Array.from(collectedTurns.values())
          .sort((a, b) => (a.order ?? 0) - (b.order ?? 0));

        const turns: StreamingTurn[] = snapshots.map((s, idx) => {
          const block = s.contentBlock;
          const blockType = block?.type || 'text';
          let content = '';
          let toolUse: StreamingTurn['toolUse'] = undefined;
          let toolResult: StreamingTurn['toolResult'] = undefined;

          if (blockType === 'text' && block && 'text' in block) {
            content = (block as { text?: string }).text || '';
          } else if (blockType === 'tool_use' && block) {
            const tb = block as { id?: string; name?: string; input?: unknown };
            content = JSON.stringify(tb.input || {});
            toolUse = {
              toolUseId: tb.id || '',
              toolName: tb.name || '',
              toolInput: tb.input as Record<string, unknown>,
            };
          } else if (blockType === 'tool_result' && block) {
            const tr = block as { toolUseId?: string; content?: unknown; isError?: boolean };
            content = String(tr.content || '');
            toolResult = {
              toolUseId: tr.toolUseId || '',
              content,
              isError: tr.isError || false,
            };
          }

          return {
            idx,
            role: s.role,
            content,
            contentBlockType: blockType,
            exchangeId: s.exchangeId ?? undefined,
            streaming: s.streaming,
            toolUse,
            toolResult,
          };
        });

        resolve(turns);
      })
    );

    timeoutId = setTimeout(() => {
      cleanup();
      reject(new Error('Timeout waiting for history'));
    }, 30000);

    client.sessionData.subscribeSession(sessionId, clientId).catch(err => {
      cleanup();
      reject(err);
    });
  });
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
  // Create debug logger using the client's WebSocket connection
  const debugLog = createDebugLogger(client);

  // Turns loaded from server (source of truth)
  const [turns, setTurns] = useState<StreamingTurn[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);

  // Robust autoscroll: follows stream, pauses on user scroll-up, resumes on click
  const { scrollRef, isFollowing, scrollToBottom } = useAutoScroll({
    deps: [turns],
    threshold: 150,
    enabled: true,
  });

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
        const clientId = `simple-view-${Date.now()}`;
        const mapped = await loadTurnsViaSubscription(client, sessionId, clientId);
        debugLog(`Initial load: ${mapped.length} turns`);
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

        try {
          const clientId = `simple-reload-${Date.now()}`;
          const mapped = await loadTurnsViaSubscription(client, sessionId, clientId);
          debugLog(`TASK_COMPLETED loaded ${mapped.length} turns`);
          setTurns(mapped);
        } catch (err) {
          debugLog(`TASK_COMPLETED reload failed: ${err}`);
        }
      })
    );

    return () => {
      unsubscribers.forEach(unsub => unsub());
    };
  }, [sessionId, client]);

  // Track streaming state from events
  useEffect(() => {
    if (!sessionId || !client) return;

    const unsubscribers: Array<() => void> = [];

    unsubscribers.push(
      client.sessionData.sessionDataStreamStarted((event) => {
        if (event.sessionId === sessionId) {
          setIsStreaming(true);
        }
      })
    );

    unsubscribers.push(
      client.sessionData.sessionDataStreamDone((event) => {
        if (event.sessionId === sessionId) {
          setIsStreaming(false);
        }
      })
    );

    unsubscribers.push(
      client.sessionData.sessionDataStreamError((event) => {
        if (event.sessionId === sessionId) {
          setIsStreaming(false);
        }
      })
    );

    return () => {
      unsubscribers.forEach(unsub => unsub());
    };
  }, [sessionId, client]);

  // Show scroll indicator when streaming and user scrolled away
  const showScrollIndicator = isStreaming && !isFollowing;

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
    <div className="simple-turns-view-container" ref={scrollRef}>
      <div className="simple-turns-view">
        <div className="simple-turns-header">
          Simple Turns View ({turns.length} turns)
        </div>
        <div className="simple-turns-list">
          {turns.map(turn => (
            <TurnCard key={turn.idx} turn={turn} />
          ))}
        </div>
      </div>
      <ScrollToBottom
        visible={showScrollIndicator}
        onClick={scrollToBottom}
        isStreaming={isStreaming}
      />
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

  // Fork proposal - rendered as interactive card
  // TODO: Import and use ForkProposalCard from StreamingTurnsView
  if (contentBlockType === 'fork_proposal') {
    return (
      <div className="turn-card system fork-proposal">
        <div className="turn-card-header">
          <span className="turn-icon">⑂</span>
          <span className="turn-label">Fork Proposal</span>
        </div>
        <div className="turn-card-body">
          <div className="fork-proposal-notice">
            ⚠️ Fork proposal cards are only fully interactive in Streaming view.
            <br />
            Switch to <strong>Streaming</strong> view (button above) to accept/reject.
          </div>
          <pre className="fork-proposal-raw">{content}</pre>
        </div>
      </div>
    );
  }

  // Merge proposal - similar treatment
  if (contentBlockType === 'merge_proposal') {
    return (
      <div className="turn-card system merge-proposal">
        <div className="turn-card-header">
          <span className="turn-icon">⤴</span>
          <span className="turn-label">Merge Proposal</span>
        </div>
        <div className="turn-card-body">
          <div className="merge-proposal-notice">
            ⚠️ Merge proposal cards are only fully interactive in Streaming view.
            <br />
            Switch to <strong>Streaming</strong> view (button above) to accept/reject.
          </div>
          <pre className="merge-proposal-raw">{content}</pre>
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
