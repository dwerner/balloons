/**
 * SystemCard - Renders system-level content blocks
 *
 * Handles: fork, merge, merged_to, link, interruption, error,
 * image, slide, review, fork_proposal, merge_proposal, archive
 *
 * Features:
 * - Raw JSON view toggle for debugging turn data
 */

import React, { useState, useCallback } from 'react';
import { MarkdownContent } from '../../../MarkdownContent';
import { SyntaxHighlightedCode } from './SyntaxHighlighter';
import { formatTimestamp } from '../../../utils';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
import type {
  ForkBlock,
  MergeBlock,
  MergedToBlock,
  ForkedFromBlock,
  LinkBlock,
  ErrorBlock,
  InterruptionBlock,
  ArchiveBlock,
  SlideBlock,
  ReviewBlock,
  ForkProposalBlock,
  MergeProposalBlock,
  ImageBlock,
  SessionSummaryBlock,
  WatchStartBlock,
  WatchStopBlock,
  WatchSummaryBlock,
} from '../../../../../generated/types';
import { useSelectSession, useClient } from './ClientContext';
import { ImageBlockView } from './ImageBlockView';
import { createLogger } from '../../../utils/debugLog';
import './cards.css';

const debugLog = createLogger('SystemCard');

type DisplayMode = 'formatted' | 'raw';

interface SystemCardProps {
  turn: SessionDataTurn;
  sessionId?: string;
}

// System block type configuration
const SYSTEM_CONFIG: Record<string, { icon: string; label: string; className: string }> = {
  fork: { icon: '⑂', label: 'Fork', className: 'system-fork' },
  forked_from: { icon: '⤵', label: 'Forked From', className: 'system-forked-from' },
  merge: { icon: '⤴', label: 'Merge', className: 'system-merge' },
  merged_to: { icon: '⤴', label: 'Merged', className: 'system-merged-to' },
  link: { icon: '🔗', label: 'Link', className: 'system-link' },
  interruption: { icon: '⚠', label: 'Interrupted', className: 'system-interruption' },
  error: { icon: '✗', label: 'Error', className: 'system-error' },
  image: { icon: '🖼', label: 'Image', className: 'system-image' },
  slide: { icon: '📊', label: 'Slide', className: 'system-slide' },
  review: { icon: '📋', label: 'Review', className: 'system-review' },
  fork_proposal: { icon: '⑂', label: 'Fork Proposal', className: 'system-fork-proposal' },
  merge_proposal: { icon: '⤴', label: 'Merge Proposal', className: 'system-merge-proposal' },
  archive: { icon: '📦', label: 'Archive', className: 'system-archive' },
  session_summary: { icon: '📝', label: 'Session Summary', className: 'system-session-summary' },
  // Watcher mode blocks
  watch_start: { icon: '👁', label: 'Watching', className: 'system-watch-start' },
  watch_stop: { icon: '👁', label: 'Stopped Watching', className: 'system-watch-stop' },
  watch_summary: { icon: '📋', label: 'Summary', className: 'system-watch-summary' },
};

/**
 * Mode switcher component - allows toggling between formatted and raw views
 */
function ModeSwitcher({
  mode,
  onModeChange,
}: {
  mode: DisplayMode;
  onModeChange: (mode: DisplayMode) => void;
}) {
  const handleFormatted = (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    onModeChange('formatted');
  };

  const handleRaw = (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    onModeChange('raw');
  };

  return (
    <div className="turn-card-mode-switcher" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        className={`mode-btn ${mode === 'formatted' ? 'active' : ''}`}
        onClick={handleFormatted}
        title="Formatted view"
      >
        <span className="mode-icon">◈</span>
      </button>
      <button
        type="button"
        className={`mode-btn ${mode === 'raw' ? 'active' : ''}`}
        onClick={handleRaw}
        title="Raw JSON (debug)"
      >
        <span className="mode-icon">{'{}'}</span>
      </button>
    </div>
  );
}

/**
 * Raw JSON display for debugging - with syntax highlighting
 */
function RawDataDisplay({ data }: { data: unknown }) {
  const formatted = JSON.stringify(data, null, 2);
  return (
    <div className="turn-raw-data">
      <SyntaxHighlightedCode code={formatted} language="json" wrapLongLines />
    </div>
  );
}

// Extract the linked session ID for navigation (if applicable)
function getLinkedSessionId(block: SessionDataTurn['contentBlock']): string | null {
  if (!block) return null;

  switch (block.type) {
    case 'fork': {
      const b = block as ForkBlock;
      return b.childSessionId || null;
    }
    case 'forked_from': {
      const b = block as ForkedFromBlock;
      return b.parentSessionId || null;
    }
    case 'merge': {
      const b = block as MergeBlock;
      return b.childSessionId || null;
    }
    case 'merged_to': {
      const b = block as MergedToBlock;
      return b.parentSessionId || null;
    }
    case 'link': {
      const b = block as LinkBlock;
      return b.linkedSessionId || null;
    }
    case 'watch_start': {
      const b = block as WatchStartBlock;
      return b.targetSessionId || null;
    }
    case 'watch_stop': {
      const b = block as WatchStopBlock;
      return b.targetSessionId || null;
    }
    case 'watch_summary': {
      const b = block as WatchSummaryBlock;
      return b.targetSessionId || null;
    }
    default:
      return null;
  }
}

// Get the navigation button label for a block type
function getNavigationLabel(block: SessionDataTurn['contentBlock']): string | null {
  if (!block) return null;

  switch (block.type) {
    case 'fork':
      return 'Go to fork';
    case 'forked_from':
      return 'Go to parent';
    case 'merge':
      return 'Go to fork';
    case 'merged_to':
      return 'Go to parent';
    case 'link':
      return 'Go to linked session';
    case 'watch_start':
    case 'watch_stop':
    case 'watch_summary':
      return 'Go to target';
    default:
      return null;
  }
}

// Extract display content from different block types
function getDisplayContent(block: SessionDataTurn['contentBlock']): string {
  if (!block) return '';

  switch (block.type) {
    case 'fork': {
      const b = block as ForkBlock;
      return `**${b.forkName || 'Fork'}**\n\n${b.prompt || ''}`;
    }
    case 'forked_from': {
      const b = block as ForkedFromBlock;
      return `Forked from **${b.parentName}**\n\n${b.prompt || ''}`;
    }
    case 'merge': {
      const b = block as MergeBlock;
      let content = `**${b.forkName || 'Merge'}**\n\n${b.message || ''}`;
      if (b.filesChanged?.length) {
        content += `\n\n**Files changed:** ${b.filesChanged.join(', ')}`;
      }
      return content;
    }
    case 'merged_to': {
      const b = block as MergedToBlock;
      return `Merged to **${b.parentName}**\n\n${b.message || ''}`;
    }
    case 'link': {
      const b = block as LinkBlock;
      return b.summary || 'Linked session';
    }
    case 'error': {
      const b = block as ErrorBlock;
      const details = b.details || '';
      const dump = b.dumpFile ? `\n\nDebug dump: ${b.dumpFile}` : '';
      return `**${b.reason}**\n\n${details}${dump}`;
    }
    case 'interruption': {
      const b = block as InterruptionBlock;
      const labels: Record<string, string> = {
        user_cancelled: 'Cancelled by user',
        timeout: 'Timed out',
      };
      return labels[b.reason ?? ''] ?? b.reason ?? 'Cancelled by user';
    }
    case 'archive': {
      const b = block as ArchiveBlock;
      return b.summary || `Archived ${b.messageCount} messages`;
    }
    case 'slide': {
      const b = block as SlideBlock;
      return `## ${b.title || 'Slide'}\n\n${b.content || ''}`;
    }
    case 'review': {
      const b = block as ReviewBlock;
      return `Review of **${b.modelUnderReview}** (${b.status})`;
    }
    case 'fork_proposal': {
      const b = block as ForkProposalBlock;
      return `**${b.name || 'Fork'}** (${b.status})\n\n${b.description || ''}`;
    }
    case 'merge_proposal': {
      const b = block as MergeProposalBlock;
      return `Merge proposal (${b.status})\n\n${b.summary || ''}`;
    }
    case 'image': {
      const b = block as ImageBlock;
      return `![${b.filename || 'Image'}](${b.filePath})`;
    }
    case 'session_summary': {
      const b = block as SessionSummaryBlock;
      const title = b.approvedTitle || b.proposedTitle || 'Session Summary';
      const statusBadge = b.status === 'approved' ? '✓ Approved' : '⏳ Pending';
      let content = `## ${title}\n\n*${statusBadge}* | Generated by ${b.reviewedByBackend || 'unknown'}\n\n`;
      if (b.markdownContent) {
        content += b.markdownContent;
      } else {
        // Fall back to structured fields if no markdown
        if (b.workDone) {
          content += `**Summary:** ${b.workDone}\n\n`;
        }
        if (b.filesModified?.length) {
          content += `**Files Modified:**\n${b.filesModified.map(f => `- ${f}`).join('\n')}\n\n`;
        }
        if (b.decisionsMade?.length) {
          content += `**Decisions Made:**\n${b.decisionsMade.map(d => `- ${d}`).join('\n')}\n\n`;
        }
        if (b.nextSteps?.length) {
          content += `**Next Steps:**\n${b.nextSteps.map(n => `- ${n}`).join('\n')}\n\n`;
        }
        if (b.questionsRaised?.length) {
          content += `**Open Questions:**\n${b.questionsRaised.map(q => `- ${q}`).join('\n')}`;
        }
      }
      return content;
    }
    // Watcher mode blocks
    case 'watch_start': {
      const b = block as WatchStartBlock;
      return `Watching **${b.targetSessionName || 'session'}**`;
    }
    case 'watch_stop': {
      const b = block as WatchStopBlock;
      const reasonText = b.reason === 'user' ? 'stopped by user' :
                         b.reason === 'session_closed' ? 'session closed' :
                         b.reason === 'session_archived' ? 'session archived' :
                         b.reason || 'unknown';
      return `Stopped watching (${reasonText})`;
    }
    case 'watch_summary': {
      const b = block as WatchSummaryBlock;
      const exchangeNum = (b.exchangeIndex ?? 0) + 1;
      const header = `**Exchange ${exchangeNum}** from *${b.targetSessionName || 'target'}*`;
      return `${header}\n\n${b.summary || ''}`;
    }
    default:
      return '';
  }
}

export const SystemCard = React.memo(function SystemCard({ turn, sessionId }: SystemCardProps) {
  const { contentBlock, streaming, order, timestamp } = turn;
  const blockType = contentBlock?.type || 'unknown';
  const selectSession = useSelectSession();
  const client = useClient();

  // Display mode state - formatted (default) or raw JSON
  const [displayMode, setDisplayMode] = useState<DisplayMode>('formatted');
  const [isRehydrating, setIsRehydrating] = useState(false);

  const config = SYSTEM_CONFIG[blockType] || {
    icon: '📄',
    label: blockType,
    className: 'system-unknown',
  };

  const displayContent = getDisplayContent(contentBlock);
  const linkedSessionId = getLinkedSessionId(contentBlock);
  const navigationLabel = getNavigationLabel(contentBlock);

  // Handler for navigating to linked session
  const handleNavigate = useCallback(() => {
    if (linkedSessionId && selectSession) {
      selectSession(linkedSessionId);
    }
  }, [linkedSessionId, selectSession]);

  // Handler for rehydrating archive blocks
  const handleRehydrate = useCallback(async () => {
    if (!client || !sessionId || blockType !== 'archive' || typeof order !== 'number') {
      return;
    }
    setIsRehydrating(true);
    try {
      const result = await client.sessions.rehydrate(sessionId, order);
      if (!result.success) {
        console.error('Rehydrate failed:', result.error);
      }
    } catch (err) {
      console.error('Rehydrate error:', err);
    } finally {
      setIsRehydrating(false);
    }
  }, [client, sessionId, blockType, order]);

  // Render body content based on display mode
  const renderBody = () => {
    if (displayMode === 'raw') {
      return <RawDataDisplay data={turn} />;
    }

    // Images are rendered as real <img> elements backed by the auth'd uploads
    // route, not as markdown (a markdown href would be a server file path the
    // browser cannot load, and an <img src> cannot carry the auth header).
    if (blockType === 'image' && contentBlock) {
      return <ImageBlockView block={contentBlock as ImageBlock} />;
    }

    if (displayContent) {
      return <MarkdownContent content={displayContent} />;
    }

    return null;
  };

  const body = renderBody();
  const showNavigationButton = linkedSessionId && selectSession && navigationLabel;
  const showRehydrateButton = blockType === 'archive' && client && sessionId && typeof order === 'number';

  // Debug archive button visibility
  if (blockType === 'archive') {
    debugLog('archive block debug', {
      hasClient: !!client,
      sessionId,
      order,
      showRehydrateButton,
    });
  }

  return (
    <div className={`turn-card system-card ${config.className} ${streaming ? 'streaming' : ''} ${displayMode === 'raw' ? 'raw-mode' : ''}`}>
      <div className="turn-card-header">
        <span className="turn-order">{order}</span>
        <span className="turn-icon">{config.icon}</span>
        <span className="turn-label">{config.label}</span>
        {timestamp && <span className="turn-timestamp">{formatTimestamp(timestamp)}</span>}
        <ModeSwitcher mode={displayMode} onModeChange={setDisplayMode} />
      </div>
      {body && (
        <div className="turn-card-body">
          {body}
        </div>
      )}
      {(showNavigationButton || showRehydrateButton) && (
        <div className="turn-card-actions">
          {showNavigationButton && (
            <button
              className="btn btn-primary btn-small session-link-btn"
              onClick={handleNavigate}
              type="button"
            >
              {navigationLabel} →
            </button>
          )}
          {showRehydrateButton && (
            <button
              className="btn btn-secondary btn-small rehydrate-btn"
              onClick={handleRehydrate}
              type="button"
              disabled={isRehydrating}
              title="Restore archived turns"
            >
              {isRehydrating ? '⏳ Restoring...' : '↩ Restore'}
            </button>
          )}
        </div>
      )}
    </div>
  );
});
