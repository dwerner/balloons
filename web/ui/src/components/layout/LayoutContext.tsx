import React, { createContext, useContext, useState, useCallback, useEffect, useMemo } from 'react';

// Breakpoints for responsive layout
export const BREAKPOINTS = {
  mobile: 0,
  tablet: 768,
  desktop: 1024,
} as const;

export type Breakpoint = keyof typeof BREAKPOINTS;

// Panel identifiers
export type PanelId = 'sidebar' | 'main' | 'detail';

// Panel state
export interface PanelState {
  isVisible: boolean;
  isCollapsed: boolean;
  width: number; // in pixels, 0 = auto
}

// Layout mode based on screen size
export type LayoutMode = 'mobile' | 'desktop';

// Layout context value
export interface LayoutContextValue {
  // Current layout mode
  layoutMode: LayoutMode;

  // Panel states
  panels: Record<PanelId, PanelState>;

  // Sidebar controls
  isSidebarOpen: boolean;
  isSidebarCollapsed: boolean;
  openSidebar: () => void;
  closeSidebar: () => void;
  toggleSidebar: () => void;
  collapseSidebar: () => void;
  expandSidebar: () => void;
  toggleSidebarCollapse: () => void;

  // Panel width controls (for future resizable panels)
  setSidebarWidth: (width: number) => void;

  // CSS custom properties for panels
  cssVars: Record<string, string>;
}

const defaultPanelState: PanelState = {
  isVisible: true,
  isCollapsed: false,
  width: 0,
};

const LayoutContext = createContext<LayoutContextValue | null>(null);

// Local storage keys
const STORAGE_KEY_SIDEBAR_WIDTH = 'balloons:sidebar-width';
const STORAGE_KEY_SIDEBAR_COLLAPSED = 'balloons:sidebar-collapsed';

// Default sidebar width
const DEFAULT_SIDEBAR_WIDTH = 320;
const MIN_SIDEBAR_WIDTH = 240;
const MAX_SIDEBAR_WIDTH = 600;  // Increased for context curation workflow
const COLLAPSED_SIDEBAR_WIDTH = 56;

export interface LayoutProviderProps {
  children: React.ReactNode;
}

export function LayoutProvider({ children }: LayoutProviderProps) {
  // Determine layout mode based on window width
  const [layoutMode, setLayoutMode] = useState<LayoutMode>(() => {
    if (typeof window === 'undefined') return 'desktop';
    return window.innerWidth >= BREAKPOINTS.tablet ? 'desktop' : 'mobile';
  });

  // Mobile sidebar open state (overlay)
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  // Desktop sidebar collapsed state (persisted)
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(() => {
    if (typeof window === 'undefined') return false;
    const stored = localStorage.getItem(STORAGE_KEY_SIDEBAR_COLLAPSED);
    return stored === 'true';
  });

  // Sidebar width (persisted)
  const [sidebarWidth, setSidebarWidthState] = useState(() => {
    if (typeof window === 'undefined') return DEFAULT_SIDEBAR_WIDTH;
    const stored = localStorage.getItem(STORAGE_KEY_SIDEBAR_WIDTH);
    if (stored) {
      const parsed = parseInt(stored, 10);
      if (!isNaN(parsed) && parsed >= MIN_SIDEBAR_WIDTH && parsed <= MAX_SIDEBAR_WIDTH) {
        return parsed;
      }
    }
    return DEFAULT_SIDEBAR_WIDTH;
  });

  // Handle window resize
  useEffect(() => {
    const handleResize = () => {
      const newMode = window.innerWidth >= BREAKPOINTS.tablet ? 'desktop' : 'mobile';
      setLayoutMode(newMode);

      // Close mobile sidebar when switching to desktop
      if (newMode === 'desktop') {
        setIsSidebarOpen(false);
      }
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Persist sidebar collapsed state
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_SIDEBAR_COLLAPSED, String(isSidebarCollapsed));
  }, [isSidebarCollapsed]);

  // Sidebar controls
  const openSidebar = useCallback(() => setIsSidebarOpen(true), []);
  const closeSidebar = useCallback(() => setIsSidebarOpen(false), []);
  const toggleSidebar = useCallback(() => setIsSidebarOpen(prev => !prev), []);

  const collapseSidebar = useCallback(() => setIsSidebarCollapsed(true), []);
  const expandSidebar = useCallback(() => setIsSidebarCollapsed(false), []);
  const toggleSidebarCollapse = useCallback(() => setIsSidebarCollapsed(prev => !prev), []);

  // Sidebar width control
  const setSidebarWidth = useCallback((width: number) => {
    const clamped = Math.max(MIN_SIDEBAR_WIDTH, Math.min(MAX_SIDEBAR_WIDTH, width));
    setSidebarWidthState(clamped);
    localStorage.setItem(STORAGE_KEY_SIDEBAR_WIDTH, String(clamped));
  }, []);

  // Build panel states
  const panels: Record<PanelId, PanelState> = useMemo(() => ({
    sidebar: {
      isVisible: layoutMode === 'desktop' || isSidebarOpen,
      isCollapsed: layoutMode === 'desktop' && isSidebarCollapsed,
      width: isSidebarCollapsed ? COLLAPSED_SIDEBAR_WIDTH : sidebarWidth,
    },
    main: {
      isVisible: true,
      isCollapsed: false,
      width: 0, // auto
    },
    detail: {
      isVisible: false,
      isCollapsed: false,
      width: 0,
    },
  }), [layoutMode, isSidebarOpen, isSidebarCollapsed, sidebarWidth]);

  // CSS custom properties
  const cssVars: Record<string, string> = useMemo(() => ({
    '--sidebar-width': `${panels.sidebar.width}px`,
    '--sidebar-collapsed-width': `${COLLAPSED_SIDEBAR_WIDTH}px`,
    '--min-sidebar-width': `${MIN_SIDEBAR_WIDTH}px`,
    '--max-sidebar-width': `${MAX_SIDEBAR_WIDTH}px`,
  }), [panels.sidebar.width]);

  const value: LayoutContextValue = useMemo(() => ({
    layoutMode,
    panels,
    isSidebarOpen,
    isSidebarCollapsed,
    openSidebar,
    closeSidebar,
    toggleSidebar,
    collapseSidebar,
    expandSidebar,
    toggleSidebarCollapse,
    setSidebarWidth,
    cssVars,
  }), [
    layoutMode,
    panels,
    isSidebarOpen,
    isSidebarCollapsed,
    openSidebar,
    closeSidebar,
    toggleSidebar,
    collapseSidebar,
    expandSidebar,
    toggleSidebarCollapse,
    setSidebarWidth,
    cssVars,
  ]);

  return (
    <LayoutContext.Provider value={value}>
      {children}
    </LayoutContext.Provider>
  );
}

export function useLayout(): LayoutContextValue {
  const context = useContext(LayoutContext);
  if (!context) {
    throw new Error('useLayout must be used within a LayoutProvider');
  }
  return context;
}

// Hook for responsive queries
export function useBreakpoint(): Breakpoint {
  const { layoutMode } = useLayout();
  return layoutMode === 'mobile' ? 'mobile' : 'desktop';
}

// Hook to check if we're at or above a certain breakpoint
export function useMediaQuery(breakpoint: Breakpoint): boolean {
  const { layoutMode } = useLayout();
  if (breakpoint === 'mobile') return true;
  if (breakpoint === 'tablet') return layoutMode === 'desktop';
  return layoutMode === 'desktop';
}
