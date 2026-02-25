/**
 * FileList - Sidebar showing files with changes
 */

import React, { memo } from 'react';
import type { DiffFile } from '../../../../generated/balloons-client';

interface FileListProps {
  files: DiffFile[];
  selectedPath: string | null;
  onSelectFile: (path: string) => void;
}

// Status icons and colors
const STATUS_CONFIG: Record<string, { icon: string; color: string; label: string }> = {
  added: { icon: '+', color: '#4ade80', label: 'Added' },
  modified: { icon: 'M', color: '#facc15', label: 'Modified' },
  deleted: { icon: '-', color: '#f87171', label: 'Deleted' },
  renamed: { icon: 'R', color: '#c084fc', label: 'Renamed' },
  copied: { icon: 'C', color: '#60a5fa', label: 'Copied' },
};

const FileListItem = memo(function FileListItem({
  file,
  isSelected,
  onClick,
}: {
  file: DiffFile;
  isSelected: boolean;
  onClick: () => void;
}) {
  const config = STATUS_CONFIG[file.status] || { icon: '?', color: '#888', label: file.status };
  const fileName = file.path.split('/').pop() || file.path;
  const dirPath = file.path.includes('/')
    ? file.path.substring(0, file.path.lastIndexOf('/'))
    : '';

  return (
    <button
      className={`code-file-list__item ${isSelected ? 'code-file-list__item--selected' : ''}`}
      onClick={onClick}
      title={file.path}
    >
      <span
        className="code-file-list__status"
        style={{ color: config.color }}
        title={config.label}
      >
        {config.icon}
      </span>
      <span className="code-file-list__name">{fileName}</span>
      {dirPath && <span className="code-file-list__dir">{dirPath}</span>}
      <span className="code-file-list__stats">
        {file.additions > 0 && (
          <span className="code-file-list__additions">+{file.additions}</span>
        )}
        {file.deletions > 0 && (
          <span className="code-file-list__deletions">-{file.deletions}</span>
        )}
      </span>
    </button>
  );
});

export const FileList = memo(function FileList({
  files,
  selectedPath,
  onSelectFile,
}: FileListProps) {
  if (files.length === 0) {
    return (
      <div className="code-file-list code-file-list--empty">
        <p>No changes detected</p>
      </div>
    );
  }

  return (
    <div className="code-file-list">
      <div className="code-file-list__header">
        Changed Files ({files.length})
      </div>
      <div className="code-file-list__items">
        {files.map((file) => (
          <FileListItem
            key={file.path}
            file={file}
            isSelected={file.path === selectedPath}
            onClick={() => onSelectFile(file.path)}
          />
        ))}
      </div>
    </div>
  );
});

export default FileList;
