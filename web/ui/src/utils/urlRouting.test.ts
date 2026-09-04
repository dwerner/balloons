import { describe, it, expect } from 'bun:test';
import {
  parseRoute,
  formatSessionRoute,
  formatGlobalRoute,
  matchSessionId,
  isSessionTab,
  isGlobalTab,
} from './urlRouting';

describe('parseRoute', () => {
  it('treats empty / bare hashes as default', () => {
    expect(parseRoute('')).toEqual({ kind: 'default' });
    expect(parseRoute('#')).toEqual({ kind: 'default' });
    expect(parseRoute('#/')).toEqual({ kind: 'default' });
    expect(parseRoute('#/sessions')).toEqual({ kind: 'default' });
  });

  it('parses a session route with default streaming tab', () => {
    expect(parseRoute('#/sessions/abc123')).toEqual({
      kind: 'session',
      sessionId: 'abc123',
      tab: 'streaming',
    });
  });

  it('parses a session route with an explicit tab', () => {
    expect(parseRoute('#/sessions/abc123/context')).toEqual({
      kind: 'session',
      sessionId: 'abc123',
      tab: 'context',
    });
    expect(parseRoute('#/sessions/abc123/properties')).toEqual({
      kind: 'session',
      sessionId: 'abc123',
      tab: 'properties',
    });
  });

  it('falls back to streaming for an unknown tab but keeps the session', () => {
    expect(parseRoute('#/sessions/abc123/bogus')).toEqual({
      kind: 'session',
      sessionId: 'abc123',
      tab: 'streaming',
    });
  });

  it('tolerates a missing leading slash', () => {
    expect(parseRoute('#sessions/abc123/context')).toEqual({
      kind: 'session',
      sessionId: 'abc123',
      tab: 'context',
    });
  });

  it('returns default for unimplemented route families', () => {
    expect(parseRoute('#/goals/g1')).toEqual({ kind: 'default' });
    expect(parseRoute('#/sessions/abc123/turn/5')).toEqual({
      kind: 'session',
      sessionId: 'abc123',
      tab: 'streaming',
    });
    expect(parseRoute('#/bogus')).toEqual({ kind: 'default' });
  });

  it('parses app-global tab routes', () => {
    expect(parseRoute('#/code')).toEqual({ kind: 'global', tab: 'code' });
    expect(parseRoute('#/logs')).toEqual({ kind: 'global', tab: 'logs' });
    expect(parseRoute('#/llm')).toEqual({ kind: 'global', tab: 'llm' });
    expect(parseRoute('#/settings')).toEqual({ kind: 'global', tab: 'settings' });
    expect(parseRoute('#/surveys')).toEqual({ kind: 'global', tab: 'surveys' });
  });

  it('tolerates a missing leading slash on a global tab', () => {
    expect(parseRoute('#settings')).toEqual({ kind: 'global', tab: 'settings' });
  });
});

describe('formatSessionRoute', () => {
  it('omits the sub-route for the streaming tab', () => {
    expect(formatSessionRoute('abc123', 'streaming')).toBe('#/sessions/abc123');
  });

  it('includes the sub-route for other session tabs', () => {
    expect(formatSessionRoute('abc123', 'context')).toBe('#/sessions/abc123/context');
    expect(formatSessionRoute('abc123', 'slides')).toBe('#/sessions/abc123/slides');
  });

  it('returns the default hash for an empty id', () => {
    expect(formatSessionRoute('', 'context')).toBe('#/');
  });

  it('round-trips through parseRoute', () => {
    for (const tab of ['streaming', 'context', 'properties', 'slides'] as const) {
      const hash = formatSessionRoute('sess-xyz', tab);
      expect(parseRoute(hash)).toEqual({ kind: 'session', sessionId: 'sess-xyz', tab });
    }
  });
});

describe('formatGlobalRoute', () => {
  it('builds a "#/<tab>" hash', () => {
    expect(formatGlobalRoute('code')).toBe('#/code');
    expect(formatGlobalRoute('settings')).toBe('#/settings');
  });

  it('round-trips through parseRoute', () => {
    for (const tab of ['code', 'logs', 'llm', 'settings', 'surveys'] as const) {
      expect(parseRoute(formatGlobalRoute(tab))).toEqual({ kind: 'global', tab });
    }
  });
});

describe('matchSessionId', () => {
  const ids = ['abc123-def456', 'abc999-000', 'zzz-111'];

  it('prefers an exact match', () => {
    expect(matchSessionId('abc123-def456', ids)).toBe('abc123-def456');
  });

  it('resolves a unique prefix', () => {
    expect(matchSessionId('zzz', ids)).toBe('zzz-111');
    expect(matchSessionId('abc999', ids)).toBe('abc999-000');
  });

  it('returns null for an ambiguous prefix', () => {
    expect(matchSessionId('abc', ids)).toBeNull();
  });

  it('returns null for no match or empty prefix', () => {
    expect(matchSessionId('nope', ids)).toBeNull();
    expect(matchSessionId('', ids)).toBeNull();
  });
});

describe('isSessionTab', () => {
  it('accepts known session tabs', () => {
    expect(isSessionTab('streaming')).toBe(true);
    expect(isSessionTab('context')).toBe(true);
    expect(isSessionTab('properties')).toBe(true);
    expect(isSessionTab('slides')).toBe(true);
  });

  it('rejects global tabs and unknown values', () => {
    expect(isSessionTab('code')).toBe(false);
    expect(isSessionTab('logs')).toBe(false);
    expect(isSessionTab(undefined)).toBe(false);
  });
});

describe('isGlobalTab', () => {
  it('accepts known global tabs', () => {
    expect(isGlobalTab('code')).toBe(true);
    expect(isGlobalTab('logs')).toBe(true);
    expect(isGlobalTab('llm')).toBe(true);
    expect(isGlobalTab('settings')).toBe(true);
    expect(isGlobalTab('surveys')).toBe(true);
  });

  it('rejects session tabs and unknown values', () => {
    expect(isGlobalTab('streaming')).toBe(false);
    expect(isGlobalTab('context')).toBe(false);
    expect(isGlobalTab('sessions')).toBe(false);
    expect(isGlobalTab(undefined)).toBe(false);
  });
});