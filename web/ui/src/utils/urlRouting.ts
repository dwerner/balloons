/**
 * URL routing (hash-based) — pure parsing/formatting helpers.
 *
 * Implements the session-route slice of docs/specs/url-routing.md:
 *
 *   #/                              default (last active session / picker)
 *   #/sessions/:sessionId           specific session, streaming tab
 *   #/sessions/:sessionId/:tab      specific session + session tab
 *
 * Session IDs support prefix matching (see matchSessionId): a shared link like
 * `#/sessions/abc` resolves to the full id `abc123-def456-...` once the session
 * list is known.
 *
 * Other route families from the spec (goals, global tabs, turns) are intentionally
 * NOT implemented yet; they parse to `default` so unknown hashes fall back to the
 * existing selection logic rather than blanking the view. This module is pure and
 * side-effect free so the logic is unit-testable without a DOM.
 */

/** Session-scoped tabs that map onto a URL sub-route. */
export type SessionTab = 'streaming' | 'context' | 'properties' | 'slides';

export const SESSION_TABS: readonly SessionTab[] = [
  'streaming',
  'context',
  'properties',
  'slides',
];

export function isSessionTab(value: string | undefined): value is SessionTab {
  return value !== undefined && (SESSION_TABS as readonly string[]).includes(value);
}

export type Route =
  | { kind: 'default' }
  | { kind: 'session'; sessionId: string; tab: SessionTab };

/**
 * Parse a raw `window.location.hash` (e.g. "#/sessions/abc/context") into a Route.
 * Leading '#' and a missing leading slash are tolerated. Unrecognized paths
 * (including not-yet-implemented route families) return `default`.
 */
export function parseRoute(hash: string): Route {
  // Strip the leading '#', then normalize to a leading slash.
  let path = (hash || '').replace(/^#/, '');
  if (!path.startsWith('/')) path = '/' + path;

  const segments = path.split('/').filter((s) => s.length > 0);

  // "#/", "", "#/sessions" (bare) → default.
  if (segments.length === 0) return { kind: 'default' };
  if (segments[0] !== 'sessions') return { kind: 'default' };

  const sessionId = segments[1];
  if (!sessionId) return { kind: 'default' };

  const rawTab = segments[2];
  const tab: SessionTab = isSessionTab(rawTab) ? rawTab : 'streaming';
  return { kind: 'session', sessionId, tab };
}

/**
 * Build a hash for a session + tab. The default 'streaming' tab omits the
 * sub-route so the common case stays short (#/sessions/:id).
 */
export function formatSessionRoute(sessionId: string, tab: SessionTab): string {
  if (!sessionId) return '#/';
  return tab === 'streaming'
    ? `#/sessions/${sessionId}`
    : `#/sessions/${sessionId}/${tab}`;
}

/**
 * Resolve a (possibly partial) session id against known ids.
 * - exact match wins
 * - otherwise a unique prefix match wins
 * - ambiguous or no match → null (caller falls back to default selection)
 */
export function matchSessionId(prefix: string, ids: readonly string[]): string | null {
  if (!prefix) return null;
  const exact = ids.find((id) => id === prefix);
  if (exact !== undefined) return exact;
  const matches = ids.filter((id) => id.startsWith(prefix));
  return matches.length === 1 ? matches[0]! : null;
}