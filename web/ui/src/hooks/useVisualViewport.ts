/**
 * useVisualViewport - Hook to handle iOS virtual keyboard in fullscreen mode
 *
 * Problem: In fullscreen mode on iOS, the virtual keyboard doesn't resize the
 * viewport like it does in normal browser mode. This causes the input area
 * to be hidden behind the keyboard.
 *
 * Solution: Use the visualViewport API to detect viewport height changes
 * (caused by the keyboard appearing) and apply a CSS custom property that
 * can be used to offset content.
 *
 * The hook sets `--keyboard-offset` on the document root, which can be used
 * in CSS to push content up when the keyboard is visible.
 */

import { useEffect, useState, useCallback } from 'react';

interface VisualViewportState {
  /** Current keyboard offset in pixels (0 when keyboard hidden) */
  keyboardOffset: number;
  /** Whether the virtual keyboard is currently visible */
  isKeyboardVisible: boolean;
  /** Visual viewport height */
  viewportHeight: number;
}

/**
 * Hook to track virtual keyboard visibility and offset
 *
 * @param enabled Whether to enable viewport tracking (e.g., only in fullscreen)
 * @returns Current viewport state including keyboard offset
 */
export function useVisualViewport(enabled: boolean = true): VisualViewportState {
  const [state, setState] = useState<VisualViewportState>({
    keyboardOffset: 0,
    isKeyboardVisible: false,
    viewportHeight: typeof window !== 'undefined' ? window.innerHeight : 0,
  });

  const updateViewport = useCallback(() => {
    if (!enabled || typeof window === 'undefined') return;

    const viewport = window.visualViewport;
    if (!viewport) return;

    // Calculate the offset between the layout viewport and visual viewport
    // When the keyboard is open, visualViewport.height < window.innerHeight
    const layoutHeight = window.innerHeight;
    const visualHeight = viewport.height;
    const offset = Math.max(0, layoutHeight - visualHeight);

    // Keyboard is considered visible if offset > 100px (ignore small differences)
    const isKeyboardVisible = offset > 100;

    // Update state
    setState({
      keyboardOffset: offset,
      isKeyboardVisible,
      viewportHeight: visualHeight,
    });

    // Set CSS custom property for use in stylesheets
    document.documentElement.style.setProperty(
      '--keyboard-offset',
      `${offset}px`
    );

    // Also set a class on document for CSS targeting
    if (isKeyboardVisible) {
      document.documentElement.classList.add('keyboard-visible');
    } else {
      document.documentElement.classList.remove('keyboard-visible');
    }
  }, [enabled]);

  useEffect(() => {
    if (!enabled || typeof window === 'undefined') return;

    const viewport = window.visualViewport;
    if (!viewport) return;

    // Initial update
    updateViewport();

    // Listen for viewport changes
    viewport.addEventListener('resize', updateViewport);
    viewport.addEventListener('scroll', updateViewport);

    // Also listen for focus events on input elements
    // This helps catch keyboard appearance faster
    const handleFocus = (e: FocusEvent) => {
      const target = e.target as HTMLElement;
      if (
        target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.isContentEditable
      ) {
        // Small delay to let the viewport settle
        setTimeout(updateViewport, 100);
        setTimeout(updateViewport, 300);

        // In fullscreen mode, exit fullscreen when input is focused
        // This is the most reliable workaround for keyboard issues in fullscreen
        // since mobile browsers don't properly handle keyboard + fullscreen
        if (document.fullscreenElement) {
          document.exitFullscreen().catch(() => {
            // Ignore errors - some browsers may not support exitFullscreen
          });
        }
      }
    };

    const handleBlur = () => {
      // Delay to let viewport settle after keyboard dismissal
      setTimeout(updateViewport, 100);
    };

    document.addEventListener('focusin', handleFocus);
    document.addEventListener('focusout', handleBlur);

    return () => {
      viewport.removeEventListener('resize', updateViewport);
      viewport.removeEventListener('scroll', updateViewport);
      document.removeEventListener('focusin', handleFocus);
      document.removeEventListener('focusout', handleBlur);

      // Clean up CSS property
      document.documentElement.style.removeProperty('--keyboard-offset');
      document.documentElement.classList.remove('keyboard-visible');
    };
  }, [enabled, updateViewport]);

  return state;
}

export default useVisualViewport;
