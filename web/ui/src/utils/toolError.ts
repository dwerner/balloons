/**
 * Tool-error content helpers.
 *
 * When a tool errors, the Anthropic-style tool_result content is wrapped as
 *   <tool_use_error>File does not exist.</tool_use_error>
 * Historically the UI rendered that verbatim inside a large multi-line block.
 * Bug #21 asks for these to render as a compact single-line error message.
 *
 * These helpers are pure so they can be unit-tested independently of React.
 */

const TOOL_USE_ERROR_RE = /^\s*<tool_use_error>([\s\S]*?)<\/tool_use_error>\s*$/;

/**
 * If `content` is entirely a `<tool_use_error>…</tool_use_error>` wrapper,
 * return the trimmed inner message; otherwise return null.
 */
export function parseToolUseError(content: string | undefined | null): string | null {
  if (!content) return null;
  const match = content.match(TOOL_USE_ERROR_RE);
  if (!match) return null;
  const inner = (match[1] ?? '').trim();
  return inner.length > 0 ? inner : null;
}

/** Collapse newlines/whitespace so the message renders on a single line. */
export function singleLine(text: string): string {
  return text.replace(/\s+/g, ' ').trim();
}
