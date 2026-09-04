import { describe, it, expect } from 'bun:test';
import { parseToolUseError, singleLine } from './toolError';

describe('parseToolUseError', () => {
  it('extracts the inner message from a tool_use_error wrapper', () => {
    expect(parseToolUseError('<tool_use_error>File does not exist.</tool_use_error>'))
      .toBe('File does not exist.');
  });

  it('trims surrounding whitespace and inner whitespace', () => {
    expect(parseToolUseError('  <tool_use_error>  Boom  </tool_use_error>  '))
      .toBe('Boom');
  });

  it('handles multi-line inner content', () => {
    expect(parseToolUseError('<tool_use_error>line one\nline two</tool_use_error>'))
      .toBe('line one\nline two');
  });

  it('returns null for non-wrapped content', () => {
    expect(parseToolUseError('just some output')).toBeNull();
  });

  it('returns null when wrapper is only part of the content', () => {
    expect(parseToolUseError('prefix <tool_use_error>x</tool_use_error> suffix')).toBeNull();
  });

  it('returns null for an empty wrapper', () => {
    expect(parseToolUseError('<tool_use_error></tool_use_error>')).toBeNull();
    expect(parseToolUseError('<tool_use_error>   </tool_use_error>')).toBeNull();
  });

  it('returns null for empty/undefined/null input', () => {
    expect(parseToolUseError('')).toBeNull();
    expect(parseToolUseError(undefined)).toBeNull();
    expect(parseToolUseError(null)).toBeNull();
  });
});

describe('singleLine', () => {
  it('collapses newlines and runs of whitespace into single spaces', () => {
    expect(singleLine('a\n\nb   c')).toBe('a b c');
  });

  it('trims leading/trailing whitespace', () => {
    expect(singleLine('  hi  ')).toBe('hi');
  });
});
