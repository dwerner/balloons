/**
 * Pure session-grouping helpers for the context tree.
 *
 * Extracted from SessionTreeView (and previously duplicated in HierarchyView)
 * so the pinned / watcher / date-grouping rules have a single source of truth
 * and can be characterized by unit tests.
 *
 * NOTE: grouping currently sorts by `lastModified`. See BUGS.md #7 — the
 * intended source of truth is the stored `modifiedAt` timestamp. The
 * characterization tests pin the *current* behaviour so a future switch is a
 * deliberate, visible change rather than a silent regression.
 */

import type { SessionInfo } from '../../../generated/balloons-client';

/** Format a timestamp into a human day-group label (Today / Yesterday / ...). */
export function formatDayGroup(dateStr: string): string {
  if (!dateStr) return 'Unknown';
  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return 'Unknown';
  const now = new Date();

  // Get start of today, yesterday, etc.
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfYesterday = new Date(startOfToday);
  startOfYesterday.setDate(startOfYesterday.getDate() - 1);
  const startOfThisWeek = new Date(startOfToday);
  startOfThisWeek.setDate(startOfThisWeek.getDate() - now.getDay());
  const startOfLastWeek = new Date(startOfThisWeek);
  startOfLastWeek.setDate(startOfLastWeek.getDate() - 7);

  if (date >= startOfToday) {
    return 'Today';
  } else if (date >= startOfYesterday) {
    return 'Yesterday';
  } else if (date >= startOfThisWeek) {
    // This week - show day name
    return date.toLocaleDateString(undefined, { weekday: 'long' });
  } else if (date >= startOfLastWeek) {
    return 'Last Week';
  } else {
    // Older - show month and year, or just month if same year
    const sameYear = date.getFullYear() === now.getFullYear();
    if (sameYear) {
      return date.toLocaleDateString(undefined, { month: 'long' });
    } else {
      return date.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
    }
  }
}

/** Stable YYYY-MM-DD key for grouping sessions by calendar day. */
export function getDayKey(dateStr: string): string {
  if (!dateStr) return '1970-01-01';
  const date = new Date(dateStr);
  // Check for invalid date
  if (isNaN(date.getTime())) return '1970-01-01';
  // Return YYYY-MM-DD format for consistent grouping
  return date.toISOString().split('T')[0] || '1970-01-01';
}

export interface WatcherGroup {
  target: SessionInfo | null;
  watchers: SessionInfo[];
  groupTime: number;
  targetName: string;
}

export interface DayGroup {
  key: string;
  label: string;
  sessions: SessionInfo[];
}

export interface GroupedSessions {
  pinned: SessionInfo[];
  watcherGroups: WatcherGroup[];
  dayGroups: DayGroup[];
}

/**
 * Group sessions into: pinned (top), watcher groups, and date-based day groups.
 *
 * Rules (pinned by tests):
 *  - Pinned sessions are pulled out first and sorted most-recent-first.
 *  - Unpinned sessions that watch a target are grouped under that target.
 *  - Remaining sessions are bucketed by day label, each bucket sorted
 *    most-recent-first, buckets ordered most-recent-first, "Unknown" last.
 */
export function groupSessions(sessions: SessionInfo[]): GroupedSessions {
  // Separate pinned and unpinned sessions
  const pinned = sessions.filter(s => s.isPinned);
  const unpinned = sessions.filter(s => !s.isPinned);

  // Sort pinned by last modified (most recent first)
  pinned.sort((a, b) => {
    return new Date(b.lastModified).getTime() - new Date(a.lastModified).getTime();
  });

  // Identify watcher sessions from persisted watcher relationships, not title prefixes.
  const watcherGroups: WatcherGroup[] = [];
  const usedSessionIds = new Set<string>();
  const sessionsById = new Map(unpinned.map(session => [session.id, session]));
  const targetIdToWatchers = new Map<string, SessionInfo[]>();

  for (const session of unpinned) {
    const targets = session.watchTargets || [];
    if (targets.length === 0) continue;
    for (const targetId of targets) {
      if (!targetIdToWatchers.has(targetId)) {
        targetIdToWatchers.set(targetId, []);
      }
      targetIdToWatchers.get(targetId)!.push(session);
    }
  }

  for (const [targetId, watchers] of targetIdToWatchers) {
    const targetSession = sessionsById.get(targetId) || null;
    const targetName = targetSession?.title || targetSession?.forkName || targetId.slice(0, 8);

    let groupTime = targetSession ? new Date(targetSession.lastModified).getTime() : 0;
    if (targetSession) {
      usedSessionIds.add(targetSession.id);
    }

    for (const watcher of watchers) {
      const watcherTime = new Date(watcher.lastModified).getTime();
      if (watcherTime > groupTime) groupTime = watcherTime;
      usedSessionIds.add(watcher.id);
    }

    watchers.sort((a, b) =>
      new Date(b.lastModified).getTime() - new Date(a.lastModified).getTime()
    );

    watcherGroups.push({ target: targetSession, watchers, groupTime, targetName });
  }

  // Sort groups by most recent activity
  watcherGroups.sort((a, b) => b.groupTime - a.groupTime);

  // Separate regular sessions (not in any watcher group)
  const regularUnpinned: SessionInfo[] = [];
  for (const session of unpinned) {
    if (!usedSessionIds.has(session.id)) {
      regularUnpinned.push(session);
    }
  }

  // Group regular unpinned by day label first, THEN sort within groups.
  // This ensures all "Today" sessions are together even if isCurrent bumps one
  // to the top.
  const dayGroupMap = new Map<string, { key: string; label: string; sessions: SessionInfo[]; sortKey: number }>();

  for (const session of regularUnpinned) {
    const dayKey = getDayKey(session.lastModified);
    const label = formatDayGroup(session.lastModified);

    if (!dayGroupMap.has(label)) {
      dayGroupMap.set(label, {
        key: dayKey,
        label,
        sessions: [],
        sortKey: new Date(dayKey).getTime(),
      });
    }
    dayGroupMap.get(label)!.sessions.push(session);
  }

  // Sort sessions within each group by last modified (most recent first)
  for (const group of dayGroupMap.values()) {
    group.sessions.sort((a, b) => {
      return new Date(b.lastModified).getTime() - new Date(a.lastModified).getTime();
    });
    // Update sortKey to be the most recent session in the group
    const mostRecent = group.sessions[0];
    if (mostRecent) {
      group.sortKey = new Date(mostRecent.lastModified).getTime();
    }
  }

  // Sort groups by their most recent session (descending - most recent first).
  // "Unknown" group always goes to the bottom.
  const dayGroups: DayGroup[] = Array.from(dayGroupMap.values())
    .sort((a, b) => {
      // Unknown always goes last
      if (a.label === 'Unknown') return 1;
      if (b.label === 'Unknown') return -1;
      // Handle NaN sortKeys (treat as very old)
      const aKey = isNaN(a.sortKey) ? 0 : a.sortKey;
      const bKey = isNaN(b.sortKey) ? 0 : b.sortKey;
      return bKey - aKey;
    })
    .map(({ key, label, sessions }) => ({ key, label, sessions }));

  return { pinned, watcherGroups, dayGroups };
}