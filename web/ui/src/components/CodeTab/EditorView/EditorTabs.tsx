/**
 * EditorTabs - Horizontal tabs for open files with map toggle checkboxes.
 *
 * Features:
 * - Tab per open file with close button
 * - Checkbox to include/exclude file from code map
 * - Active tab highlighting
 * - Horizontal scroll for many tabs
 */

import React, { memo } from 'react';
import type { EditorFile } from './types';
import { getLanguageColor } from './types';

export interface EditorTabsProps {
  files: EditorFile[];
  activeFilePath: string | null;
  mapVisible: boolean;
  onSelectFile: (path: string) => void;
  onCloseFile: (path: string) => void;
  onToggleMap: (path: string) => void;
}

/** Get filename from path */
function getFileName(path: string): string {
  return path.split('/').pop() || path;
}

/** Get directory hint (last 2 segments) */
function getPathHint(path: string): string {
  const parts = path.split('/');
  if (parts.length <= 2) return '';
  return parts.slice(-3, -1).join('/');
}

export const EditorTabs = memo(function EditorTabs({
  files,
  activeFilePath,
  mapVisible,
  onSelectFile,
  onCloseFile,
  onToggleMap,
}: EditorTabsProps) {
  if (files.length === 0) {
    return (
      <div className="editor-tabs editor-tabs--empty">
        <span className="editor-tabs__placeholder">No files open</span>
      </div>
    );
  }

  return (
    <div className="editor-tabs">
      <div className="editor-tabs__list">
        {files.map((file) => {
          const isActive = file.path === activeFilePath;
          const fileName = getFileName(file.path);
          const pathHint = getPathHint(file.path);
          const langColor = getLanguageColor(file.language);

          return (
            <div
              key={file.path}
              className={`editor-tab ${isActive ? 'editor-tab--active' : ''} ${file.isDirty ? 'editor-tab--dirty' : ''}`}
              onClick={() => onSelectFile(file.path)}
              title={file.path}
            >
              {/* Language indicator dot */}
              <span
                className="editor-tab__lang-dot"
                style={{ backgroundColor: langColor }}
                title={file.language}
              />

              {/* File name */}
              <span className="editor-tab__name">
                {fileName}
                {file.isDirty && <span className="editor-tab__dirty-dot">*</span>}
              </span>

              {/* Path hint for disambiguation */}
              {pathHint && (
                <span className="editor-tab__path-hint">{pathHint}</span>
              )}

              {/* Map checkbox (only show if map pane is visible) */}
              {mapVisible && (
                <label
                  className="editor-tab__map-toggle"
                  onClick={(e) => e.stopPropagation()}
                  title={file.includedInMap ? 'Remove from map' : 'Add to map'}
                >
                  <input
                    type="checkbox"
                    checked={file.includedInMap}
                    onChange={() => onToggleMap(file.path)}
                  />
                  <span className="editor-tab__map-icon">
                    {file.includedInMap ? '◉' : '○'}
                  </span>
                </label>
              )}

              {/* Close button */}
              <button
                className="editor-tab__close"
                onClick={(e) => {
                  e.stopPropagation();
                  onCloseFile(file.path);
                }}
                title="Close file"
              >
                ×
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
});

export default EditorTabs;
