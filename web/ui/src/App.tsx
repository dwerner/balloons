import React, { useState, useEffect, useCallback, useRef, memo } from 'react';
import { BalloonsClient } from '../../generated/balloons-client';
import type { ConnectionState, SessionInfo, TurnInfo, TaskInfo, Unsubscribe, ToolUseStartedEvent, ToolInputDeltaEvent, ToolResultEvent, ContentDeltaEvent, TurnStartedEvent, TurnFinishedEvent } from '../../generated/balloons-client';
import { MarkdownContent } from './MarkdownContent';
import { AppLayout, useLayout, useTheme } from './components/layout';

// Tool use state tracked during streaming
interface ToolUseState {
  toolUseId: string;
  toolName: string;
  turnIndex: number;
  toolIndex: number;
  exchangeId?: string;  // Used for matching tool uses to assistant turns
  status: 'streaming' | 'executing' | 'completed' | 'error';
  inputJson: string;
  result?: string;
  isError?: boolean;
  startTime: number;
  endTime?: number;
}

// Image attachment state
interface ImageAttachment {
  id: string;
  file: File;
  previewUrl: string;
  uploading: boolean;
  uploaded: boolean;
  filePath?: string;
  mediaType: string;
  width?: number;
  height?: number;
  error?: string;
}

// Collapsible component for tool input/output
const Collapsible = memo(function Collapsible({
  title,
  children,
  defaultExpanded = false
}: {
  title: string;
  children: React.ReactNode;
  defaultExpanded?: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <div className="collapsible">
      <button
        className="collapsible-header"
        onClick={() => setExpanded(!expanded)}
        type="button"
      >
        <span className="collapsible-icon">{expanded ? '▼' : '▶'}</span>
        <span className="collapsible-title">{title}</span>
      </button>
      {expanded && (
        <div className="collapsible-content">
          {children}
        </div>
      )}
    </div>
  );
});

// Tool use component for displaying individual tool calls
const ToolUseDisplay = memo(function ToolUseDisplay({ toolUse }: { toolUse: ToolUseState }) {
  const duration = toolUse.endTime
    ? ((toolUse.endTime - toolUse.startTime) / 1000).toFixed(1)
    : null;

  const statusIcon = {
    streaming: '⏳',
    executing: '⚙️',
    completed: '✓',
    error: '✗',
  }[toolUse.status];

  const statusClass = toolUse.status;

  // Format JSON for display
  const formatJson = (json: string) => {
    try {
      const parsed = JSON.parse(json);
      return JSON.stringify(parsed, null, 2);
    } catch {
      // If not valid JSON yet (streaming), just return as-is
      return json;
    }
  };

  return (
    <div className={`tool-use ${statusClass}`}>
      <div className="tool-use-header">
        <span className={`tool-use-status ${statusClass}`}>
          {toolUse.status === 'executing' ? (
            <span className="tool-spinner">{statusIcon}</span>
          ) : (
            statusIcon
          )}
        </span>
        <span className="tool-use-name">{toolUse.toolName}</span>
        {duration && (
          <span className="tool-use-duration">{duration}s</span>
        )}
      </div>

      {toolUse.inputJson && (
        <Collapsible title="Input" defaultExpanded={toolUse.status === 'streaming'}>
          <pre className="tool-use-json">
            <code>{formatJson(toolUse.inputJson)}</code>
          </pre>
        </Collapsible>
      )}

      {toolUse.result !== undefined && (
        <Collapsible title={toolUse.isError ? "Error" : "Result"}>
          <pre className={`tool-use-result ${toolUse.isError ? 'error' : ''}`}>
            <code>{toolUse.result}</code>
          </pre>
        </Collapsible>
      )}
    </div>
  );
});

// Memoized Turn component to prevent re-renders when other state changes (e.g., typing)
const Turn = memo(function Turn({
  turn,
  toolUses,
  exchangeId
}: {
  turn: TurnInfo;
  toolUses?: ToolUseState[];
  exchangeId?: string;
}) {
  // Filter tool uses for this turn
  // First try to match by exchange ID (more reliable), then fall back to turn index
  const turnToolUses = toolUses?.filter(tu => {
    // If we have an exchange ID on the turn, use that for matching
    if (turn.exchangeId) {
      return tu.exchangeId === turn.exchangeId;
    }
    // Fall back to turn index matching
    return tu.turnIndex === turn.idx;
  }) || [];

  // Debug: log when we have tool uses
  if (turn.role === 'assistant' && toolUses && toolUses.length > 0) {
    console.log('[Turn]', turn.idx, 'exchangeId:', turn.exchangeId?.slice(0, 8), 'total toolUses:', toolUses.length, 'for this turn:', turnToolUses.length);
  }

  // Render tool results (role === 'tool') as a collapsible result block
  if (turn.role === 'tool') {
    return (
      <div className={`turn tool ${turn.streaming ? 'streaming' : ''}`}>
        <div className="turn-role">tool result</div>
        <div className="turn-content">
          <Collapsible title="Result" defaultExpanded={false}>
            <pre className="tool-use-result">
              <code>{turn.content}</code>
            </pre>
          </Collapsible>
        </div>
      </div>
    );
  }

  return (
    <div className={`turn ${turn.role} ${turn.streaming ? 'streaming' : ''}`}>
      <div className="turn-role">{turn.role}</div>
      <div className="turn-content">
        {turn.role === 'user' ? (
          turn.content || '\u00A0'
        ) : (
          <MarkdownContent content={turn.content} />
        )}
      </div>
      {/* Display tool uses for assistant turns */}
      {turn.role === 'assistant' && turnToolUses.length > 0 && (
        <div className="turn-tool-uses">
          {turnToolUses.map(tu => (
            <ToolUseDisplay key={tu.toolUseId} toolUse={tu} />
          ))}
        </div>
      )}
    </div>
  );
});

// Format duration in seconds to a human-readable string
function formatDuration(seconds: number): string {
  if (seconds < 60) {
    return `${Math.floor(seconds)}s`;
  }
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}m ${secs}s`;
}

// Format token count with thousands separator
function formatTokens(count: number): string {
  if (count >= 1000) {
    return `${(count / 1000).toFixed(1)}k`;
  }
  return String(count);
}

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
  const [queuedMessageCount, setQueuedMessageCount] = useState(0);
  const [streamingTask, setStreamingTask] = useState<TaskInfo | null>(null);
  const [toolUses, setToolUses] = useState<ToolUseState[]>([]);
  const [imageAttachments, setImageAttachments] = useState<ImageAttachment[]>([]);

  const clientRef = useRef<BalloonsClient | null>(null);
  const turnsEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll to bottom when turns update
  // Use a small delay to allow markdown/syntax highlighting to render first
  useEffect(() => {
    const timeoutId = setTimeout(() => {
      turnsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, 50);
    return () => clearTimeout(timeoutId);
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

            // Load streaming task if session is already streaming
            const task = await client.tasks.getSessionTask(currentId);
            setStreamingTask(task);
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

      // Turn events for streaming - use TaskStateService events for efficient incremental updates
      // onTurnStarted: Create a placeholder turn immediately when streaming begins
      // Note: We only create visible turns for 'user' and primary 'assistant' turns.
      // Tool-related turns (additional assistant turns for tool_use, and 'tool' role for results)
      // are handled inline within the main assistant turn via tool use events.
      unsubscribers.push(
        client.tasks.onTurnStarted((data: TurnStartedEvent) => {
          if (data.sessionId === selectedSessionId) {
            // Skip creating separate turns for tool-related events
            // Tool uses are tracked separately and displayed inline in the assistant turn
            // The 'tool' role turns are for tool results which we display as part of the tool use
            if (data.role === 'tool') {
              console.log('[TurnStarted] Skipping tool result turn:', data.turnIndex);
              return;
            }

            setTurns(prev => {
              // Check if turn already exists
              const existing = prev.find(t => t.idx === data.turnIndex);
              if (existing) {
                // Update existing turn to streaming state
                return prev.map(t => t.idx === data.turnIndex ? {
                  idx: existing.idx,
                  role: existing.role,
                  content: existing.content,
                  streaming: true,
                  viewed: existing.viewed,
                  tokens: existing.tokens,
                  contextMode: existing.contextMode,
                  exchangeId: existing.exchangeId,
                } : t);
              }

              // For assistant turns, check if this might be a tool_use turn
              // (a subsequent assistant turn in the same exchange)
              // We only want to create a turn if there's no existing assistant turn
              // for this exchange, OR if this is genuinely a new assistant response segment
              if (data.role === 'assistant' && data.exchangeId) {
                const existingAssistantInExchange = prev.find(
                  t => t.role === 'assistant' && t.exchangeId === data.exchangeId
                );
                if (existingAssistantInExchange) {
                  console.log('[TurnStarted] Skipping duplicate assistant turn for exchange:', data.exchangeId?.slice(0, 8), 'existing turn:', existingAssistantInExchange.idx, 'new turn:', data.turnIndex);
                  // Don't create a new turn, tool uses will be displayed in the existing turn
                  return prev;
                }
              }

              // Create placeholder turn
              const placeholderTurn: TurnInfo = {
                idx: data.turnIndex,
                role: data.role,
                content: '',
                streaming: true,
                viewed: false,
                tokens: 0,
                contextMode: 'COPY',
                exchangeId: data.exchangeId,
              };
              return [...prev, placeholderTurn];
            });
          }
        })
      );

      // onContentDelta: Incrementally update turn content without re-fetching
      unsubscribers.push(
        client.tasks.onContentDelta((data: ContentDeltaEvent) => {
          if (data.sessionId === selectedSessionId) {
            setTurns(prev => {
              const turnIdx = data.turnIndex;
              const existing = prev.find(t => t.idx === turnIdx);
              if (existing) {
                // Update existing turn with accumulated content
                return prev.map(t => t.idx === turnIdx ? {
                  idx: existing.idx,
                  role: existing.role,
                  content: data.accumulated,
                  streaming: true,
                  viewed: existing.viewed,
                  tokens: existing.tokens,
                  contextMode: existing.contextMode,
                  exchangeId: existing.exchangeId,
                } : t);
              }

              // Check if there's already an assistant turn for this exchange
              // (Content deltas might come after tool uses for continued response)
              if (data.exchangeId) {
                const existingAssistantInExchange = prev.find(
                  t => t.role === 'assistant' && t.exchangeId === data.exchangeId
                );
                if (existingAssistantInExchange) {
                  // Update the existing assistant turn in this exchange
                  return prev.map(t =>
                    (t.role === 'assistant' && t.exchangeId === data.exchangeId) ? {
                      ...t,
                      content: data.accumulated,
                      streaming: true,
                    } : t
                  );
                }
              }

              // Turn doesn't exist yet - create it (shouldn't normally happen if onTurnStarted fires first)
              const newTurn: TurnInfo = {
                idx: turnIdx,
                role: 'assistant',
                content: data.accumulated,
                streaming: true,
                viewed: false,
                tokens: 0,
                contextMode: 'COPY',
                exchangeId: data.exchangeId,
              };
              return [...prev, newTurn];
            });
          }
        })
      );

      // onTurnFinished: Finalize turn state with complete content
      unsubscribers.push(
        client.tasks.onTurnFinished((data: TurnFinishedEvent) => {
          if (data.sessionId === selectedSessionId) {
            // Skip tool result turns - they're displayed inline via tool use events
            if (data.role === 'tool') {
              console.log('[TurnFinished] Skipping tool result turn:', data.turnIndex);
              return;
            }

            setTurns(prev => {
              const turnIdx = data.turnIndex;
              const existing = prev.find(t => t.idx === turnIdx);
              if (existing) {
                // Finalize existing turn
                return prev.map(t => t.idx === turnIdx ? {
                  idx: existing.idx,
                  role: data.role,
                  content: data.content,
                  streaming: false,
                  viewed: existing.viewed,
                  tokens: existing.tokens,
                  contextMode: existing.contextMode,
                  exchangeId: existing.exchangeId,
                } : t);
              }

              // For assistant turns without content, check if there's already an assistant turn
              // for this exchange (this could be a tool_use turn finishing)
              if (data.role === 'assistant' && data.exchangeId) {
                const existingAssistantInExchange = prev.find(
                  t => t.role === 'assistant' && t.exchangeId === data.exchangeId
                );
                if (existingAssistantInExchange && !data.content) {
                  console.log('[TurnFinished] Skipping empty assistant turn for exchange:', data.exchangeId?.slice(0, 8));
                  return prev;
                }
              }

              // Turn doesn't exist - create it with final content
              const newTurn: TurnInfo = {
                idx: turnIdx,
                role: data.role,
                content: data.content,
                streaming: false,
                viewed: false,
                tokens: 0,
                contextMode: 'COPY',
                exchangeId: data.exchangeId,
              };
              return [...prev, newTurn];
            });
          }
          // Also refresh session list to update streaming indicator
          client.tree.getAllSessions().then(sessionList => {
            setSessions(sessionList);
          });
        })
      );

      // Keep the tree-based onTurnUpdated for non-streaming updates (e.g., context mode changes)
      unsubscribers.push(
        client.tree.onTurnUpdated(async (data) => {
          if (data.sessionId === selectedSessionId && data.turnIdx != null) {
            const turnIdx = data.turnIdx;
            // Use setTurns callback to check streaming state without stale closure
            setTurns(prev => {
              const existingTurn = prev.find(t => t.idx === turnIdx);
              // If turn is currently streaming, skip fetch - onContentDelta handles it
              if (existingTurn?.streaming) {
                return prev;
              }
              // Fetch updated turn asynchronously and update state
              client.tree.getTurn(data.sessionId, turnIdx).then(updatedTurn => {
                if (updatedTurn) {
                  setTurns(current => {
                    const newTurns = [...current];
                    const idx = newTurns.findIndex(t => t.idx === turnIdx);
                    if (idx >= 0) {
                      newTurns[idx] = updatedTurn;
                    } else {
                      newTurns.push(updatedTurn);
                    }
                    return newTurns;
                  });
                }
              });
              return prev;
            });
          }
        })
      );

      // Streaming events
      unsubscribers.push(
        client.tree.onStreamingStarted(async (data) => {
          console.log('[StreamingStarted]', data.sessionId?.slice(0,8));
          const sessionList = await client.tree.getAllSessions();
          setSessions(sessionList);

          // Clear tool uses when a new streaming session starts
          if (data.sessionId === selectedSessionId) {
            console.log('[StreamingStarted] Clearing tool uses for session:', data.sessionId?.slice(0,8));
            setToolUses([]);
          }
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

      // Task events - for streaming progress indicators
      unsubscribers.push(
        client.tasks.onTaskStarted(async (data) => {
          if (data.sessionId === selectedSessionId) {
            const task = await client.tasks.getTask(data.taskId);
            if (task) {
              setStreamingTask(task);
            }
          }
        })
      );

      unsubscribers.push(
        client.tasks.onTaskUpdated(async (data) => {
          if (data.sessionId === selectedSessionId) {
            const task = await client.tasks.getTask(data.taskId);
            if (task) {
              setStreamingTask(task);
            }
          }
        })
      );

      unsubscribers.push(
        client.tasks.onTaskCompleted(async (data) => {
          if (data.sessionId === selectedSessionId) {
            setStreamingTask(null);
          }
        })
      );

      unsubscribers.push(
        client.tasks.onTaskCancelled(async (data) => {
          if (data.sessionId === selectedSessionId) {
            setStreamingTask(null);
          }
        })
      );

      unsubscribers.push(
        client.tasks.onTaskError(async (data) => {
          if (data.sessionId === selectedSessionId) {
            setStreamingTask(null);
          }
        })
      );

      // Tool use events - for visualizing tool calls during streaming
      unsubscribers.push(
        client.tasks.onToolUseStarted((data: ToolUseStartedEvent) => {
          console.log('[ToolUseStarted]', data.toolName, 'turn:', data.turnIndex, 'exchange:', data.exchangeId?.slice(0,8), 'session:', data.sessionId?.slice(0,8));
          if (data.sessionId === selectedSessionId) {
            setToolUses(prev => {
              // Check if this tool use already exists
              if (prev.some(tu => tu.toolUseId === data.toolUseId)) {
                return prev;
              }
              return [...prev, {
                toolUseId: data.toolUseId,
                toolName: data.toolName,
                turnIndex: data.turnIndex,
                toolIndex: data.toolIndex,
                exchangeId: data.exchangeId,  // Capture exchange ID for matching
                status: 'streaming',
                inputJson: '',
                startTime: Date.now(),
              }];
            });
          }
        })
      );

      unsubscribers.push(
        client.tasks.onToolInputDelta((data: ToolInputDeltaEvent) => {
          console.log('[ToolInputDelta]', data.toolUseId?.slice(0,8), 'partial:', data.partialJson?.slice(0,30));
          if (data.sessionId === selectedSessionId) {
            setToolUses(prev => prev.map(tu =>
              tu.toolUseId === data.toolUseId
                ? { ...tu, inputJson: tu.inputJson + data.partialJson }
                : tu
            ));
          }
        })
      );

      unsubscribers.push(
        client.tasks.onToolUse((data) => {
          console.log('[ToolUse]', data.toolName, 'executing');
          if (data.sessionId === selectedSessionId) {
            setToolUses(prev => prev.map(tu =>
              tu.toolUseId === data.toolUseId
                ? {
                    ...tu,
                    status: 'executing' as const,
                    inputJson: JSON.stringify(data.toolInput),
                  }
                : tu
            ));
          }
        })
      );

      unsubscribers.push(
        client.tasks.onToolResult((data: ToolResultEvent) => {
          console.log('[ToolResult]', data.toolName, 'isError:', data.isError, 'result length:', data.result?.length);
          if (data.sessionId === selectedSessionId) {
            setToolUses(prev => prev.map(tu =>
              tu.toolUseId === data.toolUseId
                ? {
                    ...tu,
                    status: data.isError ? 'error' as const : 'completed' as const,
                    result: data.result,
                    isError: data.isError,
                    endTime: Date.now(),
                  }
                : tu
            ));
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
    setError(null);
    setToolUses([]); // Clear tool uses when switching sessions

    try {
      const sessionTurns = await client.tree.getTurns(sessionId);
      setTurns(sessionTurns);

      // Load queue state for the session
      const queueInfo = await client.queue.getQueue(sessionId);
      setQueuedMessageCount(queueInfo.messageCount);

      // Load streaming task if session is streaming
      const task = await client.tasks.getSessionTask(sessionId);
      setStreamingTask(task);
    } catch (err) {
      console.error('Failed to load turns:', err);
      setError(`Failed to load turns: ${err}`);
    }
  }, [connectionState]);

  // Generate unique ID for image attachments
  const generateImageId = () => `img-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;

  // Upload image to server
  const uploadImage = useCallback(async (attachment: ImageAttachment): Promise<ImageAttachment> => {
    const client = clientRef.current;
    if (!client || connectionState !== 'connected') {
      return { ...attachment, error: 'Not connected' };
    }

    try {
      // Read file as base64
      const arrayBuffer = await attachment.file.arrayBuffer();
      const base64 = btoa(
        new Uint8Array(arrayBuffer).reduce((data, byte) => data + String.fromCharCode(byte), '')
      );

      // Upload via WebSocket RPC (images service)
      // Note: We need to call the images service - for now, we'll extend sessions
      // Actually, let's store the base64 data directly and let the backend handle it
      // when we submit the message

      // For now, mark as uploaded with the base64 data stored
      return {
        ...attachment,
        uploading: false,
        uploaded: true,
        // We'll send the base64 data with the message
      };
    } catch (err) {
      console.error('Failed to upload image:', err);
      return { ...attachment, uploading: false, error: `Upload failed: ${err}` };
    }
  }, [connectionState]);

  // Handle file selection (from file input or paste)
  const handleImageFiles = useCallback(async (files: FileList | File[]) => {
    const imageFiles = Array.from(files).filter(f => f.type.startsWith('image/'));
    if (imageFiles.length === 0) return;

    // Create attachments with preview URLs
    const newAttachments: ImageAttachment[] = await Promise.all(
      imageFiles.map(async (file) => {
        const previewUrl = URL.createObjectURL(file);

        // Get image dimensions
        const dimensions = await new Promise<{ width: number; height: number }>((resolve) => {
          const img = new Image();
          img.onload = () => resolve({ width: img.width, height: img.height });
          img.onerror = () => resolve({ width: 0, height: 0 });
          img.src = previewUrl;
        });

        return {
          id: generateImageId(),
          file,
          previewUrl,
          uploading: false,
          uploaded: false,
          mediaType: file.type,
          width: dimensions.width,
          height: dimensions.height,
        };
      })
    );

    setImageAttachments(prev => [...prev, ...newAttachments]);
  }, []);

  // Handle paste event
  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items;
    if (!items) return;

    const imageItems = Array.from(items).filter(item => item.type.startsWith('image/'));
    if (imageItems.length === 0) return;

    // Prevent default paste behavior for images
    e.preventDefault();

    const files = imageItems
      .map(item => item.getAsFile())
      .filter((f): f is File => f !== null);

    handleImageFiles(files);
  }, [handleImageFiles]);

  // Handle file input change
  const handleFileInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      handleImageFiles(files);
    }
    // Reset input so same file can be selected again
    e.target.value = '';
  }, [handleImageFiles]);

  // Remove an image attachment
  const removeImageAttachment = useCallback((id: string) => {
    setImageAttachments(prev => {
      const attachment = prev.find(a => a.id === id);
      if (attachment) {
        URL.revokeObjectURL(attachment.previewUrl);
      }
      return prev.filter(a => a.id !== id);
    });
  }, []);

  // Send a message
  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();

    const client = clientRef.current;
    if (!client || connectionState !== 'connected' || !selectedSessionId) {
      return;
    }

    // Allow sending with just images (no text) or just text (no images)
    const hasText = message.trim().length > 0;
    const hasImages = imageAttachments.length > 0;
    if (!hasText && !hasImages) {
      return;
    }

    const content = message.trim();
    const currentImages = [...imageAttachments];

    // Clear input state
    setMessage('');
    setImageAttachments([]);
    setError(null);

    // Check if session is currently streaming
    const session = sessions.find(s => s.id === selectedSessionId);
    const isStreaming = session?.isStreaming ?? false;

    try {
      if (isStreaming) {
        // Session is streaming - add to queue instead of submitting directly
        // Note: Image queueing not yet supported
        if (hasImages) {
          setError('Cannot queue messages with images while streaming. Please wait.');
          setMessage(content);
          setImageAttachments(currentImages);
          return;
        }
        const messageId = await client.queue.addMessage(selectedSessionId, content);
        console.log('Message queued:', messageId, content.substring(0, 50));
      } else if (hasImages) {
        // Submit with images - need to upload images first
        // Convert images to base64 and upload
        const imageData = await Promise.all(
          currentImages.map(async (img) => {
            const arrayBuffer = await img.file.arrayBuffer();
            const base64 = btoa(
              new Uint8Array(arrayBuffer).reduce((data, byte) => data + String.fromCharCode(byte), '')
            );

            // Upload via images service
            try {
              console.log('Uploading image:', img.file.name, 'mediaType:', img.mediaType, 'base64 length:', base64.length);
              const result = await client.images.uploadImage(
                base64,
                img.mediaType,
                selectedSessionId,
                img.file.name
              );
              console.log('Upload result:', result);
              return {
                file_path: result.filePath,
                media_type: result.mediaType,
                filename: result.filename,
                width: result.width || img.width || 0,
                height: result.height || img.height || 0,
              };
            } catch (uploadErr) {
              console.error('Image upload failed:', uploadErr);
              throw uploadErr;
            }
          })
        );

        // Submit message with uploaded images
        const result = await client.sessions.submitMessageWithImages(
          selectedSessionId,
          content || 'Please analyze this image.',
          imageData
        );
        console.log('Message with images submitted:', result.exchangeId);

        // Clean up preview URLs
        currentImages.forEach(img => URL.revokeObjectURL(img.previewUrl));
      } else {
        // Session is not streaming - submit directly (text only)
        const result = await client.sessions.submitMessage(selectedSessionId, content);
        console.log('Message submitted:', result.exchangeId, content.substring(0, 50));
      }
    } catch (err) {
      console.error('Failed to send message:', err);
      setError(`Failed to send message: ${err}`);
      setMessage(content);
      setImageAttachments(currentImages);
    }
  }, [connectionState, selectedSessionId, message, sessions, imageAttachments]);

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
    <AppLayout>
      {/* Mobile header */}
      <AppLayout.Header>
        <MobileHeader connectionState={connectionState} />
      </AppLayout.Header>

      {/* Sidebar */}
      <AppLayout.Sidebar>
        <SidebarContent
          connectionState={connectionState}
          sessions={sessions}
          selectedSessionId={selectedSessionId}
          streamingTask={streamingTask}
          onSelectSession={handleSelectSession}
        />
      </AppLayout.Sidebar>

      {/* Main content */}
      <AppLayout.Main>
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
                <Turn key={turn.idx} turn={turn} toolUses={toolUses} />
              ))}
              <div ref={turnsEndRef} />
            </div>

            <div className={`input-area ${selectedSession?.isStreaming ? 'queue-mode' : ''}`}>
              {selectedSession?.isStreaming && streamingTask && (
                <div className="streaming-status">
                  <div className="streaming-status-main">
                    <span className="streaming-indicator" />
                    <span className="streaming-model">{streamingTask.model || 'Streaming'}</span>
                    <span className="streaming-duration">{formatDuration(streamingTask.durationSeconds)}</span>
                  </div>
                  <div className="streaming-status-details">
                    {streamingTask.toolName ? (
                      <span className="streaming-tool" title={`Running tool: ${streamingTask.toolName}`}>
                        <span className="tool-icon">⚙</span>
                        {streamingTask.toolName}
                        {streamingTask.toolCount > 1 && ` (${streamingTask.toolCount})`}
                      </span>
                    ) : (
                      <span className="streaming-tokens">
                        {formatTokens(streamingTask.tokensStreamed)} tokens
                        {streamingTask.currentTokenRate > 0 && (
                          <span className="token-rate"> ({Math.round(streamingTask.currentTokenRate)}/s)</span>
                        )}
                      </span>
                    )}
                    {queuedMessageCount > 0 && (
                      <span className="queue-badge">{queuedMessageCount} queued</span>
                    )}
                  </div>
                </div>
              )}
              {/* Image preview area */}
              {imageAttachments.length > 0 && (
                <div className="image-preview-area">
                  {imageAttachments.map(img => (
                    <div key={img.id} className={`image-preview ${img.error ? 'error' : ''}`}>
                      <img src={img.previewUrl} alt={img.file.name} />
                      <button
                        type="button"
                        className="image-remove-button"
                        onClick={() => removeImageAttachment(img.id)}
                        title="Remove image"
                      >
                        ×
                      </button>
                      {img.error && <span className="image-error">{img.error}</span>}
                    </div>
                  ))}
                </div>
              )}
              <form className="input-form" onSubmit={handleSubmit}>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/gif,image/webp"
                  multiple
                  onChange={handleFileInputChange}
                  style={{ display: 'none' }}
                />
                <button
                  type="button"
                  className="attach-button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={connectionState !== 'connected' || selectedSession?.isStreaming}
                  title="Attach image (or paste from clipboard)"
                >
                  📎
                </button>
                <textarea
                  className="input-field"
                  placeholder={selectedSession?.isStreaming
                    ? "Type to queue... (messages will be sent after streaming completes)"
                    : "Type a message... (Enter to send, Shift+Enter for newline, Ctrl+V to paste image)"}
                  value={message}
                  onChange={e => setMessage(e.target.value)}
                  onKeyDown={handleKeyDown}
                  onPaste={handlePaste}
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
                    disabled={connectionState !== 'connected' || (!message.trim() && imageAttachments.length === 0)}
                  >
                    Send
                  </button>
                )}
              </form>
            </div>
          </>
        )}
      </AppLayout.Main>
    </AppLayout>
  );
}

// ============================================================================
// Header and Sidebar Components (extracted to use layout context)
// ============================================================================

interface MobileHeaderProps {
  connectionState: ConnectionState;
}

function MobileHeader({ connectionState }: MobileHeaderProps) {
  const { openSidebar } = useLayout();

  return (
    <>
      <button className="menu-button" onClick={openSidebar} aria-label="Open menu">
        ☰
      </button>
      <div className={`connection-status ${connectionState}`} title={connectionState} />
      <h1>Balloons</h1>
    </>
  );
}

interface SidebarContentProps {
  connectionState: ConnectionState;
  sessions: SessionInfo[];
  selectedSessionId: string | null;
  streamingTask: TaskInfo | null;
  onSelectSession: (sessionId: string) => void;
}

function SidebarContent({
  connectionState,
  sessions,
  selectedSessionId,
  streamingTask,
  onSelectSession,
}: SidebarContentProps) {
  const { closeSidebar, layoutMode } = useLayout();
  const { resolvedTheme, toggleTheme } = useTheme();

  const handleSelectSession = useCallback((sessionId: string) => {
    onSelectSession(sessionId);
    // Close sidebar on mobile after selection
    if (layoutMode === 'mobile') {
      closeSidebar();
    }
  }, [onSelectSession, closeSidebar, layoutMode]);

  return (
    <>
      <header className="sidebar-header">
        <div className={`connection-status ${connectionState}`} title={connectionState} />
        <h1>Balloons</h1>
        <button
          className="theme-toggle"
          onClick={toggleTheme}
          aria-label={`Switch to ${resolvedTheme === 'dark' ? 'light' : 'dark'} theme`}
          title={`Switch to ${resolvedTheme === 'dark' ? 'light' : 'dark'} theme`}
        >
          {resolvedTheme === 'dark' ? '☀️' : '🌙'}
        </button>
        {layoutMode === 'mobile' && (
          <button className="close-button" onClick={closeSidebar} aria-label="Close menu">
            ✕
          </button>
        )}
      </header>

      <div className="session-list">
        {sessions.length === 0 && connectionState === 'connected' && (
          <div style={{ padding: '16px', color: '#666', textAlign: 'center' }}>
            No sessions
          </div>
        )}

        {sessions.map(session => {
          const isSelected = session.id === selectedSessionId;
          const showStreamingDetails = isSelected && session.isStreaming && streamingTask;
          return (
            <div
              key={session.id}
              className={`session-item ${isSelected ? 'selected' : ''} ${session.isStreaming ? 'streaming' : ''}`}
              onClick={() => handleSelectSession(session.id)}
            >
              <div className="session-title">
                {session.title || `Session ${session.id.slice(0, 8)}`}
              </div>
              <div className="session-meta">
                {session.messageCount} messages
                {session.isStreaming && !showStreamingDetails && ' • streaming'}
              </div>
              {showStreamingDetails && (
                <div className="session-streaming-info">
                  <span className="streaming-badge">
                    <span className="streaming-dot" />
                    {streamingTask.toolName ? (
                      <span>{streamingTask.toolName}</span>
                    ) : (
                      <span>{formatTokens(streamingTask.tokensStreamed)} tokens</span>
                    )}
                  </span>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}
