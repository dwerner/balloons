/**
 * LinkStashArea - Display area for link stash items near the message input
 *
 * Features:
 * - Shows stash items as clickable cards (click to navigate)
 * - Checkbox for selecting items to include in link
 * - Apply button to use single item immediately
 * - Remove button to delete from stash
 * - Hover/long-press for content preview
 * - Batch actions when items are checked
 */

import React, { useState, useCallback, memo } from 'react';
import type { LinkStashItem } from '../../hooks/useLinkStash';
import './LinkStashArea.css';

export interface LinkStashAreaProps {
  /** Items in the stash */
  items: LinkStashItem[];
  /** Number of checked items */
  checkedCount: number;
  /** Whether currently in Link send mode (enables selection/apply) */
  isLinkMode: boolean;
  /** Called when item checkbox is toggled */
  onToggleItem: (id: string) => void;
  /** Called when item should be removed from stash */
  onRemoveItem: (id: string) => void;
  /** Called when user clicks item to navigate */
  onNavigate: (sessionId: string, turnIndex: number) => void;
  /** Called when user wants to apply a single item immediately */
  onApplySingle: (item: LinkStashItem) => void;
  /** Called when user wants to clear all items */
  onClearAll: () => void;
  /** Whether the stash area is collapsed */
  collapsed?: boolean;
  /** Called when collapsed state changes */
  onCollapseChange?: (collapsed: boolean) => void;
}

/**
 * Single stash item card
 */
interface StashItemCardProps {
  item: LinkStashItem;
  isLinkMode: boolean;
  onToggle: () => void;
  onRemove: () => void;
  onNavigate: () => void;
  onApply: () => void;
}

const StashItemCard = memo(function StashItemCard({
  item,
  isLinkMode,
  onToggle,
  onRemove,
  onNavigate,
  onApply,
}: StashItemCardProps) {
  const [showPreview, setShowPreview] = useState(false);

  // Format turn range for display
  const turnRange =
    item.turnIndices.length === 1
      ? `turn ${item.turnIndices[0]}`
      : `turns ${item.turnIndices[0]}-${item.turnIndices[item.turnIndices.length - 1]}`;

  const handleCardClick = useCallback(
    (e: React.MouseEvent) => {
      // Don't navigate if clicking on a button
      if ((e.target as HTMLElement).closest('button')) {
        return;
      }
      onNavigate();
    },
    [onNavigate]
  );

  const handleCheckboxClick = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      onToggle();
    },
    [onToggle]
  );

  return (
    <div
      className={`link-stash-item ${item.checked ? 'link-stash-item--checked' : ''}`}
      onClick={handleCardClick}
      onMouseEnter={() => setShowPreview(true)}
      onMouseLeave={() => setShowPreview(false)}
      title="Click to navigate to source"
    >
      <button
        type="button"
        className={`link-stash-item__checkbox ${!isLinkMode ? 'link-stash-item__checkbox--disabled' : ''}`}
        onClick={handleCheckboxClick}
        disabled={!isLinkMode}
        aria-label={item.checked ? 'Unselect' : 'Select'}
        title={isLinkMode ? (item.checked ? 'Unselect' : 'Select for linking') : 'Switch to Link mode to select'}
      >
        {item.checked ? '●' : '○'}
      </button>

      <div className="link-stash-item__content">
        <div className="link-stash-item__header">
          <span className="link-stash-item__icon">🔗</span>
          <span className="link-stash-item__session">{item.sourceSessionName}</span>
          <span className="link-stash-item__range">{turnRange}</span>
        </div>
        <div className="link-stash-item__excerpt">{item.excerpt}</div>
      </div>

      <div className="link-stash-item__actions">
        {isLinkMode && (
          <button
            type="button"
            className="link-stash-item__apply"
            onClick={(e) => {
              e.stopPropagation();
              onApply();
            }}
            title="Apply this link now"
          >
            ↗
          </button>
        )}
        <button
          type="button"
          className="link-stash-item__remove"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          title="Remove from stash"
        >
          ×
        </button>
      </div>

      {/* Preview popover on hover */}
      {showPreview && item.excerpt.length > 50 && (
        <div className="link-stash-item__preview">
          <div className="link-stash-item__preview-header">
            {item.sourceSessionName} - {turnRange}
          </div>
          <div className="link-stash-item__preview-content">{item.excerpt}</div>
        </div>
      )}
    </div>
  );
});

/**
 * Main stash area component
 */
export const LinkStashArea = memo(function LinkStashArea({
  items,
  checkedCount,
  isLinkMode,
  onToggleItem,
  onRemoveItem,
  onNavigate,
  onApplySingle,
  onClearAll,
  collapsed = false,
  onCollapseChange,
}: LinkStashAreaProps) {
  // Hooks must run unconditionally; the empty guard lives below them.
  const handleToggleCollapse = useCallback(() => {
    onCollapseChange?.(!collapsed);
  }, [collapsed, onCollapseChange]);

  if (items.length === 0) {
    return null;
  }

  return (
    <div className={`link-stash-area ${collapsed ? 'link-stash-area--collapsed' : ''}`}>
      <div className="link-stash-area__header">
        <button
          type="button"
          className="link-stash-area__toggle"
          onClick={handleToggleCollapse}
          aria-label={collapsed ? 'Expand link stash' : 'Collapse link stash'}
        >
          <span className="link-stash-area__toggle-icon">
            {collapsed ? '▶' : '▼'}
          </span>
          <span className="link-stash-area__title">
            Link Stash ({items.length})
            {isLinkMode && checkedCount > 0 && (
              <span className="link-stash-area__selected">
                {' '}- {checkedCount} selected
              </span>
            )}
            {!isLinkMode && (
              <span className="link-stash-area__hint">
                {' '}- use Link mode to select
              </span>
            )}
          </span>
        </button>

        <div className="link-stash-area__batch-actions">
          <button
            type="button"
            className="link-stash-area__clear-btn"
            onClick={onClearAll}
            title="Clear all items"
          >
            Clear
          </button>
        </div>
      </div>

      {!collapsed && (
        <div className="link-stash-area__items">
          {items.map((item) => (
            <StashItemCard
              key={item.id}
              item={item}
              isLinkMode={isLinkMode}
              onToggle={() => onToggleItem(item.id)}
              onRemove={() => onRemoveItem(item.id)}
              onNavigate={() => onNavigate(item.sourceSessionId, item.turnIndices[0] ?? 0)}
              onApply={() => onApplySingle(item)}
            />
          ))}
        </div>
      )}
    </div>
  );
});

export default LinkStashArea;
