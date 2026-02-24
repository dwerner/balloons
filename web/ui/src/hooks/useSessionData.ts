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
  SessionStreamProgressEvent,
  SessionStreamErrorEvent,
  SessionToolUseStartedEvent,
  SessionToolInputDeltaEvent,
  SessionToolUseEvent,
  SessionToolResultEvent,
  SessionHistoryChunkEvent,
  SessionHistoryCompleteEvent,
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

// Create a debug logger that respects the global debug toggle
import { createLogger } from '../utils/debugLog';
const debugLog = createLogger('useSessionData');

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
  /** Parallel group ID for visually grouping parallel tool calls */
  parallelGroupId?: string;
}

/**
 * Streaming progress info for status bar display.
 * Updated periodically (throttled) during streaming.
 */
export interface StreamingProgress {
  /** Estimated output tokens so far */
  tokensStreamed: number;
  /** Current token rate (tokens/sec) */
  currentTokenRate: number;
  /** Currently executing tool name, if any */
  toolName: string | null;
  /** Number of tools executed so far */
  toolCount: number;
  /** Model name */
  model: string;
  /** Model's context window size */
  contextWindow: number;
  /** Duration since stream started (seconds) */
  durationSeconds: number;
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
  /** Whether history chunks are still being loaded */
  isLoadingHistory: boolean;
  /** Highest turn order received from history chunks (for gap detection) */
  historyWatermark: number;
  /** Stream error message if any */
  streamError: string | null;
  /** Error message if any */
  error: string | null;
  /** Session ID we're subscribed to */
  sessionId: string | null;
  /** Streaming progress info (updated periodically during streaming) */
  streamingProgress: StreamingProgress | null;
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
  // State
  const [turnsById, setTurnsById] = useState<Map<string, SessionDataTurn>>(new Map());
  const [isLoading, setIsLoading] = useState(false);
  const [isSubscribed, setIsSubscribed] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [historyWatermark, setHistoryWatermark] = useState(-1);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [streamingProgress, setStreamingProgress] = useState<StreamingProgress | null>(null);

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
    setIsLoadingHistory(false);
    setHistoryWatermark(-1);
    setStreamError(null);
    setError(null);
    setSessionId(null);
    setStreamingProgress(null);
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
        debugLog('[useSessionData] Unsubscribe skipped (disconnected):', err);
      }
    }

    // Clear state
    clear();
  }, [client, clear]);

  // Subscribe to a session
  const subscribe = useCallback(
    async (newSessionId: string) => {
      debugLog('[useSessionData] subscribe called', {
        newSessionId,
        hasClient: !!client,
        currentSession: currentSessionRef.current,
        isSubscribed,
      });

      if (!client) {
        debugLog('[useSessionData] subscribe: no client');
        setError('Client not connected');
        return;
      }

      // Set loading state immediately to prevent "empty" flash during session switch
      setIsLoading(true);

      // Unsubscribe from previous session if any
      if (currentSessionRef.current && currentSessionRef.current !== newSessionId) {
        debugLog('[useSessionData] subscribe: unsubscribing from previous session', {
          previousSession: currentSessionRef.current,
        });
        await unsubscribe();
      }

      // Skip if already subscribed to this session
      if (currentSessionRef.current === newSessionId && isSubscribed) {
        debugLog('[useSessionData] subscribe: already subscribed, skipping');
        setIsLoading(false);  // Restore loading state since we didn't actually subscribe
        return;
      }

      debugLog('[useSessionData] subscribe: proceeding with subscription');
      setError(null);
      setSessionId(newSessionId);
      currentSessionRef.current = newSessionId;

      try {
        // IMPORTANT: Set up event handlers BEFORE subscribing to avoid race conditions
        // History chunks may arrive immediately after subscription, before the async
        // subscribe call returns. If handlers aren't registered, events are lost.
        const handlers: Unsubscribe[] = [];

        // Turn created - add new turn
        debugLog('Setting up sessionDataTurnCreated handler');
        handlers.push(
          client.sessionData.sessionDataTurnCreated((event: SessionTurnCreatedEvent) => {
            debugLog('[TURN_ORDER] turnCreated received', {
              order: event.order,
              turnId: event.turnId?.substring(0, 8),
              role: event.role,
              contentBlockType: event.contentBlockType,
              parallelGroupId: event.parallelGroupId?.substring(0, 8),
            });

            if (!event || typeof event !== 'object') {
              debugLog('[useSessionData] turnCreated received invalid event:', event);
              return;
            }

            if (event.sessionId !== newSessionId) {
              return;
            }

            const turnId = event.turnId ?? '';
            if (!turnId) {
              debugLog('[useSessionData] turnCreated missing turnId:', event);
              return;
            }

            setTurnsById((prev) => {
              if (prev.has(turnId)) {
                debugLog('[TURN_ORDER] turnCreated: turn already exists, skipping', { turnId: turnId.substring(0, 8) });
                return prev;
              }

              const next = new Map(prev);
              const serverOrder = event.order ?? 0;
              const contentBlockType = event.contentBlockType ?? 'text';

              debugLog('[TURN_ORDER] turnCreated: adding new turn', {
                turnId: turnId.substring(0, 8),
                order: serverOrder,
                contentBlockType,
                parallelGroupId: event.parallelGroupId?.substring(0, 8),
                existingTurns: Array.from(prev.values()).map(t => ({ order: t.order, type: t.contentBlock?.type })),
              });

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
                parallelGroupId: event.parallelGroupId ?? undefined,
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
              debugLog('[useSessionData] turnDelta missing turnId:', event);
              return;
            }

            setTurnsById((prev) => {
              const existing = prev.get(turnId);
              if (!existing) {
                // Turn not found - create it with text block
                debugLog(`[useSessionData] turnDelta for unknown turn ${turnId}, creating`);
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
            debugLog('[TURN_ORDER] turnFinished received', {
              order: event.order,
              turnId: event.turnId?.substring(0, 8),
              role: event.role,
              contentBlockType: event.contentBlock?.type,
            });

            if (!event || typeof event !== 'object') {
              debugLog('[useSessionData] turnFinished received invalid event:', event);
              return;
            }

            if (event.sessionId !== newSessionId) return;

            const turnId = event.turnId || '';
            if (!turnId) {
              debugLog('[useSessionData] turnFinished missing turnId:', event);
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
                debugLog('[TURN_ORDER] turnFinished for unknown turn, creating', {
                  turnId: turnId.substring(0, 8),
                  order: event.order,
                  existingTurns: Array.from(prev.values()).map(t => ({ order: t.order, type: t.contentBlock?.type })),
                });
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

              // Use event.order if provided, otherwise keep existing order
              const effectiveOrder = event.order !== undefined && event.order !== null
                ? event.order
                : existing.order;

              debugLog('[TURN_ORDER] turnFinished updating existing turn', {
                turnId: turnId.substring(0, 8),
                existingOrder: existing.order,
                eventOrder: event.order,
                effectiveOrder,
              });

              const next = new Map(prev);
              next.set(turnId, {
                ...existing,
                order: effectiveOrder,
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
            // Reset progress when stream starts
            setStreamingProgress(null);
          })
        );

        handlers.push(
          client.sessionData.sessionDataStreamDone((event: SessionStreamDoneEvent) => {
            if (event.sessionId !== newSessionId) return;
            setIsStreaming(false);
            // Clear progress when stream ends
            setStreamingProgress(null);
          })
        );

        // Stream progress - throttled updates during streaming
        handlers.push(
          client.sessionData.sessionDataStreamProgress((event: SessionStreamProgressEvent) => {
            if (event.sessionId !== newSessionId) return;
            setStreamingProgress({
              tokensStreamed: event.tokensStreamed,
              currentTokenRate: event.currentTokenRate,
              toolName: event.toolName,
              toolCount: event.toolCount,
              model: event.model,
              contextWindow: event.contextWindow,
              durationSeconds: event.durationSeconds,
            });
          })
        );

        handlers.push(
          client.sessionData.sessionDataStreamError((event: SessionStreamErrorEvent) => {
            if (event.sessionId !== newSessionId) return;
            setIsStreaming(false);
            setStreamError(event.error);
            setStreamingProgress(null);
          })
        );

        // Tool events - update turn content blocks
        handlers.push(
          client.sessionData.sessionDataToolUseStarted((event: SessionToolUseStartedEvent) => {
            if (event.sessionId !== newSessionId) return;
            debugLog('sessionDataToolUseStarted', event);

            // Find the tool_use turn by turn_index and update it with the tool info
            // Note: parallelGroupId is already set via the turnCreated event
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

        // History chunk - merge historical turns (Phase 4: chunked history loading)
        handlers.push(
          client.sessionData.sessionDataHistoryChunk((event: SessionHistoryChunkEvent) => {
            if (event.sessionId !== newSessionId) return;
            debugLog('sessionDataHistoryChunk', {
              chunkIndex: event.chunkIndex,
              totalChunks: event.totalChunks,
              turnsCount: event.turns?.length ?? 0,
            });

            // Mark that we're loading history
            setIsLoadingHistory(true);

            // Merge historical turns into state
            // IMPORTANT: Don't overwrite turns that are already present (they may be streaming)
            setTurnsById((prev) => {
              const next = new Map(prev);
              let maxWatermark = -1;

              for (const turn of event.turns || []) {
                const turnId = turn.turnId || '';
                if (!turnId) continue;

                // Get the order from the turn data
                const order = turn.order ?? 0;
                if (order > maxWatermark) {
                  maxWatermark = order;
                }

                // Only add if not already present - streaming turns take precedence
                if (!next.has(turnId)) {
                  next.set(turnId, {
                    turnId,
                    order,
                    role: turn.role,
                    contentBlock: turn.contentBlock,
                    streaming: turn.streaming || false,
                    viewed: turn.viewed || false,
                    tokens: turn.tokens || 0,
                    contextMode: turn.contextMode || 'copy',
                    exchangeId: turn.exchangeId ?? undefined,
                  });
                }
              }

              // Update watermark
              if (maxWatermark > -1) {
                setHistoryWatermark((prev) => Math.max(prev, maxWatermark));
              }

              return next;
            });
          })
        );

        // History complete - all historical turns have been sent
        handlers.push(
          client.sessionData.sessionDataHistoryComplete((event: SessionHistoryCompleteEvent) => {
            if (event.sessionId !== newSessionId) return;
            debugLog('sessionDataHistoryComplete', {
              totalTurns: event.totalTurns,
              finalWatermark: event.finalWatermark,
            });

            setIsLoadingHistory(false);
            setHistoryWatermark(event.finalWatermark);
          })
        );

        // Save handlers immediately so events can be processed
        unsubscribersRef.current = handlers;

        // NOW subscribe - handlers are ready to receive events
        const result = await client.sessionData.subscribeSession(newSessionId);

        if (!result.subscribed) {
          // Cleanup handlers on failure
          handlers.forEach((unsub) => unsub());
          unsubscribersRef.current = [];
          throw new Error(result.error || 'Subscription failed');
        }

        // Process snapshot (metadata only - history arrives via chunks)
        debugLog('[useSessionData] subscription result', {
          hasSnapshot: !!result.snapshot,
          turnCount: result.snapshot?.turns?.length ?? 0,
          isStreaming: result.snapshot?.isStreaming,
        });

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

        debugLog('[useSessionData] setting state: isSubscribed=true, isLoading=false', {
          initialTurnsCount: initialTurns.size,
        });
        setTurnsById(initialTurns);
        setIsSubscribed(true);
        setIsLoading(false);

        // History loading state: if snapshot has no turns, history will arrive via chunks
        const hasTurnsInSnapshot = (result.snapshot?.turns?.length ?? 0) > 0;
        setIsLoadingHistory(!hasTurnsInSnapshot);
        setHistoryWatermark(-1);

        // Initialize streaming state from snapshot
        if (result.snapshot?.isStreaming !== undefined) {
          setIsStreaming(result.snapshot.isStreaming);
        } else {
          setIsStreaming(false);
        }
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
    debugLog('[useSessionData] useEffect triggered', {
      hasClient: !!client,
      autoSubscribe,
      isSubscribed,
      currentSession: currentSessionRef.current,
    });

    if (!client || !autoSubscribe) {
      if (isSubscribed && !autoSubscribe) {
        debugLog('[useSessionData] unsubscribing (no autoSubscribe)');
        unsubscribe();
      }
      return;
    }

    debugLog('[useSessionData] calling subscribe', { autoSubscribe });
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
        debugLog('[useSessionData] Client reconnected, re-subscribing to session:', autoSubscribe);

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
    isLoadingHistory,
    historyWatermark,
    streamError,
    error,
    sessionId,
    streamingProgress,
    subscribe,
    unsubscribe,
    getTurn,
    clear,
  };
}

export default useSessionData;
