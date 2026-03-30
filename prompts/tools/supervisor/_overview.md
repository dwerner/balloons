## Process Supervisor Tools

Tools for managing long-running background processes. Use these when you need to:
- Start a dev server, watcher, or long build that should run while you work on other tasks
- Check on the status or output of running processes
- Stop processes when done
- Run commands on remote hosts via SSH

### Why Use the Supervisor?

The regular `Bash` tool waits for commands to complete, which blocks your workflow for long-running processes. The supervisor tools let you:
- **Start processes in background**: Run `npm run dev` or `cargo watch` without blocking
- **Check output later**: Query process output at any time
- **Session-scoped**: Processes are tied to the session and cleaned up appropriately
- **Remote execution**: Run commands on SSH-accessible hosts defined in supervisor.yaml

### Good Use Cases

- **Dev servers**: `npm run dev`, `python manage.py runserver`, `cargo run`
- **File watchers**: `cargo watch -x test`, `nodemon`, `inotifywait` loops
- **Long builds**: `make all`, `cargo build --release`, `docker build`
- **Database/services**: `docker-compose up`, `redis-server`
- **Remote commands**: GPU monitoring, remote builds, deployment tasks

### Process Status

Processes report one of three states:
- `{"state": "running", "pid": 12345}` - Currently running
- `{"state": "exited", "code": 0, "signal": null}` - Completed normally
- `{"state": "failed", "error": "message"}` - Failed to start or crashed
