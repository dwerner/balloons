# LSP Server Management UI Plan

## Overview

This document outlines the UI design for managing LSP (Language Server Protocol) servers in Balloons. The UI allows users to:
- View configured language servers
- Monitor running server instances
- Start, stop, and restart servers
- View server status and health

## Design Options

### Option A: Integrate into Supervisor Tab

Add an "LSP Servers" section to the existing Supervisor tab, keeping all process management in one place.

**Pros:**
- Consistent with existing patterns
- LSP servers are just supervised processes
- No new navigation needed

**Cons:**
- Supervisor tab could get cluttered
- LSP servers have different management needs than general processes

### Option B: Separate LSP Tab

Create a dedicated "LSP" or "Language Servers" tab.

**Pros:**
- Clean separation of concerns
- Room for future LSP-specific features (diagnostics, logs)
- Better focus for LSP management

**Cons:**
- Another tab to navigate
- Some overlap with Supervisor (process viewing)

### Option C: Collapsible Section in Supervisor (Recommended)

Add a collapsible "Language Servers" section to Supervisor, visually distinct from regular processes.

**Pros:**
- Best of both worlds
- Can be collapsed when not needed
- Natural grouping with other process management
- LSP processes already appear in process list with `process_type: "lsp"`

## Recommended Design: Option C

### Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  Supervisor                                                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  🖥️ HOSTS (3)                                     [+ Add Host]  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ 🟢 local          this machine           2 processes        ││
│  │ 🟢 gpu-box        dan@192.168.1.50       0 processes  Check ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
│  🔤 LANGUAGE SERVERS                              [▼ Collapse]  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                                                              ││
│  │  Configured Servers                                          ││
│  │  ┌─────────────────────────────────────────────────────────┐││
│  │  │  python     pyright-langserver --stdio     .py .pyi     │││
│  │  │             Idle timeout: 5m               [Start]       │││
│  │  ├─────────────────────────────────────────────────────────┤││
│  │  │  typescript typescript-language-server     .ts .tsx     │││
│  │  │             Idle timeout: 5m               [Start]       │││
│  │  ├─────────────────────────────────────────────────────────┤││
│  │  │  rust       rust-analyzer                  .rs          │││
│  │  │             Idle timeout: 10m              [Start]       │││
│  │  └─────────────────────────────────────────────────────────┘││
│  │                                                              ││
│  │  Running Instances (1)                                       ││
│  │  ┌─────────────────────────────────────────────────────────┐││
│  │  │ 🟢 python:/home/dan/project                              │││
│  │  │    pyright                 idle: 45s    init: ✓          │││
│  │  │    Process: abc123...                   [Logs] [Restart] │││
│  │  └─────────────────────────────────────────────────────────┘││
│  │                                                              ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
│  ⚙️ PROCESSES (3)                                 1 running     │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  local (2)                                                   ││
│  │  ┌─────────────────────────────────────────────────────────┐││
│  │  │ 🟢 dev-server                                            │││
│  │  │    npm run dev                    Runtime: 2h 15m        │││
│  │  │    Session: abc123...             [Logs] [Stop]          │││
│  │  └─────────────────────────────────────────────────────────┘││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Components

#### 1. LSPSection Component

Main collapsible section for language servers.

```typescript
interface LSPSectionProps {
  lspClient: LSPServiceClient;
  isCollapsed: boolean;
  onToggleCollapse: () => void;
}

function LSPSection({ lspClient, isCollapsed, onToggleCollapse }: LSPSectionProps) {
  // Fetch status, handle events, render sub-components
}
```

#### 2. LSPServerConfigCard Component

Shows a configured server that may or may not be running.

```typescript
interface LSPServerConfigCardProps {
  config: LSPServerConfig;
  runningInstances: LSPServerInstance[];  // Instances of this server
  onStart: (language: string, workspace?: string) => void;
  onStopAll: (language: string) => void;
}
```

**Display:**
- Server name (python, typescript, rust, go)
- Command (e.g., `pyright-langserver --stdio`)
- File extensions (e.g., `.py`, `.pyi`)
- Idle timeout
- Number of running instances for this server type

**Actions:**
- Start (opens workspace picker if needed)
- Stop All instances of this server type

#### 3. LSPInstanceCard Component

Shows a running server instance.

```typescript
interface LSPInstanceCardProps {
  instance: LSPServerInstance;
  onViewLogs: (processId: string) => void;
  onRestart: (key: string) => void;
  onStop: (key: string) => void;
}
```

**Display:**
- Status indicator (running/stopped)
- Server type + workspace (e.g., `python:/home/dan/project`)
- Initialization status (✓ or spinning)
- Idle time
- Pending requests count
- Process ID (abbreviated)

**Actions:**
- View Logs (reuses ProcessLogViewer)
- Restart
- Stop

#### 4. WorkspacePickerModal Component

When starting a server, let user choose workspace.

```typescript
interface WorkspacePickerModalProps {
  isOpen: boolean;
  serverName: string;
  recentWorkspaces: string[];  // From session working directories
  onSelect: (workspace: string) => void;
  onCancel: () => void;
}
```

**Display:**
- Server name being started
- List of recent workspaces (from sessions)
- Text input for custom path
- Browse button (if we have file browser)

### Events

The UI should subscribe to LSP events for real-time updates:

```typescript
// In LSPSection
useEffect(() => {
  const unsubs = [
    lspClient.lspServerStarted((data) => {
      // Add to running instances
    }),
    lspClient.lspServerStopped((data) => {
      // Remove from running instances
    }),
    lspClient.lspServerRestarted((data) => {
      // Update instance
    }),
  ];
  return () => unsubs.forEach(u => u());
}, [lspClient]);
```

### State Management

```typescript
interface LSPSectionState {
  status: LSPStatusResult | null;
  isLoading: boolean;
  error: string | null;
  isCollapsed: boolean;
  startingServer: string | null;  // Language being started
  stoppingServers: Set<string>;   // Keys being stopped
}
```

### Styling

Follow existing Supervisor tab patterns:
- Cards with status indicators
- Action buttons with consistent styling
- Grouped sections with headers
- Collapse/expand controls

Add LSP-specific classes:
```css
.lsp-section { /* Collapsible wrapper */ }
.lsp-section--collapsed { /* Hidden content */ }
.lsp-config-card { /* Server config card */ }
.lsp-instance-card { /* Running instance card */ }
.lsp-instance-card__workspace { /* Truncated workspace path */ }
.lsp-instance-card__status { /* Init/idle status */ }
```

### Integration Points

1. **ProcessLogViewer**: Reuse existing component for viewing LSP server logs
2. **SupervisorStateService**: Filter `process_type: "lsp"` processes
3. **LSPService**: Primary API for LSP-specific operations

### Future Enhancements

1. **Diagnostics Panel**: Show LSP diagnostics for the current file
2. **Server Health**: Memory usage, request latency stats
3. **Auto-start**: Automatically start servers when opening relevant files
4. **Workspace Association**: Remember which servers are used for which workspaces

## Implementation Steps

1. **Create LSPSection component** (`components/SupervisorTab/LSPSection.tsx`)
   - Basic structure with configured servers and running instances
   - Connect to LSPServiceClient

2. **Add LSPServerConfigCard** - Display configured servers

3. **Add LSPInstanceCard** - Display running instances with actions

4. **Integrate into SupervisorTab** - Add collapsible section

5. **Add event subscriptions** - Real-time updates

6. **Add WorkspacePickerModal** - For starting servers

7. **Style and polish** - CSS matching existing tab

## Files to Create/Modify

### New Files
- `web/ui/src/components/SupervisorTab/LSPSection.tsx`
- `web/ui/src/components/SupervisorTab/LSPSection.css`
- `web/ui/src/components/SupervisorTab/LSPServerConfigCard.tsx`
- `web/ui/src/components/SupervisorTab/LSPInstanceCard.tsx`
- `web/ui/src/components/SupervisorTab/WorkspacePickerModal.tsx`

### Modified Files
- `web/ui/src/components/SupervisorTab/SupervisorTab.tsx` - Add LSPSection
- `web/ui/src/components/SupervisorTab/SupervisorTab.css` - Add LSP styles
