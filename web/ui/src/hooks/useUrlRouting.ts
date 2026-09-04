/**
 * useUrlRouting — syncs the session selection with the hash URL.
 *
 * This is the "URL as mirror + back/forward" model (not a full router):
 *  - `initialRoute` is parsed once on mount, so a deep link (#/sessions/:id)
 *    can seed the initial session selection.
 *  - `currentRoute` updates on popstate/hashchange, so browser back/forward
 *    (and manual URL edits) can drive selection.
 *  - `replaceSession` writes the hash via history.replaceState for
 *    app-initiated selection changes. replaceState does NOT fire popstate /
 *    hashchange, so App's own writes never re-enter the reactive route —
 *    this is what keeps the selection→URL and URL→selection effects from
 *    looping.
 *
 * Scope: session routes only (see utils/urlRouting). Global-tab / goal / turn
 * routes are future work; they parse to `default` and are ignored here.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import {
  parseRoute,
  formatSessionRoute,
  formatGlobalRoute,
  type Route,
  type SessionTab,
  type GlobalTab,
} from '../utils/urlRouting';

export interface UrlRouting {
  /** Route parsed once on mount (deep-link seed). */
  initialRoute: Route;
  /** Reactive route, updated on popstate/hashchange. */
  currentRoute: Route;
  /** Write the session hash without adding a history entry (no event fired). */
  replaceSession: (sessionId: string, tab: SessionTab) => void;
  /** Write a global-tab hash without adding a history entry (no event fired). */
  replaceGlobalTab: (tab: GlobalTab) => void;
}

function readHash(): string {
  return typeof window !== 'undefined' ? window.location.hash : '';
}

/**
 * @param onNavigate invoked ONLY on genuine user navigation (popstate /
 *   hashchange) with the freshly parsed route. It is deliberately NOT called by
 *   replaceSession — replaceState emits no event — which is what makes
 *   selection→URL mirroring and URL→selection handling free of feedback loops.
 *   The latest callback is always used (stored in a ref), so callers can pass a
 *   closure over current state without re-subscribing.
 */
export function useUrlRouting(onNavigate?: (route: Route) => void): UrlRouting {
  const [initialRoute] = useState<Route>(() => parseRoute(readHash()));
  const [currentRoute, setCurrentRoute] = useState<Route>(initialRoute);

  const onNavigateRef = useRef(onNavigate);
  onNavigateRef.current = onNavigate;

  useEffect(() => {
    const onNav = () => {
      const route = parseRoute(readHash());
      setCurrentRoute(route);
      onNavigateRef.current?.(route);
    };
    window.addEventListener('popstate', onNav);
    window.addEventListener('hashchange', onNav);
    return () => {
      window.removeEventListener('popstate', onNav);
      window.removeEventListener('hashchange', onNav);
    };
  }, []);

  const replaceSession = useCallback((sessionId: string, tab: SessionTab) => {
    const hash = formatSessionRoute(sessionId, tab);
    // Only touch history when it actually differs; replaceState emits no event,
    // so this never bounces back through the popstate/hashchange listener.
    if (window.location.hash !== hash) {
      window.history.replaceState(null, '', hash);
    }
  }, []);

  const replaceGlobalTab = useCallback((tab: GlobalTab) => {
    const hash = formatGlobalRoute(tab);
    if (window.location.hash !== hash) {
      window.history.replaceState(null, '', hash);
    }
  }, []);

  return { initialRoute, currentRoute, replaceSession, replaceGlobalTab };
}