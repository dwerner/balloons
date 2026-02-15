import React, { useState, useEffect, useCallback, useRef } from 'react';
import { BalloonsClient } from '../../generated/balloons-client';
import type { ConnectionState, SessionInfo, TurnInfo, Unsubscribe } from '../../generated/balloons-client';

// Get WebSocket URL from environment, query param, or derive from current host
function getWsUrl(): string {
  // Check for explicit override
  if (typeof window !== 'undefined' && (window as any).BALLOONS_WS_URL) {
    return (window as any).BALLOONS_WS_URL;
  }

  // Check URL query param: ?ws=host:port
  if (typeof window !== 'undefined') {
    const params = new URLSearchParams(window.location.search);
    const wsParam = params.get('ws');
    if (wsParam) {
      return `ws://${wsParam}`;
    }

    // Default: use same host as the page, port 8765
    return `ws://${window.location.hostname}:8765`;
  }

  return 'ws://localhost:8765';
}

const WS_URL = getWsUrl();

export function App() {
  const [connectionState, setConnectionState] = useState<ConnectionState>('disconnected');
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [turns, setTurns] = useState<TurnInfo[]>([]);
  const [message, setMessage] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [queuedMessageCount, setQueuedMessageCount] = useState(0);

  const clientRef = useRef<BalloonsClient | null>(null);
  const turnsEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when turns update
  useEffect(() => {
    turnsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [turns]);

  // Initialize client and connect
  useEffect(() => {
    const client = new BalloonsClient(WS_URL, {
      autoReconnect: true,
      reconnectDelay: 2000,
      maxReconnectAttempts: 10,
    });
    clientRef.current = client;

    // Track connection state
    const unsubState = client.onStateChange(setConnectionState);

    // Connect
    client.connect()
      .then(async () => {
        console.log('Connected to Balloons backend');
        setError(null);

        // Load initial session list
        try {
          const sessionList = await client.tree.getAllSessions();
          setSessions(sessionList);

          // If there's a current session, select it
          const currentId = await client.tree.getCurrentSessionId();
          if (currentId) {
            setSelectedSessionId(currentId);
            const sessionTurns = await client.tree.getTurns(currentId);
            setTurns(sessionTurns);

            // Load queue state for the current session
            const queueInfo = await client.queue.getQueue(currentId);
            setQueuedMessageCount(queueInfo.messageCount);
          }
        } catch (err) {
          console.error('Failed to load sessions:', err);
          setError(`Failed to load sessions: ${err}`);
        }
      })
      .catch(err => {
        console.error('Connection failed:', err);
        setError(`Connection failed: ${err.message}`);
      });

    return () => {
      unsubState();
      client.disconnect();
    };
  }, []);

  // Subscribe to events when connected
  useEffect(() => {
    const client = clientRef.current;
    if (!client || connectionState !== 'connected') return;

    const unsubscribers: Unsubscribe[] = [];

    try {
      // Session events
      unsubscribers.push(
        client.tree.onSessionAdded(async () => {
          const sessionList = await client.tree.getAllSessions();
          setSessions(sessionList);
        })
      );

      unsubscribers.push(
        client.tree.onSessionUpdated(async (data) => {
          const sessionList = await client.tree.getAllSessions();
          setSessions(sessionList);

          // If this is the selected session, refresh turns too
          if (data.sessionId === selectedSessionId) {
            const sessionTurns = await client.tree.getTurns(data.sessionId);
            setTurns(sessionTurns);
          }
        })
      );

      unsubscribers.push(
        client.tree.onSessionRemoved(async (data) => {
          const sessionList = await client.tree.getAllSessions();
          setSessions(sessionList);

          if (data.sessionId === selectedSessionId) {
            setSelectedSessionId(null);
            setTurns([]);
          }
        })
      );

      // Turn events for streaming
      unsubscribers.push(
        client.tree.onTurnStarted(async (data) => {
          if (data.sessionId === selectedSessionId) {
            const sessionTurns = await client.tree.getTurns(data.sessionId);
            setTurns(sessionTurns);
          }
        })
      );

      unsubscribers.push(
        client.tree.onTurnUpdated(async (data) => {
          if (data.sessionId === selectedSessionId && data.turnIdx != null) {
            // Update just the specific turn for better performance
            const turnIdx = data.turnIdx;
            const updatedTurn = await client.tree.getTurn(data.sessionId, turnIdx);
            if (updatedTurn) {
              setTurns(prev => {
                const newTurns = [...prev];
                const idx = newTurns.findIndex(t => t.idx === turnIdx);
                if (idx >= 0) {
                  newTurns[idx] = updatedTurn;
                } else {
                  newTurns.push(updatedTurn);
                }
                return newTurns;
              });
            }
          }
        })
      );

      unsubscribers.push(
        client.tree.onTurnFinished(async (data) => {
          if (data.sessionId === selectedSessionId) {
            const sessionTurns = await client.tree.getTurns(data.sessionId);
            setTurns(sessionTurns);
          }
          // Also refresh session list to update streaming indicator
          const sessionList = await client.tree.getAllSessions();
          setSessions(sessionList);
        })
      );

      // Streaming events
      unsubscribers.push(
        client.tree.onStreamingStarted(async (data) => {
          console.log('streamingStarted event received:', data);
          const sessionList = await client.tree.getAllSessions();
          console.log('Sessions after streamingStarted:', sessionList.map(s => ({ id: s.id.slice(0,8), isStreaming: s.isStreaming })));
          setSessions(sessionList);
        })
      );

      unsubscribers.push(
        client.tree.onStreamingStopped(async (data) => {
          console.log('streamingStopped event received:', data);
          const sessionList = await client.tree.getAllSessions();
          console.log('Sessions after streamingStopped:', sessionList.map(s => ({ id: s.id.slice(0,8), isStreaming: s.isStreaming })));
          setSessions(sessionList);
        })
      );

      // Queue events - track queued messages for the selected session
      unsubscribers.push(
        client.queue.onMessageAdded(async (data) => {
          console.log('Queue messageAdded event:', data);
          if (data.sessionId === selectedSessionId) {
            const queueInfo = await client.queue.getQueue(data.sessionId);
            setQueuedMessageCount(queueInfo.messageCount);
          }
        })
      );

      unsubscribers.push(
        client.queue.onMessageRemoved(async (data) => {
          console.log('Queue messageRemoved event:', data);
          if (data.sessionId === selectedSessionId) {
            const queueInfo = await client.queue.getQueue(data.sessionId);
            setQueuedMessageCount(queueInfo.messageCount);
          }
        })
      );

      unsubscribers.push(
        client.queue.onQueueDrained(async (data) => {
          console.log('Queue drained event:', data);
          if (data.sessionId === selectedSessionId) {
            // Queue was drained - messages are being processed
            const queueInfo = await client.queue.getQueue(data.sessionId);
            setQueuedMessageCount(queueInfo.messageCount);
          }
        })
      );

      unsubscribers.push(
        client.queue.onQueueCleared(async (data) => {
          console.log('Queue cleared event:', data);
          if (data.sessionId === selectedSessionId) {
            setQueuedMessageCount(0);
          }
        })
      );
    } catch (err) {
      console.error('Failed to set up event subscriptions:', err);
    }

    return () => {
      unsubscribers.forEach(unsub => unsub());
    };
  }, [connectionState, selectedSessionId]);

  // Select a session
  const handleSelectSession = useCallback(async (sessionId: string) => {
    const client = clientRef.current;
    if (!client || connectionState !== 'connected') return;

    setSelectedSessionId(sessionId);
    setSidebarOpen(false); // Close sidebar on mobile after selection
    setError(null);

    try {
      const sessionTurns = await client.tree.getTurns(sessionId);
      setTurns(sessionTurns);

      // Load queue state for the session
      const queueInfo = await client.queue.getQueue(sessionId);
      setQueuedMessageCount(queueInfo.messageCount);
    } catch (err) {
      console.error('Failed to load turns:', err);
      setError(`Failed to load turns: ${err}`);
    }
  }, [connectionState]);

  // Send a message
  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();

    const client = clientRef.current;
    if (!client || connectionState !== 'connected' || !selectedSessionId || !message.trim()) {
      return;
    }

    const content = message.trim();
    setMessage('');
    setError(null);

    // Check if session is currently streaming
    const session = sessions.find(s => s.id === selectedSessionId);
    const isStreaming = session?.isStreaming ?? false;

    try {
      if (isStreaming) {
        // Session is streaming - add to queue instead of submitting directly
        const messageId = await client.queue.addMessage(selectedSessionId, content);
        console.log('Message queued:', messageId, content.substring(0, 50));
        // Queue state will be updated via onMessageAdded event
      } else {
        // Session is not streaming - submit directly
        const result = await client.sessions.submitMessage(selectedSessionId, content);
        console.log('Message submitted:', result.exchangeId, content.substring(0, 50));
      }
    } catch (err) {
      console.error('Failed to send message:', err);
      setError(`Failed to send message: ${err}`);
      setMessage(content); // Restore the message on failure
    }
  }, [connectionState, selectedSessionId, message, sessions]);

  // Handle Enter key in textarea
  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  }, [handleSubmit]);

  // Stop streaming
  const handleStopStreaming = useCallback(async () => {
    const client = clientRef.current;
    if (!client || connectionState !== 'connected' || !selectedSessionId) {
      return;
    }

    try {
      await client.sessions.cancelStreaming(selectedSessionId);
      console.log('Streaming cancelled');
    } catch (err) {
      console.error('Failed to stop streaming:', err);
      setError(`Failed to stop streaming: ${err}`);
    }
  }, [connectionState, selectedSessionId]);

  const selectedSession = sessions.find(s => s.id === selectedSessionId);

  // Debug: log when selectedSession.isStreaming changes
  console.log('Render - selectedSession:', selectedSession?.id?.slice(0,8), 'isStreaming:', selectedSession?.isStreaming);

  return (
    <div className="app">
      {/* Mobile header */}
      <header className="mobile-header">
        <button className="menu-button" onClick={() => setSidebarOpen(true)} aria-label="Open menu">
          ☰
        </button>
        <div className={`connection-status ${connectionState}`} title={connectionState} />
        <h1>Balloons</h1>
      </header>

      {/* Sidebar overlay for mobile */}
      <div
        className={`sidebar-overlay ${sidebarOpen ? 'visible' : ''}`}
        onClick={() => setSidebarOpen(false)}
      />

      <aside className={`sidebar ${sidebarOpen ? 'open' : ''}`}>
        <header className="sidebar-header">
          <div className={`connection-status ${connectionState}`} title={connectionState} />
          <h1>Balloons</h1>
          <button className="close-button" onClick={() => setSidebarOpen(false)} aria-label="Close menu">
            ✕
          </button>
        </header>

        <div className="session-list">
          {sessions.length === 0 && connectionState === 'connected' && (
            <div style={{ padding: '16px', color: '#666', textAlign: 'center' }}>
              No sessions
            </div>
          )}

          {sessions.map(session => (
            <div
              key={session.id}
              className={`session-item ${session.id === selectedSessionId ? 'selected' : ''} ${session.isStreaming ? 'streaming' : ''}`}
              onClick={() => handleSelectSession(session.id)}
            >
              <div className="session-title">
                {session.title || `Session ${session.id.slice(0, 8)}`}
              </div>
              <div className="session-meta">
                {session.messageCount} messages
                {session.isStreaming && ' • streaming'}
              </div>
            </div>
          ))}
        </div>
      </aside>

      <main className="main-panel">
        {error && (
          <div className="error-message">
            {error}
          </div>
        )}

        {!selectedSessionId ? (
          <div className="empty-state">
            <h2>No Session Selected</h2>
            <p>Select a session from the sidebar to view its conversation.</p>
          </div>
        ) : (
          <>
            <div className="turns-container">
              {turns.length === 0 && (
                <div className="empty-state">
                  <h2>No Messages Yet</h2>
                  <p>Send a message to start the conversation.</p>
                </div>
              )}

              {turns.map(turn => (
                <div
                  key={turn.idx}
                  className={`turn ${turn.role} ${turn.streaming ? 'streaming' : ''}`}
                >
                  <div className="turn-role">{turn.role}</div>
                  <div className="turn-content">{turn.content}</div>
                </div>
              ))}
              <div ref={turnsEndRef} />
            </div>

            <div className={`input-area ${selectedSession?.isStreaming ? 'queue-mode' : ''}`}>
              {selectedSession?.isStreaming && (
                <div className="queue-indicator">
                  <span className="queue-dot" />
                  {queuedMessageCount > 0 ? `${queuedMessageCount} queued` : 'Queue mode'}
                </div>
              )}
              <form className="input-form" onSubmit={handleSubmit}>
                <textarea
                  className="input-field"
                  placeholder={selectedSession?.isStreaming
                    ? "Type to queue... (messages will be sent after streaming completes)"
                    : "Type a message... (Enter to send, Shift+Enter for newline)"}
                  value={message}
                  onChange={e => setMessage(e.target.value)}
                  onKeyDown={handleKeyDown}
                  disabled={connectionState !== 'connected'}
                  rows={1}
                />
                {selectedSession?.isStreaming ? (
                  <>
                    <button
                      type="submit"
                      className="queue-button"
                      disabled={connectionState !== 'connected' || !message.trim()}
                    >
                      Queue
                    </button>
                    <button
                      type="button"
                      className="stop-button"
                      onClick={handleStopStreaming}
                      disabled={connectionState !== 'connected'}
                    >
                      Stop
                    </button>
                  </>
                ) : (
                  <button
                    type="submit"
                    className="send-button"
                    disabled={connectionState !== 'connected' || !message.trim()}
                  >
                    Send
                  </button>
                )}
              </form>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
