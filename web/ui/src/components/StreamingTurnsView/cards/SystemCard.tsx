/**
 * SystemCard - Renders system-level content blocks
 *
 * Handles: fork, merge, merged_to, link, interruption, error,
 * image, slide, review, fork_proposal, merge_proposal, archive
 */

import React from 'react';
import { MarkdownContent } from '../../../MarkdownContent';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
import type {
  ForkBlock,
  MergeBlock,
  MergedToBlock,
  LinkBlock,
  ErrorBlock,
  InterruptionBlock,
  ArchiveBlock,
  SlideBlock,
  ReviewBlock,
  ForkProposalBlock,
  MergeProposalBlock,
  ImageBlock,
} from '../../../../../generated/types';
import './cards.css';

interface SystemCardProps {
  turn: SessionDataTurn;
}

// System block type configuration
const SYSTEM_CONFIG: Record<string, { icon: string; label: string; className: string }> = {
  fork: { icon: '⑂', label: 'Fork', className: 'system-fork' },
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
};

// Extract display content from different block types
function getDisplayContent(block: SessionDataTurn['contentBlock']): string {
  if (!block) return '';

  switch (block.type) {
    case 'fork': {
      const b = block as ForkBlock;
      return `**${b.forkName || 'Fork'}**\n\n${b.prompt || ''}`;
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
      return `**${b.reason}**\n\n${b.details || ''}`;
    }
    case 'interruption': {
      const b = block as InterruptionBlock;
      return b.reason || 'User cancelled';
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
    default:
      return '';
  }
}

export function SystemCard({ turn }: SystemCardProps) {
  const { contentBlock, streaming } = turn;
  const blockType = contentBlock?.type || 'unknown';

  const config = SYSTEM_CONFIG[blockType] || {
    icon: '📄',
    label: blockType,
    className: 'system-unknown',
  };

  const displayContent = getDisplayContent(contentBlock);

  return (
    <div className={`turn-card system-card ${config.className} ${streaming ? 'streaming' : ''}`}>
      <div className="turn-card-header">
        <span className="turn-icon">{config.icon}</span>
        <span className="turn-label">{config.label}</span>
        {streaming && <span className="streaming-indicator">●</span>}
      </div>
      {displayContent && (
        <div className="turn-card-body">
          <MarkdownContent content={displayContent} />
        </div>
      )}
    </div>
  );
}
