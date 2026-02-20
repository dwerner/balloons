/**
 * Card components for StreamingTurnsView
 *
 * Each card type handles a specific content block type with appropriate
 * rendering and streaming state visualization.
 *
 * Tool-specific cards extend BaseToolCard for consistent structure:
 * - ReadCard: File reading with compact path display
 * - EditCard: Diff-focused file editing
 * - WriteCard: File creation/writing
 * - BashCard: Command execution
 * - GrepCard: Search pattern + results
 * - GlobCard: File pattern matching
 * - GenericToolCard: Fallback for unknown tools
 */

// Main dispatcher
export { TurnCard, type TurnCardProps } from './TurnCard';

// Client context for interactive cards
export { ClientContext, useClient, useRequiredClient } from './ClientContext';

// Base components
export { TextCard } from './TextCard';
export { ToolResultCard } from './ToolResultCard';
export { SystemCard } from './SystemCard';
export { BaseToolCard, type BaseToolCardProps, type ToolPhase } from './BaseToolCard';

// Interactive proposal cards
export { ForkProposalCard } from './ForkProposalCard';
export { MergeProposalCard } from './MergeProposalCard';
export { ContextPlanTree, type ContextAssignment } from './ContextPlanTree';

// Tool-specific cards
export { ReadCard } from './ReadCard';
export { EditCard } from './EditCard';
export { WriteCard } from './WriteCard';
export { BashCard } from './BashCard';
export { GrepCard } from './GrepCard';
export { GlobCard } from './GlobCard';
export { GenericToolCard } from './GenericToolCard';

// Syntax highlighting utilities
export {
  SyntaxHighlightedCode,
  DiffHighlightedCode,
  GrepHighlightedResults,
  getLanguageFromPath,
} from './SyntaxHighlighter';

// Legacy - kept for backwards compatibility but not used in new code
export { ToolUseCard } from './ToolUseCard';

// Re-export content types for convenience
export type {
  ContentBlock,
  ContentBlockType,
  TextBlock,
  ToolUseBlock,
  ToolResultBlock,
  ImageBlock,
  ForkBlock,
  MergeBlock,
  MergedToBlock,
  LinkBlock,
  InterruptionBlock,
  ErrorBlock,
  ArchiveBlock,
  SlideBlock,
  ReviewBlock,
  ForkProposalBlock,
  MergeProposalBlock,
} from './contentTypes';

export {
  isTextBlock,
  isToolUseBlock,
  isToolResultBlock,
  isForkBlock,
  isMergeBlock,
  isMergedToBlock,
  isErrorBlock,
  isImageBlock,
  isForkProposalBlock,
  isMergeProposalBlock,
} from './contentTypes';
