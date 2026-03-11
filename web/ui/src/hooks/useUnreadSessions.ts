/**
 * useUnreadSessions - Track sessions that finished streaming but haven't been viewed
 *
 * This hook detects when sessions transition from streaming to not-streaming,
 * and marks them as "unread" if they weren't the currently selected session
 * at the time. The unread state persists to localStorage to survive page refreshes.
 */

import { useState, useEffect, useRef, useCallback } from 'react';

const UNREAD_SESSIONS_KEY = 'balloons:unread-sessions';

export interface UseUnreadSessionsOptions {
  /** All sessions with their streaming state */
  sessions: Array<{ id: string; isStreaming: boolean }>;
  /** Currently selected session ID */
  selectedSessionId: string | null;
}

export interface UseUnreadSessionsReturn {
  /** Set of session IDs that are unread */
  unreadSessionIds: Set<string>;
  /** Manually mark a session as read */
  markAsRead: (sessionId: string) => void;
  /** Manually mark a session as unread */
  markAsUnread: (sessionId: string) => void;
  /** Clear all unread sessions */
  clearAll: () => void;
}

/**
 * Track sessions that finished streaming but haven't been viewed yet.
 *
 * - When a session transitions from streaming → not streaming and it's not selected, mark as unread
 * - When a session is selected, mark it as read
 * - State persists to localStorage
 */
export function useUnreadSessions({
  sessions,
  selectedSessionId,
}: UseUnreadSessionsOptions): UseUnreadSessionsReturn {
  // Load initial state from localStorage
  const [unreadSessionIds, setUnreadSessionIds] = useState<Set<string>>(() => {
    if (typeof window === 'undefined') return new Set();
    try {
      const stored = localStorage.getItem(UNREAD_SESSIONS_KEY);
      if (stored) {
        const ids = JSON.parse(stored);
        if (Array.isArray(ids)) {
          return new Set(ids.filter((id): id is string => typeof id === 'string'));
        }
      }
    } catch {
      // Ignore parse errors
    }
    return new Set();
  });

  // Track previous streaming state to detect transitions
  const prevStreamingRef = useRef<Set<string>>(new Set());

  // Detect streaming → not streaming transitions
  useEffect(() => {
    const currentStreaming = new Set(
      sessions.filter(s => s.isStreaming).map(s => s.id)
    );
    const prevStreaming = prevStreamingRef.current;

    // Find sessions that were streaming but aren't anymore
    const justFinished: string[] = [];
    for (const id of prevStreaming) {
      if (!currentStreaming.has(id)) {
        justFinished.push(id);
      }
    }

    // Mark finished sessions as unread (unless currently selected)
    if (justFinished.length > 0) {
      setUnreadSessionIds(prev => {
        const next = new Set(prev);
        let changed = false;
        for (const id of justFinished) {
          if (id !== selectedSessionId && !next.has(id)) {
            next.add(id);
            changed = true;
          }
        }
        if (changed) {
          // Persist to localStorage
          localStorage.setItem(UNREAD_SESSIONS_KEY, JSON.stringify([...next]));
        }
        return changed ? next : prev;
      });
    }

    // Update the ref for next comparison
    prevStreamingRef.current = currentStreaming;
  }, [sessions, selectedSessionId]);

  // Clear unread when session is selected
  useEffect(() => {
    if (selectedSessionId) {
      setUnreadSessionIds(prev => {
        if (prev.has(selectedSessionId)) {
          const next = new Set(prev);
          next.delete(selectedSessionId);
          localStorage.setItem(UNREAD_SESSIONS_KEY, JSON.stringify([...next]));
          return next;
        }
        return prev;
      });
    }
  }, [selectedSessionId]);

  // Clean up unread IDs for sessions that no longer exist
  // This prevents localStorage bloat from deleted sessions
  useEffect(() => {
    const sessionIds = new Set(sessions.map(s => s.id));
    setUnreadSessionIds(prev => {
      let changed = false;
      const next = new Set<string>();
      for (const id of prev) {
        if (sessionIds.has(id)) {
          next.add(id);
        } else {
          changed = true;
        }
      }
      if (changed) {
        localStorage.setItem(UNREAD_SESSIONS_KEY, JSON.stringify([...next]));
        return next;
      }
      return prev;
    });
  }, [sessions]);

  // Manual control functions
  const markAsRead = useCallback((sessionId: string) => {
    setUnreadSessionIds(prev => {
      if (prev.has(sessionId)) {
        const next = new Set(prev);
        next.delete(sessionId);
        localStorage.setItem(UNREAD_SESSIONS_KEY, JSON.stringify([...next]));
        return next;
      }
      return prev;
    });
  }, []);

  const markAsUnread = useCallback((sessionId: string) => {
    setUnreadSessionIds(prev => {
      if (!prev.has(sessionId)) {
        const next = new Set(prev);
        next.add(sessionId);
        localStorage.setItem(UNREAD_SESSIONS_KEY, JSON.stringify([...next]));
        return next;
      }
      return prev;
    });
  }, []);

  const clearAll = useCallback(() => {
    setUnreadSessionIds(new Set());
    localStorage.removeItem(UNREAD_SESSIONS_KEY);
  }, []);

  return {
    unreadSessionIds,
    markAsRead,
    markAsUnread,
    clearAll,
  };
}
