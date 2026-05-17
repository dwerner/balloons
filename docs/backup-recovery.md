# LMDB Backup and Recovery Utilities

## Overview

Balloons stores session data in an LMDB database at `~/.balloons/sessions.lmdb`. This document describes the backup and recovery utilities for protecting and managing this data.

## Quick Start

```bash
# Check database health
python scripts/backup_db.py health

# Create a backup before making changes
python scripts/backup_db.py backup

# Export to portable JSON format
python scripts/backup_db.py export ~/balloons-backup

# Restore from backup if needed
python scripts/backup_db.py restore ~/.balloons/sessions.lmdb.backup.20260212_120000
```

## Commands

### health - Check Database Health

Verifies database integrity and reports statistics.

```bash
python scripts/backup_db.py health
```

Output:
```
Checking health of: /home/user/.balloons/sessions.lmdb
------------------------------------------------------------
Status:          HEALTHY
Can open:        Yes
Sessions:        140
Turns:           20500
Size:            46.3 MB
```

With `--json` for scripting:
```bash
python scripts/backup_db.py --json health
```

Returns exit code 1 if database is unhealthy.

### backup - Create File Backup

Creates a timestamped copy of the LMDB database files.

```bash
# Default: creates backup next to source
python scripts/backup_db.py backup
# Creates: ~/.balloons/sessions.lmdb.backup.20260212_120000/

# Custom location
python scripts/backup_db.py backup --backup-dir /path/to/backup
```

This copies `data.mdb` and `lock.mdb` files. Fast but LMDB-specific.

### list-backups - List Available Backups

Shows all backups found for the database.

```bash
python scripts/backup_db.py list-backups
```

Output:
```
Found 3 backup(s):

Timestamp            Size         Path
--------------------------------------------------------------------------------
20260212_140000      46.3 MB      /home/user/.balloons/sessions.lmdb.backup.20260212_140000
20260211_100000      45.1 MB      /home/user/.balloons/sessions.lmdb.backup.20260211_100000
20260210_090000      44.0 MB      /home/user/.balloons/sessions.lmdb.backup.20260210_090000
```

### restore - Restore from Backup

Restores LMDB files from a backup directory.

```bash
# Restore to original location (prompts for confirmation)
python scripts/backup_db.py restore /path/to/backup

# Restore to different location
python scripts/backup_db.py restore /path/to/backup --target /path/to/new.lmdb

# Force overwrite without prompting
python scripts/backup_db.py restore /path/to/backup --force
```

### export - Export to JSON

Exports all data to portable JSON files. Human-readable and can be imported into a fresh database.

```bash
python scripts/backup_db.py export /path/to/export
```

Creates:
```
/path/to/export/
├── manifest.json           # Export metadata, session history
└── sessions/
    ├── session-id-1.json   # Session data + turns
    ├── session-id-2.json
    └── ...
```

Use `--force` to overwrite existing export directory.

### import - Import from JSON

Restores data from a JSON export. Sessions that already exist are skipped.

```bash
# Import to default database
python scripts/backup_db.py import /path/to/export

# Import to different database
python scripts/backup_db.py import /path/to/export --target /path/to/new.lmdb
```

### recover - Database-to-Database Recovery

Copies sessions from one LMDB database to another. Useful for merging databases or recovering from a corrupted database.

```bash
python scripts/backup_db.py recover /path/to/source.lmdb
```

Sessions that already exist in the target are skipped.

## Global Options

| Option | Description |
|--------|-------------|
| `--db-path PATH` | Path to LMDB database (default: `~/.balloons/sessions.lmdb`) |
| `--json`, `-j` | Output results as JSON (for scripting) |

## Python API

All functions are available via the `balloons_py` module:

```python
import balloons_py

# Health check
report = balloons_py.health_check("/path/to/db")
print(f"Healthy: {report['is_healthy']}, Sessions: {report['session_count']}")

# Create backup
result = balloons_py.create_backup("/path/to/db")
print(f"Backup created at: {result['backup_path']}")

# Create backup to specific directory
result = balloons_py.create_backup("/path/to/db", "/path/to/backup")

# List backups
backups = balloons_py.list_backups("/path/to/db")
for b in backups:
    print(f"{b['timestamp']}: {b['backup_path']}")

# Restore from backup
result = balloons_py.restore_from_backup("/path/to/backup", "/path/to/target")

# Export to JSON
result = balloons_py.export_to_json("/path/to/db", "/path/to/export")
print(f"Exported {result['sessions_exported']} sessions")

# Import from JSON
result = balloons_py.import_from_json("/path/to/export", "/path/to/db")
print(f"Imported {result['sessions_imported']}, skipped {result['sessions_skipped']}")

# Recover between databases
result = balloons_py.recover_database("/path/to/source", "/path/to/target")
```

## Backup Strategies

### 1. File Backup (Fast, LMDB-only)

Use `backup` for quick snapshots before risky operations:
- Before upgrading balloons
- Before manual database edits
- Regular periodic backups

Pros: Fast, small, exact copy
Cons: LMDB-specific, not human-readable

### 2. JSON Export (Portable, Readable)

Use `export` for long-term archival or migration:
- Moving to a new machine
- Debugging session data
- Archiving old sessions

Pros: Portable, human-readable, can inspect/edit
Cons: Slower, larger than LMDB files

## Recovery Scenarios

### Corrupted Database

```bash
# 1. Check health
python scripts/backup_db.py health
# Status: UNHEALTHY

# 2. Try to export what's readable
python scripts/backup_db.py export /tmp/recovery-export

# 3. Create fresh database from export
mv ~/.balloons/sessions.lmdb ~/.balloons/sessions.lmdb.corrupted
python scripts/backup_db.py import /tmp/recovery-export
```

### Restore from Backup

```bash
# 1. Stop balloons if running

# 2. Restore from most recent backup
python scripts/backup_db.py list-backups
python scripts/backup_db.py restore ~/.balloons/sessions.lmdb.backup.20260212_120000 --force
```

### Merge Databases

```bash
# Recover sessions from old database into current
python scripts/backup_db.py recover ~/.balloons/old-sessions.lmdb
```

## Data Format

### JSON Export Manifest

```json
{
  "version": "1.0",
  "exported_at": "2026-02-12T20:14:54+00:00",
  "session_count": 140,
  "turn_count": 20452,
  "session_history": ["session-id-1", "session-id-2", ...]
}
```

### Exported Session

```json
{
  "session": {
    "id": "uuid",
    "title": "Session Title",
    "created": "2026-01-01T00:00:00Z",
    "last_modified": "2026-01-02T00:00:00Z",
    "model": "claude-3-opus",
    "total_input_tokens": 1000,
    "total_output_tokens": 500,
    ...
  },
  "turns": [
    {
      "id": "turn-uuid",
      "role": "user",
      "content_block": {"type": "text", "text": "Hello"},
      "tokens": 10,
      "timestamp": "2026-01-01T00:00:00Z",
      ...
    },
    ...
  ]
}
```

## Automation

### Cron Backup

Create daily backups with cron:

```bash
# crontab -e
0 3 * * * /path/to/balloons/.venv/bin/python /path/to/balloons/scripts/backup_db.py backup --backup-dir /backups/balloons/$(date +\%Y\%m\%d)
```

### Pre-operation Backup

In your own scripts:

```python
import balloons_py

def backup_before_operation():
    result = balloons_py.create_backup("~/.balloons/sessions.lmdb")
    print(f"Backup created: {result['backup_path']}")
    return result['backup_path']

# Use in risky operations
backup_path = backup_before_operation()
try:
    do_risky_operation()
except Exception:
    balloons_py.restore_from_backup(backup_path, "~/.balloons/sessions.lmdb")
    raise
```
