/**
 * SessionDataContext - React context for centralized session data management
 *
 * Provides a single source of truth for session turns, streaming state, and
 * subscription management across the application.
 *
 * Usage:
 *   <SessionDataProvider client={client}>
 *     <App />
 *   </SessionDataProvider>
 *
 *   // In a component:
 *   const { turns, isStreaming, setActiveSession } = useSessionDataContext();
 */

import React, {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  useMemo,
  useRef,
} from 'react';
import type { BalloonsClient } from '../../../generated/balloons-client';
import {
  SessionDataManager,
  type ManagedTurn,
  type StreamingProgress,
  type SessionState,
} from '../lib/SessionDataManager';
import { createLogger } from '../utils/debugLog';

const debugLog = createLogger('SessionDataContext');

/**
 * Context value shape
 */
export interface SessionDataContextValue {
  /** The underlying manager instance */
  manager: SessionDataManager | null;

  /** Currently active session ID */
  activeSessionId: string | null;

  /** Set the active session (triggers full subscription) */
  setActiveSession: (sessionId: string | null) => Promise<void>;

  /** Get turns for a session (returns empty array if not subscribed) */
  getTurns: (sessionId: string) => ManagedTurn[];

  /** Get turns for the active session */
  activeSessionTurns: ManagedTurn[];

  /** Whether the active session is streaming */
  isStreaming: boolean;

  /** Streaming progress for active session */
  streamingProgress: StreamingProgress | null;

  /** Stream error for active session */
  streamError: string | null;

  /** Whether history is loaded for active session */
  historyLoaded: boolean;

  /** Whether history is currently loading for active session */
  isLoadingHistory: boolean;
}

const SessionDataContext = createContext<SessionDataContextValue | null>(null);

interface SessionDataProviderProps {
  client: BalloonsClient | null;
  children: React.ReactNode;
}

export function SessionDataProvider({ client, children }: SessionDataProviderProps): React.ReactElement {
  // Manager instance - created when client connects
  const managerRef = useRef<SessionDataManager | null>(null);

  // Track state for active session
  const [activeSessionId, setActiveSessionIdState] = useState<string | null>(null);
  const [activeSessionState, setActiveSessionState] = useState<SessionState | null>(null);

  // Derived state for convenience
  const activeSessionTurns = useMemo(() => {
    if (!activeSessionState) return [];
    return Array.from(activeSessionState.turns.values()).sort((a, b) => a.order - b.order);
  }, [activeSessionState]);

  // Initialize manager when client connects
  useEffect(() => {
    if (!client?.isConnected) {
      // Clean up old manager
      if (managerRef.current) {
        managerRef.current.destroy();
        managerRef.current = null;
      }
      setActiveSessionIdState(null);
      setActiveSessionState(null);
      return;
    }

    // Wait for clientId to be available
    if (!client.hasClientId) {
      debugLog('Waiting for clientId');
      return;
    }

    // Create new manager
    const manager = new SessionDataManager(client);
    managerRef.current = manager;

    // Listen for state changes
    const unsubscribe = manager.addListener((sessionId, state) => {
      if (sessionId === manager.getActiveSessionId()) {
        setActiveSessionState({ ...state, turns: new Map(state.turns) });
      }
    });

    debugLog('Manager initialized', { clientId: client.clientId });

    return () => {
      unsubscribe();
      manager.destroy();
      managerRef.current = null;
    };
  }, [client, client?.isConnected, client?.hasClientId]);

  // Set active session
  const setActiveSession = useCallback(async (sessionId: string | null): Promise<void> => {
    const manager = managerRef.current;
    if (!manager) {
      debugLog('setActiveSession: no manager');
      return;
    }

    debugLog('setActiveSession', { sessionId: sessionId?.slice(0, 8) });

    await manager.setActiveSession(sessionId);
    setActiveSessionIdState(sessionId);

    // Get initial state
    if (sessionId) {
      const state = manager.getSession(sessionId);
      if (state) {
        setActiveSessionState({ ...state, turns: new Map(state.turns) });
      }
    } else {
      setActiveSessionState(null);
    }
  }, []);

  // Get turns for any session
  const getTurns = useCallback((sessionId: string): ManagedTurn[] => {
    const manager = managerRef.current;
    if (!manager) return [];
    return manager.getTurns(sessionId);
  }, []);

  // Context value
  const value = useMemo<SessionDataContextValue>(() => ({
    manager: managerRef.current,
    activeSessionId,
    setActiveSession,
    getTurns,
    activeSessionTurns,
    isStreaming: activeSessionState?.isStreaming ?? false,
    streamingProgress: activeSessionState?.streamingProgress ?? null,
    streamError: activeSessionState?.streamError ?? null,
    historyLoaded: activeSessionState?.historyLoaded ?? false,
    isLoadingHistory: !activeSessionState?.historyLoaded && activeSessionId !== null,
  }), [
    activeSessionId,
    setActiveSession,
    getTurns,
    activeSessionTurns,
    activeSessionState,
  ]);

  return (
    <SessionDataContext.Provider value={value}>
      {children}
    </SessionDataContext.Provider>
  );
}

/**
 * Hook to access session data context
 */
export function useSessionDataContext(): SessionDataContextValue {
  const context = useContext(SessionDataContext);
  if (!context) {
    throw new Error('useSessionDataContext must be used within a SessionDataProvider');
  }
  return context;
}

/**
 * Hook to get turns for a specific session
 * Returns reactive updates when the session changes
 */
export function useSessionTurns(sessionId: string | null): ManagedTurn[] {
  const { manager, activeSessionId, activeSessionTurns, getTurns } = useSessionDataContext();
  const [turns, setTurns] = useState<ManagedTurn[]>([]);

  useEffect(() => {
    if (!sessionId || !manager) {
      setTurns([]);
      return;
    }

    // If this is the active session, we already have reactive updates
    if (sessionId === activeSessionId) {
      setTurns(activeSessionTurns);
      return;
    }

    // For non-active sessions, get cached turns and listen for changes
    setTurns(getTurns(sessionId));

    const unsubscribe = manager.addListener((changedSessionId, state) => {
      if (changedSessionId === sessionId) {
        setTurns(Array.from(state.turns.values()).sort((a, b) => a.order - b.order));
      }
    });

    return unsubscribe;
  }, [sessionId, manager, activeSessionId, activeSessionTurns, getTurns]);

  return sessionId === activeSessionId ? activeSessionTurns : turns;
}
