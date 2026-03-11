/**
 * useNotifications - React hook for browser notifications
 *
 * Handles browser notification permissions and triggers notifications
 * when streaming events occur. Per-session notification preferences
 * are stored in localStorage.
 *
 * Usage:
 *   const {
 *     notificationsEnabled,
 *     toggleNotifications,
 *     requestPermission,
 *     permissionState,
 *     showNotification
 *   } = useNotifications(sessionId);
 *
 *   // Check if enabled for this session
 *   if (notificationsEnabled) { ... }
 *
 *   // Toggle notifications for this session
 *   toggleNotifications();
 *
 *   // Manually show a notification
 *   showNotification('Task Complete', 'Your streaming task finished');
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import type { BalloonsClient, SessionStreamDoneEvent, SessionStreamErrorEvent } from '../../../generated/balloons-client';

// localStorage key prefix for per-session notification settings
const STORAGE_PREFIX = 'balloons:notifications:session:';

// Global notification permission state
type PermissionState = 'default' | 'granted' | 'denied' | 'unsupported';

export interface UseNotificationsReturn {
  /** Whether notifications are enabled for this session */
  notificationsEnabled: boolean;
  /** Toggle notifications for this session */
  toggleNotifications: () => void;
  /** Set notifications enabled/disabled for this session */
  setNotificationsEnabled: (enabled: boolean) => void;
  /** Browser notification permission state */
  permissionState: PermissionState;
  /** Request browser notification permission */
  requestPermission: () => Promise<boolean>;
  /** Manually show a notification */
  showNotification: (title: string, body?: string, options?: NotificationOptions) => void;
}

/**
 * Get the localStorage key for a session's notification setting
 */
function getStorageKey(sessionId: string): string {
  return `${STORAGE_PREFIX}${sessionId}`;
}

/**
 * Load notification preference for a session from localStorage
 */
function loadNotificationPref(sessionId: string): boolean {
  if (typeof window === 'undefined' || !sessionId) return false;
  const stored = localStorage.getItem(getStorageKey(sessionId));
  // Default to false (notifications off) for new sessions
  return stored === 'true';
}

/**
 * Save notification preference for a session to localStorage
 */
function saveNotificationPref(sessionId: string, enabled: boolean): void {
  if (typeof window === 'undefined' || !sessionId) return;
  localStorage.setItem(getStorageKey(sessionId), String(enabled));
}

/**
 * Check browser notification permission state
 */
function getPermissionState(): PermissionState {
  if (typeof window === 'undefined' || !('Notification' in window)) {
    return 'unsupported';
  }
  return Notification.permission as PermissionState;
}

/**
 * Hook for managing browser notifications per session.
 *
 * @param sessionId - The session ID to manage notifications for
 * @param client - Optional BalloonsClient for subscribing to streaming events
 */
export function useNotifications(
  sessionId: string | null,
  client?: BalloonsClient | null
): UseNotificationsReturn {
  // Per-session notification enabled state
  const [notificationsEnabled, setNotificationsEnabledState] = useState<boolean>(() =>
    sessionId ? loadNotificationPref(sessionId) : false
  );

  // Browser permission state
  const [permissionState, setPermissionState] = useState<PermissionState>(() =>
    getPermissionState()
  );

  // Update state when sessionId changes
  useEffect(() => {
    if (sessionId) {
      setNotificationsEnabledState(loadNotificationPref(sessionId));
    } else {
      setNotificationsEnabledState(false);
    }
  }, [sessionId]);

  // Monitor permission changes (some browsers support this)
  useEffect(() => {
    if (typeof window === 'undefined' || !('Notification' in window)) return;

    // Check permission state periodically (some browsers don't fire events)
    const checkPermission = () => {
      const current = getPermissionState();
      setPermissionState(current);
    };

    // Initial check
    checkPermission();

    // Some browsers support permission change events
    if ('permissions' in navigator) {
      navigator.permissions.query({ name: 'notifications' as PermissionName }).then((status) => {
        status.onchange = checkPermission;
      }).catch(() => {
        // Ignore errors - not all browsers support this
      });
    }
  }, []);

  // Request browser notification permission
  const requestPermission = useCallback(async (): Promise<boolean> => {
    if (typeof window === 'undefined' || !('Notification' in window)) {
      return false;
    }

    try {
      const permission = await Notification.requestPermission();
      setPermissionState(permission as PermissionState);
      return permission === 'granted';
    } catch (err) {
      console.error('[useNotifications] Failed to request permission:', err);
      return false;
    }
  }, []);

  // Set notifications enabled (with permission request if needed)
  const setNotificationsEnabled = useCallback(async (enabled: boolean) => {
    if (!sessionId) return;

    if (enabled && permissionState === 'default') {
      // Request permission when enabling
      const granted = await requestPermission();
      if (!granted) {
        // Don't enable if permission denied
        return;
      }
    }

    setNotificationsEnabledState(enabled);
    saveNotificationPref(sessionId, enabled);
  }, [sessionId, permissionState, requestPermission]);

  // Toggle notifications for this session
  const toggleNotifications = useCallback(() => {
    setNotificationsEnabled(!notificationsEnabled);
  }, [notificationsEnabled, setNotificationsEnabled]);

  // Show a notification
  const showNotification = useCallback((
    title: string,
    body?: string,
    options?: NotificationOptions
  ) => {
    if (typeof window === 'undefined' || !('Notification' in window)) {
      return;
    }

    if (Notification.permission !== 'granted') {
      return;
    }

    try {
      // Create notification options, filtering out any unsupported properties
      const notificationOptions: NotificationOptions = {
        body,
        icon: '/favicon.ico',
        badge: '/favicon.ico',
        tag: sessionId || 'balloons',
        ...options,
      };

      const notification = new Notification(title, notificationOptions);

      // Auto-close after 5 seconds
      setTimeout(() => {
        notification.close();
      }, 5000);

      // Focus window on click
      notification.onclick = () => {
        window.focus();
        notification.close();
      };
    } catch (err) {
      console.warn('[useNotifications] Failed to show notification:', err);
    }
  }, [sessionId]);

  // Subscribe to streaming events and show notifications
  useEffect(() => {
    if (!client?.isConnected || !sessionId || !notificationsEnabled) {
      return;
    }

    // Don't show notifications if permission not granted
    if (permissionState !== 'granted') {
      return;
    }

    // Don't show notifications if the document is visible (user is looking at it)
    const shouldNotify = () => document.hidden;

    const unsubscribers: (() => void)[] = [];

    // Stream done event
    unsubscribers.push(
      client.sessionData.sessionDataStreamDone((event: SessionStreamDoneEvent) => {
        if (event.sessionId === sessionId && shouldNotify()) {
          showNotification('Streaming Complete', 'Your session has finished streaming.');
        }
      })
    );

    // Stream error event
    unsubscribers.push(
      client.sessionData.sessionDataStreamError((event: SessionStreamErrorEvent) => {
        if (event.sessionId === sessionId && shouldNotify()) {
          showNotification('Streaming Error', event.error || 'An error occurred during streaming.');
        }
      })
    );

    return () => {
      unsubscribers.forEach(unsub => unsub());
    };
  }, [client, sessionId, notificationsEnabled, permissionState, showNotification]);

  return {
    notificationsEnabled,
    toggleNotifications,
    setNotificationsEnabled,
    permissionState,
    requestPermission,
    showNotification,
  };
}

export default useNotifications;
