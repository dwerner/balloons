/**
 * Type definitions for the Code Tab code review system.
 *
 * Note: DiffFile, DiffHunk, DiffChange, and GitDiffResult are imported from
 * the generated balloons-client types. This file only defines the local
 * CodeReview types.
 */

/**
 * A code review comment attached to a specific location in code.
 */
export interface CodeReviewComment {
  /** Unique identifier for this comment */
  id: string;
  /** Absolute path to the file */
  file_path: string;
  /** Starting line number (1-indexed) */
  line_start: number;
  /** Ending line number for multi-line selections (1-indexed, optional) */
  line_end?: number;
  /** User's freeform comment text */
  comment: string;

  /** Whether this is from a diff or a file reference */
  context_type: 'diff' | 'file_reference';
  /** The actual code lines being commented on */
  context_lines: string[];

  /** For diffs only: the full hunk containing this change */
  diff_hunk?: string;
  /** For diffs only: type of change */
  change_type?: 'add' | 'delete' | 'modify' | 'context';
}

/**
 * A complete code review containing multiple comments.
 */
export interface CodeReview {
  /** Unique identifier for this review */
  id: string;
  /** All comments in the review */
  comments: CodeReviewComment[];
  /** When the review was started */
  created_at: string;
}

/**
 * State of the review workflow.
 */
export interface ReviewState {
  /** Whether review mode is active */
  active: boolean;
  /** The current review (null if not active) */
  review: CodeReview | null;
}
