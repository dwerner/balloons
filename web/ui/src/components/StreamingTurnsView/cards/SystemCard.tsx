/**
 * SystemCard - Renders system-level content blocks
 *
 * Handles: fork, merge, merged_to, link, interruption, error,
 * image, slide, review, fork_proposal, merge_proposal, archive
 */

import React from 'react';
import { MarkdownContent } from '../../../MarkdownContent';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
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

export function SystemCard({ turn }: SystemCardProps) {
  const { content, contentBlockType, streaming } = turn;
  const blockType = contentBlockType || 'unknown';

  const config = SYSTEM_CONFIG[blockType] || {
    icon: '📄',
    label: blockType,
    className: 'system-unknown',
  };

  return (
    <div className={`turn-card system-card ${config.className} ${streaming ? 'streaming' : ''}`}>
      <div className="turn-card-header">
        <span className="turn-icon">{config.icon}</span>
        <span className="turn-label">{config.label}</span>
        {streaming && <span className="streaming-indicator">●</span>}
      </div>
      {content && (
        <div className="turn-card-body">
          <MarkdownContent content={content} />
        </div>
      )}
    </div>
  );
}
