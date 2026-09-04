/**
 * SessionDataContext - React context for centralized session data management
 *
 * Provides a single source of truth for session turns, streaming state, and
 * subscription management across the application.
 *
 * PERFORMANCE OPTIMIZATIONS:
 * - Uses versioned state tracking to avoid creating new objects on every update
 * - Separates high-frequency updates (progress) from structural changes (turns)
 * - Maintains stable array references using cached sorted turns
 * - Only triggers React re-renders when relevant data actually changes
 *
 * URL ROUTING INTEGRATION:
 * - setActiveSession() should be called by the router when session route changes
 * - Router should update URL when setActiveSession() is called from UI actions
 * - See docs/specs/url-routing.md for the full routing design
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
  type ChangeType,
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

  /** Version counter for turns (increments on structural changes) */
  turnsVersion: number;

  /** Version counter for streaming state */
  streamingVersion: number;
}

const SessionDataContext = createContext<SessionDataContextValue | null>(null);

interface SessionDataProviderProps {
  client: BalloonsClient | null;
  children: React.ReactNode;
}

/**
 * Cached sorted turns array to avoid recreating on every render.
 * Only rebuilt when the turns Map actually changes.
 */
interface TurnsCache {
  /** Version when this cache was built */
  version: number;
  /** The cached sorted array */
  turns: ManagedTurn[];
  /** Session ID this cache is for */
  sessionId: string | null;
}

export function SessionDataProvider({ client, children }: SessionDataProviderProps): React.ReactElement {
  // Manager instance - created when client connects
  const managerRef = useRef<SessionDataManager | null>(null);

  // Version counters for different types of changes
  // Incrementing these triggers selective re-renders
  const [turnsVersion, setTurnsVersion] = useState(0);
  const [streamingVersion, setStreamingVersion] = useState(0);

  // Active session tracking
  const [activeSessionId, setActiveSessionIdState] = useState<string | null>(null);

  // Cache for sorted turns array - avoids recreating array on every render
  const turnsCacheRef = useRef<TurnsCache>({ version: -1, turns: [], sessionId: null });

  // Direct state access refs (avoid triggering re-renders for high-frequency updates)
  const streamingProgressRef = useRef<StreamingProgress | null>(null);
  const isStreamingRef = useRef(false);
  const streamErrorRef = useRef<string | null>(null);
  const historyLoadedRef = useRef(false);

  // Progress update batching - don't trigger re-renders for every progress tick
  const lastProgressRenderRef = useRef(0);
  const PROGRESS_RENDER_INTERVAL_MS = 200; // Only render progress updates every 200ms

  // Get sorted turns array, using cache when possible
  const getActiveSessionTurns = useCallback((): ManagedTurn[] => {
    const manager = managerRef.current;
    if (!manager || !activeSessionId) {
      return [];
    }

    const cache = turnsCacheRef.current;
    // Return cached array if version matches and same session
    if (cache.version === turnsVersion && cache.sessionId === activeSessionId) {
      return cache.turns;
    }

    // Rebuild cache
    const turns = manager.getTurns(activeSessionId);
    turnsCacheRef.current = {
      version: turnsVersion,
      turns,
      sessionId: activeSessionId,
    };

    return turns;
  }, [activeSessionId, turnsVersion]);

  // Initialize manager when client connects
  useEffect(() => {
    if (!client?.isConnected) {
      // Clean up old manager
      if (managerRef.current) {
        managerRef.current.destroy();
        managerRef.current = null;
      }
      setActiveSessionIdState(null);
      setTurnsVersion(0);
      setStreamingVersion(0);
      streamingProgressRef.current = null;
      isStreamingRef.current = false;
      streamErrorRef.current = null;
      historyLoadedRef.current = false;
      turnsCacheRef.current = { version: -1, turns: [], sessionId: null };
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

    // Listen for state changes with change type awareness
    const unsubscribe = manager.addListener((sessionId, state, changeType) => {
      // Only process updates for the active session
      if (sessionId !== manager.getActiveSessionId()) {
        return;
      }

      switch (changeType) {
        case 'turns':
        case 'history':
          // Structural changes - update refs and increment version
          historyLoadedRef.current = state.historyLoaded;
          setTurnsVersion(v => v + 1);
          break;

        case 'streaming':
          // Streaming state changed - update refs and increment version
          isStreamingRef.current = state.isStreaming;
          streamingProgressRef.current = state.streamingProgress;
          setStreamingVersion(v => v + 1);
          break;

        case 'progress':
          // High-frequency progress updates - only trigger render periodically
          streamingProgressRef.current = state.streamingProgress;
          const now = Date.now();
          if (now - lastProgressRenderRef.current >= PROGRESS_RENDER_INTERVAL_MS) {
            lastProgressRenderRef.current = now;
            setStreamingVersion(v => v + 1);
          }
          break;

        case 'error':
          // Error state - always render immediately
          streamErrorRef.current = state.streamError;
          isStreamingRef.current = state.isStreaming;
          setStreamingVersion(v => v + 1);
          break;
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

    // Update local state immediately
    setActiveSessionIdState(sessionId);

    // Clear cache for new session
    turnsCacheRef.current = { version: -1, turns: [], sessionId: null };

    // Subscribe to new session
    await manager.setActiveSession(sessionId);

    // Initialize refs from session state
    if (sessionId) {
      const state = manager.getSession(sessionId);
      if (state) {
        isStreamingRef.current = state.isStreaming;
        streamingProgressRef.current = state.streamingProgress;
        streamErrorRef.current = state.streamError;
        historyLoadedRef.current = state.historyLoaded;
      }
    } else {
      isStreamingRef.current = false;
      streamingProgressRef.current = null;
      streamErrorRef.current = null;
      historyLoadedRef.current = false;
    }

    // Trigger re-render with new session data
    setTurnsVersion(v => v + 1);
    setStreamingVersion(v => v + 1);
  }, []);

  // Get turns for any session (used by tree view for non-active sessions)
  const getTurns = useCallback((sessionId: string): ManagedTurn[] => {
    const manager = managerRef.current;
    if (!manager) return [];
    return manager.getTurns(sessionId);
  }, []);

  // Memoized turns array - only changes when turnsVersion or activeSessionId changes
  const activeSessionTurns = useMemo(() => {
    return getActiveSessionTurns();
  }, [getActiveSessionTurns]);

  // Context value - only recreated when versions or session change
  const value = useMemo<SessionDataContextValue>(() => ({
    manager: managerRef.current,
    activeSessionId,
    setActiveSession,
    getTurns,
    activeSessionTurns,
    // Read from refs for latest values without triggering re-renders
    isStreaming: isStreamingRef.current,
    streamingProgress: streamingProgressRef.current,
    streamError: streamErrorRef.current,
    historyLoaded: historyLoadedRef.current,
    isLoadingHistory: !historyLoadedRef.current && activeSessionId !== null,
    turnsVersion,
    streamingVersion,
  }), [
    activeSessionId,
    setActiveSession,
    getTurns,
    activeSessionTurns,
    turnsVersion,
    streamingVersion,
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
 *
 * Optimized to avoid re-renders when the actual turn content hasn't changed.
 */
export function useSessionTurns(sessionId: string | null): ManagedTurn[] {
  const { manager, activeSessionId, activeSessionTurns, getTurns, turnsVersion } = useSessionDataContext();
  const [localTurns, setLocalTurns] = useState<ManagedTurn[]>([]);
  const localVersionRef = useRef(-1);

  useEffect(() => {
    if (!sessionId || !manager) {
      if (localTurns.length > 0) {
        setLocalTurns([]);
      }
      return;
    }

    // If this is the active session, we already have reactive updates via context
    if (sessionId === activeSessionId) {
      return;
    }

    // For non-active sessions, get cached turns
    setLocalTurns(getTurns(sessionId));

    // Listen for changes to this specific session
    const unsubscribe = manager.addListener((changedSessionId, state, changeType) => {
      if (changedSessionId === sessionId && (changeType === 'turns' || changeType === 'history')) {
        // Only update if turns actually changed (new turn added, content changed, etc.)
        const newTurns = Array.from(state.turns.values()).sort((a, b) => a.order - b.order);
        setLocalTurns(newTurns);
      }
    });

    return unsubscribe;
  }, [sessionId, manager, activeSessionId, getTurns, localTurns.length]);

  // Return active session turns from context, or local turns for non-active sessions
  return sessionId === activeSessionId ? activeSessionTurns : localTurns;
}

/**
 * Hook for components that only care about streaming state
 * Optimized to only re-render on streaming state changes, not turn changes
 */
export function useStreamingState(): {
  isStreaming: boolean;
  progress: StreamingProgress | null;
  error: string | null;
} {
  const { isStreaming, streamingProgress, streamError, streamingVersion } = useSessionDataContext();

  // Re-render when streamingVersion changes (isStreaming/progress/error changed)
  return useMemo(() => ({
    isStreaming,
    progress: streamingProgress,
    error: streamError,
  }), [isStreaming, streamingProgress, streamError, streamingVersion]);
}
