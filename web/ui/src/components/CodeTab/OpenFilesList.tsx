/**
 * OpenFilesList - Sidebar showing files opened for browsing
 */

import React, { memo } from 'react';

export interface OpenFile {
  /** Absolute path to the file */
  path: string;
  /** File size in bytes */
  size: number;
}

interface OpenFilesListProps {
  files: OpenFile[];
  selectedPath: string | null;
  onSelectFile: (path: string) => void;
  onCloseFile: (path: string) => void;
}

// Format file size
function formatSize(bytes: number): string {
  if (bytes === 0) return '0B';
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}K`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)}M`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)}G`;
}

// Get file icon based on extension
function getFileIcon(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase() || '';

  // Code files
  if (['ts', 'tsx', 'js', 'jsx'].includes(ext)) return '\uD83D\uDCDC';
  if (['py', 'pyw'].includes(ext)) return '\uD83D\uDC0D';
  if (['rs'].includes(ext)) return '\u2699\uFE0F';
  if (['go'].includes(ext)) return '\uD83D\uDC39';
  if (['c', 'cpp', 'h', 'hpp'].includes(ext)) return '\uD83D\uDCBB';
  if (['java', 'kt', 'scala'].includes(ext)) return '\u2615';
  if (['rb'].includes(ext)) return '\uD83D\uDC8E';
  if (['php'].includes(ext)) return '\uD83D\uDC18';

  // Data files
  if (['json', 'yaml', 'yml', 'toml'].includes(ext)) return '\uD83D\uDCCB';
  if (['md', 'mdx', 'txt', 'rst'].includes(ext)) return '\uD83D\uDCDD';
  if (['csv', 'tsv'].includes(ext)) return '\uD83D\uDCCA';

  // Config files
  if (['gitignore', 'dockerignore', 'env'].includes(ext)) return '\u2699\uFE0F';

  // Web files
  if (['html', 'htm'].includes(ext)) return '\uD83C\uDF10';
  if (['css', 'scss', 'less', 'sass'].includes(ext)) return '\uD83C\uDFA8';
  if (['svg'].includes(ext)) return '\uD83D\uDDBC\uFE0F';

  // Images
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'ico'].includes(ext)) return '\uD83D\uDDBC\uFE0F';

  // Default
  return '\uD83D\uDCC4';
}

const OpenFileListItem = memo(function OpenFileListItem({
  file,
  isSelected,
  onClick,
  onClose,
}: {
  file: OpenFile;
  isSelected: boolean;
  onClick: () => void;
  onClose: (e: React.MouseEvent) => void;
}) {
  const fileName = file.path.split('/').pop() || file.path;
  const dirPath = file.path.includes('/')
    ? file.path.substring(0, file.path.lastIndexOf('/'))
    : '';
  const icon = getFileIcon(file.path);

  return (
    <button
      className={`code-file-list__item ${isSelected ? 'code-file-list__item--selected' : ''}`}
      onClick={onClick}
      title={file.path}
    >
      <span className="code-file-list__icon">{icon}</span>
      <span className="code-file-list__name">{fileName}</span>
      {dirPath && <span className="code-file-list__dir">{dirPath}</span>}
      <span className="code-file-list__size">{formatSize(file.size)}</span>
      <button
        className="code-file-list__close"
        onClick={onClose}
        title="Close file"
      >
        ×
      </button>
    </button>
  );
});

export const OpenFilesList = memo(function OpenFilesList({
  files,
  selectedPath,
  onSelectFile,
  onCloseFile,
}: OpenFilesListProps) {
  if (files.length === 0) {
    return (
      <div className="code-file-list code-file-list--empty">
        <p>No files open</p>
        <p className="code-file-list__hint">Select a file from the browser to open it here</p>
      </div>
    );
  }

  return (
    <div className="code-file-list">
      <div className="code-file-list__header">
        Open Files ({files.length})
      </div>
      <div className="code-file-list__items">
        {files.map((file) => (
          <OpenFileListItem
            key={file.path}
            file={file}
            isSelected={file.path === selectedPath}
            onClick={() => onSelectFile(file.path)}
            onClose={(e) => {
              e.stopPropagation();
              onCloseFile(file.path);
            }}
          />
        ))}
      </div>
    </div>
  );
});

export default OpenFilesList;
