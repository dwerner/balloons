/**
 * EditorView - Main component combining Monaco editor and Code Map.
 *
 * Desktop: Side-by-side split with draggable handle
 * Mobile: Full-screen toggle between Editor and Map
 *
 * State:
 * - Open files with map inclusion checkboxes
 * - Split ratio (persisted to localStorage)
 * - Entity extraction from mapped files
 */

import React, { useState, useCallback, useMemo, useEffect, memo } from 'react';
import type { LSPServiceClient } from '../../../../../generated/balloons-client';
import type { EditorFile, CodeEntity, CodeRelation } from './types';
import { detectLanguage } from './types';
import { EditorTabs } from './EditorTabs';
import { MonacoWrapper } from './MonacoWrapper';
import { SplitHandle } from './SplitHandle';
import { CodeMapPane } from './CodeMapPane';
import { useLSPEntities } from './useLSPEntities';

// LocalStorage key for split ratio
const SPLIT_RATIO_KEY = 'balloons:editor-split-ratio';

export interface EditorViewProps {
  /** File state service client for reading files */
  client?: {
    readFile: (path: string) => Promise<string>;
  };
  /** LSP service client for code intelligence */
  lspClient?: LSPServiceClient;
  /** Current theme (dark/light) */
  isDarkMode: boolean;
  /** Whether on mobile layout */
  isMobile: boolean;
  /** Files to open (externally controlled) */
  initialFiles?: Array<{ path: string; content?: string }>;
  /** Callback when requesting to open a file */
  onOpenFile?: (path: string) => void;
}

// Load split ratio from localStorage
function loadSplitRatio(): number {
  try {
    const saved = localStorage.getItem(SPLIT_RATIO_KEY);
    if (saved) {
      const ratio = parseFloat(saved);
      if (!isNaN(ratio) && ratio >= 0.2 && ratio <= 0.8) {
        return ratio;
      }
    }
  } catch {
    // Ignore
  }
  return 0.6; // Default: 60% editor, 40% map
}

// Save split ratio to localStorage
function saveSplitRatio(ratio: number): void {
  try {
    localStorage.setItem(SPLIT_RATIO_KEY, ratio.toString());
  } catch {
    // Ignore
  }
}

export const EditorView = memo(function EditorView({
  client,
  lspClient,
  isDarkMode,
  isMobile,
  initialFiles = [],
  onOpenFile,
}: EditorViewProps) {
  // State
  const [files, setFiles] = useState<EditorFile[]>(() =>
    initialFiles.map((f) => ({
      path: f.path,
      content: f.content,
      language: detectLanguage(f.path),
      includedInMap: false,
      isDirty: false,
    }))
  );
  const [activeFilePath, setActiveFilePath] = useState<string | null>(
    initialFiles.length > 0 ? initialFiles[0]!.path : null
  );
  const [mapVisible, setMapVisible] = useState(false);
  const [splitRatio, setSplitRatio] = useState(loadSplitRatio);
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);
  const [mobileView, setMobileView] = useState<'editor' | 'map'>('editor');
  const [editorFullscreen, setEditorFullscreen] = useState(false);
  const [mapFullscreen, setMapFullscreen] = useState(false);

  // Persist split ratio
  useEffect(() => {
    saveSplitRatio(splitRatio);
  }, [splitRatio]);

  // Get active file
  const activeFile = useMemo(
    () => files.find((f) => f.path === activeFilePath),
    [files, activeFilePath]
  );

  // Extract entities from files using LSP (falls back to regex)
  const { entities, relations, isLoading: isExtractingEntities } = useLSPEntities({
    lspClient,
    files,
  });

  // Handle file selection
  const handleSelectFile = useCallback(async (path: string) => {
    setActiveFilePath(path);

    // Load content if not already loaded
    const file = files.find((f) => f.path === path);
    if (file && !file.content && client) {
      try {
        const content = await client.readFile(path);
        setFiles((prev) =>
          prev.map((f) =>
            f.path === path ? { ...f, content } : f
          )
        );
      } catch (e) {
        console.error('Failed to load file:', e);
      }
    }
  }, [files, client]);

  // Handle file close
  const handleCloseFile = useCallback((path: string) => {
    setFiles((prev) => prev.filter((f) => f.path !== path));

    // If closing active file, select another
    if (activeFilePath === path) {
      const remaining = files.filter((f) => f.path !== path);
      setActiveFilePath(remaining.length > 0 ? remaining[0]!.path : null);
    }
  }, [files, activeFilePath]);

  // Handle map toggle for a file
  const handleToggleMap = useCallback((path: string) => {
    setFiles((prev) =>
      prev.map((f) =>
        f.path === path ? { ...f, includedInMap: !f.includedInMap } : f
      )
    );
  }, []);

  // Handle split ratio change
  const handleRatioChange = useCallback((ratio: number) => {
    setSplitRatio(ratio);
  }, []);

  // Handle entity selection in map
  const handleSelectEntity = useCallback((entityId: string) => {
    setSelectedEntityId(entityId);

    // Find the entity and navigate to its file/line
    const entity = entities.find((e) => e.id === entityId);
    if (entity) {
      // If file is not open, open it
      const file = files.find((f) => f.path === entity.filePath);
      if (!file) {
        onOpenFile?.(entity.filePath);
      } else {
        setActiveFilePath(entity.filePath);
      }
    }
  }, [entities, files, onOpenFile]);

  // Handle cursor position change in editor
  const handleCursorChange = useCallback((line: number, _column: number) => {
    // Find entity at this line
    const entity = entities.find(
      (e) => e.filePath === activeFilePath && e.lineStart <= line && line <= e.lineEnd
    );
    if (entity) {
      setSelectedEntityId(entity.id);
    }
  }, [entities, activeFilePath]);

  // Toggle map visibility
  const toggleMap = useCallback(() => {
    setMapVisible((prev) => !prev);
  }, []);

  // Mobile view toggle
  const toggleMobileView = useCallback(() => {
    setMobileView((prev) => (prev === 'editor' ? 'map' : 'editor'));
  }, []);

  // Fullscreen toggles
  const toggleEditorFullscreen = useCallback(() => {
    setEditorFullscreen((prev) => !prev);
    if (!editorFullscreen) {
      setMapFullscreen(false);  // Can only have one fullscreen at a time
    }
  }, [editorFullscreen]);

  const toggleMapFullscreen = useCallback(() => {
    setMapFullscreen((prev) => !prev);
    if (!mapFullscreen) {
      setEditorFullscreen(false);  // Can only have one fullscreen at a time
    }
  }, [mapFullscreen]);

  // Highlight line from selected entity
  const highlightLine = useMemo(() => {
    if (!selectedEntityId || !activeFile) return undefined;
    const entity = entities.find(
      (e) => e.id === selectedEntityId && e.filePath === activeFilePath
    );
    return entity?.lineStart;
  }, [selectedEntityId, entities, activeFilePath, activeFile]);

  // Count of files in map
  const mapFileCount = useMemo(
    () => files.filter((f) => f.includedInMap).length,
    [files]
  );

  // Render mobile layout
  if (isMobile) {
    return (
      <div className="editor-view editor-view--mobile">
        {/* Mobile header with toggle */}
        <div className="editor-view__mobile-header">
          <button
            className={`editor-view__mobile-tab ${mobileView === 'editor' ? 'editor-view__mobile-tab--active' : ''}`}
            onClick={() => setMobileView('editor')}
          >
            Editor
          </button>
          <button
            className={`editor-view__mobile-tab ${mobileView === 'map' ? 'editor-view__mobile-tab--active' : ''}`}
            onClick={() => setMobileView('map')}
          >
            Map {mapFileCount > 0 && <span className="editor-view__badge">{mapFileCount}</span>}
          </button>
        </div>

        {mobileView === 'editor' ? (
          <div className="editor-view__editor-container">
            <EditorTabs
              files={files}
              activeFilePath={activeFilePath}
              mapVisible={true} // Always show map checkbox on mobile
              onSelectFile={handleSelectFile}
              onCloseFile={handleCloseFile}
              onToggleMap={handleToggleMap}
            />
            {activeFile?.content ? (
              <MonacoWrapper
                filePath={activeFile.path}
                content={activeFile.content}
                language={activeFile.language}
                isDarkMode={isDarkMode}
                highlightLine={highlightLine}
                onCursorChange={handleCursorChange}
              />
            ) : (
              <div className="editor-view__empty">
                <p>No file selected</p>
              </div>
            )}
          </div>
        ) : (
          <div className={`editor-view__map-container ${mapFullscreen ? 'editor-view__map-container--fullscreen' : ''}`}>
            <CodeMapPane
              entities={entities}
              relations={relations}
              selectedEntityId={selectedEntityId}
              isDarkMode={isDarkMode}
              isMobile={true}
              onSelectEntity={handleSelectEntity}
              onToggleFullscreen={toggleMapFullscreen}
              isFullscreen={mapFullscreen}
            />
          </div>
        )}
      </div>
    );
  }

  // Render desktop layout
  return (
    <div className="editor-view editor-view--desktop">
      {/* Editor tabs */}
      <EditorTabs
        files={files}
        activeFilePath={activeFilePath}
        mapVisible={mapVisible}
        onSelectFile={handleSelectFile}
        onCloseFile={handleCloseFile}
        onToggleMap={handleToggleMap}
      />

      {/* Map toggle button */}
      <button
        className={`editor-view__map-toggle ${mapVisible ? 'editor-view__map-toggle--active' : ''}`}
        onClick={toggleMap}
        title={mapVisible ? 'Hide code map' : 'Show code map'}
      >
        ◉ Map {mapFileCount > 0 && <span className="editor-view__badge">{mapFileCount}</span>}
      </button>

      {/* Split container */}
      <div className="editor-view__split">
        {/* Editor pane */}
        <div
          className={`editor-view__pane editor-view__pane--editor ${editorFullscreen ? 'editor-view__pane--fullscreen' : ''}`}
          style={{ width: mapVisible && !editorFullscreen ? `${splitRatio * 100}%` : '100%' }}
        >
          {/* Editor fullscreen button */}
          <button
            className="editor-view__pane-fullscreen-btn"
            onClick={toggleEditorFullscreen}
            title={editorFullscreen ? 'Exit fullscreen' : 'Fullscreen editor'}
          >
            {editorFullscreen ? '⊗' : '⛶'}
          </button>

          {activeFile?.content ? (
            <MonacoWrapper
              filePath={activeFile.path}
              content={activeFile.content}
              language={activeFile.language}
              isDarkMode={isDarkMode}
              highlightLine={highlightLine}
              onCursorChange={handleCursorChange}
            />
          ) : (
            <div className="editor-view__empty">
              <p>No file selected</p>
              <p className="editor-view__empty-hint">
                Open a file from the file browser
              </p>
            </div>
          )}
        </div>

        {/* Split handle (only when map visible and not in fullscreen) */}
        {mapVisible && !editorFullscreen && !mapFullscreen && (
          <SplitHandle
            splitRatio={splitRatio}
            onRatioChange={handleRatioChange}
            orientation="horizontal"
            minSize={0.25}
          />
        )}

        {/* Map pane (only when visible and editor not fullscreen) */}
        {mapVisible && !editorFullscreen && (
          <div
            className={`editor-view__pane editor-view__pane--map ${mapFullscreen ? 'editor-view__pane--fullscreen' : ''}`}
            style={{ width: mapFullscreen ? '100%' : `${(1 - splitRatio) * 100}%` }}
          >
            <CodeMapPane
              entities={entities}
              relations={relations}
              selectedEntityId={selectedEntityId}
              isDarkMode={isDarkMode}
              isMobile={false}
              onSelectEntity={handleSelectEntity}
              onToggleFullscreen={toggleMapFullscreen}
              isFullscreen={mapFullscreen}
            />
          </div>
        )}
      </div>
    </div>
  );
});

export default EditorView;
