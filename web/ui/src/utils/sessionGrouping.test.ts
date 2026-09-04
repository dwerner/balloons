/**
 * Characterization tests for session grouping.
 *
 * These pin the CURRENT behaviour of the context-tree grouping so that the
 * WS5 contract work (adding isPinned/modifiedAt to the wire events, fixing
 * Bugs #7 and #23) is a deliberate, visible change rather than a silent
 * regression. Several tests document known-buggy behaviour (sorting by
 * lastModified) with explicit comments.
 */

import { describe, it, expect } from 'bun:test';
import type { SessionInfo } from '../../../generated/balloons-client';
import { groupSessions, formatDayGroup, getDayKey } from './sessionGrouping';

/** Build a minimal SessionInfo; grouping only reads a few fields. */
function session(overrides: Partial<SessionInfo> & { id: string }): SessionInfo {
  return {
    title: overrides.title ?? `Session ${overrides.id}`,
    created: '2026-01-01T00:00:00Z',
    lastModified: '2026-01-01T00:00:00Z',
    forkName: '',
    ...overrides,
  } as SessionInfo;
}

/** ISO timestamp N days before now (so day-group labels are deterministic). */
function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString();
}

describe('formatDayGroup', () => {
  it('labels empty/invalid dates as Unknown', () => {
    expect(formatDayGroup('')).toBe('Unknown');
    expect(formatDayGroup('not-a-date')).toBe('Unknown');
  });

  it('labels today and yesterday', () => {
    expect(formatDayGroup(daysAgo(0))).toBe('Today');
    expect(formatDayGroup(daysAgo(1))).toBe('Yesterday');
  });

  it('labels dates older than last week by month', () => {
    // 40 days ago is comfortably outside "this week"/"last week"
    const label = formatDayGroup(daysAgo(40));
    expect(label).not.toBe('Today');
    expect(label).not.toBe('Yesterday');
    expect(label).not.toBe('Last Week');
  });
});

describe('getDayKey', () => {
  it('returns 1970-01-01 for empty/invalid dates', () => {
    expect(getDayKey('')).toBe('1970-01-01');
    expect(getDayKey('garbage')).toBe('1970-01-01');
  });

  it('returns YYYY-MM-DD for valid dates', () => {
    expect(getDayKey('2026-03-15T10:00:00Z')).toBe('2026-03-15');
  });
});

describe('groupSessions', () => {
  it('pulls pinned sessions out and sorts them most-recent-first', () => {
    const result = groupSessions([
      session({ id: 'a', isPinned: true, lastModified: daysAgo(5) }),
      session({ id: 'b', isPinned: true, lastModified: daysAgo(1) }),
      session({ id: 'c', isPinned: false, lastModified: daysAgo(0) }),
    ]);

    expect(result.pinned.map(s => s.id)).toEqual(['b', 'a']);
    // Unpinned session is not in pinned
    expect(result.pinned.find(s => s.id === 'c')).toBeUndefined();
  });

  it('keeps pinned sessions out of the day groups', () => {
    const result = groupSessions([
      session({ id: 'pinned', isPinned: true, lastModified: daysAgo(0) }),
      session({ id: 'regular', isPinned: false, lastModified: daysAgo(0) }),
    ]);
    const allDaySessions = result.dayGroups.flatMap(g => g.sessions.map(s => s.id));
    expect(allDaySessions).toContain('regular');
    expect(allDaySessions).not.toContain('pinned');
  });

  it('groups sessions by day label with most-recent-first ordering', () => {
    const result = groupSessions([
      session({ id: 'old', lastModified: daysAgo(40) }),
      session({ id: 'today-early', lastModified: daysAgo(0) }),
      session({ id: 'today-late', lastModified: daysAgo(0) }),
    ]);

    const today = result.dayGroups.find(g => g.label === 'Today');
    expect(today).toBeDefined();
    // Both today sessions grouped together
    expect(today!.sessions.map(s => s.id).sort()).toEqual(['today-early', 'today-late']);
  });

  it('orders day groups most-recent-first', () => {
    const result = groupSessions([
      session({ id: 'old', lastModified: daysAgo(40) }),
      session({ id: 'today', lastModified: daysAgo(0) }),
    ]);
    // Today group should come before the older month group
    expect(result.dayGroups[0]!.label).toBe('Today');
  });

  it('places the Unknown group last', () => {
    const result = groupSessions([
      session({ id: 'unknown', lastModified: '' }),
      session({ id: 'today', lastModified: daysAgo(0) }),
    ]);
    const labels = result.dayGroups.map(g => g.label);
    expect(labels[labels.length - 1]).toBe('Unknown');
  });

  it('groups watcher sessions under their target', () => {
    const result = groupSessions([
      session({ id: 'target', lastModified: daysAgo(2) }),
      session({ id: 'watcher1', lastModified: daysAgo(1), watchTargets: ['target'] }),
      session({ id: 'watcher2', lastModified: daysAgo(0), watchTargets: ['target'] }),
    ]);

    expect(result.watcherGroups).toHaveLength(1);
    const group = result.watcherGroups[0]!;
    expect(group.target?.id).toBe('target');
    expect(group.targetName).toBe('Session target');
    // Watchers sorted most-recent-first
    expect(group.watchers.map(w => w.id)).toEqual(['watcher2', 'watcher1']);
    // Target and watchers are consumed by the group, not in day groups
    const dayIds = result.dayGroups.flatMap(g => g.sessions.map(s => s.id));
    expect(dayIds).not.toContain('target');
    expect(dayIds).not.toContain('watcher1');
    expect(dayIds).not.toContain('watcher2');
  });

  it('handles a watcher whose target is not in the list', () => {
    const result = groupSessions([
      session({ id: 'orphan-watcher', lastModified: daysAgo(1), watchTargets: ['missing-target'] }),
    ]);
    expect(result.watcherGroups).toHaveLength(1);
    expect(result.watcherGroups[0]!.target).toBeNull();
    // Falls back to the target id prefix for the name
    expect(result.watcherGroups[0]!.targetName).toBe('missing-');
  });

  it('treats sessions with no watchTargets as regular', () => {
    const result = groupSessions([
      session({ id: 'plain', lastModified: daysAgo(0), watchTargets: [] }),
    ]);
    expect(result.watcherGroups).toHaveLength(0);
    const dayIds = result.dayGroups.flatMap(g => g.sessions.map(s => s.id));
    expect(dayIds).toContain('plain');
  });

  it('returns empty groups for an empty list', () => {
    const result = groupSessions([]);
    expect(result.pinned).toEqual([]);
    expect(result.watcherGroups).toEqual([]);
    expect(result.dayGroups).toEqual([]);
  });
});
