/**
 * FileBrowserView - File browser with git status integration
 *
 * Features:
 * - Directory tree navigation with lazy loading
 * - Git status indicators (modified, staged, untracked, ignored)
 * - Breadcrumb navigation
 * - Context menu for file operations
 * - Session CWD management
 */

import React, { useState, useCallback, useEffect, useMemo, memo, useRef, forwardRef, useImperativeHandle } from 'react';
import type { FileEntry, DirectoryListing, FileStateServiceClient } from '../../../../generated/balloons-client';
import { createLogger } from '../../utils/debugLog';
import './FileBrowserView.css';

// Create scoped logger for this module
const debugLog = createLogger('FileBrowserView');

// Git status icons and colors
const GIT_STATUS_CONFIG: Record<string, { icon: string; color: string; title: string }> = {
  ' ': { icon: '', color: '', title: 'Clean' },
  'M': { icon: 'M', color: '#facc15', title: 'Modified' },
  'A': { icon: 'A', color: '#4ade80', title: 'Added' },
  'D': { icon: 'D', color: '#f87171', title: 'Deleted' },
  'R': { icon: 'R', color: '#c084fc', title: 'Renamed' },
  '?': { icon: '?', color: '#888', title: 'Untracked' },
  '!': { icon: '!', color: '#555', title: 'Ignored' },
  'T': { icon: 'T', color: '#60a5fa', title: 'Type changed' },
};

// File type icons
function getFileIcon(entry: FileEntry): string {
  if (entry.isDirectory) {
    return '\uD83D\uDCC1'; // folder emoji
  }

  const name = entry.name.toLowerCase();
  const ext = name.split('.').pop() || '';

  // Code files
  if (['ts', 'tsx', 'js', 'jsx'].includes(ext)) return '\uD83D\uDCDC'; // scroll (JS/TS)
  if (['py', 'pyw'].includes(ext)) return '\uD83D\uDC0D'; // snake (Python)
  if (['rs'].includes(ext)) return '\u2699\uFE0F'; // gear (Rust)
  if (['go'].includes(ext)) return '\uD83D\uDC39'; // hamster face (Go gopher-ish)
  if (['c', 'cpp', 'h', 'hpp'].includes(ext)) return '\uD83D\uDCBB'; // laptop (C/C++)
  if (['java', 'kt', 'scala'].includes(ext)) return '\u2615'; // coffee (Java)
  if (['rb'].includes(ext)) return '\uD83D\uDC8E'; // gem (Ruby)
  if (['php'].includes(ext)) return '\uD83D\uDC18'; // elephant (PHP)

  // Data files
  if (['json', 'yaml', 'yml', 'toml'].includes(ext)) return '\uD83D\uDCCB'; // clipboard
  if (['md', 'mdx', 'txt', 'rst'].includes(ext)) return '\uD83D\uDCDD'; // memo
  if (['csv', 'tsv'].includes(ext)) return '\uD83D\uDCCA'; // chart

  // Config files
  if (['gitignore', 'dockerignore', 'env'].includes(ext) || name.startsWith('.')) {
    return '\u2699\uFE0F'; // gear
  }
  if (['dockerfile'].includes(name) || ext === 'docker') return '\uD83D\uDC33'; // whale

  // Web files
  if (['html', 'htm'].includes(ext)) return '\uD83C\uDF10'; // globe
  if (['css', 'scss', 'less', 'sass'].includes(ext)) return '\uD83C\uDFA8'; // palette
  if (['svg'].includes(ext)) return '\uD83D\uDDBC\uFE0F'; // framed picture

  // Images
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'ico'].includes(ext)) return '\uD83D\uDDBC\uFE0F'; // framed picture

  // Archives
  if (['zip', 'tar', 'gz', 'bz2', 'xz', 'rar', '7z'].includes(ext)) return '\uD83D\uDCE6'; // package

  // Default
  return '\uD83D\uDCC4'; // page facing up
}

// Format file size
function formatSize(bytes: number): string {
  if (bytes === 0) return '';
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}K`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)}M`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)}G`;
}

// Arrow icon component
function Arrow({ open }: { open: boolean }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`file-arrow ${open ? 'file-arrow--open' : ''}`}
    >
      <path d="M9 18l6-6-6-6" />
    </svg>
  );
}

// Home icon
function HomeIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
      <polyline points="9,22 9,12 15,12 15,22" />
    </svg>
  );
}

// Up icon for parent directory
function UpIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 19V5M5 12l7-7 7 7" />
    </svg>
  );
}

// Refresh icon
function RefreshIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M23 4v6h-6" />
      <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
    </svg>
  );
}

// Default config for unknown statuses
const DEFAULT_STATUS_CONFIG = { icon: '', color: '', title: 'Unknown' };

// Git status badge component
function GitStatusBadge({ status, isStaged }: { status: string; isStaged: boolean }) {
  const config = GIT_STATUS_CONFIG[status] ?? DEFAULT_STATUS_CONFIG;
  if (!config.icon) return null;

  return (
    <span
      className={`file-git-status ${isStaged ? 'file-git-status--staged' : ''}`}
      style={{ color: config.color }}
      title={`${config.title}${isStaged ? ' (staged)' : ''}`}
    >
      {config.icon}
    </span>
  );
}

// Breadcrumb navigation component
interface BreadcrumbProps {
  path: string;
  onNavigate: (path: string) => void;
  onGoHome: () => void;
  onGoUp: () => void;
  onRefresh: () => void;
}

function Breadcrumb({ path, onNavigate, onGoHome, onGoUp, onRefresh }: BreadcrumbProps) {
  const parts = useMemo(() => {
    // Split path into segments
    const segments = path.split('/').filter(Boolean);
    const result: { name: string; path: string }[] = [];

    // Build path progressively
    let currentPath = '';
    for (const segment of segments) {
      currentPath += '/' + segment;
      result.push({ name: segment, path: currentPath });
    }

    return result;
  }, [path]);

  return (
    <div className="file-breadcrumb">
      <button
        className="file-breadcrumb__button"
        onClick={onGoHome}
        title="Go to home directory"
      >
        <HomeIcon />
      </button>
      <button
        className="file-breadcrumb__button"
        onClick={onGoUp}
        title="Go to parent directory"
      >
        <UpIcon />
      </button>
      <button
        className="file-breadcrumb__button"
        onClick={onRefresh}
        title="Refresh"
      >
        <RefreshIcon />
      </button>
      <div className="file-breadcrumb__path">
        <span className="file-breadcrumb__separator">/</span>
        {parts.map((part, index) => (
          <React.Fragment key={part.path}>
            <button
              className="file-breadcrumb__segment"
              onClick={() => onNavigate(part.path)}
            >
              {part.name}
            </button>
            {index < parts.length - 1 && (
              <span className="file-breadcrumb__separator">/</span>
            )}
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}

// File tree node component
interface FileTreeNodeProps {
  entry: FileEntry;
  depth: number;
  isExpanded: boolean;
  isLoading: boolean;
  children: FileEntry[];
  onToggle: () => void;
  onSelect: () => void;
  onNavigate: (path: string) => void;
  onContextMenu?: (e: React.MouseEvent, entry: FileEntry) => void;
  expandedPaths: Set<string>;
  loadingPaths: Set<string>;
  childrenCache: Map<string, FileEntry[]>;
}

const FileTreeNode = memo(function FileTreeNode({
  entry,
  depth,
  isExpanded,
  isLoading,
  children,
  onToggle,
  onSelect,
  onNavigate,
  onContextMenu,
  expandedPaths,
  loadingPaths,
  childrenCache,
}: FileTreeNodeProps) {
  const hasChildren = entry.isDirectory && (entry.childrenCount ?? 0) > 0;
  const icon = getFileIcon(entry);
  const sizeStr = !entry.isDirectory ? formatSize(entry.size) : '';

  const handleDoubleClick = useCallback(() => {
    if (entry.isDirectory) {
      onNavigate(entry.path);
    }
  }, [entry, onNavigate]);

  const handleClick = useCallback(() => {
    if (entry.isDirectory) {
      onToggle();
    } else {
      onSelect();
    }
  }, [entry.isDirectory, onToggle, onSelect]);

  const handleArrowClick = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    onToggle();
  }, [onToggle]);

  const handleRightClick = useCallback((e: React.MouseEvent) => {
    if (onContextMenu) {
      onContextMenu(e, entry);
    }
  }, [entry, onContextMenu]);

  return (
    <li className={`file-node ${entry.isIgnored ? 'file-node--ignored' : ''}`}>
      <div
        className="file-node__content"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        onClick={handleClick}
        onDoubleClick={handleDoubleClick}
        onContextMenu={handleRightClick}
      >
        <span className="file-node__toggle" onClick={handleArrowClick}>
          {hasChildren ? (
            isLoading ? (
              <span className="file-node__spinner" />
            ) : (
              <Arrow open={isExpanded} />
            )
          ) : (
            <span className="file-node__spacer" />
          )}
        </span>
        <span className="file-node__icon">{icon}</span>
        <span className="file-node__name">{entry.name}</span>
        <GitStatusBadge status={entry.gitStatus} isStaged={entry.isStaged} />
        {sizeStr && <span className="file-node__size">{sizeStr}</span>}
        {entry.isDirectory && entry.childrenCount != null && (
          <span className="file-node__count">{entry.childrenCount}</span>
        )}
      </div>

      {isExpanded && children.length > 0 && (
        <ul className="file-children">
          {children.map(child => {
            const childExpanded = expandedPaths.has(child.path);
            const childLoading = loadingPaths.has(child.path);
            const childChildren = childrenCache.get(child.path) || [];

            return (
              <FileTreeNode
                key={child.path}
                entry={child}
                depth={depth + 1}
                isExpanded={childExpanded}
                isLoading={childLoading}
                children={childChildren}
                onToggle={() => { }} // Will be wired up by parent
                onSelect={() => { }}
                onNavigate={onNavigate}
                onContextMenu={onContextMenu}
                expandedPaths={expandedPaths}
                loadingPaths={loadingPaths}
                childrenCache={childrenCache}
              />
            );
          })}
        </ul>
      )}
    </li>
  );
});

// Props for main component
export interface FileBrowserViewProps {
  /** Initial path to show (defaults to home directory) */
  initialPath?: string;

  /** Current session ID for CWD tracking */
  sessionId?: string;

  /** Callback when a file is selected */
  onFileSelect?: (path: string) => void;

  /** Callback when "Set as Working Directory" is selected on a folder */
  onSetWorkingDirectory?: (path: string) => void;

  /** Callback when "Insert Path" is selected - inserts path into chat input */
  onInsertPath?: (path: string) => void;

  /** FileStateService client - stable reference avoids re-renders */
  client: FileStateServiceClient;
}

// Ref handle for external control
export interface FileBrowserViewRef {
  /** Navigate to a specific directory */
  navigateTo: (path: string) => Promise<void>;
  /** Get the current path */
  getCurrentPath: () => string | null;
}

// Simple cache for directory listings - persists until user explicitly refreshes
const listingCache = new Map<string, DirectoryListing>();

function getCachedListing(path: string): DirectoryListing | null {
  return listingCache.get(path) ?? null;
}

function setCachedListing(path: string, listing: DirectoryListing): void {
  listingCache.set(path, listing);
}

export function invalidateListingCache(path?: string): void {
  if (path) {
    listingCache.delete(path);
  } else {
    listingCache.clear();
  }
}

export const FileBrowserView = memo(forwardRef<FileBrowserViewRef, FileBrowserViewProps>(function FileBrowserView({
  initialPath,
  sessionId,
  onFileSelect,
  onSetWorkingDirectory,
  onInsertPath,
  client,
}, ref) {
  // Current directory listing
  const [listing, setListing] = useState<DirectoryListing | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Expanded directories for lazy loading
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set());
  const [loadingPaths, setLoadingPaths] = useState<Set<string>>(new Set());
  const [childrenCache, setChildrenCache] = useState<Map<string, FileEntry[]>>(new Map());

  // Home directory path
  const [homePath, setHomePath] = useState<string>('');

  // Track initialization to show better loading state
  const [isInitializing, setIsInitializing] = useState(true);

  // Use ref to track if initial load has happened
  const initialLoadDone = useRef(false);

  // Track initial path to detect changes
  const prevInitialPath = useRef(initialPath);

  // Context menu state
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    entry: FileEntry | null;  // null when right-clicking on empty space
  } | null>(null);

  // Show hidden files toggle
  const [showHidden, setShowHidden] = useState(() => {
    // Persist preference in localStorage
    const saved = localStorage.getItem('fileBrowser.showHidden');
    return saved === 'true';
  });

  // Load home directory on mount (only once)
  useEffect(() => {
    client.getHomeDirectory().then(setHomePath).catch((err: unknown) => {
      debugLog('Failed to get home directory', { error: err });
    });
  }, [client]);

  // Load directory with caching
  const loadDirectory = useCallback(async (path: string, skipCache = false, includeHidden = showHidden) => {
    debugLog('Loading directory', { path, skipCache, includeHidden });

    // Include hidden status in cache key
    const cacheKey = includeHidden ? `${path}:hidden` : path;

    // Check cache first (unless refresh requested)
    if (!skipCache) {
      const cached = getCachedListing(cacheKey);
      if (cached) {
        debugLog('Using cached listing', { path, includeHidden });
        setListing(cached);
        setIsLoading(false);
        return;
      }
    }

    setIsLoading(true);
    setError(null);

    try {
      const result = includeHidden
        ? await client.listDirectoryWithHidden(path)
        : await client.listDirectory(path);
      setCachedListing(cacheKey, result);
      setListing(result);
      debugLog('Directory loaded', { path, entryCount: result.entries.length, includeHidden });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      debugLog('Failed to load directory', { path, error: message });
    } finally {
      setIsLoading(false);
    }
  }, [client, showHidden]);

  // Load initial directory - use initialPath if provided, otherwise home
  // Only runs once on mount, or when initialPath changes
  useEffect(() => {
    // Skip if we already loaded and initialPath hasn't changed
    if (initialLoadDone.current && prevInitialPath.current === initialPath) {
      return;
    }

    const loadInitial = async () => {
      setIsInitializing(true);
      try {
        const startPath = initialPath || await client.getHomeDirectory();
        debugLog('Loading initial directory', { startPath, initialPath });
        await loadDirectory(startPath);
        initialLoadDone.current = true;
        prevInitialPath.current = initialPath;
      } finally {
        setIsInitializing(false);
      }
    };
    loadInitial();
  }, [initialPath, client, loadDirectory]);

  // Navigate to a directory
  const navigateTo = useCallback(async (path: string) => {
    // Clear expansion state when navigating to new root
    setExpandedPaths(new Set());
    setChildrenCache(new Map());
    await loadDirectory(path);
  }, [loadDirectory]);

  // Expose methods via ref for external control
  useImperativeHandle(ref, () => ({
    navigateTo,
    getCurrentPath: () => listing?.path ?? null,
  }), [navigateTo, listing]);

  // Go to home directory
  const goHome = useCallback(async () => {
    const home = await client.getHomeDirectory();
    await navigateTo(home);
  }, [client, navigateTo]);

  // Go to parent directory
  const goUp = useCallback(async () => {
    if (!listing) return;
    const parent = await client.getParentDirectory(listing.path);
    if (parent !== listing.path) {
      await navigateTo(parent);
    }
  }, [listing, client, navigateTo]);

  // Refresh current directory (skip cache)
  const refresh = useCallback(() => {
    if (listing) {
      invalidateListingCache(listing.path);
      loadDirectory(listing.path, true);
    }
  }, [listing, loadDirectory]);

  // Toggle directory expansion (lazy load children)
  const toggleExpanded = useCallback(async (entry: FileEntry) => {
    if (!entry.isDirectory) return;

    const isExpanded = expandedPaths.has(entry.path);

    if (isExpanded) {
      // Collapse
      setExpandedPaths(prev => {
        const next = new Set(prev);
        next.delete(entry.path);
        return next;
      });
    } else {
      // Expand - load children if not cached
      if (!childrenCache.has(entry.path)) {
        setLoadingPaths(prev => new Set(prev).add(entry.path));
        try {
          const result = await client.listDirectory(entry.path);
          setCachedListing(entry.path, result);
          setChildrenCache(prev => new Map(prev).set(entry.path, result.entries));
        } catch (err) {
          debugLog('Failed to load children', { path: entry.path, error: err });
        } finally {
          setLoadingPaths(prev => {
            const next = new Set(prev);
            next.delete(entry.path);
            return next;
          });
        }
      }

      setExpandedPaths(prev => new Set(prev).add(entry.path));
    }
  }, [expandedPaths, childrenCache, client]);

  // Handle file selection
  const handleSelect = useCallback((entry: FileEntry) => {
    if (!entry.isDirectory && onFileSelect) {
      onFileSelect(entry.path);
    }
  }, [onFileSelect]);

  // Handle context menu
  const handleContextMenu = useCallback((e: React.MouseEvent, entry: FileEntry) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({
      x: e.clientX,
      y: e.clientY,
      entry,
    });
  }, []);

  // Close context menu
  const closeContextMenu = useCallback(() => {
    setContextMenu(null);
  }, []);

  // Handle set working directory from context menu
  const handleSetWorkingDirectory = useCallback(() => {
    if (contextMenu?.entry?.isDirectory && onSetWorkingDirectory) {
      onSetWorkingDirectory(contextMenu.entry.path);
    }
    setContextMenu(null);
  }, [contextMenu, onSetWorkingDirectory]);

  // Handle insert path from context menu
  const handleInsertPath = useCallback(() => {
    if (contextMenu?.entry && onInsertPath) {
      onInsertPath(contextMenu.entry.path);
    }
    setContextMenu(null);
  }, [contextMenu, onInsertPath]);

  // Handle toggle show hidden files
  const handleToggleShowHidden = useCallback(() => {
    const newValue = !showHidden;
    setShowHidden(newValue);
    localStorage.setItem('fileBrowser.showHidden', String(newValue));
    // Reload current directory with new setting
    if (listing) {
      loadDirectory(listing.path, true, newValue);
    }
    setContextMenu(null);
  }, [showHidden, listing, loadDirectory]);

  // Close context menu on escape or click outside
  useEffect(() => {
    if (!contextMenu) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        closeContextMenu();
      }
    };

    const handleClick = () => {
      closeContextMenu();
    };

    document.addEventListener('keydown', handleKeyDown);
    document.addEventListener('click', handleClick);

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('click', handleClick);
    };
  }, [contextMenu, closeContextMenu]);

  // Render loading state
  if ((isLoading || isInitializing) && !listing) {
    return (
      <div className="file-browser file-browser--loading">
        <div className="file-browser__spinner" />
        <span>{isInitializing ? 'Initializing...' : 'Loading directory...'}</span>
      </div>
    );
  }

  // Render error state
  if (error && !listing) {
    return (
      <div className="file-browser file-browser--error">
        <span className="file-browser__error-icon">!</span>
        <span className="file-browser__error-text">{error}</span>
        <button className="file-browser__retry" onClick={goHome}>
          Go Home
        </button>
      </div>
    );
  }

  if (!listing) {
    return null;
  }

  return (
    <div className="file-browser">
      {/* Breadcrumb navigation */}
      <Breadcrumb
        path={listing.path}
        onNavigate={navigateTo}
        onGoHome={goHome}
        onGoUp={goUp}
        onRefresh={refresh}
      />

      {/* Git info bar */}
      {listing.gitRoot && (
        <div className="file-browser__git-info">
          <span className="file-browser__git-icon">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
              <path d="M23.546 10.93L13.067.452c-.604-.603-1.582-.603-2.188 0L8.708 2.627l2.76 2.76c.645-.215 1.379-.07 1.889.441.516.515.658 1.258.438 1.9l2.658 2.66c.645-.223 1.387-.078 1.9.435.721.72.721 1.884 0 2.604-.719.719-1.881.719-2.6 0-.539-.541-.674-1.337-.404-1.996L12.86 8.955v6.525c.176.086.342.203.488.348.713.721.713 1.883 0 2.6-.719.721-1.889.721-2.609 0-.719-.719-.719-1.879 0-2.598.182-.18.387-.316.605-.406V8.835c-.217-.091-.424-.222-.6-.401-.545-.545-.676-1.342-.396-2.009L7.636 3.7.45 10.881c-.6.605-.6 1.584 0 2.189l10.48 10.477c.604.604 1.582.604 2.186 0l10.43-10.43c.605-.603.605-1.582 0-2.187" />
            </svg>
          </span>
          <span className="file-browser__git-root">
            {listing.gitPath || '/'}
          </span>
        </div>
      )}

      {/* File list */}
      <ul
        className="file-list"
        onContextMenu={(e) => {
          // Only trigger if clicking on the list itself, not on a file entry
          if (e.target === e.currentTarget) {
            e.preventDefault();
            setContextMenu({ x: e.clientX, y: e.clientY, entry: null });
          }
        }}
      >
        {listing.entries.length === 0 ? (
          <li
            className="file-node file-node--empty"
            onContextMenu={(e) => {
              e.preventDefault();
              setContextMenu({ x: e.clientX, y: e.clientY, entry: null });
            }}
          >
            <div className="file-node__content">
              <span className="file-node__name file-node__name--muted">
                Empty directory
              </span>
            </div>
          </li>
        ) : (
          listing.entries.map(entry => {
            const isExpanded = expandedPaths.has(entry.path);
            const isEntryLoading = loadingPaths.has(entry.path);
            const children = childrenCache.get(entry.path) || [];

            return (
              <FileTreeNode
                key={entry.path}
                entry={entry}
                depth={0}
                isExpanded={isExpanded}
                isLoading={isEntryLoading}
                children={children}
                onToggle={() => toggleExpanded(entry)}
                onSelect={() => handleSelect(entry)}
                onNavigate={navigateTo}
                onContextMenu={handleContextMenu}
                expandedPaths={expandedPaths}
                loadingPaths={loadingPaths}
                childrenCache={childrenCache}
              />
            );
          })
        )}
      </ul>

      {/* Loading overlay for refresh */}
      {isLoading && listing && (
        <div className="file-browser__loading-overlay">
          <div className="file-browser__spinner" />
        </div>
      )}

      {/* Context menu */}
      {contextMenu && (
        <div
          className="file-browser__context-menu"
          style={{
            position: 'fixed',
            left: contextMenu.x,
            top: contextMenu.y,
          }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* File/folder specific options */}
          {contextMenu.entry && (
            <>
              {contextMenu.entry.isDirectory && onSetWorkingDirectory && (
                <button
                  className="file-browser__context-menu-item"
                  onClick={handleSetWorkingDirectory}
                >
                  <span className="file-browser__context-menu-icon">📁</span>
                  Set as Working Directory
                </button>
              )}
              <button
                className="file-browser__context-menu-item"
                onClick={() => {
                  navigateTo(contextMenu.entry!.isDirectory ? contextMenu.entry!.path : listing.path);
                  closeContextMenu();
                }}
              >
                <span className="file-browser__context-menu-icon">📂</span>
                {contextMenu.entry.isDirectory ? 'Open in Browser' : 'Open Containing Folder'}
              </button>
              <button
                className="file-browser__context-menu-item"
                onClick={() => {
                  navigator.clipboard.writeText(contextMenu.entry!.path);
                  closeContextMenu();
                }}
              >
                <span className="file-browser__context-menu-icon">📋</span>
                Copy Path
              </button>
              {onInsertPath && (
                <button
                  className="file-browser__context-menu-item"
                  onClick={handleInsertPath}
                >
                  <span className="file-browser__context-menu-icon">⌨️</span>
                  Insert Path
                </button>
              )}
              <div className="file-browser__context-menu-divider" />
            </>
          )}
          {/* General options (always shown) */}
          <button
            className="file-browser__context-menu-item"
            onClick={handleToggleShowHidden}
          >
            <span className="file-browser__context-menu-icon">{showHidden ? '✓' : ' '}</span>
            Show Hidden Files
          </button>
        </div>
      )}
    </div>
  );
}));

export default FileBrowserView;
