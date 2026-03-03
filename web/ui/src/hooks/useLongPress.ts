/**
 * useLongPress - Custom hook for detecting long press gestures
 *
 * Supports both mouse and touch events for mobile and desktop.
 * Returns event handlers to attach to the target element.
 *
 * Features:
 * - Configurable delay (default 500ms)
 * - Prevents click event when long press is detected
 * - Handles touch cancel and mouse leave
 * - Works on both mobile (touch) and desktop (mouse)
 */

import { useCallback, useRef } from 'react';

export interface UseLongPressOptions {
  /** Delay in milliseconds before triggering long press (default: 500) */
  delay?: number;

  /** Called when long press is detected */
  onLongPress: () => void;

  /** Called on regular click (not long press) */
  onClick?: () => void;
}

export interface UseLongPressReturn {
  /** Attach to onMouseDown */
  onMouseDown: (e: React.MouseEvent) => void;

  /** Attach to onMouseUp */
  onMouseUp: (e: React.MouseEvent) => void;

  /** Attach to onMouseLeave */
  onMouseLeave: (e: React.MouseEvent) => void;

  /** Attach to onTouchStart */
  onTouchStart: (e: React.TouchEvent) => void;

  /** Attach to onTouchEnd */
  onTouchEnd: (e: React.TouchEvent) => void;

  /** Attach to onTouchMove (cancels long press if finger moves) */
  onTouchMove: (e: React.TouchEvent) => void;

  /** Attach to onTouchCancel (optional but recommended) */
  onTouchCancel?: (e: React.TouchEvent) => void;

  /** Attach to onClick to prevent click after long press */
  onClick: (e: React.MouseEvent) => void;
}

/**
 * Hook for detecting long press gestures.
 *
 * @example
 * ```tsx
 * const longPressHandlers = useLongPress({
 *   onLongPress: () => setRenameModalOpen(true),
 *   onClick: () => console.log('Regular click'),
 *   delay: 500,
 * });
 *
 * return <div {...longPressHandlers}>Press and hold me</div>;
 * ```
 */
export function useLongPress({
  delay = 500,
  onLongPress,
  onClick,
}: UseLongPressOptions): UseLongPressReturn {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isLongPressRef = useRef(false);
  const startPosRef = useRef<{ x: number; y: number } | null>(null);

  // Clear the timer
  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  // Start the timer
  const startTimer = useCallback(() => {
    clearTimer();
    isLongPressRef.current = false;
    timerRef.current = setTimeout(() => {
      isLongPressRef.current = true;
      onLongPress();
    }, delay);
  }, [delay, onLongPress, clearTimer]);

  // Mouse event handlers
  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      // Only respond to left click
      if (e.button !== 0) return;
      startPosRef.current = { x: e.clientX, y: e.clientY };
      startTimer();
    },
    [startTimer]
  );

  const onMouseUp = useCallback(() => {
    clearTimer();
    startPosRef.current = null;
  }, [clearTimer]);

  const onMouseLeave = useCallback(() => {
    clearTimer();
    startPosRef.current = null;
  }, [clearTimer]);

  // Touch event handlers
  const onTouchStart = useCallback(
    (e: React.TouchEvent) => {
      const touch = e.touches[0];
      if (touch) {
        startPosRef.current = { x: touch.clientX, y: touch.clientY };
      }
      startTimer();
    },
    [startTimer]
  );

  const onTouchEnd = useCallback(() => {
    clearTimer();
    startPosRef.current = null;
  }, [clearTimer]);

  const onTouchCancel = useCallback(() => {
    clearTimer();
    startPosRef.current = null;
  }, [clearTimer]);

  // Touch move handler - cancel long press if finger moves too far (allows scrolling)
  const onTouchMove = useCallback(
    (e: React.TouchEvent) => {
      if (!startPosRef.current) return;

      const touch = e.touches[0];
      if (!touch) return;

      // Calculate distance moved
      const dx = Math.abs(touch.clientX - startPosRef.current.x);
      const dy = Math.abs(touch.clientY - startPosRef.current.y);

      // If finger moved more than 10px, cancel the long press (user is scrolling)
      if (dx > 10 || dy > 10) {
        clearTimer();
        startPosRef.current = null;
      }
    },
    [clearTimer]
  );

  // Click handler - prevent click if long press was detected
  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      if (isLongPressRef.current) {
        // Prevent the click event after a long press
        e.preventDefault();
        e.stopPropagation();
        isLongPressRef.current = false;
        return;
      }

      // Regular click - call onClick handler if provided
      onClick?.();
    },
    [onClick]
  );

  return {
    onMouseDown,
    onMouseUp,
    onMouseLeave,
    onTouchStart,
    onTouchEnd,
    onTouchMove,
    onTouchCancel,
    onClick: handleClick,
  };
}

export default useLongPress;
