"""WebSocket-exposed service for file browsing with git status.

This service provides file system browsing with git status integration,
designed for the Balloons file browser UI.

Example usage:
    service = FileStateService()

    # Service methods are called via WebSocket RPC:
    # {"id": "1", "method": "listDirectory", "params": {"path": "/home/user/project"}}
    # -> {"id": "1", "result": {"path": "...", "entries": [...], "gitRoot": "..."}}

    # Events are pushed when CWD changes:
    # {"event": "cwdChanged", "data": {"sessionId": "abc", "cwd": "/new/path"}}
"""

from dataclasses import dataclass, field
from typing import Callable, Any
import os

from codegen import ws_service, ws_expose, ws_event, ws_type

# Import the Rust binding
try:
    from balloons_storage import list_directory as rust_list_directory
except ImportError:
    rust_list_directory = None


# =============================================================================
# Wire Types for WebSocket Codegen
# =============================================================================


@ws_type
@dataclass
class FileEntry:
    """A single file or directory entry with git status."""

    name: str
    path: str  # Absolute path
    relative_path: str  # Relative to listing root
    is_directory: bool
    size: int  # bytes
    modified: str  # ISO timestamp
    git_status: str  # ' '=clean, 'M'=modified, 'A'=added, '?'=untracked, '!'=ignored
    is_staged: bool
    is_ignored: bool
    children_count: int | None = None  # For directories only


@ws_type
@dataclass
class DirectoryListing:
    """Result of listing a directory."""

    path: str  # Absolute path
    entries: list[FileEntry]
    git_root: str | None = None  # Git repository root (if in a git repo)
    git_path: str | None = None  # Path relative to git root


@ws_type
@dataclass
class SessionCwd:
    """Current working directory for a session."""

    session_id: str
    cwd: str


@ws_type
@dataclass
class CwdChangedData:
    """Event data for CWD changes."""

    session_id: str
    old_cwd: str | None
    new_cwd: str


@ws_type
@dataclass
class FileOperationResult:
    """Result of a file operation."""

    success: bool
    message: str
    path: str | None = None


# =============================================================================
# Git Diff Types
# =============================================================================


@ws_type
@dataclass
class DiffChange:
    """A single line change in a diff."""

    type: str  # 'normal', 'insert', or 'delete'
    old_line_number: int | None  # null for inserts
    new_line_number: int | None  # null for deletes
    content: str  # line content without +/- prefix


@ws_type
@dataclass
class DiffHunk:
    """A hunk in a unified diff."""

    header: str  # e.g., "@@ -1,5 +1,6 @@"
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    changes: list[DiffChange]


@ws_type
@dataclass
class DiffFile:
    """A file with changes in the git diff."""

    path: str  # relative path from git root
    absolute_path: str
    old_path: str | None  # for renames
    status: str  # 'added', 'modified', 'deleted', 'renamed', 'copied'
    additions: int
    deletions: int
    is_binary: bool
    hunks: list[DiffHunk]


@ws_type
@dataclass
class GitDiffResult:
    """Result of getting git diff."""

    git_root: str
    files: list[DiffFile]
    has_unstaged: bool
    has_staged: bool


# =============================================================================
# Service Class
# =============================================================================


@ws_service
class FileStateService:
    """WebSocket-exposed service for file browsing with git status.

    Provides directory listing with git status integration and session CWD management.
    """

    def __init__(self):
        """Initialize service."""
        self._event_handlers: list[Callable[[str, dict], None]] = []
        # Session ID -> current working directory
        self._session_cwds: dict[str, str] = {}

    def add_event_handler(self, handler: Callable[[str, dict], None]) -> None:
        """Register a handler for WebSocket events.

        The handler will be called with (event_name, data) for each event.
        """
        self._event_handlers.append(handler)

    def remove_event_handler(self, handler: Callable[[str, dict], None]) -> None:
        """Unregister an event handler."""
        if handler in self._event_handlers:
            self._event_handlers.remove(handler)

    def _emit_event(self, event_name: str, data: dict) -> None:
        """Emit an event to all registered handlers."""
        for handler in self._event_handlers:
            handler(event_name, data)

    # --- Directory Listing ---

    @ws_expose
    async def list_directory(self, path: str) -> DirectoryListing:
        """List a directory with git status information.

        Hidden files (starting with '.') are excluded from the listing.
        Entries are sorted with directories first, then alphabetically by name.

        Args:
            path: Absolute path to the directory to list

        Returns:
            DirectoryListing with entries enriched with git status

        Raises:
            ValueError: If path doesn't exist or isn't a directory
        """
        if rust_list_directory is None:
            raise RuntimeError("balloons_storage module not available")

        # Validate path before calling Rust
        if not os.path.exists(path):
            raise ValueError(f"Path not found: {path}")
        if not os.path.isdir(path):
            raise ValueError(f"Not a directory: {path}")

        import json

        # Call Rust implementation
        result_json = rust_list_directory(path)
        result = json.loads(result_json)

        # Convert to wire types
        entries = [
            FileEntry(
                name=e["name"],
                path=e["path"],
                relative_path=e["relative_path"],
                is_directory=e["is_directory"],
                size=e["size"],
                modified=e["modified"],
                git_status=e["git_status"],
                is_staged=e["is_staged"],
                is_ignored=e["is_ignored"],
                children_count=e.get("children_count"),
            )
            for e in result["entries"]
        ]

        return DirectoryListing(
            path=result["path"],
            entries=entries,
            git_root=result.get("git_root"),
            git_path=result.get("git_path"),
        )

    @ws_expose
    async def list_directory_with_hidden(self, path: str) -> DirectoryListing:
        """List a directory including hidden files.

        Same as list_directory but includes files starting with '.'.

        Args:
            path: Absolute path to the directory to list

        Returns:
            DirectoryListing with all entries (including hidden)
        """
        # For now, we need to implement this in Python since Rust filters hidden files
        # In the future, we could add a parameter to the Rust function
        import json
        from datetime import datetime

        if not os.path.exists(path):
            raise ValueError(f"Path not found: {path}")
        if not os.path.isdir(path):
            raise ValueError(f"Not a directory: {path}")

        abs_path = os.path.abspath(path)

        # Get git info from a regular listing (for git_root/git_path)
        git_root = None
        git_path = None
        if rust_list_directory is not None:
            try:
                result_json = rust_list_directory(path)
                result = json.loads(result_json)
                git_root = result.get("git_root")
                git_path = result.get("git_path")
            except Exception:
                pass

        entries = []
        for name in os.listdir(abs_path):
            entry_path = os.path.join(abs_path, name)
            try:
                stat = os.stat(entry_path)
                is_dir = os.path.isdir(entry_path)

                entries.append(
                    FileEntry(
                        name=name,
                        path=entry_path,
                        relative_path=name,
                        is_directory=is_dir,
                        size=stat.st_size,
                        modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        git_status=" ",  # Would need git integration
                        is_staged=False,
                        is_ignored=name.startswith("."),
                        children_count=len(os.listdir(entry_path)) if is_dir else None,
                    )
                )
            except OSError:
                continue

        # Sort: directories first, then by name (case-insensitive)
        entries.sort(key=lambda e: (not e.is_directory, e.name.lower()))

        return DirectoryListing(
            path=abs_path,
            entries=entries,
            git_root=git_root,
            git_path=git_path,
        )

    # --- Session CWD Management ---

    @ws_expose
    async def get_cwd(self, session_id: str) -> str:
        """Get the current working directory for a session.

        Args:
            session_id: The session ID

        Returns:
            The current working directory, or server's cwd if not set
        """
        # Default to server's CWD (where headless.py was started from)
        # This is typically the project root, which is more useful than ~
        return self._session_cwds.get(session_id, os.getcwd())

    @ws_expose
    async def set_cwd(self, session_id: str, cwd: str) -> FileOperationResult:
        """Set the current working directory for a session.

        Args:
            session_id: The session ID
            cwd: The new working directory (must exist)

        Returns:
            Operation result with success/failure status
        """
        if not os.path.exists(cwd):
            return FileOperationResult(
                success=False,
                message=f"Path does not exist: {cwd}",
            )
        if not os.path.isdir(cwd):
            return FileOperationResult(
                success=False,
                message=f"Path is not a directory: {cwd}",
            )

        abs_cwd = os.path.abspath(cwd)
        old_cwd = self._session_cwds.get(session_id)
        self._session_cwds[session_id] = abs_cwd

        # Emit event
        self._emit_event(
            "cwdChanged",
            {
                "session_id": session_id,
                "old_cwd": old_cwd,
                "new_cwd": abs_cwd,
            },
        )

        return FileOperationResult(
            success=True,
            message=f"CWD set to {abs_cwd}",
            path=abs_cwd,
        )

    @ws_expose
    async def get_all_cwds(self) -> list[SessionCwd]:
        """Get all session CWDs.

        Returns:
            List of session CWD mappings
        """
        return [
            SessionCwd(session_id=sid, cwd=cwd) for sid, cwd in self._session_cwds.items()
        ]

    @ws_expose
    async def clear_session_cwd(self, session_id: str) -> None:
        """Clear the CWD for a session (e.g., when session is deleted).

        Args:
            session_id: The session ID to clear
        """
        if session_id in self._session_cwds:
            del self._session_cwds[session_id]

    # --- Path Utilities ---

    @ws_expose
    async def get_parent_directory(self, path: str) -> str:
        """Get the parent directory of a path.

        Args:
            path: The path to get parent of

        Returns:
            The parent directory path
        """
        return os.path.dirname(os.path.abspath(path))

    @ws_expose
    async def resolve_path(self, base: str, relative: str) -> str:
        """Resolve a relative path against a base directory.

        Args:
            base: The base directory
            relative: The relative path (can include .. and .)

        Returns:
            The resolved absolute path
        """
        return os.path.normpath(os.path.join(base, relative))

    @ws_expose
    async def path_exists(self, path: str) -> bool:
        """Check if a path exists.

        Args:
            path: The path to check

        Returns:
            True if the path exists
        """
        return os.path.exists(path)

    @ws_expose
    async def is_directory(self, path: str) -> bool:
        """Check if a path is a directory.

        Args:
            path: The path to check

        Returns:
            True if the path is a directory
        """
        return os.path.isdir(path)

    @ws_expose
    async def get_home_directory(self) -> str:
        """Get the user's home directory.

        Returns:
            The home directory path
        """
        return os.path.expanduser("~")

    # --- Git Diff ---

    @ws_expose
    async def get_git_diff(self, path: str, staged: bool = False) -> GitDiffResult:
        """Get git diff for a directory.

        Returns the unstaged (or staged) changes in a git repository.
        Parses the unified diff format into structured data.

        Args:
            path: Path to a directory inside a git repository
            staged: If True, show staged changes; if False, show unstaged changes

        Returns:
            GitDiffResult with parsed diff information

        Raises:
            ValueError: If path is not in a git repository
        """
        import subprocess
        import re

        # Find git root
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=path,
                capture_output=True,
                text=True,
                check=True,
            )
            git_root = result.stdout.strip()
        except subprocess.CalledProcessError:
            raise ValueError(f"Not a git repository: {path}")

        # Get diff
        diff_cmd = ["git", "diff"]
        if staged:
            diff_cmd.append("--cached")
        diff_cmd.extend(["--no-color", "--unified=3"])

        result = subprocess.run(
            diff_cmd,
            cwd=git_root,
            capture_output=True,
            text=True,
        )
        diff_output = result.stdout

        # Check for staged/unstaged changes
        has_staged = False
        has_unstaged = False

        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=git_root,
            capture_output=True,
            text=True,
        )
        for line in status_result.stdout.splitlines():
            if len(line) >= 2:
                index_status = line[0]
                worktree_status = line[1]
                if index_status not in (' ', '?'):
                    has_staged = True
                if worktree_status not in (' ', '?'):
                    has_unstaged = True

        # Parse the diff output
        files = self._parse_diff_output(diff_output, git_root)

        return GitDiffResult(
            git_root=git_root,
            files=files,
            has_unstaged=has_unstaged,
            has_staged=has_staged,
        )

    def _parse_diff_output(self, diff_output: str, git_root: str) -> list[DiffFile]:
        """Parse unified diff output into structured DiffFile objects."""
        import re

        files: list[DiffFile] = []
        current_file: DiffFile | None = None
        current_hunk: DiffHunk | None = None

        # Regex patterns
        diff_header = re.compile(r'^diff --git a/(.+) b/(.+)$')
        old_file = re.compile(r'^--- (?:a/)?(.+)$')
        new_file = re.compile(r'^\+\+\+ (?:b/)?(.+)$')
        hunk_header = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')
        index_line = re.compile(r'^index [0-9a-f]+\.\.[0-9a-f]+')
        mode_line = re.compile(r'^(new|deleted|old|new file|deleted file|similarity|rename|copy)')
        binary_line = re.compile(r'^Binary files')

        old_line_num = 0
        new_line_num = 0

        for line in diff_output.splitlines():
            # Check for diff header (new file)
            m = diff_header.match(line)
            if m:
                # Save previous file if exists
                if current_file is not None:
                    if current_hunk is not None:
                        current_file.hunks.append(current_hunk)
                    files.append(current_file)

                old_path = m.group(1)
                new_path = m.group(2)

                current_file = DiffFile(
                    path=new_path,
                    absolute_path=os.path.join(git_root, new_path),
                    old_path=old_path if old_path != new_path else None,
                    status='modified',  # Will be updated based on mode lines
                    additions=0,
                    deletions=0,
                    is_binary=False,
                    hunks=[],
                )
                current_hunk = None
                continue

            # Skip index and mode lines but extract status
            if index_line.match(line):
                continue

            if mode_line.match(line):
                if current_file:
                    if 'new file' in line:
                        current_file.status = 'added'
                    elif 'deleted file' in line:
                        current_file.status = 'deleted'
                    elif 'rename' in line:
                        current_file.status = 'renamed'
                    elif 'copy' in line:
                        current_file.status = 'copied'
                continue

            # Check for binary file
            if binary_line.match(line):
                if current_file:
                    current_file.is_binary = True
                continue

            # Skip old/new file headers
            if old_file.match(line) or new_file.match(line):
                continue

            # Check for hunk header
            m = hunk_header.match(line)
            if m:
                # Save previous hunk
                if current_hunk is not None and current_file is not None:
                    current_file.hunks.append(current_hunk)

                old_start = int(m.group(1))
                old_lines = int(m.group(2)) if m.group(2) else 1
                new_start = int(m.group(3))
                new_lines = int(m.group(4)) if m.group(4) else 1

                current_hunk = DiffHunk(
                    header=line,
                    old_start=old_start,
                    old_lines=old_lines,
                    new_start=new_start,
                    new_lines=new_lines,
                    changes=[],
                )
                old_line_num = old_start
                new_line_num = new_start
                continue

            # Parse change lines (within a hunk)
            if current_hunk is not None:
                if line.startswith('+'):
                    change = DiffChange(
                        type='insert',
                        old_line_number=None,
                        new_line_number=new_line_num,
                        content=line[1:],  # Remove + prefix
                    )
                    current_hunk.changes.append(change)
                    if current_file:
                        current_file.additions += 1
                    new_line_num += 1
                elif line.startswith('-'):
                    change = DiffChange(
                        type='delete',
                        old_line_number=old_line_num,
                        new_line_number=None,
                        content=line[1:],  # Remove - prefix
                    )
                    current_hunk.changes.append(change)
                    if current_file:
                        current_file.deletions += 1
                    old_line_num += 1
                elif line.startswith(' ') or line == '':
                    # Context line
                    content = line[1:] if line.startswith(' ') else ''
                    change = DiffChange(
                        type='normal',
                        old_line_number=old_line_num,
                        new_line_number=new_line_num,
                        content=content,
                    )
                    current_hunk.changes.append(change)
                    old_line_num += 1
                    new_line_num += 1
                # Ignore \ No newline at end of file and other special lines

        # Don't forget the last file/hunk
        if current_file is not None:
            if current_hunk is not None:
                current_file.hunks.append(current_hunk)
            files.append(current_file)

        return files

    @ws_expose
    async def read_file(self, path: str) -> str:
        """Read a file's content.

        Args:
            path: Absolute path to the file

        Returns:
            The file content as a string

        Raises:
            ValueError: If path doesn't exist or is a directory
        """
        if not os.path.exists(path):
            raise ValueError(f"File not found: {path}")
        if os.path.isdir(path):
            raise ValueError(f"Path is a directory: {path}")

        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()

    # --- Events ---

    @ws_event
    async def on_cwd_changed(self) -> CwdChangedData:
        """Emitted when a session's CWD changes."""
        ...

    @ws_event
    async def on_directory_changed(self) -> DirectoryListing:
        """Emitted when a watched directory's contents change.

        Note: Directory watching is not yet implemented.
        """
        ...
