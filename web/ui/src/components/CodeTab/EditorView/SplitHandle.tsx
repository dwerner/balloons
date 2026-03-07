/**
 * SplitHandle - Draggable resize handle for the editor/map split.
 *
 * Features:
 * - Drag to resize panes
 * - Double-click to reset to 50/50
 * - Visual feedback on hover/drag
 * - Minimum pane sizes enforced
 */

import React, { useRef, useCallback, memo, useState } from 'react';

export interface SplitHandleProps {
  /** Current split ratio (0-1, percentage for left pane) */
  splitRatio: number;
  /** Callback when ratio changes */
  onRatioChange: (ratio: number) => void;
  /** Orientation */
  orientation?: 'horizontal' | 'vertical';
  /** Minimum size for each pane (0-0.5) */
  minSize?: number;
}

export const SplitHandle = memo(function SplitHandle({
  splitRatio,
  onRatioChange,
  orientation = 'horizontal',
  minSize = 0.2,
}: SplitHandleProps) {
  const handleRef = useRef<HTMLDivElement>(null);
  const [isDragging, setIsDragging] = useState(false);

  // Handle drag start
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);

    const container = handleRef.current?.parentElement;
    if (!container) return;

    const rect = container.getBoundingClientRect();
    const isHorizontal = orientation === 'horizontal';

    const handleMouseMove = (moveEvent: MouseEvent) => {
      const position = isHorizontal
        ? moveEvent.clientX - rect.left
        : moveEvent.clientY - rect.top;
      const size = isHorizontal ? rect.width : rect.height;

      let newRatio = position / size;

      // Enforce minimum sizes
      newRatio = Math.max(minSize, Math.min(1 - minSize, newRatio));

      onRatioChange(newRatio);
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    document.body.style.cursor = isHorizontal ? 'col-resize' : 'row-resize';
    document.body.style.userSelect = 'none';
  }, [orientation, minSize, onRatioChange]);

  // Handle double-click to reset
  const handleDoubleClick = useCallback(() => {
    onRatioChange(0.5);
  }, [onRatioChange]);

  // Handle touch events for mobile
  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    if (e.touches.length !== 1) return;
    e.preventDefault();
    setIsDragging(true);

    const container = handleRef.current?.parentElement;
    if (!container) return;

    const rect = container.getBoundingClientRect();
    const isHorizontal = orientation === 'horizontal';

    const handleTouchMove = (moveEvent: TouchEvent) => {
      if (moveEvent.touches.length !== 1) return;
      const touch = moveEvent.touches[0]!;

      const position = isHorizontal
        ? touch.clientX - rect.left
        : touch.clientY - rect.top;
      const size = isHorizontal ? rect.width : rect.height;

      let newRatio = position / size;
      newRatio = Math.max(minSize, Math.min(1 - minSize, newRatio));

      onRatioChange(newRatio);
    };

    const handleTouchEnd = () => {
      setIsDragging(false);
      document.removeEventListener('touchmove', handleTouchMove);
      document.removeEventListener('touchend', handleTouchEnd);
    };

    document.addEventListener('touchmove', handleTouchMove, { passive: false });
    document.addEventListener('touchend', handleTouchEnd);
  }, [orientation, minSize, onRatioChange]);

  return (
    <div
      ref={handleRef}
      className={`split-handle split-handle--${orientation} ${isDragging ? 'split-handle--dragging' : ''}`}
      onMouseDown={handleMouseDown}
      onDoubleClick={handleDoubleClick}
      onTouchStart={handleTouchStart}
      title="Drag to resize, double-click to reset"
    >
      <div className="split-handle__grip">
        <span className="split-handle__dot" />
        <span className="split-handle__dot" />
        <span className="split-handle__dot" />
      </div>
    </div>
  );
});

export default SplitHandle;
