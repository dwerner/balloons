import { useState, useRef, useEffect, useCallback } from 'react';
import type { MouseEvent as ReactMouseEvent, TouchEvent as ReactTouchEvent } from 'react';

const STORAGE_KEY = 'balloons:input-area-height';
const MIN_HEIGHT = 60;
const MAX_HEIGHT = 500;

/**
 * Resizable composer input area height, persisted to localStorage.
 *
 * Dragging the top edge up increases the height. Extracted from App.tsx so the
 * drag listeners, persistence, and refs live in one place.
 */
export function useInputAreaResize(): {
  inputAreaHeight: number;
  handleResizeStart: (e: ReactMouseEvent | ReactTouchEvent) => void;
} {
  const [inputAreaHeight, setInputAreaHeight] = useState(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    const height = saved ? parseInt(saved, 10) : 100;
    // On mobile, cap at 150px by default to prevent huge text areas.
    const isMobile = typeof window !== 'undefined' && window.innerWidth <= 767;
    return isMobile ? Math.min(height, 150) : height;
  });
  const resizing = useRef(false);
  const startY = useRef(0);
  const startHeight = useRef(0);

  // Persist height across sessions.
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, String(inputAreaHeight));
  }, [inputAreaHeight]);

  const handleResizeStart = useCallback(
    (e: ReactMouseEvent | ReactTouchEvent) => {
      e.preventDefault();
      resizing.current = true;
      const clientY = 'touches' in e ? e.touches[0]?.clientY ?? 0 : e.clientY;
      startY.current = clientY;
      startHeight.current = inputAreaHeight;
      document.body.style.cursor = 'row-resize';
      document.body.style.userSelect = 'none';
    },
    [inputAreaHeight]
  );

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!resizing.current) return;
      // Dragging up (negative delta) should increase height.
      const delta = startY.current - e.clientY;
      const newHeight = Math.max(MIN_HEIGHT, Math.min(MAX_HEIGHT, startHeight.current + delta));
      setInputAreaHeight(newHeight);
    };

    const handleTouchMove = (e: TouchEvent) => {
      if (!resizing.current) return;
      const touch = e.touches[0];
      if (!touch) return;
      const delta = startY.current - touch.clientY;
      const newHeight = Math.max(MIN_HEIGHT, Math.min(MAX_HEIGHT, startHeight.current + delta));
      setInputAreaHeight(newHeight);
    };

    const handleEnd = () => {
      if (resizing.current) {
        resizing.current = false;
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      }
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleEnd);
    document.addEventListener('touchmove', handleTouchMove);
    document.addEventListener('touchend', handleEnd);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleEnd);
      document.removeEventListener('touchmove', handleTouchMove);
      document.removeEventListener('touchend', handleEnd);
    };
  }, []);

  return { inputAreaHeight, handleResizeStart };
}