# Supervisor Tab - Design Document

## What Is It?

The Supervisor Tab is a **command center for distributed infrastructure**. It gives both Claude and humans visibility and control over:

- **Hosts**: Machines where work can happen (local + SSH remotes)
- **Processes**: Long-running tasks spawned by sessions
- **Backends**: Where LLM inference runs

## Why Does It Exist?

**Key insight**: Claude often needs to run things—dev servers, builds, ML inference—on machines other than where the UI runs. The Supervisor gives Claude:

1. **Awareness** - "What machines are available? What capabilities do they have?"
2. **Action** - "Start this process on the GPU box"
3. **Monitoring** - "Is that build still running? What's the output?"

We're NOT building Ansible/Kubernetes. We're giving Claude just enough infrastructure awareness to be useful without requiring the user to manage a complex orchestration system.

---

## Core Concepts

### Hosts

A **host** is a machine where processes can run.

```yaml
hosts:
  local:
    type: local
    tags: [docker, rust, python]
    description: This machine

  gpu-box:
    type: ssh
    host: 192.168.0.196
    user: dan
    tags: [amd, ml, llama, docker]
    description: AMD GPU workstation for ML inference
```

- **local**: Always exists, represents the Balloons server machine
- **ssh**: Remote machines accessible via SSH
- **tags**: Capabilities for semantic queries ("where can I run docker?")
- Relies on `~/.ssh/config` and ssh-agent for auth (no credentials stored)

### Processes

A **process** is a long-running command spawned by a session.

- Tied to a session (ownership is clear)
- Can run on any configured host
- Output is captured (stdout/stderr with timestamps)
- States: `running`, `exited`, `failed`

Use cases:
- Dev servers (`npm run dev`)
- File watchers (`cargo watch`)
- Long builds (`docker build`)
- Remote commands (`nvidia-smi` on GPU box)

### Backend Mappings

Maps LLM backend names (from `config.yaml`) to hosts where they run.

```yaml
backend_hosts:
  llama-amd: gpu-box
  llama-nvidia: gpu-box
```

This lets Claude know: "If I'm using the llama-amd backend, I should run ML commands on gpu-box."

---

## Capabilities

### For Claude (LLM Tools)

| Tool | Purpose |
|------|---------|
| `supervisor_start` | Start a background process (local or remote) |
| `supervisor_list` | See what's running |
| `supervisor_output` | Read process logs |
| `supervisor_stop` | Stop a process |
| `supervisor_query` | Find hosts by tags |
| `supervisor_host_status` | Check if host is reachable |

### For Humans (UI)

**View**:
- Hosts with status indicators (ready/reachable/unreachable)
- Processes grouped by host
- Backend-to-host mappings

**Actions**:
- Add/edit/remove hosts
- Check host connectivity (SSH ping)
- View process logs
- Stop processes
- Remove backend mappings

---

## What's Built vs What's Incomplete

### Built

- Config file schema and loading (`supervisor.yaml`)
- Host CRUD (add, edit, delete via UI)
- SSH connectivity checks with latency display
- Process listing and status display
- Backend mapping display and removal
- LLM tools for process management
- Real-time events for state changes
- Error display in scrollable pre blocks

### Incomplete / Stubs

**Process Management**:
- Log viewer UI (button exists, no viewer)
- Start process from UI (LLM-only currently)
- Real-time log streaming
- Process restart

**Host Management**:
- Add backend mapping from UI (can only remove)
- Connection test before saving new host

**Integration**:
- Click process → navigate to spawning session
- Notifications when processes fail
- Batch operations (stop all for session/host)

**Maybe Someday**:
- Host health monitoring (periodic pings, uptime)
- Resource usage display (disk, memory)
- File browser on remote hosts
- Embedded SSH terminal

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Separate `supervisor.yaml` | Infrastructure config is a different concern from app config |
| Tags not roles | Composable (`docker + ml`), queryable by capability |
| SSH not agents | Universal, no install, uses existing `~/.ssh/config` |
| Session-scoped processes | Clear ownership, natural cleanup, prevents orphans |

---

## Open Questions

1. **Multi-user**: How do processes work with multiple authenticated users?
2. **Persistence**: Should process state survive Balloons server restart?
3. **Quotas**: Limit processes per session/user/host?
4. **Security**: Which users can access which hosts?

---

## Files

| File | Purpose |
|------|---------|
| `supervisor_config.py` | Config loading, HostConfig dataclass |
| `core/supervisor_tools.py` | LLM tool implementations |
| `core/tools.py` | Tool definitions |
| `service/supervisor_state_service.py` | WebSocket service, CRUD |
| `prompts/claude-balloons-tools.md` | LLM tool documentation |
| `web/ui/src/components/SupervisorTab/` | React UI |
| `~/.balloons/supervisor.yaml` | User config |
