/**
 * useSessionData - React hook for SessionDataService subscription
 *
 * Provides subscription-based real-time session data streaming:
 * - Subscribe/unsubscribe lifecycle management
 * - Map<turn_id, TurnInfo> for efficient turn lookup
 * - Apply deltas incrementally
 * - Expose sorted turns array
 *
 * This hook uses SessionDataService (turn_id based) rather than
 * TaskStateService (turn_index based) for the new streaming architecture.
 *
 * @see service/session_data_service.py
 */

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import type { BalloonsClient, Unsubscribe } from '../../../generated/balloons-client';
import type {
  SessionTurnCreatedEvent,
  SessionTurnDeltaEvent,
  SessionTurnFinishedEvent,
  SessionStreamStartedEvent,
  SessionStreamDoneEvent,
  SessionStreamErrorEvent,
  SessionToolUseStartedEvent,
  SessionToolInputDeltaEvent,
  SessionToolUseEvent,
  SessionToolResultEvent,
  TurnSnapshot,
  TextBlock,
  ToolUseBlock,
  ToolResultBlock,
  ImageBlock,
  InterruptionBlock,
  ErrorBlock,
  LinkBlock,
  ForkBlock,
  MergeBlock,
  MergedToBlock,
  ArchiveBlock,
  SlideBlock,
  ReviewBlock,
  ForkProposalBlock,
  MergeProposalBlock,
} from '../../../generated/types';

/**
 * Union of all content block types
 */
export type ContentBlock =
  | TextBlock
  | ImageBlock
  | ToolUseBlock
  | ToolResultBlock
  | InterruptionBlock
  | ErrorBlock
  | LinkBlock
  | ForkBlock
  | MergeBlock
  | MergedToBlock
  | ArchiveBlock
  | SlideBlock
  | ReviewBlock
  | ForkProposalBlock
  | MergeProposalBlock;

// Create a debug logger that uses the client's WebSocket connection
function createDebugLog(client: BalloonsClient | null) {
  return (message: string, data?: unknown): void => {
    console.log('[useSessionData]', message, data);
    if (client?.isConnected) {
      client.debugLog.info(message, 'web.useSessionData', '', data as Record<string, unknown> | null).catch(() => {});
    }
  };
}

/**
 * Internal turn state maintained by the hook.
 * Uses turn_id (UUID) as the key, not turn index.
 */
export interface SessionDataTurn {
  /** Stable UUID for this turn (primary identifier) */
  turnId: string;
  /** Insertion order (for display ordering) - derived from array position */
  order: number;
  /** Turn role: "user", "assistant", "tool", "system" */
  role: string;
  /** Full structured content block - source of truth for turn content */
  contentBlock: ContentBlock;
  /** Whether this turn is currently streaming */
  streaming: boolean;
  /** Whether this turn has been viewed */
  viewed: boolean;
  /** Token count (set when turn finishes) */
  tokens: number;
  /** Context mode: "copy", "compress", "drop" */
  contextMode: string;
  /** Exchange ID for grouping related turns */
  exchangeId?: string;
}

export interface UseSessionDataState {
  /** Map of turn_id -> turn data */
  turnsById: Map<string, SessionDataTurn>;
  /** Sorted array of turns (by order) */
  turns: SessionDataTurn[];
  /** Whether initial snapshot is loading */
  isLoading: boolean;
  /** Whether we're subscribed to the session */
  isSubscribed: boolean;
  /** Whether the session is currently streaming */
  isStreaming: boolean;
  /** Stream error message if any */
  streamError: string | null;
  /** Error message if any */
  error: string | null;
  /** Session ID we're subscribed to */
  sessionId: string | null;
}

export interface UseSessionDataReturn extends UseSessionDataState {
  /** Subscribe to a session */
  subscribe: (sessionId: string) => Promise<void>;
  /** Unsubscribe from current session */
  unsubscribe: () => Promise<void>;
  /** Get a turn by ID */
  getTurn: (turnId: string) => SessionDataTurn | undefined;
  /** Clear all state */
  clear: () => void;
}

/**
 * Extract display text from a content block.
 * Used for streaming accumulation and display.
 */
function getTextFromBlock(block: ContentBlock): string {
  if (!block) return '';
  switch (block.type) {
    case 'text':
      return (block as TextBlock).text ?? '';
    case 'tool_result':
      return (block as ToolResultBlock).content ?? '';
    default:
      return '';
  }
}

/**
 * Create an initial content block for a streaming turn.
 */
function createInitialBlock(contentBlockType: string): ContentBlock {
  switch (contentBlockType) {
    case 'text':
      return { type: 'text', text: '' } as TextBlock;
    case 'tool_use':
      return { type: 'tool_use', id: '', name: '', input: {} } as ToolUseBlock;
    case 'tool_result':
      return { type: 'tool_result', toolUseId: '', content: '', isError: false } as ToolResultBlock;
    case 'image':
      return { type: 'image', filePath: '', mediaType: '', filename: '' } as ImageBlock;
    case 'fork':
      return { type: 'fork', forkId: '', childSessionId: '', forkName: '', prompt: '', status: 'active' } as ForkBlock;
    case 'merge':
      return { type: 'merge', mergeId: '', childSessionId: '', forkName: '', message: '' } as MergeBlock;
    case 'merged_to':
      return { type: 'merged_to', mergeId: '', parentSessionId: '', parentName: '', message: '' } as MergedToBlock;
    case 'link':
      return { type: 'link', linkId: '', linkedSessionId: '', summary: '' } as LinkBlock;
    case 'interruption':
      return { type: 'interruption', reason: 'user_cancelled' } as InterruptionBlock;
    case 'error':
      return { type: 'error', reason: 'stream_error', details: '' } as ErrorBlock;
    case 'archive':
      return { type: 'archive', archiveId: '', filePath: '', summary: '' } as ArchiveBlock;
    case 'slide':
      return { type: 'slide', title: '', content: '', notes: '' } as SlideBlock;
    case 'review':
      return { type: 'review', reviewId: '', childSessionId: '', status: 'active' } as ReviewBlock;
    case 'fork_proposal':
      return { type: 'fork_proposal', proposalId: '', name: '', description: '', status: 'pending' } as ForkProposalBlock;
    case 'merge_proposal':
      return { type: 'merge_proposal', proposalId: '', summary: '', status: 'pending' } as MergeProposalBlock;
    default:
      // Default to text block for unknown types
      return { type: 'text', text: '' } as TextBlock;
  }
}

/**
 * Update a text block with a delta.
 */
function appendTextDelta(block: ContentBlock, delta: string): ContentBlock {
  if (block.type === 'text') {
    const textBlock = block as TextBlock;
    return { ...textBlock, text: (textBlock.text ?? '') + delta };
  }
  // For non-text blocks during streaming, we can't really append
  // This shouldn't happen normally - tool input streams via separate events
  return block;
}

/**
 * Hook for subscribing to session data via SessionDataService
 *
 * @param client - BalloonsClient instance
 * @param autoSubscribe - Session ID to automatically subscribe to (optional)
 */
export function useSessionData(
  client: BalloonsClient | null,
  autoSubscribe?: string | null
): UseSessionDataReturn {
  // Create debug logger using the client's WebSocket connection
  const debugLog = createDebugLog(client);

  // State
  const [turnsById, setTurnsById] = useState<Map<string, SessionDataTurn>>(new Map());
  const [isLoading, setIsLoading] = useState(false);
  const [isSubscribed, setIsSubscribed] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);

  // Refs for cleanup
  const unsubscribersRef = useRef<Unsubscribe[]>([]);
  const currentSessionRef = useRef<string | null>(null);

  // Derive sorted turns array from map (sorted by insertion order)
  const turns = useMemo(() => {
    return Array.from(turnsById.values()).sort((a, b) => a.order - b.order);
  }, [turnsById]);

  // Get a turn by ID
  const getTurn = useCallback(
    (turnId: string): SessionDataTurn | undefined => {
      return turnsById.get(turnId);
    },
    [turnsById]
  );

  // Clear all state
  const clear = useCallback(() => {
    setTurnsById(new Map());
    setIsLoading(false);
    setIsSubscribed(false);
    setIsStreaming(false);
    setStreamError(null);
    setError(null);
    setSessionId(null);
    currentSessionRef.current = null;
  }, []);

  // Unsubscribe from current session
  const unsubscribe = useCallback(async () => {
    // Clean up event handlers
    unsubscribersRef.current.forEach((unsub) => unsub());
    unsubscribersRef.current = [];

    // Unsubscribe from session on server (only if client is still connected)
    if (client && client.isConnected && currentSessionRef.current) {
      try {
        await client.sessionData.unsubscribeSession(
          currentSessionRef.current
        );
      } catch (err) {
        // Ignore unsubscribe errors during disconnect
        console.debug('[useSessionData] Unsubscribe skipped (disconnected):', err);
      }
    }

    // Clear state
    clear();
  }, [client, clear]);

  // Subscribe to a session
  const subscribe = useCallback(
    async (newSessionId: string) => {
      if (!client) {
        setError('Client not connected');
        return;
      }

      // Unsubscribe from previous session if any
      if (currentSessionRef.current && currentSessionRef.current !== newSessionId) {
        await unsubscribe();
      }

      // Skip if already subscribed to this session
      if (currentSessionRef.current === newSessionId && isSubscribed) {
        return;
      }

      setIsLoading(true);
      setError(null);
      setSessionId(newSessionId);
      currentSessionRef.current = newSessionId;

      try {
        console.log(`[useSessionData] Subscribing to session ${newSessionId}`);

        // Subscribe to session - returns snapshot atomically with subscription
        const result = await client.sessionData.subscribeSession(newSessionId);

        console.log(`[useSessionData] Subscribe result:`, result);

        if (!result.subscribed) {
          throw new Error(result.error || 'Subscription failed');
        }

        console.log(`[useSessionData] Subscription successful, snapshot has ${result.snapshot?.turns?.length ?? 0} turns`);

        // Convert snapshot turns to our format
        const initialTurns = new Map<string, SessionDataTurn>();
        if (result.snapshot?.turns) {
          result.snapshot.turns.forEach((turn: TurnSnapshot, arrayIndex: number) => {
            const turnId = turn.turnId || `snapshot-${newSessionId}-${arrayIndex}`;
            initialTurns.set(turnId, {
              turnId,
              order: arrayIndex,
              role: turn.role,
              contentBlock: turn.contentBlock,
              streaming: turn.streaming || false,
              viewed: turn.viewed || false,
              tokens: turn.tokens || 0,
              contextMode: turn.contextMode || 'copy',
              exchangeId: turn.exchangeId ?? undefined,
            });
          });
        }

        setTurnsById(initialTurns);
        setIsSubscribed(true);
        setIsLoading(false);

        // Initialize streaming state from snapshot
        // This handles the case where we reconnect to a session that was streaming
        // or reconnect after it stopped streaming while we were disconnected
        if (result.snapshot?.isStreaming !== undefined) {
          setIsStreaming(result.snapshot.isStreaming);
        } else {
          // If no snapshot streaming info, default to false
          setIsStreaming(false);
        }

        // Set up event handlers
        const handlers: Unsubscribe[] = [];

        // Turn created - add new turn
        debugLog('Setting up sessionDataTurnCreated handler');
        handlers.push(
          client.sessionData.sessionDataTurnCreated((event: SessionTurnCreatedEvent) => {
            debugLog('sessionDataTurnCreated received', event);

            if (!event || typeof event !== 'object') {
              console.warn('[useSessionData] turnCreated received invalid event:', event);
              return;
            }

            if (event.sessionId !== newSessionId) {
              return;
            }

            const turnId = event.turnId ?? '';
            if (!turnId) {
              console.warn('[useSessionData] turnCreated missing turnId:', event);
              return;
            }

            setTurnsById((prev) => {
              if (prev.has(turnId)) {
                return prev;
              }

              const next = new Map(prev);
              const serverOrder = event.order ?? 0;
              const contentBlockType = event.contentBlockType ?? 'text';

              next.set(turnId, {
                turnId,
                order: serverOrder,
                role: event.role ?? 'assistant',
                contentBlock: createInitialBlock(contentBlockType),
                streaming: true,
                viewed: false,
                tokens: 0,
                contextMode: 'copy',
                exchangeId: event.exchangeId ?? undefined,
              });

              return next;
            });
          })
        );

        // Turn delta - update content (for text blocks)
        debugLog('Setting up sessionDataTurnDelta handler');
        handlers.push(
          client.sessionData.sessionDataTurnDelta((event: SessionTurnDeltaEvent) => {
            debugLog('sessionDataTurnDelta received', event);

            if (!event || typeof event !== 'object') {
              return;
            }

            if (event.sessionId !== newSessionId) {
              return;
            }

            const delta = event.delta ?? '';
            const turnId = event.turnId ?? '';

            if (!turnId) {
              console.warn('[useSessionData] turnDelta missing turnId:', event);
              return;
            }

            setTurnsById((prev) => {
              const existing = prev.get(turnId);
              if (!existing) {
                // Turn not found - create it with text block
                console.warn(`[useSessionData] turnDelta for unknown turn ${turnId}, creating`);
                const maxOrder = Math.max(-1, ...Array.from(prev.values()).map((t) => t.order));

                const next = new Map(prev);
                next.set(turnId, {
                  turnId,
                  order: maxOrder + 1,
                  role: 'assistant',
                  contentBlock: { type: 'text', text: delta } as TextBlock,
                  streaming: true,
                  viewed: false,
                  tokens: 0,
                  contextMode: 'copy',
                });
                return next;
              }

              // Append delta to existing turn's content block
              const next = new Map(prev);
              next.set(turnId, {
                ...existing,
                contentBlock: appendTextDelta(existing.contentBlock, delta),
                streaming: true,
              });
              return next;
            });
          })
        );

        // Turn finished - finalize turn with complete content block
        handlers.push(
          client.sessionData.sessionDataTurnFinished((event: SessionTurnFinishedEvent) => {
            console.log('[useSessionData] turnFinished raw event:', event);

            if (!event || typeof event !== 'object') {
              console.warn('[useSessionData] turnFinished received invalid event:', event);
              return;
            }

            if (event.sessionId !== newSessionId) return;

            const turnId = event.turnId || '';
            if (!turnId) {
              console.warn('[useSessionData] turnFinished missing turnId:', event);
              return;
            }

            setTurnsById((prev) => {
              const existing = prev.get(turnId);

              // Get the final content block from the event
              // Prefer contentBlock, fall back to finalContent as TextBlock, fall back to existing
              let finalContentBlock: ContentBlock;
              if (event.contentBlock) {
                finalContentBlock = event.contentBlock;
              } else if (event.finalContent) {
                finalContentBlock = { type: 'text', text: event.finalContent } as TextBlock;
              } else if (existing?.contentBlock) {
                finalContentBlock = existing.contentBlock;
              } else {
                finalContentBlock = { type: 'text', text: '' } as TextBlock;
              }

              if (!existing) {
                console.warn(`[useSessionData] turnFinished for unknown turn ${turnId}, creating`);
                // Use order from event if available, otherwise fall back to maxOrder + 1
                const serverOrder = event.order;
                const effectiveOrder = serverOrder !== undefined && serverOrder !== null
                  ? serverOrder
                  : Math.max(-1, ...Array.from(prev.values()).map((t) => t.order)) + 1;

                const next = new Map(prev);
                next.set(turnId, {
                  turnId,
                  order: effectiveOrder,
                  role: event.role ?? 'assistant',
                  contentBlock: finalContentBlock,
                  streaming: false,
                  viewed: false,
                  tokens: event.tokens ?? 0,
                  contextMode: 'copy',
                });
                return next;
              }

              const next = new Map(prev);
              next.set(turnId, {
                ...existing,
                contentBlock: finalContentBlock,
                tokens: event.tokens ?? 0,
                streaming: false,
              });
              return next;
            });
          })
        );

        // Stream lifecycle events
        handlers.push(
          client.sessionData.sessionDataStreamStarted((event: SessionStreamStartedEvent) => {
            if (event.sessionId !== newSessionId) return;
            setIsStreaming(true);
            setStreamError(null);
          })
        );

        handlers.push(
          client.sessionData.sessionDataStreamDone((event: SessionStreamDoneEvent) => {
            if (event.sessionId !== newSessionId) return;
            setIsStreaming(false);
          })
        );

        handlers.push(
          client.sessionData.sessionDataStreamError((event: SessionStreamErrorEvent) => {
            if (event.sessionId !== newSessionId) return;
            setIsStreaming(false);
            setStreamError(event.error);
          })
        );

        // Tool events - update turn content blocks
        handlers.push(
          client.sessionData.sessionDataToolUseStarted((event: SessionToolUseStartedEvent) => {
            if (event.sessionId !== newSessionId) return;
            debugLog('sessionDataToolUseStarted', event);

            // Find the tool_use turn by turn_index and update it with the tool info
            setTurnsById((prev) => {
              // Find a tool_use turn at this turn_index that needs initialization
              for (const [turnId, turn] of prev.entries()) {
                if (
                  turn.contentBlock?.type === 'tool_use' &&
                  turn.order === event.turnIndex &&
                  !(turn.contentBlock as ToolUseBlock).id
                ) {
                  debugLog('Populating tool_use ID', {
                    turnId: turnId.substring(0, 8),
                    turnIndex: event.turnIndex,
                    toolUseId: event.toolUseId,
                    toolName: event.toolName,
                    previousId: (turn.contentBlock as ToolUseBlock).id || '(empty)',
                  });
                  const next = new Map(prev);
                  const block = turn.contentBlock as ToolUseBlock;
                  next.set(turnId, {
                    ...turn,
                    contentBlock: {
                      ...block,
                      id: event.toolUseId,
                      name: event.toolName,
                    } as ToolUseBlock,
                  });
                  return next;
                }
              }
              debugLog('sessionDataToolUseStarted: could not find matching turn', {
                turnIndex: event.turnIndex,
                toolUseId: event.toolUseId,
                toolName: event.toolName,
                turnsCount: prev.size,
                turnOrders: Array.from(prev.values()).map((t) => ({ order: t.order, type: t.contentBlock?.type })),
              });
              return prev;
            });
          })
        );

        handlers.push(
          client.sessionData.sessionDataToolInputDelta((event: SessionToolInputDeltaEvent) => {
            if (event.sessionId !== newSessionId) return;
            // Update tool_use block with streaming input
            setTurnsById((prev) => {
              // Find the turn with this tool_use_id
              for (const [turnId, turn] of prev.entries()) {
                if (
                  turn.contentBlock?.type === 'tool_use' &&
                  (turn.contentBlock as ToolUseBlock).id === event.toolUseId
                ) {
                  const next = new Map(prev);
                  const block = turn.contentBlock as ToolUseBlock;
                  // Append to partial input display (stored as string for streaming)
                  next.set(turnId, {
                    ...turn,
                    contentBlock: {
                      ...block,
                      input: { _streaming: event.partialJson },
                    } as ToolUseBlock,
                  });
                  return next;
                }
              }
              return prev;
            });
          })
        );

        handlers.push(
          client.sessionData.sessionDataToolUse((event: SessionToolUseEvent) => {
            if (event.sessionId !== newSessionId) return;
            // Update tool_use block with final input
            setTurnsById((prev) => {
              for (const [turnId, turn] of prev.entries()) {
                if (
                  turn.contentBlock?.type === 'tool_use' &&
                  (turn.contentBlock as ToolUseBlock).id === event.toolUseId
                ) {
                  const next = new Map(prev);
                  const block = turn.contentBlock as ToolUseBlock;
                  next.set(turnId, {
                    ...turn,
                    contentBlock: {
                      ...block,
                      input: event.toolInput,
                    } as ToolUseBlock,
                  });
                  return next;
                }
              }
              return prev;
            });
          })
        );

        handlers.push(
          client.sessionData.sessionDataToolResult((event: SessionToolResultEvent) => {
            if (event.sessionId !== newSessionId) return;
            // Tool result turn is created via turnCreated/turnFinished - this is informational
            debugLog('sessionDataToolResult', event);
          })
        );

        unsubscribersRef.current = handlers;
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        setError(`Subscription failed: ${message}`);
        setIsLoading(false);
        setIsSubscribed(false);
        currentSessionRef.current = null;
      }
    },
    [client, isSubscribed, unsubscribe]
  );

  // Auto-subscribe when autoSubscribe changes
  useEffect(() => {
    if (!client || !autoSubscribe) {
      if (isSubscribed && !autoSubscribe) {
        unsubscribe();
      }
      return;
    }

    subscribe(autoSubscribe);

    return () => {
      unsubscribe();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, autoSubscribe]);

  // Re-subscribe when client reconnects
  // This handles the case where the WebSocket disconnects (e.g., phone sleeps)
  // and then reconnects - we need to re-establish the subscription and refresh state
  useEffect(() => {
    if (!client || !autoSubscribe) return;

    // Track previous state to detect reconnection
    let wasConnected = client.isConnected;

    const unsubStateChange = client.onStateChange((state) => {
      const isNowConnected = state === 'connected';

      // Detect reconnection: was disconnected, now connected
      if (!wasConnected && isNowConnected) {
        console.log('[useSessionData] Client reconnected, re-subscribing to session:', autoSubscribe);

        // Clear stale subscription state since handlers are likely invalid
        unsubscribersRef.current.forEach((unsub) => unsub());
        unsubscribersRef.current = [];
        setIsSubscribed(false);

        // Re-subscribe to get fresh state
        subscribe(autoSubscribe);
      }

      wasConnected = isNowConnected;
    });

    return () => {
      unsubStateChange();
    };
    // Note: we intentionally don't depend on subscribe to avoid infinite loops
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, autoSubscribe]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      unsubscribersRef.current.forEach((unsub) => unsub());
      unsubscribersRef.current = [];
    };
  }, []);

  return {
    turnsById,
    turns,
    isLoading,
    isSubscribed,
    isStreaming,
    streamError,
    error,
    sessionId,
    subscribe,
    unsubscribe,
    getTurn,
    clear,
  };
}

export default useSessionData;
