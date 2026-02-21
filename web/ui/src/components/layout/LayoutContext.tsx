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

  // Sidebar controls (left panel)
  isSidebarOpen: boolean;
  isSidebarCollapsed: boolean;
  openSidebar: () => void;
  closeSidebar: () => void;
  toggleSidebar: () => void;
  collapseSidebar: () => void;
  expandSidebar: () => void;
  toggleSidebarCollapse: () => void;
  setSidebarWidth: (width: number) => void;

  // Detail panel controls (right panel)
  isDetailOpen: boolean;
  isDetailCollapsed: boolean;
  openDetail: () => void;
  closeDetail: () => void;
  toggleDetail: () => void;
  collapseDetail: () => void;
  expandDetail: () => void;
  toggleDetailCollapse: () => void;
  setDetailWidth: (width: number) => void;

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
const STORAGE_KEY_DETAIL_WIDTH = 'balloons:detail-width';
const STORAGE_KEY_DETAIL_COLLAPSED = 'balloons:detail-collapsed';

// Default sidebar width
const DEFAULT_SIDEBAR_WIDTH = 320;
const MIN_SIDEBAR_WIDTH = 240;
const MAX_SIDEBAR_WIDTH = 600;  // Increased for context curation workflow
const COLLAPSED_SIDEBAR_WIDTH = 56;

// Default detail panel width
const DEFAULT_DETAIL_WIDTH = 320;
const MIN_DETAIL_WIDTH = 240;
const MAX_DETAIL_WIDTH = 600;
const COLLAPSED_DETAIL_WIDTH = 56;

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

  // Mobile detail panel open state (overlay)
  const [isDetailOpen, setIsDetailOpen] = useState(false);

  // Desktop detail panel collapsed state (persisted)
  const [isDetailCollapsed, setIsDetailCollapsed] = useState(() => {
    if (typeof window === 'undefined') return true; // Default collapsed on desktop
    const stored = localStorage.getItem(STORAGE_KEY_DETAIL_COLLAPSED);
    return stored !== 'false'; // Default to true (collapsed)
  });

  // Detail panel width (persisted)
  const [detailWidth, setDetailWidthState] = useState(() => {
    if (typeof window === 'undefined') return DEFAULT_DETAIL_WIDTH;
    const stored = localStorage.getItem(STORAGE_KEY_DETAIL_WIDTH);
    if (stored) {
      const parsed = parseInt(stored, 10);
      if (!isNaN(parsed) && parsed >= MIN_DETAIL_WIDTH && parsed <= MAX_DETAIL_WIDTH) {
        return parsed;
      }
    }
    return DEFAULT_DETAIL_WIDTH;
  });

  // Handle window resize
  useEffect(() => {
    const handleResize = () => {
      const newMode = window.innerWidth >= BREAKPOINTS.tablet ? 'desktop' : 'mobile';
      setLayoutMode(newMode);

      // Close mobile panels when switching to desktop
      if (newMode === 'desktop') {
        setIsSidebarOpen(false);
        setIsDetailOpen(false);
      }
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Persist sidebar collapsed state
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_SIDEBAR_COLLAPSED, String(isSidebarCollapsed));
  }, [isSidebarCollapsed]);

  // Persist detail panel collapsed state
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_DETAIL_COLLAPSED, String(isDetailCollapsed));
  }, [isDetailCollapsed]);

  // Sidebar controls - close detail panel on mobile when opening sidebar
  const openSidebar = useCallback(() => {
    if (layoutMode === 'mobile') {
      setIsDetailOpen(false); // Only one panel at a time on mobile
    }
    setIsSidebarOpen(true);
  }, [layoutMode]);
  const closeSidebar = useCallback(() => setIsSidebarOpen(false), []);
  const toggleSidebar = useCallback(() => {
    setIsSidebarOpen(prev => {
      if (!prev && layoutMode === 'mobile') {
        setIsDetailOpen(false);
      }
      return !prev;
    });
  }, [layoutMode]);

  const collapseSidebar = useCallback(() => setIsSidebarCollapsed(true), []);
  const expandSidebar = useCallback(() => setIsSidebarCollapsed(false), []);
  const toggleSidebarCollapse = useCallback(() => setIsSidebarCollapsed(prev => !prev), []);

  // Sidebar width control
  const setSidebarWidth = useCallback((width: number) => {
    const clamped = Math.max(MIN_SIDEBAR_WIDTH, Math.min(MAX_SIDEBAR_WIDTH, width));
    setSidebarWidthState(clamped);
    localStorage.setItem(STORAGE_KEY_SIDEBAR_WIDTH, String(clamped));
  }, []);

  // Detail panel controls - close sidebar on mobile when opening detail
  const openDetail = useCallback(() => {
    if (layoutMode === 'mobile') {
      setIsSidebarOpen(false); // Only one panel at a time on mobile
    }
    setIsDetailOpen(true);
  }, [layoutMode]);
  const closeDetail = useCallback(() => setIsDetailOpen(false), []);
  const toggleDetail = useCallback(() => {
    setIsDetailOpen(prev => {
      if (!prev && layoutMode === 'mobile') {
        setIsSidebarOpen(false);
      }
      return !prev;
    });
  }, [layoutMode]);

  const collapseDetail = useCallback(() => setIsDetailCollapsed(true), []);
  const expandDetail = useCallback(() => setIsDetailCollapsed(false), []);
  const toggleDetailCollapse = useCallback(() => setIsDetailCollapsed(prev => !prev), []);

  // Detail panel width control
  const setDetailWidth = useCallback((width: number) => {
    const clamped = Math.max(MIN_DETAIL_WIDTH, Math.min(MAX_DETAIL_WIDTH, width));
    setDetailWidthState(clamped);
    localStorage.setItem(STORAGE_KEY_DETAIL_WIDTH, String(clamped));
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
      isVisible: layoutMode === 'desktop' ? !isDetailCollapsed : isDetailOpen,
      isCollapsed: layoutMode === 'desktop' && isDetailCollapsed,
      // On mobile, always use full width; on desktop, use collapsed width when collapsed
      width: layoutMode === 'mobile' ? detailWidth : (isDetailCollapsed ? COLLAPSED_DETAIL_WIDTH : detailWidth),
    },
  }), [layoutMode, isSidebarOpen, isSidebarCollapsed, sidebarWidth, isDetailOpen, isDetailCollapsed, detailWidth]);

  // CSS custom properties
  const cssVars: Record<string, string> = useMemo(() => ({
    '--sidebar-width': `${panels.sidebar.width}px`,
    '--sidebar-collapsed-width': `${COLLAPSED_SIDEBAR_WIDTH}px`,
    '--min-sidebar-width': `${MIN_SIDEBAR_WIDTH}px`,
    '--max-sidebar-width': `${MAX_SIDEBAR_WIDTH}px`,
    '--detail-width': `${panels.detail.width}px`,
    '--detail-collapsed-width': `${COLLAPSED_DETAIL_WIDTH}px`,
    '--min-detail-width': `${MIN_DETAIL_WIDTH}px`,
    '--max-detail-width': `${MAX_DETAIL_WIDTH}px`,
  }), [panels.sidebar.width, panels.detail.width]);

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
    isDetailOpen,
    isDetailCollapsed,
    openDetail,
    closeDetail,
    toggleDetail,
    collapseDetail,
    expandDetail,
    toggleDetailCollapse,
    setDetailWidth,
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
    isDetailOpen,
    isDetailCollapsed,
    openDetail,
    closeDetail,
    toggleDetail,
    collapseDetail,
    expandDetail,
    toggleDetailCollapse,
    setDetailWidth,
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
