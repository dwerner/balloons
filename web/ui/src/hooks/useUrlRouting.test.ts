import { describe, it, expect, afterEach, beforeEach } from 'bun:test';
import { renderHook, act, cleanup } from '@testing-library/react';
import { useUrlRouting } from './useUrlRouting';

afterEach(cleanup);

beforeEach(() => {
  // Reset to a clean hash before each test.
  window.history.replaceState(null, '', '#/');
});

describe('useUrlRouting', () => {
  it('seeds initialRoute from the hash at mount', () => {
    window.history.replaceState(null, '', '#/sessions/abc123/context');
    const { result } = renderHook(() => useUrlRouting());
    expect(result.current.initialRoute).toEqual({
      kind: 'session',
      sessionId: 'abc123',
      tab: 'context',
    });
  });

  it('replaceSession writes the hash without firing a reactive route change', () => {
    const { result } = renderHook(() => useUrlRouting());
    act(() => {
      result.current.replaceSession('sess-9', 'properties');
    });
    expect(window.location.hash).toBe('#/sessions/sess-9/properties');
    // replaceState emits no event, so currentRoute stays at its mount value.
    expect(result.current.currentRoute).toEqual({ kind: 'default' });
  });

  it('replaceSession is a no-op when the hash already matches', () => {
    window.history.replaceState(null, '', '#/sessions/sess-9');
    const { result } = renderHook(() => useUrlRouting());
    const before = window.history.length;
    act(() => {
      result.current.replaceSession('sess-9', 'streaming');
    });
    expect(window.location.hash).toBe('#/sessions/sess-9');
    expect(window.history.length).toBe(before);
  });

  it('currentRoute updates on hashchange', () => {
    const { result } = renderHook(() => useUrlRouting());
    expect(result.current.currentRoute).toEqual({ kind: 'default' });

    act(() => {
      // Simulate a user edit / back-nav: change the hash and dispatch the event.
      window.history.replaceState(null, '', '#/sessions/zzz/slides');
      window.dispatchEvent(new HashChangeEvent('hashchange'));
    });

    expect(result.current.currentRoute).toEqual({
      kind: 'session',
      sessionId: 'zzz',
      tab: 'slides',
    });
  });

  it('currentRoute updates on popstate', () => {
    const { result } = renderHook(() => useUrlRouting());
    act(() => {
      window.history.replaceState(null, '', '#/sessions/qqq');
      window.dispatchEvent(new PopStateEvent('popstate'));
    });
    expect(result.current.currentRoute).toEqual({
      kind: 'session',
      sessionId: 'qqq',
      tab: 'streaming',
    });
  });

  it('onNavigate fires on popstate/hashchange with the parsed route', () => {
    const calls: unknown[] = [];
    renderHook(() => useUrlRouting((r) => calls.push(r)));

    act(() => {
      window.history.replaceState(null, '', '#/sessions/nav1/context');
      window.dispatchEvent(new HashChangeEvent('hashchange'));
    });
    act(() => {
      window.history.replaceState(null, '', '#/sessions/nav2');
      window.dispatchEvent(new PopStateEvent('popstate'));
    });

    expect(calls).toEqual([
      { kind: 'session', sessionId: 'nav1', tab: 'context' },
      { kind: 'session', sessionId: 'nav2', tab: 'streaming' },
    ]);
  });

  it('onNavigate is NOT called by replaceSession (no feedback loop)', () => {
    const calls: unknown[] = [];
    const { result } = renderHook(() => useUrlRouting((r) => calls.push(r)));
    act(() => {
      result.current.replaceSession('mirror1', 'slides');
    });
    expect(window.location.hash).toBe('#/sessions/mirror1/slides');
    expect(calls).toHaveLength(0);
  });

  it('replaceGlobalTab writes the hash without firing a reactive route change', () => {
    const { result } = renderHook(() => useUrlRouting());
    act(() => {
      result.current.replaceGlobalTab('settings');
    });
    expect(window.location.hash).toBe('#/settings');
    // replaceState emits no event, so currentRoute stays at its mount value.
    expect(result.current.currentRoute).toEqual({ kind: 'default' });
  });

  it('onNavigate is NOT called by replaceGlobalTab (no feedback loop)', () => {
    const calls: unknown[] = [];
    const { result } = renderHook(() => useUrlRouting((r) => calls.push(r)));
    act(() => {
      result.current.replaceGlobalTab('code');
    });
    expect(window.location.hash).toBe('#/code');
    expect(calls).toHaveLength(0);
  });

  it('currentRoute + onNavigate update on hashchange to a global route', () => {
    const calls: unknown[] = [];
    const { result } = renderHook(() => useUrlRouting((r) => calls.push(r)));
    act(() => {
      window.history.replaceState(null, '', '#/logs');
      window.dispatchEvent(new HashChangeEvent('hashchange'));
    });
    expect(result.current.currentRoute).toEqual({ kind: 'global', tab: 'logs' });
    expect(calls).toEqual([{ kind: 'global', tab: 'logs' }]);
  });
});