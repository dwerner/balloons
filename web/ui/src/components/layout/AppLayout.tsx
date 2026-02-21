import React, { useEffect, useCallback, useRef, useState } from 'react';
import { useLayout, LayoutProvider } from './LayoutContext';
import { ThemeProvider } from './ThemeContext';
import './AppLayout.css';

export interface AppLayoutProps {
  children: React.ReactNode;
}

/**
 * AppLayout provides the foundational grid structure for the application.
 *
 * Desktop (>=768px): 2-column grid with sidebar + main content
 * - Sidebar is always visible, can be collapsed
 * - CSS Grid: [sidebar-width] [1fr]
 *
 * Mobile (<768px): Single column with overlay navigation
 * - Sidebar appears as a slide-out overlay
 * - CSS Grid: [1fr]
 *
 * Usage:
 * ```tsx
 * <AppLayout>
 *   <AppLayout.Sidebar>
 *     <SessionList />
 *   </AppLayout.Sidebar>
 *   <AppLayout.Main>
 *     <ChatView />
 *   </AppLayout.Main>
 * </AppLayout>
 * ```
 */
function AppLayoutInner({ children }: AppLayoutProps) {
  const { layoutMode, isSidebarOpen, isDetailOpen, cssVars, closeSidebar, closeDetail, panels } = useLayout();

  // Apply CSS variables to the root element
  useEffect(() => {
    const root = document.documentElement;
    Object.entries(cssVars).forEach(([key, value]) => {
      root.style.setProperty(key, value);
    });

    return () => {
      Object.keys(cssVars).forEach(key => {
        root.style.removeProperty(key);
      });
    };
  }, [cssVars]);

  // Close panels when pressing Escape on mobile
  useEffect(() => {
    if (layoutMode !== 'mobile') return;
    if (!isSidebarOpen && !isDetailOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (isSidebarOpen) closeSidebar();
        if (isDetailOpen) closeDetail();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [layoutMode, isSidebarOpen, isDetailOpen, closeSidebar, closeDetail]);

  // Prevent body scroll when mobile panel is open
  useEffect(() => {
    if (layoutMode === 'mobile' && (isSidebarOpen || isDetailOpen)) {
      document.body.style.overflow = 'hidden';
      return () => {
        document.body.style.overflow = '';
      };
    }
  }, [layoutMode, isSidebarOpen, isDetailOpen]);

  return (
    <div
      className={`app-layout app-layout--${layoutMode} ${panels.detail.isVisible && layoutMode === 'desktop' ? 'app-layout--detail-visible' : ''}`}
      data-sidebar-open={isSidebarOpen}
      data-detail-open={isDetailOpen}
    >
      {children}
    </div>
  );
}

/**
 * AppLayout with LayoutProvider and ThemeProvider wrappers
 */
export function AppLayout({ children }: AppLayoutProps) {
  return (
    <ThemeProvider>
      <LayoutProvider>
        <AppLayoutInner>{children}</AppLayoutInner>
      </LayoutProvider>
    </ThemeProvider>
  );
}

// ============================================================================
// Sub-components
// ============================================================================

interface SidebarProps {
  children: React.ReactNode;
  className?: string;
}

interface ResizeHandleProps {
  panel: 'sidebar' | 'detail';
  position: 'right' | 'left' | 'bottom';
}

/**
 * Resize handle for panels (sidebar or detail)
 * Supports vertical (right/left edge) and horizontal (bottom edge) resize
 */
function ResizeHandle({ panel, position }: ResizeHandleProps) {
  const {
    layoutMode,
    isSidebarCollapsed,
    isDetailCollapsed,
    setSidebarWidth,
    setDetailWidth,
    panels
  } = useLayout();
  const [isDragging, setIsDragging] = useState(false);
  const startPosRef = useRef(0);
  const startWidthRef = useRef(0);

  const isCollapsed = panel === 'sidebar' ? isSidebarCollapsed : isDetailCollapsed;
  const setWidth = panel === 'sidebar' ? setSidebarWidth : setDetailWidth;
  const currentWidth = panels[panel].width;
  const isVertical = position === 'right' || position === 'left';
  const isBottomHandle = position === 'bottom';

  // Bottom handle is for mobile, vertical handles are for desktop
  const shouldShow = isBottomHandle
    ? layoutMode === 'mobile' && panels[panel].isVisible
    : layoutMode === 'desktop' && !isCollapsed;

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (!shouldShow) return;

    e.preventDefault();
    setIsDragging(true);
    startPosRef.current = isBottomHandle ? e.clientX : e.clientX;
    startWidthRef.current = currentWidth;

    document.body.style.cursor = isBottomHandle ? 'ew-resize' : 'col-resize';
    document.body.style.userSelect = 'none';
  }, [shouldShow, currentWidth, isBottomHandle]);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    if (!shouldShow) return;

    const touch = e.touches[0];
    if (!touch) return;

    setIsDragging(true);
    startPosRef.current = touch.clientX;
    startWidthRef.current = currentWidth;
  }, [shouldShow, currentWidth]);

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      let delta: number;
      if (isBottomHandle) {
        // For bottom handle on mobile, drag right = wider (for left sidebar)
        // For right panel, drag left = wider
        delta = panel === 'sidebar'
          ? e.clientX - startPosRef.current
          : startPosRef.current - e.clientX;
      } else {
        // For vertical handles
        delta = position === 'right'
          ? e.clientX - startPosRef.current
          : startPosRef.current - e.clientX;
      }
      const newWidth = startWidthRef.current + delta;
      setWidth(newWidth);
    };

    const handleTouchMove = (e: TouchEvent) => {
      const touch = e.touches[0];
      if (!touch) return;

      let delta: number;
      if (isBottomHandle) {
        delta = panel === 'sidebar'
          ? touch.clientX - startPosRef.current
          : startPosRef.current - touch.clientX;
      } else {
        delta = position === 'right'
          ? touch.clientX - startPosRef.current
          : startPosRef.current - touch.clientX;
      }
      const newWidth = startWidthRef.current + delta;
      setWidth(newWidth);
    };

    const handleEnd = () => {
      setIsDragging(false);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleEnd);
    document.addEventListener('touchmove', handleTouchMove);
    document.addEventListener('touchend', handleEnd);
    document.addEventListener('touchcancel', handleEnd);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleEnd);
      document.removeEventListener('touchmove', handleTouchMove);
      document.removeEventListener('touchend', handleEnd);
      document.removeEventListener('touchcancel', handleEnd);
    };
  }, [isDragging, setWidth, position, panel, isBottomHandle]);

  if (!shouldShow) return null;

  const handleClass = isBottomHandle
    ? 'app-layout__resize-handle--bottom'
    : `app-layout__resize-handle--${position}`;

  return (
    <div
      className={`app-layout__resize-handle ${handleClass} ${isDragging ? 'app-layout__resize-handle--active' : ''}`}
      onMouseDown={handleMouseDown}
      onTouchStart={handleTouchStart}
      role="separator"
      aria-orientation={isBottomHandle ? 'horizontal' : 'vertical'}
      aria-label={`Resize ${panel}`}
      tabIndex={0}
      onKeyDown={(e) => {
        // Keyboard resize support
        const delta = 10;
        if (isBottomHandle || position === 'right') {
          if (e.key === 'ArrowLeft') setWidth(currentWidth - delta);
          else if (e.key === 'ArrowRight') setWidth(currentWidth + delta);
        } else {
          if (e.key === 'ArrowLeft') setWidth(currentWidth + delta);
          else if (e.key === 'ArrowRight') setWidth(currentWidth - delta);
        }
      }}
    />
  );
}

/**
 * Sidebar panel - appears on the left in desktop mode, slides in as overlay on mobile
 */
function Sidebar({ children, className = '' }: SidebarProps) {
  const { layoutMode, isSidebarOpen, isSidebarCollapsed, closeSidebar } = useLayout();

  const isVisible = layoutMode === 'desktop' || isSidebarOpen;

  return (
    <>
      {/* Overlay for mobile */}
      {layoutMode === 'mobile' && (
        <div
          className={`app-layout__sidebar-overlay ${isSidebarOpen ? 'app-layout__sidebar-overlay--visible' : ''}`}
          onClick={closeSidebar}
          aria-hidden="true"
        />
      )}

      <aside
        className={`app-layout__sidebar ${className} ${isVisible ? 'app-layout__sidebar--visible' : ''} ${isSidebarCollapsed ? 'app-layout__sidebar--collapsed' : ''}`}
        aria-hidden={!isVisible}
      >
        {children}
        {/* Desktop: right edge resize handle */}
        <ResizeHandle panel="sidebar" position="right" />
        {/* Mobile: bottom resize handle */}
        <ResizeHandle panel="sidebar" position="bottom" />
      </aside>
    </>
  );
}

interface MainProps {
  children: React.ReactNode;
  className?: string;
}

/**
 * Main content panel - takes remaining space after sidebar
 */
function Main({ children, className = '' }: MainProps) {
  return (
    <main className={`app-layout__main ${className}`}>
      {children}
    </main>
  );
}

interface DetailProps {
  children: React.ReactNode;
  className?: string;
}

/**
 * Detail panel - appears on the right in desktop mode, slides in as overlay on mobile
 */
function Detail({ children, className = '' }: DetailProps) {
  const { layoutMode, isDetailOpen, isDetailCollapsed, closeDetail } = useLayout();

  const isVisible = layoutMode === 'desktop' ? !isDetailCollapsed : isDetailOpen;

  return (
    <>
      {/* Overlay for mobile */}
      {layoutMode === 'mobile' && (
        <div
          className={`app-layout__detail-overlay ${isDetailOpen ? 'app-layout__detail-overlay--visible' : ''}`}
          onClick={closeDetail}
          aria-hidden="true"
        />
      )}

      <aside
        className={`app-layout__detail ${className} ${isVisible ? 'app-layout__detail--visible' : ''} ${isDetailCollapsed ? 'app-layout__detail--collapsed' : ''}`}
        aria-hidden={!isVisible}
      >
        {/* Desktop: left edge resize handle */}
        <ResizeHandle panel="detail" position="left" />
        {/* Mobile: bottom resize handle */}
        <ResizeHandle panel="detail" position="bottom" />
        {children}
      </aside>
    </>
  );
}

interface HeaderProps {
  children: React.ReactNode;
  className?: string;
}

/**
 * Mobile header - visible on mobile, hidden on desktop via CSS
 */
function Header({ children, className = '' }: HeaderProps) {
  return (
    <header className={`app-layout__header ${className}`}>
      {children}
    </header>
  );
}

// Attach sub-components
AppLayout.Sidebar = Sidebar;
AppLayout.Main = Main;
AppLayout.Detail = Detail;
AppLayout.Header = Header;
