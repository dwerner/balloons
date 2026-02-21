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
  const { layoutMode, isSidebarOpen, cssVars, closeSidebar } = useLayout();

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

  // Close sidebar when pressing Escape on mobile
  useEffect(() => {
    if (layoutMode !== 'mobile' || !isSidebarOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        closeSidebar();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [layoutMode, isSidebarOpen, closeSidebar]);

  // Prevent body scroll when mobile sidebar is open
  useEffect(() => {
    if (layoutMode === 'mobile' && isSidebarOpen) {
      document.body.style.overflow = 'hidden';
      return () => {
        document.body.style.overflow = '';
      };
    }
  }, [layoutMode, isSidebarOpen]);

  return (
    <div
      className={`app-layout app-layout--${layoutMode}`}
      data-sidebar-open={isSidebarOpen}
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

/**
 * Resize handle for the sidebar
 */
function ResizeHandle() {
  const { layoutMode, isSidebarCollapsed, setSidebarWidth, panels } = useLayout();
  const [isDragging, setIsDragging] = useState(false);
  const startXRef = useRef(0);
  const startWidthRef = useRef(0);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (layoutMode !== 'desktop' || isSidebarCollapsed) return;

    e.preventDefault();
    setIsDragging(true);
    startXRef.current = e.clientX;
    startWidthRef.current = panels.sidebar.width;

    // Add grabbing cursor to body during drag
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, [layoutMode, isSidebarCollapsed, panels.sidebar.width]);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    if (layoutMode !== 'desktop' || isSidebarCollapsed) return;

    const touch = e.touches[0];
    if (!touch) return;

    setIsDragging(true);
    startXRef.current = touch.clientX;
    startWidthRef.current = panels.sidebar.width;
  }, [layoutMode, isSidebarCollapsed, panels.sidebar.width]);

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      const delta = e.clientX - startXRef.current;
      const newWidth = startWidthRef.current + delta;
      setSidebarWidth(newWidth);
    };

    const handleTouchMove = (e: TouchEvent) => {
      const touch = e.touches[0];
      if (!touch) return;
      const delta = touch.clientX - startXRef.current;
      const newWidth = startWidthRef.current + delta;
      setSidebarWidth(newWidth);
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
  }, [isDragging, setSidebarWidth]);

  // Only show on desktop when not collapsed
  if (layoutMode !== 'desktop' || isSidebarCollapsed) return null;

  return (
    <div
      className={`app-layout__resize-handle ${isDragging ? 'app-layout__resize-handle--active' : ''}`}
      onMouseDown={handleMouseDown}
      onTouchStart={handleTouchStart}
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize sidebar"
      tabIndex={0}
      onKeyDown={(e) => {
        // Keyboard resize support
        if (e.key === 'ArrowLeft') {
          setSidebarWidth(panels.sidebar.width - 10);
        } else if (e.key === 'ArrowRight') {
          setSidebarWidth(panels.sidebar.width + 10);
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
        <ResizeHandle />
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
AppLayout.Header = Header;
