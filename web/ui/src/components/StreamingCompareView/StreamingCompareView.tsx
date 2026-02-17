import React, { useState, useEffect, useRef, useCallback } from 'react';
import type { BalloonsClient } from '../../../../generated/balloons-client';
import './StreamingCompareView.css';

interface StreamingCompareViewProps {
  sessionId: string | null;
  client: BalloonsClient;
  onCopyToInput?: (content: string) => void;
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

interface ServerTurn {
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

interface Diff {
  field: string;
  streaming: unknown;
  server: unknown;
}

interface EventLog {
  timestamp: number;
  event: string;
  data: Record<string, unknown>;
}

// Safe helper to check if client is connected without throwing
function isClientConnected(client: BalloonsClient): boolean {
  try {
    return client.isConnected;
  } catch {
    return false;
  }
}

/**
 * StreamingCompareView - Debug tool to compare streaming state vs server state
 *
 * Shows side-by-side:
 * - Left: Turns built from streaming events (NO reload on task complete)
 * - Right: Turns from getTurns() server call
 * - Bottom: Diffs between the two
 * - Event log: All streaming events received
 */
export function StreamingCompareView({ sessionId, client, onCopyToInput }: StreamingCompareViewProps) {
  // Track connection state locally to avoid issues with client getters
  const [isConnected, setIsConnected] = useState(() => isClientConnected(client));
  // Streaming state - built purely from events, NO server reload
  const [streamingTurns, setStreamingTurns] = useState<StreamingTurn[]>([]);

  // Server state - loaded from getTurns()
  const [serverTurns, setServerTurns] = useState<ServerTurn[]>([]);

  // Event log
  const [eventLog, setEventLog] = useState<EventLog[]>([]);

  // Diffs
  const [diffs, setDiffs] = useState<Map<number, Diff[]>>(new Map());

  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoRefreshServer, setAutoRefreshServer] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const eventLogRef = useRef<HTMLDivElement>(null);

  // Monitor connection state
  useEffect(() => {
    const checkConnection = () => {
      const connected = isClientConnected(client);
      setIsConnected(connected);
      if (!connected) {
        setError('Not connected');
      }
    };

    // Check immediately
    checkConnection();

    // Check periodically (client doesn't expose connection events directly)
    const interval = setInterval(checkConnection, 1000);
    return () => clearInterval(interval);
  }, [client]);

  // Log an event
  const logEvent = useCallback((event: string, data: Record<string, unknown>) => {
    setEventLog(prev => [...prev.slice(-200), {
      timestamp: Date.now(),
      event,
      data,
    }]);
  }, []);

  // Load server turns
  const loadServerTurns = useCallback(async () => {
    if (!sessionId || !isConnected) return;
    try {
      const turns = await client.tree.getTurns(sessionId);
      const mapped: ServerTurn[] = turns.map(t => ({
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
      setServerTurns(mapped);
      logEvent('SERVER_LOAD', { turnCount: mapped.length });
    } catch (err) {
      setError(`Failed to load server turns: ${err}`);
    }
  }, [sessionId, client, isConnected, logEvent]);

  // Reset state when session changes
  useEffect(() => {
    if (!sessionId || !isConnected) {
      setStreamingTurns([]);
      setServerTurns([]);
      setEventLog([]);
      setDiffs(new Map());
      return;
    }

    setIsLoading(true);
    setError(null);
    setStreamingTurns([]);
    setEventLog([]);

    // Load initial server state
    loadServerTurns().finally(() => setIsLoading(false));
  }, [sessionId, isConnected, loadServerTurns]);

  // Compute diffs whenever turns change
  useEffect(() => {
    const newDiffs = new Map<number, Diff[]>();

    // Get all turn indices from both sides
    const allIndices = new Set([
      ...streamingTurns.map(t => t.idx),
      ...serverTurns.map(t => t.idx),
    ]);

    for (const idx of allIndices) {
      const streamTurn = streamingTurns.find(t => t.idx === idx);
      const serverTurn = serverTurns.find(t => t.idx === idx);
      const turnDiffs: Diff[] = [];

      if (!streamTurn && serverTurn) {
        turnDiffs.push({ field: 'MISSING_IN_STREAMING', streaming: null, server: serverTurn });
      } else if (streamTurn && !serverTurn) {
        turnDiffs.push({ field: 'EXTRA_IN_STREAMING', streaming: streamTurn, server: null });
      } else if (streamTurn && serverTurn) {
        // Compare fields
        if (streamTurn.role !== serverTurn.role) {
          turnDiffs.push({ field: 'role', streaming: streamTurn.role, server: serverTurn.role });
        }
        if (streamTurn.content !== serverTurn.content) {
          turnDiffs.push({ field: 'content', streaming: streamTurn.content?.slice(0, 100), server: serverTurn.content?.slice(0, 100) });
        }
        if (streamTurn.contentBlockType !== serverTurn.contentBlockType) {
          turnDiffs.push({ field: 'contentBlockType', streaming: streamTurn.contentBlockType, server: serverTurn.contentBlockType });
        }
        if (streamTurn.streaming !== serverTurn.streaming) {
          turnDiffs.push({ field: 'streaming', streaming: streamTurn.streaming, server: serverTurn.streaming });
        }
        // Compare toolUse
        const streamToolUse = JSON.stringify(streamTurn.toolUse);
        const serverToolUse = JSON.stringify(serverTurn.toolUse);
        if (streamToolUse !== serverToolUse) {
          turnDiffs.push({ field: 'toolUse', streaming: streamTurn.toolUse, server: serverTurn.toolUse });
        }
        // Compare toolResult
        const streamToolResult = JSON.stringify(streamTurn.toolResult);
        const serverToolResult = JSON.stringify(serverTurn.toolResult);
        if (streamToolResult !== serverToolResult) {
          turnDiffs.push({ field: 'toolResult', streaming: streamTurn.toolResult, server: serverTurn.toolResult });
        }
      }

      if (turnDiffs.length > 0) {
        newDiffs.set(idx, turnDiffs);
      }
    }

    setDiffs(newDiffs);
  }, [streamingTurns, serverTurns]);

  // Subscribe to streaming events - NO reload on task complete
  useEffect(() => {
    if (!sessionId || !isConnected) return;

    const unsubscribers: (() => void)[] = [];

    // onTurnStarted - create placeholder turn
    unsubscribers.push(
      client.tasks.onTurnStarted((data) => {
        if (data.sessionId !== sessionId) return;
        logEvent('onTurnStarted', { turnIndex: data.turnIndex, role: data.role, exchangeId: data.exchangeId, turnType: data.turnType });

        setStreamingTurns(prev => {
          const existing = prev.find(t => t.idx === data.turnIndex);
          if (existing) return prev;

          const newTurn: StreamingTurn = {
            idx: data.turnIndex,
            role: data.role,
            content: '',
            contentBlockType: data.turnType ?? undefined,
            exchangeId: data.exchangeId,
            streaming: true,
          };
          return [...prev, newTurn].sort((a, b) => a.idx - b.idx);
        });
      })
    );

    // Content delta - update turn content
    unsubscribers.push(
      client.tasks.onContentDelta((data) => {
        if (data.sessionId !== sessionId) return;
        logEvent('onContentDelta', { turnIndex: data.turnIndex, deltaLen: data.delta?.length, accumulatedLen: data.accumulated?.length });

        setStreamingTurns(prev => {
          const turnIdx = prev.findIndex(t => t.idx === data.turnIndex);
          const existing = prev[turnIdx];
          if (turnIdx >= 0 && existing) {
            const updated = [...prev];
            updated[turnIdx] = {
              ...existing,
              content: data.accumulated,
              streaming: true,
            };
            return updated;
          } else {
            // Create turn if it doesn't exist
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
        logEvent('onTurnFinished', { turnIndex: data.turnIndex, role: data.role, contentLen: data.content?.length });

        setStreamingTurns(prev => {
          const turnIdx = prev.findIndex(t => t.idx === data.turnIndex);
          const existing = prev[turnIdx];
          if (turnIdx >= 0 && existing) {
            const updated = [...prev];
            updated[turnIdx] = {
              ...existing,
              role: data.role,
              content: data.content,
              streaming: false,
            };
            return updated;
          } else {
            // Create turn if it doesn't exist
            const newTurn: StreamingTurn = {
              idx: data.turnIndex,
              role: data.role,
              content: data.content,
              streaming: false,
            };
            return [...prev, newTurn].sort((a, b) => a.idx - b.idx);
          }
        });
      })
    );

    // Tool use started - add/update turn with tool info
    unsubscribers.push(
      client.tasks.onToolUseStarted((data) => {
        if (data.sessionId !== sessionId) return;
        logEvent('onToolUseStarted', { turnIndex: data.turnIndex, toolName: data.toolName, toolUseId: data.toolUseId });

        setStreamingTurns(prev => {
          const turnIdx = prev.findIndex(t => t.idx === data.turnIndex);
          const existing = prev[turnIdx];
          if (turnIdx >= 0 && existing) {
            const updated = [...prev];
            updated[turnIdx] = {
              ...existing,
              contentBlockType: 'tool_use',
              streaming: true,
              toolUse: {
                toolUseId: data.toolUseId,
                toolName: data.toolName,
                toolInput: {},
              },
            };
            return updated;
          } else {
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
        logEvent('onToolUse', { toolUseId: data.toolUseId, toolName: data.toolName, hasInput: !!data.toolInput });

        setStreamingTurns(prev => {
          const turnIdx = prev.findIndex(t => t.toolUse?.toolUseId === data.toolUseId);
          const existing = prev[turnIdx];
          if (turnIdx >= 0 && existing && existing.toolUse) {
            const updated = [...prev];
            updated[turnIdx] = {
              ...existing,
              toolUse: {
                ...existing.toolUse,
                toolInput: data.toolInput,
              },
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
        logEvent('onToolResult', { turnIndex: data.turnIndex, toolUseId: data.toolUseId, isError: data.isError, resultLen: data.result?.length });

        setStreamingTurns(prev => {
          const turnIdx = prev.findIndex(t => t.idx === data.turnIndex);
          const existing = prev[turnIdx];
          if (turnIdx >= 0 && existing) {
            const updated = [...prev];
            updated[turnIdx] = {
              ...existing,
              role: 'tool',
              content: data.result,
              contentBlockType: 'tool_result',
              streaming: false,
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

    // Task completed - DON'T reload, just log
    unsubscribers.push(
      client.tasks.onTaskCompleted(async (data) => {
        if (data.sessionId !== sessionId) return;
        logEvent('onTaskCompleted', { taskId: data.taskId, NO_RELOAD: true });

        // Only refresh server side if auto-refresh is enabled
        if (autoRefreshServer) {
          await loadServerTurns();
        }
      })
    );

    // Task cancelled
    unsubscribers.push(
      client.tasks.onTaskCancelled((data) => {
        if (data.sessionId !== sessionId) return;
        logEvent('onTaskCancelled', { taskId: data.taskId });
      })
    );

    // Task error
    unsubscribers.push(
      client.tasks.onTaskError((data) => {
        if (data.sessionId !== sessionId) return;
        logEvent('onTaskError', { taskId: data.taskId, error: data.error });
      })
    );

    return () => {
      unsubscribers.forEach(unsub => unsub());
    };
  }, [sessionId, client, isConnected, logEvent, autoRefreshServer, loadServerTurns]);

  // Auto-scroll event log
  useEffect(() => {
    if (eventLogRef.current) {
      eventLogRef.current.scrollTop = eventLogRef.current.scrollHeight;
    }
  }, [eventLog]);

  const clearEventLog = useCallback(() => {
    setEventLog([]);
  }, []);

  const resetStreamingState = useCallback(() => {
    setStreamingTurns([]);
    logEvent('RESET_STREAMING', {});
  }, [logEvent]);

  // Sync streaming state with server state (set same baseline)
  const syncWithServer = useCallback(() => {
    setStreamingTurns(serverTurns.map(t => ({ ...t })));
    logEvent('SYNC_WITH_SERVER', { turnCount: serverTurns.length });
  }, [serverTurns, logEvent]);

  // Package diffs as JSON for sending to LLM
  const packageDiffsAsJson = useCallback(() => {
    const diffData = {
      sessionId,
      timestamp: new Date().toISOString(),
      stats: {
        streamingTurnCount: streamingTurns.length,
        serverTurnCount: serverTurns.length,
        diffCount: Array.from(diffs.values()).reduce((sum, d) => sum + d.length, 0),
      },
      diffs: Array.from(diffs.entries()).map(([idx, turnDiffs]) => ({
        turnIndex: idx,
        differences: turnDiffs.map(d => ({
          field: d.field,
          streaming: d.streaming,
          server: d.server,
        })),
      })),
      recentEvents: eventLog.slice(-20).map(e => ({
        time: new Date(e.timestamp).toISOString(),
        event: e.event,
        data: e.data,
      })),
    };
    return JSON.stringify(diffData, null, 2);
  }, [sessionId, streamingTurns.length, serverTurns.length, diffs, eventLog]);

  // Copy diffs to input or clipboard
  const copyDiffsToInput = useCallback(() => {
    const json = packageDiffsAsJson();
    if (onCopyToInput) {
      onCopyToInput(`Here's the streaming vs server state comparison:\n\n\`\`\`json\n${json}\n\`\`\``);
    } else {
      // Fallback: copy to clipboard
      navigator.clipboard.writeText(json).then(() => {
        logEvent('COPIED_TO_CLIPBOARD', { length: json.length });
      }).catch(err => {
        console.error('Failed to copy to clipboard:', err);
      });
    }
  }, [packageDiffsAsJson, onCopyToInput, logEvent]);

  if (!sessionId) {
    return <div className="streaming-compare-view empty">No session selected</div>;
  }

  if (isLoading) {
    return <div className="streaming-compare-view loading">Loading...</div>;
  }

  if (error) {
    return <div className="streaming-compare-view error">{error}</div>;
  }

  const diffCount = Array.from(diffs.values()).reduce((sum, d) => sum + d.length, 0);

  return (
    <div className="streaming-compare-view" ref={scrollRef}>
      {/* Controls */}
      <div className="compare-controls">
        <div className="compare-stats">
          <span className="stat">Streaming: {streamingTurns.length} turns</span>
          <span className="stat">Server: {serverTurns.length} turns</span>
          <span className={`stat ${diffCount > 0 ? 'has-diffs' : 'no-diffs'}`}>
            Diffs: {diffCount}
          </span>
        </div>
        <div className="compare-actions">
          <label className="toggle-label">
            <input
              type="checkbox"
              checked={autoRefreshServer}
              onChange={(e) => setAutoRefreshServer(e.target.checked)}
            />
            Auto-refresh server on task complete
          </label>
          <button onClick={loadServerTurns} className="action-btn">
            Refresh Server
          </button>
          <button onClick={syncWithServer} className="action-btn" title="Copy server state to streaming (set same baseline)">
            Sync Baseline
          </button>
          <button onClick={resetStreamingState} className="action-btn">
            Reset Streaming
          </button>
          <button onClick={clearEventLog} className="action-btn">
            Clear Log
          </button>
          <button
            onClick={copyDiffsToInput}
            className="action-btn copy-to-input-btn"
            title={onCopyToInput ? "Paste diffs JSON to input" : "Copy diffs JSON to clipboard"}
          >
            {onCopyToInput ? "📋 Paste to Input" : "📋 Copy JSON"}
          </button>
        </div>
      </div>

      {/* Main content: 3 columns */}
      <div className="compare-main">
        {/* Column 1: Streaming state */}
        <div className="compare-panel streaming-panel">
          <div className="panel-header">
            <span className="panel-title">🔴 Streaming State</span>
            <span className="panel-subtitle">(No reload on task complete)</span>
          </div>
          <div className="panel-content">
            {streamingTurns.map(turn => (
              <TurnCard
                key={turn.idx}
                turn={turn}
                hasDiff={diffs.has(turn.idx)}
                side="streaming"
              />
            ))}
            {streamingTurns.length === 0 && (
              <div className="no-turns">No streaming turns yet</div>
            )}
          </div>
        </div>

        {/* Column 2: Server state */}
        <div className="compare-panel server-panel">
          <div className="panel-header">
            <span className="panel-title">🟢 Server State</span>
            <span className="panel-subtitle">(From getTurns())</span>
          </div>
          <div className="panel-content">
            {serverTurns.map(turn => (
              <TurnCard
                key={turn.idx}
                turn={turn}
                hasDiff={diffs.has(turn.idx)}
                side="server"
              />
            ))}
            {serverTurns.length === 0 && (
              <div className="no-turns">No server turns</div>
            )}
          </div>
        </div>

        {/* Column 3: Diffs and Event log */}
        <div className="compare-right-column">
          {/* Diffs panel */}
          <div className="diffs-panel">
            <div className="panel-header">
              <span className="panel-title">⚠️ Differences ({diffCount})</span>
            </div>
            <div className="diffs-content">
              {diffCount > 0 ? (
                Array.from(diffs.entries()).map(([idx, turnDiffs]) => (
                  <div key={idx} className="diff-group">
                    <div className="diff-turn-header">Turn #{idx}</div>
                    {turnDiffs.map((diff, i) => (
                      <div key={i} className="diff-item">
                        <span className="diff-field">{diff.field}:</span>
                        <div className="diff-values">
                          <div className="diff-streaming">
                            <span className="diff-label">Streaming:</span>
                            <code>{JSON.stringify(diff.streaming, null, 2)}</code>
                          </div>
                          <div className="diff-server">
                            <span className="diff-label">Server:</span>
                            <code>{JSON.stringify(diff.server, null, 2)}</code>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ))
              ) : (
                <div className="no-diffs-message">No differences detected</div>
              )}
            </div>
          </div>

          {/* Event log */}
          <div className="event-log-panel">
            <div className="panel-header">
              <span className="panel-title">📋 Event Log ({eventLog.length})</span>
            </div>
            <div className="event-log-content" ref={eventLogRef}>
              {eventLog.map((log, i) => (
                <div key={i} className={`event-entry event-${log.event.toLowerCase().replace(/^on/, '')}`}>
                  <span className="event-time">
                    {new Date(log.timestamp).toLocaleTimeString('en-US', { hour12: false })}
                  </span>
                  <span className="event-name">{log.event}</span>
                  <span className="event-data">{JSON.stringify(log.data)}</span>
                </div>
              ))}
              {eventLog.length === 0 && (
                <div className="no-events">No events yet - start a task to see streaming events</div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

interface TurnCardProps {
  turn: StreamingTurn | ServerTurn;
  hasDiff: boolean;
  side: 'streaming' | 'server';
}

function TurnCard({ turn, hasDiff, side }: TurnCardProps) {
  const { idx, role, content, contentBlockType, streaming, toolUse, toolResult } = turn;

  const isToolUse = contentBlockType === 'tool_use' || toolUse;
  const isToolResult = contentBlockType === 'tool_result' || toolResult;

  const cardClass = `turn-card ${role} ${isToolUse ? 'tool-use' : ''} ${isToolResult ? 'tool-result' : ''} ${streaming ? 'streaming' : ''} ${hasDiff ? 'has-diff' : ''}`;

  return (
    <div className={cardClass}>
      <div className="turn-card-header">
        <span className="turn-idx">#{idx}</span>
        <span className="turn-role">{role}</span>
        {contentBlockType && <span className="turn-type">{contentBlockType}</span>}
        {streaming && <span className="streaming-badge">⏳</span>}
        {hasDiff && <span className="diff-badge">⚠️</span>}
      </div>
      <div className="turn-card-body">
        {isToolUse && toolUse ? (
          <div className="tool-info">
            <div className="tool-name">{toolUse.toolName}</div>
            {toolUse.toolInput && Object.keys(toolUse.toolInput).length > 0 && (
              <pre className="tool-input">{JSON.stringify(toolUse.toolInput, null, 2).slice(0, 200)}</pre>
            )}
          </div>
        ) : isToolResult && toolResult ? (
          <div className="tool-result-info">
            <pre className="tool-result-content">
              {toolResult.content.slice(0, 200)}
              {toolResult.content.length > 200 && '...'}
            </pre>
            {toolResult.isError && <span className="error-badge">ERROR</span>}
          </div>
        ) : content ? (
          <div className="content-preview">
            {content.slice(0, 200)}
            {content.length > 200 && '...'}
          </div>
        ) : (
          <div className="empty-content">(empty)</div>
        )}
      </div>
    </div>
  );
}

export default StreamingCompareView;
