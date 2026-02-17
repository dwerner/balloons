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
  TurnSnapshot,
} from '../../../generated/types';

// Debug logging to server
function debugLog(message: string, data?: unknown): void {
  const payload = { message, data, timestamp: Date.now() };
  console.log('[useSessionData]', message, data);
  fetch('/debug-log', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).catch(() => {}); // Ignore errors
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
  /** Turn role: "user", "assistant", "tool" */
  role: string;
  /** Content accumulated so far */
  content: string;
  /** Whether this turn is currently streaming */
  streaming: boolean;
  /** Whether this turn has been viewed */
  viewed: boolean;
  /** Token count (set when turn finishes) */
  tokens: number;
  /** Context mode: "copy", "compress", "drop" */
  contextMode: string;
  /** Content block type */
  contentBlockType?: string;
  /** Exchange ID for grouping related turns */
  exchangeId?: string;
  /** Accumulated content length for validation */
  accumulatedLength: number;
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

// Note: Client ID is now injected by the ws_server, not generated client-side.
// This ensures the client_id used for subscription matches the WebSocket client_id
// for proper event targeting.

/**
 * Hook for subscribing to session data via SessionDataService
 *
 * @param client - BalloonsClient instance
 * @param autoSubscribe - Session ID to automatically subscribe to (optional)
 *
 * @example
 * ```tsx
 * function MyComponent({ sessionId, client }) {
 *   const { turns, isLoading, isSubscribed, error } = useSessionData(client, sessionId);
 *
 *   if (isLoading) return <div>Loading...</div>;
 *   if (error) return <div>Error: {error}</div>;
 *
 *   return (
 *     <div>
 *       {turns.map(turn => (
 *         <TurnCard key={turn.turnId} turn={turn} />
 *       ))}
 *     </div>
 *   );
 * }
 * ```
 */
export function useSessionData(
  client: BalloonsClient | null,
  autoSubscribe?: string | null
): UseSessionDataReturn {
  // State
  const [turnsById, setTurnsById] = useState<Map<string, SessionDataTurn>>(new Map());
  const [isLoading, setIsLoading] = useState(false);
  const [isSubscribed, setIsSubscribed] = useState(false);
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
    // Note: Don't pass clientId - let ws_server inject the real client ID
    if (client && client.isConnected && currentSessionRef.current) {
      try {
        await client.sessionData.unsubscribeSession(
          currentSessionRef.current
        );
      } catch (err) {
        // Ignore unsubscribe errors during disconnect - this is expected
        // when the component unmounts after the client disconnects
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
        // Note: Don't pass clientId - let ws_server inject the real client ID
        const result = await client.sessionData.subscribeSession(
          newSessionId
        );

        console.log(`[useSessionData] Subscribe result:`, result);

        if (!result.subscribed) {
          throw new Error(result.error || 'Subscription failed');
        }

        console.log(`[useSessionData] Subscription successful, snapshot has ${result.snapshot?.turns?.length ?? 0} turns`);

        // Convert snapshot turns to our format (snapshot is included in subscribe result)
        // Turns come in array order - use array index for ordering
        const initialTurns = new Map<string, SessionDataTurn>();
        if (result.snapshot?.turns) {
          result.snapshot.turns.forEach((turn: TurnSnapshot, arrayIndex: number) => {
            // Use the real turn_id from the snapshot (or fall back to generated ID)
            const turnId = turn.turnId || `snapshot-${newSessionId}-${arrayIndex}`;
            initialTurns.set(turnId, {
              turnId,
              order: arrayIndex,  // Use array position for ordering
              role: turn.role,
              content: turn.content || '',
              streaming: turn.streaming || false,
              viewed: turn.viewed || false,
              tokens: turn.tokens || 0,
              contextMode: turn.contextMode || 'copy',
              contentBlockType: turn.contentBlockType,
              exchangeId: turn.exchangeId ?? undefined,
              accumulatedLength: turn.content?.length || 0,
            });
          });
        }

        setTurnsById(initialTurns);
        setIsSubscribed(true);
        setIsLoading(false);

        // Set up event handlers
        const handlers: Unsubscribe[] = [];

        // Turn created - add new turn
        debugLog('Setting up sessionDataTurnCreated handler');
        handlers.push(
          client.sessionData.sessionDataTurnCreated((event: SessionTurnCreatedEvent) => {
            debugLog('sessionDataTurnCreated received', event);

            // Defensive: check if event is valid
            if (!event || typeof event !== 'object') {
              console.warn('[useSessionData] turnCreated received invalid event:', event);
              return;
            }

            if (event.sessionId !== newSessionId) {
              console.log(`[useSessionData] turnCreated for different session: ${event.sessionId} vs ${newSessionId}`);
              return;
            }

            const turnId = event.turnId ?? '';
            if (!turnId) {
              console.warn('[useSessionData] turnCreated missing turnId:', event);
              return;
            }

            setTurnsById((prev) => {
              // Skip if turn already exists
              if (prev.has(turnId)) {
                return prev;
              }

              const next = new Map(prev);
              // Use the order from the server (authoritative)
              const serverOrder = event.order ?? 0;

              next.set(turnId, {
                turnId: turnId,
                order: serverOrder,
                role: event.role ?? 'assistant',
                content: '',
                streaming: true,
                viewed: false,
                tokens: 0,
                contextMode: 'copy',
                contentBlockType: event.contentBlockType,
                exchangeId: event.exchangeId ?? undefined,
                accumulatedLength: 0,
              });

              return next;
            });
          })
        );

        // Turn delta - update content
        debugLog('Setting up sessionDataTurnDelta handler');
        handlers.push(
          client.sessionData.sessionDataTurnDelta((event: SessionTurnDeltaEvent) => {
            debugLog('sessionDataTurnDelta received', event);

            // Defensive: check if event is valid
            if (!event || typeof event !== 'object') {
              debugLog('turnDelta received invalid event', event);
              return;
            }

            if (event.sessionId !== newSessionId) {
              debugLog(`turnDelta for different session: ${event.sessionId} vs ${newSessionId}`);
              return;
            }

            const delta = event.delta ?? '';
            const turnId = event.turnId ?? '';
            const accumulatedLength = event.accumulatedLength ?? 0;

            if (!turnId) {
              console.warn('[useSessionData] turnDelta missing turnId:', event);
              return;
            }

            setTurnsById((prev) => {
              const existing = prev.get(turnId);
              if (!existing) {
                // Turn not found - create it (turnCreated should have arrived first)
                // Use maxOrder+1 as fallback - may cause ordering issues
                console.warn(`[useSessionData] turnDelta for unknown turn ${turnId}, creating with fallback order`);
                const maxOrder = Math.max(-1, ...Array.from(prev.values()).map((t) => t.order));
                const newOrder = maxOrder + 1;

                const next = new Map(prev);
                next.set(turnId, {
                  turnId: turnId,
                  order: newOrder,
                  role: 'assistant',
                  content: delta,
                  streaming: true,
                  viewed: false,
                  tokens: 0,
                  contextMode: 'copy',
                  accumulatedLength: accumulatedLength,
                });
                return next;
              }

              // Validate accumulated length matches (only if delta is non-empty)
              if (delta.length > 0) {
                const expectedLength = existing.accumulatedLength + delta.length;
                if (accumulatedLength !== expectedLength) {
                  console.warn(
                    `[useSessionData] Length mismatch for turn ${turnId}: ` +
                      `expected ${expectedLength}, got ${accumulatedLength}`
                  );
                }
              }

              // Update existing turn
              const next = new Map(prev);
              next.set(turnId, {
                ...existing,
                content: existing.content + delta,
                accumulatedLength: accumulatedLength,
                streaming: true,
              });
              return next;
            });
          })
        );

        // Turn finished - finalize turn
        handlers.push(
          client.sessionData.sessionDataTurnFinished((event: SessionTurnFinishedEvent) => {
            // Debug: log raw event to understand what we're receiving
            console.log('[useSessionData] turnFinished raw event:', event);

            // Defensive: check if event is valid
            if (!event || typeof event !== 'object') {
              console.warn('[useSessionData] turnFinished received invalid event:', event);
              return;
            }

            if (event.sessionId !== newSessionId) return;

            // Handle potentially undefined finalContent (defensive - use || for falsy values too)
            const finalContent = (event.finalContent !== undefined && event.finalContent !== null)
              ? String(event.finalContent)
              : '';

            const turnId = event.turnId || '';
            if (!turnId) {
              console.warn('[useSessionData] turnFinished missing turnId:', event);
              return;
            }

            setTurnsById((prev) => {
              const existing = prev.get(turnId);
              if (!existing) {
                // Create the turn if it doesn't exist (turnCreated should have arrived first)
                // Use maxOrder+1 as fallback - may cause ordering issues
                console.warn(`[useSessionData] turnFinished for unknown turn ${turnId}, creating with fallback order`);
                const maxOrder = Math.max(-1, ...Array.from(prev.values()).map((t) => t.order));
                const newOrder = maxOrder + 1;

                const next = new Map(prev);
                next.set(turnId, {
                  turnId: turnId,
                  order: newOrder,
                  role: 'assistant',
                  content: finalContent,
                  streaming: false,
                  viewed: false,
                  tokens: event.tokens ?? 0,
                  contextMode: 'copy',
                  accumulatedLength: finalContent.length,
                });
                return next;
              }

              const next = new Map(prev);
              next.set(turnId, {
                ...existing,
                content: finalContent,
                tokens: event.tokens ?? 0,
                streaming: false,
                accumulatedLength: finalContent.length,
              });
              return next;
            });
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
      // If no auto-subscribe session and we're subscribed, unsubscribe
      if (isSubscribed && !autoSubscribe) {
        unsubscribe();
      }
      return;
    }

    // Subscribe to the new session
    subscribe(autoSubscribe);

    // Cleanup on unmount or session change
    return () => {
      unsubscribe();
    };
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
    error,
    sessionId,
    subscribe,
    unsubscribe,
    getTurn,
    clear,
  };
}

export default useSessionData;
