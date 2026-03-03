# URL Routing Design

This document describes the planned URL routing system for Balloons, which provides deep-linking and browser navigation support.

## Overview

Balloons uses a **hash-based routing** scheme (`#/path`) to enable:
- **Deep linking**: Share URLs that jump to specific sessions, turns, goals, etc.
- **Browser navigation**: Back/forward buttons work naturally
- **Bookmarks**: Save specific views for quick access
- **No server changes**: Hash routing works with static file serving

## URL Scheme

### Session Routes

```
#/                                    # Default: last active session or session list
#/sessions                            # Session tree view (sidebar focus)
#/sessions/:sessionId                 # Specific session, streaming tab
#/sessions/:sessionId/context         # Session context view
#/sessions/:sessionId/properties      # Session properties view
#/sessions/:sessionId/slides          # Session slides view
#/sessions/:sessionId/turn/:turnIndex # Jump to specific turn in session
```

Session IDs support **prefix matching** - `/sessions/abc` will match `abc123-def456-...`

### Goal Routes

```
#/goals                               # Goal tree / Kanban view
#/goals/:goalId                       # Specific goal expanded
#/goals/:goalId/plans/:planId         # Plan detail view
#/goals/:goalId/plans/:planId/todos/:todoId  # Todo detail/focus
```

### Global Tab Routes

```
#/code                                # Code tab
#/code/*filePath                      # Code tab with specific file open
#/logs                                # Logs tab
#/llm                                 # LLM tab
#/settings                            # Settings tab
#/supervisor                          # Process supervisor tab
#/supervisor/:processId               # Supervisor with process selected
```

### Query Parameters

Query params are preserved across navigation:

| Param | Purpose | Example |
|-------|---------|---------|
| `slot` | Server slot selection | `?slot=b` |
| `search` | Search/filter within view | `?search=error` |
| `highlight` | Highlight specific element | `?highlight=turn-5` |

## Implementation Architecture

### Router Hook (`useRouter`)

The router is implemented as a React hook that:
1. Parses the current `window.location.hash`
2. Provides navigation functions (`navigate`, `replace`)
3. Syncs URL changes back to app state
4. Handles browser popstate events

```typescript
// Conceptual API
const { route, navigate, replace } = useRouter();

// route contains parsed path info:
// { path: '/sessions/abc123/context', params: { sessionId: 'abc123', tab: 'context' } }

// Navigate (pushes history)
navigate('/sessions/def456');

// Replace (no history entry)
replace('/sessions/def456/slides');
```

### Route Definitions

Routes are defined in a central location for maintainability:

```typescript
// web/ui/src/routes.ts
export const ROUTES = {
  // Session routes
  SESSION_LIST: '/sessions',
  SESSION: '/sessions/:sessionId',
  SESSION_TAB: '/sessions/:sessionId/:tab',
  SESSION_TURN: '/sessions/:sessionId/turn/:turnIndex',

  // Goal routes
  GOALS: '/goals',
  GOAL: '/goals/:goalId',
  PLAN: '/goals/:goalId/plans/:planId',
  TODO: '/goals/:goalId/plans/:planId/todos/:todoId',

  // Global tabs
  CODE: '/code',
  CODE_FILE: '/code/*filePath',
  LOGS: '/logs',
  LLM: '/llm',
  SETTINGS: '/settings',
  SUPERVISOR: '/supervisor',
  SUPERVISOR_PROCESS: '/supervisor/:processId',
} as const;
```

### Integration Points

The router integrates with existing state management:

1. **SessionDataContext**: `setActiveSession()` is called when session route changes
2. **Tab state**: `mainContentTab` is set based on route
3. **Goal tree**: Goal/plan/todo expansion state synced from URL
4. **Code tab**: File selection synced from URL

## Adding New Routes

When adding new UI tabs or navigable areas:

### 1. Define the Route

Add route pattern to `ROUTES` in `web/ui/src/routes.ts`:

```typescript
export const ROUTES = {
  // ... existing routes
  NEW_TAB: '/new-tab',
  NEW_TAB_DETAIL: '/new-tab/:itemId',
} as const;
```

### 2. Add Route Handler

In the router's route matching logic, add a case for the new route:

```typescript
// In useRouter or route handler
if (matchRoute(ROUTES.NEW_TAB, path)) {
  setMainContentTab('new-tab');
  return;
}
```

### 3. Update Navigation Actions

When user actions should change the URL, call `navigate()`:

```typescript
// In component
const { navigate } = useRouter();

const handleItemClick = (itemId: string) => {
  navigate(`/new-tab/${itemId}`);
};
```

### 4. Document the Route

Add the new route to this document's URL Scheme section.

## Files to Update

When implementing or extending routing, these files are involved:

| File | Purpose |
|------|---------|
| `web/ui/src/routes.ts` | Route definitions (create this) |
| `web/ui/src/hooks/useRouter.ts` | Router hook (create this) |
| `web/ui/src/App.tsx` | Route handling, tab state sync |
| `web/ui/src/contexts/SessionDataContext.tsx` | Session navigation |
| `web/ui/src/components/SessionTreeView/` | Session selection |
| `web/ui/src/components/GoalTreeView/` | Goal navigation |
| `web/ui/src/components/CodeTab/` | File selection |

## Design Decisions

### Why Hash Routing?

1. **No server changes**: Works with any static file server
2. **Simpler deployment**: No need for catch-all routes
3. **Sufficient for dev tools**: SEO not relevant for Balloons

### Why Not react-router?

1. **Minimal needs**: We only need basic path matching
2. **Bundle size**: Avoid adding dependencies
3. **Control**: Easier to customize for our specific needs (prefix matching, etc.)

### Session ID Prefix Matching

Full session IDs are UUIDs like `abc12345-def6-7890-...`. For usability:
- URLs can use prefixes: `#/sessions/abc12`
- Router resolves to full ID from session list
- Minimum prefix length: 4 characters (avoid ambiguity)

## Future Considerations

### Potential Enhancements

- **Shareable links**: Copy URL button in UI
- **Recent routes**: Track recently visited for quick navigation
- **Route aliases**: Named bookmarks for frequent destinations
- **Query param persistence**: Remember filters across navigation

### Integration with Fork/Merge

When forking:
- Child session URL could be shown for easy sharing
- Navigation to fork updates URL automatically

When merging:
- Could navigate back to parent session URL
- Or stay on child with merge indicator

## Status

**Status**: Design phase - not yet implemented

**Next steps**:
1. Create `useRouter` hook with basic hash parsing
2. Implement session route handling
3. Add URL updates to session selection
4. Extend to goal routes
5. Add global tab routes
