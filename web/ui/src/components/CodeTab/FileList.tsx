/**
 * FileList - Sidebar showing files with changes, organized by staging status
 *
 * Displays three sections:
 * - Staged: Files ready to commit (can be unstaged)
 * - Unstaged: Modified tracked files (can be staged)
 * - Untracked: New files not yet tracked by git (can be staged)
 */

import React, { memo, useCallback, useRef } from 'react';
import type { DiffFile, UntrackedFile } from '../../../../generated/balloons-client';

// Long press duration in ms
const LONG_PRESS_DURATION = 400;

interface FileListProps {
  stagedFiles: DiffFile[];
  unstagedFiles: DiffFile[];
  untrackedFiles: UntrackedFile[];
  selectedPath: string | null;
  selectedSection: 'staged' | 'unstaged' | 'untracked';
  onSelectFile: (path: string, section: 'staged' | 'unstaged' | 'untracked') => void;
  onStageFile: (path: string) => void;
  onUnstageFile: (path: string) => void;
}

// Status icons and colors
const STATUS_CONFIG: Record<string, { icon: string; color: string; label: string }> = {
  added: { icon: '+', color: '#4ade80', label: 'Added' },
  modified: { icon: 'M', color: '#facc15', label: 'Modified' },
  deleted: { icon: '-', color: '#f87171', label: 'Deleted' },
  renamed: { icon: 'R', color: '#c084fc', label: 'Renamed' },
  copied: { icon: 'C', color: '#60a5fa', label: 'Copied' },
  untracked: { icon: '?', color: '#60a5fa', label: 'Untracked' },
};

/** A single diff file item with stage/unstage action */
const DiffFileItem = memo(function DiffFileItem({
  file,
  isSelected,
  section,
  onClick,
  onAction,
  actionLabel,
}: {
  file: DiffFile;
  isSelected: boolean;
  section: 'staged' | 'unstaged';
  onClick: () => void;
  onAction: () => void;
  actionLabel: string;
}) {
  const config = STATUS_CONFIG[file.status] || { icon: '?', color: '#888', label: file.status };
  const fileName = file.path.split('/').pop() || file.path;
  const dirPath = file.path.includes('/')
    ? file.path.substring(0, file.path.lastIndexOf('/'))
    : '';

  const handleAction = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    onAction();
  }, [onAction]);

  return (
    <div
      className={`code-file-list__item ${isSelected ? 'code-file-list__item--selected' : ''}`}
      onClick={onClick}
      title={file.path}
      role="button"
      tabIndex={0}
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
      <button
        className={`code-file-list__action code-file-list__action--${section === 'staged' ? 'unstage' : 'stage'}`}
        onClick={handleAction}
        title={actionLabel}
      >
        {section === 'staged' ? '−' : '+'}
      </button>
    </div>
  );
});

/** An untracked file item */
const UntrackedFileItem = memo(function UntrackedFileItem({
  file,
  isSelected,
  onClick,
  onStage,
}: {
  file: UntrackedFile;
  isSelected: boolean;
  onClick: () => void;
  onStage: () => void;
}) {
  const fileName = file.path.split('/').pop() || file.path;
  const dirPath = file.path.includes('/')
    ? file.path.substring(0, file.path.lastIndexOf('/'))
    : '';

  const handleStage = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    onStage();
  }, [onStage]);

  return (
    <div
      className={`code-file-list__item ${isSelected ? 'code-file-list__item--selected' : ''}`}
      onClick={onClick}
      title={file.path}
      role="button"
      tabIndex={0}
    >
      <span
        className="code-file-list__status"
        style={{ color: '#60a5fa' }}
        title="Untracked"
      >
        ?
      </span>
      <span className="code-file-list__name">{fileName}</span>
      {dirPath && <span className="code-file-list__dir">{dirPath}</span>}
      <button
        className="code-file-list__action code-file-list__action--stage"
        onClick={handleStage}
        title="Stage file"
      >
        +
      </button>
    </div>
  );
});

/** Section header with count */
const SectionHeader = memo(function SectionHeader({
  title,
  count,
  variant,
}: {
  title: string;
  count: number;
  variant: 'staged' | 'unstaged' | 'untracked';
}) {
  if (count === 0) return null;

  return (
    <div className={`code-file-list__section-header code-file-list__section-header--${variant}`}>
      <span className="code-file-list__section-title">{title}</span>
      <span className="code-file-list__section-count">{count}</span>
    </div>
  );
});

export const FileList = memo(function FileList({
  stagedFiles,
  unstagedFiles,
  untrackedFiles,
  selectedPath,
  selectedSection,
  onSelectFile,
  onStageFile,
  onUnstageFile,
}: FileListProps) {
  const totalFiles = stagedFiles.length + unstagedFiles.length + untrackedFiles.length;

  if (totalFiles === 0) {
    return (
      <div className="code-file-list code-file-list--empty">
        <p>No changes detected</p>
      </div>
    );
  }

  return (
    <div className="code-file-list">
      <div className="code-file-list__header">
        Changes ({totalFiles})
      </div>
      <div className="code-file-list__items">
        {/* Staged files section */}
        {stagedFiles.length > 0 && (
          <>
            <SectionHeader title="Staged" count={stagedFiles.length} variant="staged" />
            {stagedFiles.map((file) => (
              <DiffFileItem
                key={`staged-${file.path}`}
                file={file}
                isSelected={file.path === selectedPath && selectedSection === 'staged'}
                section="staged"
                onClick={() => onSelectFile(file.path, 'staged')}
                onAction={() => onUnstageFile(file.path)}
                actionLabel="Unstage"
              />
            ))}
          </>
        )}

        {/* Unstaged files section */}
        {unstagedFiles.length > 0 && (
          <>
            <SectionHeader title="Unstaged" count={unstagedFiles.length} variant="unstaged" />
            {unstagedFiles.map((file) => (
              <DiffFileItem
                key={`unstaged-${file.path}`}
                file={file}
                isSelected={file.path === selectedPath && selectedSection === 'unstaged'}
                section="unstaged"
                onClick={() => onSelectFile(file.path, 'unstaged')}
                onAction={() => onStageFile(file.path)}
                actionLabel="Stage"
              />
            ))}
          </>
        )}

        {/* Untracked files section */}
        {untrackedFiles.length > 0 && (
          <>
            <SectionHeader title="Untracked" count={untrackedFiles.length} variant="untracked" />
            {untrackedFiles.map((file) => (
              <UntrackedFileItem
                key={`untracked-${file.path}`}
                file={file}
                isSelected={file.path === selectedPath && selectedSection === 'untracked'}
                onClick={() => onSelectFile(file.path, 'untracked')}
                onStage={() => onStageFile(file.path)}
              />
            ))}
          </>
        )}
      </div>
    </div>
  );
});

export default FileList;
