/**
 * ToolResultCard rendering tests (Bug #21).
 *
 * A tool_result whose content is a <tool_use_error>…</tool_use_error> wrapper
 * must render as a compact single-line error (message only), not a large
 * multi-line block containing the raw wrapper tags.
 */

import { describe, it, expect, afterEach } from 'bun:test';
import { render, screen, cleanup } from '@testing-library/react';
import { ToolResultCard } from './ToolResultCard';
import type { SessionDataTurn } from '../../../hooks/useSessionData';

function turnWithResult(content: string, isError = false): SessionDataTurn {
  return {
    turnId: 't1',
    order: 0,
    role: 'tool',
    contentBlock: { type: 'tool_result', toolUseId: 'u1', content, isError },
    streaming: false,
    viewed: false,
    tokens: 0,
    contextMode: 'copy',
  } as unknown as SessionDataTurn;
}

afterEach(cleanup);

describe('ToolResultCard tool_use_error rendering', () => {
  it('renders the inner message as a single line without the raw wrapper', () => {
    render(<ToolResultCard turn={turnWithResult('<tool_use_error>File does not exist.</tool_use_error>')} />);

    expect(screen.getByText('File does not exist.')).toBeTruthy();
    // The raw wrapper tags must not leak into the rendered output.
    expect(screen.queryByText(/<tool_use_error>/)).toBeNull();
    expect(document.querySelector('.tool-result-error-line')).not.toBeNull();
  });

  it('collapses a multi-line error onto one line', () => {
    render(<ToolResultCard turn={turnWithResult('<tool_use_error>line one\nline two</tool_use_error>')} />);
    expect(screen.getByText('line one line two')).toBeTruthy();
  });

  it('renders normal (non-error) results in the output block, not the error line', () => {
    render(<ToolResultCard turn={turnWithResult('all good')} />);
    expect(screen.getByText('all good')).toBeTruthy();
    expect(document.querySelector('.tool-result-error-line')).toBeNull();
  });
});
