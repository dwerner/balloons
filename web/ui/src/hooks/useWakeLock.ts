/**
 * useWakeLock - React hook for the Screen Wake Lock API
 *
 * Keeps the screen awake while enabled, useful for:
 * - Reading long conversations without screen dimming
 * - Watching streaming responses on mobile devices
 * - Presenting content without screen timeout
 *
 * The wake lock is automatically:
 * - Released when the tab becomes hidden
 * - Re-acquired when the tab becomes visible (if still enabled)
 * - Released on component unmount
 *
 * @see https://developer.mozilla.org/en-US/docs/Web/API/Screen_Wake_Lock_API
 */

import { useState, useEffect, useCallback, useRef } from 'react';

export interface WakeLockState {
  /** Whether the wake lock is currently active */
  isActive: boolean;
  /** Whether the Wake Lock API is supported in this browser */
  isSupported: boolean;
  /** Error message if wake lock acquisition failed */
  error: string | null;
}

export interface UseWakeLockReturn extends WakeLockState {
  /** Request a wake lock (keeps screen awake) */
  request: () => Promise<void>;
  /** Release the current wake lock */
  release: () => Promise<void>;
  /** Toggle wake lock on/off */
  toggle: () => Promise<void>;
}

/**
 * Hook to manage the Screen Wake Lock API
 *
 * @example
 * ```tsx
 * function MyComponent() {
 *   const { isActive, isSupported, toggle, error } = useWakeLock();
 *
 *   if (!isSupported) return null;
 *
 *   return (
 *     <button onClick={toggle}>
 *       {isActive ? '☀️ Screen awake' : '🌙 Allow sleep'}
 *     </button>
 *   );
 * }
 * ```
 */
export function useWakeLock(): UseWakeLockReturn {
  const [isActive, setIsActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wakeLockRef = useRef<WakeLockSentinel | null>(null);
  const wantedActiveRef = useRef(false);

  // Check if Wake Lock API is supported
  const isSupported = typeof navigator !== 'undefined' && 'wakeLock' in navigator;

  // Request a wake lock
  const request = useCallback(async () => {
    if (!isSupported) {
      setError('Wake Lock API is not supported in this browser');
      return;
    }

    // Don't request if already active
    if (wakeLockRef.current) {
      return;
    }

    try {
      wantedActiveRef.current = true;
      const sentinel = await navigator.wakeLock.request('screen');
      wakeLockRef.current = sentinel;
      setIsActive(true);
      setError(null);

      // Listen for release events (e.g., when tab becomes hidden)
      sentinel.addEventListener('release', () => {
        wakeLockRef.current = null;
        setIsActive(false);
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to acquire wake lock';
      setError(message);
      setIsActive(false);
      wantedActiveRef.current = false;
    }
  }, [isSupported]);

  // Release the wake lock
  const release = useCallback(async () => {
    wantedActiveRef.current = false;

    if (wakeLockRef.current) {
      try {
        await wakeLockRef.current.release();
        wakeLockRef.current = null;
        setIsActive(false);
        setError(null);
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to release wake lock';
        setError(message);
      }
    }
  }, []);

  // Toggle wake lock
  const toggle = useCallback(async () => {
    if (isActive) {
      await release();
    } else {
      await request();
    }
  }, [isActive, request, release]);

  // Re-acquire wake lock when page becomes visible again
  useEffect(() => {
    if (!isSupported) return;

    const handleVisibilityChange = async () => {
      if (document.visibilityState === 'visible' && wantedActiveRef.current && !wakeLockRef.current) {
        // Page became visible and we want to be active - re-acquire
        try {
          const sentinel = await navigator.wakeLock.request('screen');
          wakeLockRef.current = sentinel;
          setIsActive(true);
          setError(null);

          sentinel.addEventListener('release', () => {
            wakeLockRef.current = null;
            setIsActive(false);
          });
        } catch (err) {
          // Silently fail on re-acquire - user can retry manually
          console.warn('Failed to re-acquire wake lock:', err);
        }
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [isSupported]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (wakeLockRef.current) {
        wakeLockRef.current.release().catch(() => {
          // Ignore errors on cleanup
        });
      }
    };
  }, []);

  return {
    isActive,
    isSupported,
    error,
    request,
    release,
    toggle,
  };
}

export default useWakeLock;
