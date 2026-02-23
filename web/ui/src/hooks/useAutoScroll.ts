/**
 * useAutoScroll - Robust autoscroll hook for streaming content
 *
 * Provides intelligent autoscroll behavior:
 * - Autoscrolls to bottom when near bottom (within threshold)
 * - Detects user scroll-up to break out of autoscroll
 * - Provides a "scroll to bottom" action to resume following
 * - Handles edge cases: resize, content changes, momentum scrolling
 *
 * Usage:
 *   const { scrollRef, isAtBottom, scrollToBottom } = useAutoScroll({
 *     deps: [content],  // Re-scroll when these change
 *     threshold: 100,   // Pixels from bottom to consider "at bottom"
 *   });
 *
 *   return (
 *     <div ref={scrollRef}>
 *       {content}
 *       {!isAtBottom && <ScrollToBottomButton onClick={scrollToBottom} />}
 *     </div>
 *   );
 */

import { useRef, useState, useEffect, useCallback } from 'react';

export interface UseAutoScrollOptions {
  /**
   * Dependencies that trigger a scroll check/action.
   * Typically the content array that's being rendered.
   */
  deps?: unknown[];

  /**
   * Distance from the bottom (in pixels) within which we consider
   * the user to be "at the bottom" and auto-scroll should be active.
   * Default: 100px
   */
  threshold?: number;

  /**
   * Whether to use smooth scrolling when auto-scrolling.
   * Smooth is better UX but can lag behind fast streaming.
   * Default: false (instant scroll for streaming)
   */
  smoothScroll?: boolean;

  /**
   * Debounce time (ms) for scroll event handling.
   * Higher values reduce CPU but make state updates laggier.
   * Default: 50ms
   */
  scrollDebounceMs?: number;

  /**
   * Whether autoscroll is enabled. Can be toggled externally.
   * Default: true
   */
  enabled?: boolean;
}

export interface UseAutoScrollReturn {
  /**
   * Callback ref to attach to the scrollable container element.
   */
  scrollRef: (element: HTMLDivElement | null) => void;

  /**
   * Whether the user is currently at/near the bottom.
   * When true, new content will auto-scroll into view.
   */
  isAtBottom: boolean;

  /**
   * Whether auto-scroll is currently active (user hasn't scrolled away).
   * This tracks user intent - if they scroll up, this becomes false.
   */
  isFollowing: boolean;

  /**
   * Scroll to the bottom and resume following.
   * Call this from a "scroll to bottom" button.
   */
  scrollToBottom: () => void;

  /**
   * Manually pause following (user scrolled up).
   */
  pauseFollowing: () => void;

  /**
   * Resume following without scrolling (for when user reaches bottom manually).
   */
  resumeFollowing: () => void;
}

/**
 * Calculates whether we're at the bottom of a scrollable element.
 * Uses a threshold to be forgiving of rounding errors and momentum.
 */
function isNearBottom(element: HTMLElement, threshold: number): boolean {
  const { scrollTop, scrollHeight, clientHeight } = element;
  const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
  return distanceFromBottom <= threshold;
}

export function useAutoScroll(options: UseAutoScrollOptions = {}): UseAutoScrollReturn {
  const {
    deps = [],
    threshold = 100,
    smoothScroll = false,
    scrollDebounceMs = 50,
    enabled = true,
  } = options;

  const scrollRef = useRef<HTMLDivElement>(null);

  // Track whether user is actively following the stream
  // Persist to localStorage so it survives reconnects
  const [isFollowing, setIsFollowingState] = useState(() => {
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem('balloons:autoscroll-following');
      // Default to true if not set
      return stored !== 'false';
    }
    return true;
  });

  // Wrapper that persists to localStorage
  const setIsFollowing = useCallback((value: boolean | ((prev: boolean) => boolean)) => {
    setIsFollowingState(prev => {
      const newValue = typeof value === 'function' ? value(prev) : value;
      localStorage.setItem('balloons:autoscroll-following', String(newValue));
      return newValue;
    });
  }, []);

  // Track actual scroll position (debounced)
  const [isAtBottom, setIsAtBottom] = useState(true);

  // Ref to track programmatic scrolls (to distinguish from user scrolls)
  const isProgrammaticScrollRef = useRef(false);

  // Last scroll position to detect scroll direction
  const lastScrollTopRef = useRef(0);

  // Debounce timer
  const scrollDebounceRef = useRef<number | null>(null);

  /**
   * Check scroll position and update state.
   * Called on scroll events and content changes.
   */
  const checkScrollPosition = useCallback(() => {
    const element = scrollRef.current;
    if (!element) return;

    const atBottom = isNearBottom(element, threshold);
    setIsAtBottom(atBottom);

    // If user scrolls to bottom naturally, resume following
    if (atBottom && !isFollowing) {
      setIsFollowing(true);
    }
  }, [threshold, isFollowing]);

  /**
   * Scroll to the bottom of the container.
   * Marks it as programmatic to avoid triggering "user scrolled away" logic.
   */
  const scrollToBottom = useCallback(() => {
    const element = scrollRef.current;
    if (!element) return;

    isProgrammaticScrollRef.current = true;
    setIsFollowing(true);
    setIsAtBottom(true);

    element.scrollTo({
      top: element.scrollHeight,
      behavior: smoothScroll ? 'smooth' : 'instant',
    });

    // Reset programmatic flag after scroll completes
    // Use a small delay to account for smooth scrolling
    setTimeout(() => {
      isProgrammaticScrollRef.current = false;
    }, smoothScroll ? 300 : 50);
  }, [smoothScroll]);

  /**
   * Pause following - called when user scrolls up.
   */
  const pauseFollowing = useCallback(() => {
    setIsFollowing(false);
  }, []);

  /**
   * Resume following without scrolling.
   */
  const resumeFollowing = useCallback(() => {
    setIsFollowing(true);
  }, []);

  /**
   * Handle scroll events with debouncing.
   * Detects user scroll-up to break autoscroll.
   */
  const handleScroll = useCallback(
    (event: Event) => {
      const element = event.target as HTMLElement;

      // Clear existing debounce timer
      if (scrollDebounceRef.current !== null) {
        window.clearTimeout(scrollDebounceRef.current);
      }

      // Debounce the scroll handling
      scrollDebounceRef.current = window.setTimeout(() => {
        // Skip if this was a programmatic scroll
        if (isProgrammaticScrollRef.current) {
          lastScrollTopRef.current = element.scrollTop;
          return;
        }

        const atBottom = isNearBottom(element, threshold);
        const scrollDirection = element.scrollTop - lastScrollTopRef.current;
        lastScrollTopRef.current = element.scrollTop;

        setIsAtBottom(atBottom);

        // User scrolled UP (negative direction) and away from bottom
        // This indicates intent to review content
        if (scrollDirection < -10 && !atBottom) {
          setIsFollowing(false);
        }

        // User scrolled to bottom, resume following
        if (atBottom) {
          setIsFollowing(true);
        }
      }, scrollDebounceMs);
    },
    [threshold, scrollDebounceMs]
  );

  /**
   * Auto-scroll when deps change (new content) and we're following.
   */
  useEffect(() => {
    if (!enabled || !isFollowing) return;

    const element = scrollRef.current;
    if (!element) return;

    // Use requestAnimationFrame to ensure DOM has updated
    requestAnimationFrame(() => {
      isProgrammaticScrollRef.current = true;
      element.scrollTo({
        top: element.scrollHeight,
        behavior: 'instant', // Always instant for streaming updates
      });

      // Short delay to reset flag
      setTimeout(() => {
        isProgrammaticScrollRef.current = false;
      }, 16);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  /**
   * Set up scroll event listener using a callback ref.
   * This ensures the listener is attached when the element mounts.
   */
  const handleScrollRef = useRef(handleScroll);
  handleScrollRef.current = handleScroll;

  const cleanupRef = useRef<(() => void) | null>(null);

  const setScrollRef = useCallback((element: HTMLDivElement | null) => {
    // Clean up previous listener
    if (cleanupRef.current) {
      cleanupRef.current();
      cleanupRef.current = null;
    }

    // Update the ref
    (scrollRef as React.MutableRefObject<HTMLDivElement | null>).current = element;

    if (!element) return;

    // Create scroll handler that uses the ref
    const scrollHandler = (e: Event) => handleScrollRef.current(e);
    element.addEventListener('scroll', scrollHandler, { passive: true });

    // Initial position
    lastScrollTopRef.current = element.scrollTop;

    // Store cleanup
    cleanupRef.current = () => {
      element.removeEventListener('scroll', scrollHandler);
      if (scrollDebounceRef.current !== null) {
        window.clearTimeout(scrollDebounceRef.current);
      }
    };
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (cleanupRef.current) {
        cleanupRef.current();
      }
    };
  }, []);

  /**
   * Handle window resize - re-check position.
   */
  useEffect(() => {
    const handleResize = () => {
      checkScrollPosition();
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [checkScrollPosition]);

  return {
    scrollRef: setScrollRef,
    isAtBottom,
    isFollowing,
    scrollToBottom,
    pauseFollowing,
    resumeFollowing,
  };
}

export default useAutoScroll;
