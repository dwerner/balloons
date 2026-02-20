/**
 * ScrollToBottom - Floating indicator to resume autoscroll
 *
 * Shows when user has scrolled away from the bottom during streaming.
 * Clicking it scrolls to bottom and resumes following.
 *
 * Features:
 * - Animated entrance/exit
 * - Shows new message count or "New content" indicator
 * - Click to scroll + follow
 * - Accessible (button semantics, focus management)
 */

import React from 'react';
import './ScrollToBottom.css';

export interface ScrollToBottomProps {
  /**
   * Whether to show the indicator.
   * Typically: isStreaming && !isFollowing
   */
  visible: boolean;

  /**
   * Callback when clicked - should call scrollToBottom().
   */
  onClick: () => void;

  /**
   * Optional: number of new items since user scrolled away.
   * If provided, shows "N new" badge.
   */
  newCount?: number;

  /**
   * Whether content is actively streaming (shows animation).
   */
  isStreaming?: boolean;

  /**
   * Optional custom label.
   * Default: "Scroll to bottom" or "N new"
   */
  label?: string;
}

export function ScrollToBottom({
  visible,
  onClick,
  newCount,
  isStreaming = false,
  label,
}: ScrollToBottomProps) {
  // Build label text
  let displayLabel = label;
  if (!displayLabel) {
    if (newCount && newCount > 0) {
      displayLabel = `${newCount} new`;
    } else if (isStreaming) {
      displayLabel = 'Following...';
    } else {
      displayLabel = 'Scroll to bottom';
    }
  }

  return (
    <button
      className={`scroll-to-bottom ${visible ? 'visible' : ''} ${isStreaming ? 'streaming' : ''}`}
      onClick={onClick}
      aria-label="Scroll to bottom and resume following"
      tabIndex={visible ? 0 : -1}
    >
      <span className="scroll-to-bottom-icon">↓</span>
      <span className="scroll-to-bottom-label">{displayLabel}</span>
      {isStreaming && (
        <span className="scroll-to-bottom-streaming-indicator">
          <span className="dot"></span>
          <span className="dot"></span>
          <span className="dot"></span>
        </span>
      )}
    </button>
  );
}

export default ScrollToBottom;
