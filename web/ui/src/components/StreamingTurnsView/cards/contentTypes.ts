/**
 * Content block types for card rendering
 *
 * Re-exports from generated types plus convenience utilities
 */

import type {
  TextBlock,
  MarkdownBlock,
  ImageBlock,
  ToolUseBlock,
  ToolResultBlock,
  InterruptionBlock,
  ErrorBlock,
  LinkBlock,
  ForkBlock,
  MergeBlock,
  MergedToBlock,
  ArchiveBlock,
  SlideBlock,
  ReviewBlock,
  ForkProposalBlock,
  MergeProposalBlock,
} from '../../../../../generated/types';

// Re-export individual block types
export type {
  TextBlock,
  MarkdownBlock,
  ImageBlock,
  ToolUseBlock,
  ToolResultBlock,
  InterruptionBlock,
  ErrorBlock,
  LinkBlock,
  ForkBlock,
  MergeBlock,
  MergedToBlock,
  ArchiveBlock,
  SlideBlock,
  ReviewBlock,
  ForkProposalBlock,
  MergeProposalBlock,
};

/**
 * Union of all content block types
 */
export type ContentBlock =
  | TextBlock
  | MarkdownBlock
  | ImageBlock
  | ToolUseBlock
  | ToolResultBlock
  | InterruptionBlock
  | ErrorBlock
  | LinkBlock
  | ForkBlock
  | MergeBlock
  | MergedToBlock
  | ArchiveBlock
  | SlideBlock
  | ReviewBlock
  | ForkProposalBlock
  | MergeProposalBlock;

/**
 * All possible content block type strings
 */
export type ContentBlockType =
  | 'text'
  | 'markdown'
  | 'image'
  | 'tool_use'
  | 'tool_result'
  | 'interruption'
  | 'error'
  | 'link'
  | 'fork'
  | 'merge'
  | 'merged_to'
  | 'archive'
  | 'slide'
  | 'review'
  | 'fork_proposal'
  | 'merge_proposal';

/**
 * Type guard to check if a block is of a specific type
 */
export function isBlockType<T extends ContentBlock>(
  block: ContentBlock | null | undefined,
  type: string
): block is T {
  return block !== null && block !== undefined && block.type === type;
}

// Specific type guards
export function isTextBlock(block: ContentBlock | null | undefined): block is TextBlock {
  return isBlockType(block, 'text');
}

export function isMarkdownBlock(block: ContentBlock | null | undefined): block is MarkdownBlock {
  return isBlockType(block, 'markdown');
}

export function isToolUseBlock(block: ContentBlock | null | undefined): block is ToolUseBlock {
  return isBlockType(block, 'tool_use');
}

export function isToolResultBlock(block: ContentBlock | null | undefined): block is ToolResultBlock {
  return isBlockType(block, 'tool_result');
}

export function isForkBlock(block: ContentBlock | null | undefined): block is ForkBlock {
  return isBlockType(block, 'fork');
}

export function isMergeBlock(block: ContentBlock | null | undefined): block is MergeBlock {
  return isBlockType(block, 'merge');
}

export function isMergedToBlock(block: ContentBlock | null | undefined): block is MergedToBlock {
  return isBlockType(block, 'merged_to');
}

export function isErrorBlock(block: ContentBlock | null | undefined): block is ErrorBlock {
  return isBlockType(block, 'error');
}

export function isImageBlock(block: ContentBlock | null | undefined): block is ImageBlock {
  return isBlockType(block, 'image');
}

export function isForkProposalBlock(block: ContentBlock | null | undefined): block is ForkProposalBlock {
  return isBlockType(block, 'fork_proposal');
}

export function isMergeProposalBlock(block: ContentBlock | null | undefined): block is MergeProposalBlock {
  return isBlockType(block, 'merge_proposal');
}
