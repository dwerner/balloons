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

/**
 * Internal turn state maintained by the hook.
 * Uses turn_id (UUID) as the key, not turn index.
 */
export interface SessionDataTurn {
  /** Stable UUID for this turn */
  turnId: string;
  /** Turn index (for ordering) */
  idx: number;
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
  /** Sorted array of turns (by idx) */
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

// Generate a unique client ID for this hook instance
function generateClientId(): string {
  return `web-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
}

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
  const clientIdRef = useRef<string>(generateClientId());
  const unsubscribersRef = useRef<Unsubscribe[]>([]);
  const currentSessionRef = useRef<string | null>(null);

  // Derive sorted turns array from map
  const turns = useMemo(() => {
    return Array.from(turnsById.values()).sort((a, b) => a.idx - b.idx);
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

    // Unsubscribe from session on server
    if (client && currentSessionRef.current) {
      try {
        await client.sessionData.unsubscribeSession(
          currentSessionRef.current,
          clientIdRef.current
        );
      } catch (err) {
        console.warn('Failed to unsubscribe from session:', err);
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
        // Subscribe to session - returns snapshot atomically with subscription
        const result = await client.sessionData.subscribeSession(
          newSessionId,
          clientIdRef.current
        );

        if (!result.subscribed) {
          throw new Error(result.error || 'Subscription failed');
        }

        // Convert snapshot turns to our format (snapshot is included in subscribe result)
        const initialTurns = new Map<string, SessionDataTurn>();
        if (result.snapshot?.turns) {
          result.snapshot.turns.forEach((turn: TurnSnapshot) => {
            // Use the real turn_id from the snapshot (or fall back to index-based ID)
            const turnId = turn.turnId || `snapshot-${newSessionId}-${turn.idx}`;
            initialTurns.set(turnId, {
              turnId,
              idx: turn.idx,
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
        handlers.push(
          client.sessionData.onTurnCreated((event: SessionTurnCreatedEvent) => {
            // Defensive: check if event is valid
            if (!event || typeof event !== 'object') {
              console.warn('[useSessionData] turnCreated received invalid event:', event);
              return;
            }

            if (event.sessionId !== newSessionId) return;

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
              // Determine idx - for new turns, use highest idx + 1
              const maxIdx = Math.max(-1, ...Array.from(prev.values()).map((t) => t.idx));
              const newIdx = maxIdx + 1;

              next.set(turnId, {
                turnId: turnId,
                idx: newIdx,
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
        handlers.push(
          client.sessionData.onTurnDelta((event: SessionTurnDeltaEvent) => {
            // Defensive: check if event is valid
            if (!event || typeof event !== 'object') {
              console.warn('[useSessionData] turnDelta received invalid event:', event);
              return;
            }

            if (event.sessionId !== newSessionId) return;

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
                // Turn not found - create it
                const maxIdx = Math.max(-1, ...Array.from(prev.values()).map((t) => t.idx));
                const newIdx = maxIdx + 1;

                const next = new Map(prev);
                next.set(turnId, {
                  turnId: turnId,
                  idx: newIdx,
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
          client.sessionData.onTurnFinished((event: SessionTurnFinishedEvent) => {
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
                // Create the turn if it doesn't exist
                const maxIdx = Math.max(-1, ...Array.from(prev.values()).map((t) => t.idx));
                const newIdx = maxIdx + 1;

                const next = new Map(prev);
                next.set(turnId, {
                  turnId: turnId,
                  idx: newIdx,
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
