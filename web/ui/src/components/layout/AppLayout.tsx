import React, { useEffect } from 'react';
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
