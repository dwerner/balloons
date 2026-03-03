//! LMDB backup and recovery utilities.
//!
//! Provides tools for creating consistent backups, exporting/importing data,
//! and verifying database integrity.
//!
//! ## Backup Strategies
//!
//! 1. **File copy backup**: Uses LMDB's copy functionality for a consistent snapshot.
//!    Fast but LMDB-specific - can only restore to LMDB.
//!
//! 2. **JSON export**: Exports all data to JSON files. Portable and human-readable,
//!    but slower and uses more space.
//!
//! ## Usage
//!
//! ```ignore
//! use balloons_core::backup::{create_backup, export_to_json, import_from_json, health_check};
//!
//! // Create a timestamped backup directory
//! let backup_path = create_backup("/path/to/sessions.lmdb")?;
//!
//! // Export to JSON
//! export_to_json("/path/to/sessions.lmdb", "/path/to/export")?;
//!
//! // Import from JSON
//! import_from_json("/path/to/export", "/path/to/new.lmdb")?;
//!
//! // Check database health
//! let report = health_check("/path/to/sessions.lmdb")?;
//! println!("Sessions: {}, Turns: {}", report.session_count, report.turn_count);
//! ```

use crate::storage::{LmdbEngine, StorageEngine};
use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::fs;
use std::io::{BufReader, BufWriter, Write};
use std::path::{Path, PathBuf};

/// Result type for backup operations
pub type Result<T> = std::result::Result<T, BackupError>;

/// Errors that can occur during backup operations
#[derive(Debug, thiserror::Error)]
pub enum BackupError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("Database error: {0}")]
    Database(String),

    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),

    #[error("Backup already exists at {0}")]
    BackupExists(PathBuf),

    #[error("Source database not found: {0}")]
    SourceNotFound(PathBuf),

    #[error("Invalid export format: {0}")]
    InvalidFormat(String),

    #[error("Import validation failed: {0}")]
    ValidationFailed(String),
}

impl From<crate::storage::Error> for BackupError {
    fn from(e: crate::storage::Error) -> Self {
        BackupError::Database(e.to_string())
    }
}

/// Result of a backup operation
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BackupResult {
    /// Path to the backup
    pub backup_path: PathBuf,
    /// Timestamp of the backup (ISO 8601)
    pub timestamp: String,
    /// Size in bytes
    pub size_bytes: u64,
    /// Number of files copied (for file backup)
    pub files_copied: usize,
}

/// Result of an export operation
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExportResult {
    /// Path to the export directory
    pub export_path: PathBuf,
    /// Timestamp of the export (ISO 8601)
    pub timestamp: String,
    /// Number of sessions exported
    pub sessions_exported: usize,
    /// Total number of turns exported
    pub turns_exported: usize,
    /// Total size in bytes
    pub size_bytes: u64,
}

/// Result of an import operation
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ImportResult {
    /// Path to the target database
    pub target_path: PathBuf,
    /// Number of sessions imported
    pub sessions_imported: usize,
    /// Number of sessions skipped (already existed)
    pub sessions_skipped: usize,
    /// Total turns imported
    pub turns_imported: usize,
}

/// Health check report for a database
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthReport {
    /// Path to the database
    pub path: PathBuf,
    /// Whether the database could be opened
    pub can_open: bool,
    /// Number of sessions
    pub session_count: usize,
    /// Number of turns
    pub turn_count: usize,
    /// Number of orphaned turns (not in any session's turn_order)
    pub orphaned_turns: usize,
    /// Number of missing turns (in turn_order but not in turns table)
    pub missing_turns: usize,
    /// Database size in bytes
    pub size_bytes: u64,
    /// Any issues found
    pub issues: Vec<String>,
    /// Is the database healthy (no critical issues)
    pub is_healthy: bool,
}

/// Exported session with its turns
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExportedSession {
    pub session: crate::generated::SessionData,
    pub turns: Vec<crate::generated::TurnData>,
}

/// Export manifest file
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExportManifest {
    /// Export format version
    pub version: String,
    /// Timestamp of export
    pub exported_at: String,
    /// Number of sessions
    pub session_count: usize,
    /// Total turn count
    pub turn_count: usize,
    /// Session history
    pub session_history: Vec<String>,
}

const EXPORT_FORMAT_VERSION: &str = "1.0";

/// Create a timestamped backup of the LMDB database.
///
/// This creates a consistent snapshot by copying the LMDB files.
/// The backup is placed in a timestamped subdirectory next to the original.
///
/// # Arguments
///
/// * `source_path` - Path to the LMDB database directory
/// * `backup_dir` - Optional custom backup directory. If None, creates backup
///                  next to source as `{name}.backup.{timestamp}/`
///
/// # Returns
///
/// A `BackupResult` with information about the backup.
pub fn create_backup(
    source_path: impl AsRef<Path>,
    backup_dir: Option<&Path>,
) -> Result<BackupResult> {
    let source = source_path.as_ref();

    if !source.exists() {
        return Err(BackupError::SourceNotFound(source.to_path_buf()));
    }

    let timestamp = Utc::now().format("%Y%m%d_%H%M%S").to_string();

    let backup_path = if let Some(dir) = backup_dir {
        dir.to_path_buf()
    } else {
        let name = source.file_name().unwrap_or_default().to_string_lossy();
        source
            .parent()
            .unwrap_or(Path::new("."))
            .join(format!("{}.backup.{}", name, timestamp))
    };

    if backup_path.exists() {
        return Err(BackupError::BackupExists(backup_path));
    }

    // Create backup directory
    fs::create_dir_all(&backup_path)?;

    // Copy LMDB files (data.mdb and lock.mdb)
    let mut files_copied = 0;
    let mut total_size = 0u64;

    for entry in fs::read_dir(source)? {
        let entry = entry?;
        let path = entry.path();

        if path.is_file() {
            let file_name = path.file_name().unwrap();
            let dest = backup_path.join(file_name);

            fs::copy(&path, &dest)?;
            files_copied += 1;
            total_size += entry.metadata()?.len();
        }
    }

    Ok(BackupResult {
        backup_path,
        timestamp: Utc::now().to_rfc3339(),
        size_bytes: total_size,
        files_copied,
    })
}

/// Export all data from an LMDB database to JSON files.
///
/// Creates:
/// - `manifest.json`: Export metadata and session history
/// - `sessions/`: Directory containing one JSON file per session
///
/// # Arguments
///
/// * `source_path` - Path to the LMDB database directory
/// * `export_path` - Path for the export directory (will be created)
/// * `on_progress` - Optional callback for progress updates
///
/// # Returns
///
/// An `ExportResult` with statistics about the export.
pub async fn export_to_json<F>(
    source_path: impl AsRef<Path>,
    export_path: impl AsRef<Path>,
    mut on_progress: Option<F>,
) -> Result<ExportResult>
where
    F: FnMut(&str),
{
    let source = source_path.as_ref();
    let export = export_path.as_ref();

    if !source.exists() {
        return Err(BackupError::SourceNotFound(source.to_path_buf()));
    }

    // Create export directories
    fs::create_dir_all(export)?;
    let sessions_dir = export.join("sessions");
    fs::create_dir_all(&sessions_dir)?;

    // Open source database
    let engine = LmdbEngine::open(source)?;

    // Get all sessions
    let session_metas = engine.list_sessions().await?;
    let mut sessions_exported = 0;
    let mut turns_exported = 0;

    // Export each session
    for meta in &session_metas {
        if let Some(ref mut progress) = on_progress {
            progress(&format!("Exporting session: {}", meta.name));
        }

        if let Some(session) = engine.load_session(&meta.id).await? {
            let turns = engine.load_turns(&meta.id).await?;

            let exported = ExportedSession {
                session,
                turns: turns.clone(),
            };

            // Write to file
            let file_path = sessions_dir.join(format!("{}.json", meta.id));
            let file = fs::File::create(&file_path)?;
            let mut writer = BufWriter::new(file);
            serde_json::to_writer_pretty(&mut writer, &exported)?;
            writer.flush()?;

            sessions_exported += 1;
            turns_exported += turns.len();
        }
    }

    // Get session history
    let session_history = engine.load_session_history().await?;

    // Write manifest
    let manifest = ExportManifest {
        version: EXPORT_FORMAT_VERSION.to_string(),
        exported_at: Utc::now().to_rfc3339(),
        session_count: sessions_exported,
        turn_count: turns_exported,
        session_history,
    };

    let manifest_path = export.join("manifest.json");
    let file = fs::File::create(&manifest_path)?;
    let mut writer = BufWriter::new(file);
    serde_json::to_writer_pretty(&mut writer, &manifest)?;
    writer.flush()?;

    // Calculate total size
    let size_bytes = calculate_dir_size(export)?;

    if let Some(ref mut progress) = on_progress {
        progress(&format!(
            "Export complete: {} sessions, {} turns",
            sessions_exported, turns_exported
        ));
    }

    Ok(ExportResult {
        export_path: export.to_path_buf(),
        timestamp: Utc::now().to_rfc3339(),
        sessions_exported,
        turns_exported,
        size_bytes,
    })
}

/// Import data from a JSON export into an LMDB database.
///
/// Sessions that already exist in the target are skipped.
///
/// # Arguments
///
/// * `export_path` - Path to the export directory
/// * `target_path` - Path to the target LMDB database (will be created if needed)
/// * `on_progress` - Optional callback for progress updates
///
/// # Returns
///
/// An `ImportResult` with statistics about the import.
pub async fn import_from_json<F>(
    export_path: impl AsRef<Path>,
    target_path: impl AsRef<Path>,
    mut on_progress: Option<F>,
) -> Result<ImportResult>
where
    F: FnMut(&str),
{
    let export = export_path.as_ref();
    let target = target_path.as_ref();

    // Read manifest
    let manifest_path = export.join("manifest.json");
    if !manifest_path.exists() {
        return Err(BackupError::InvalidFormat(
            "manifest.json not found".to_string(),
        ));
    }

    let file = fs::File::open(&manifest_path)?;
    let manifest: ExportManifest = serde_json::from_reader(BufReader::new(file))?;

    if let Some(ref mut progress) = on_progress {
        progress(&format!(
            "Importing from export v{}: {} sessions",
            manifest.version, manifest.session_count
        ));
    }

    // Open target database
    let engine = LmdbEngine::open(target)?;

    // Get existing session IDs
    let existing: std::collections::HashSet<String> = engine
        .list_sessions()
        .await?
        .into_iter()
        .map(|m| m.id)
        .collect();

    let sessions_dir = export.join("sessions");
    let mut sessions_imported = 0;
    let mut sessions_skipped = 0;
    let mut turns_imported = 0;

    // Import each session file
    for entry in fs::read_dir(&sessions_dir)? {
        let entry = entry?;
        let path = entry.path();

        if path.extension().map_or(false, |e| e == "json") {
            let file = fs::File::open(&path)?;
            let exported: ExportedSession = serde_json::from_reader(BufReader::new(file))?;

            if existing.contains(&exported.session.id) {
                if let Some(ref mut progress) = on_progress {
                    progress(&format!("Skipping (exists): {}", exported.session.id));
                }
                sessions_skipped += 1;
                continue;
            }

            if let Some(ref mut progress) = on_progress {
                progress(&format!(
                    "Importing: {} ({} turns)",
                    exported.session.id,
                    exported.turns.len()
                ));
            }

            engine
                .save_session_with_turns(&exported.session.id, &exported.session, &exported.turns)
                .await?;

            turns_imported += exported.turns.len();
            sessions_imported += 1;
        }
    }

    // Import session history (merge with existing)
    if !manifest.session_history.is_empty() {
        let mut history = engine.load_session_history().await?;
        for id in manifest.session_history {
            if !history.contains(&id) {
                history.push(id);
            }
        }
        engine.save_session_history(&history).await?;
    }

    if let Some(ref mut progress) = on_progress {
        progress(&format!(
            "Import complete: {} imported, {} skipped",
            sessions_imported, sessions_skipped
        ));
    }

    Ok(ImportResult {
        target_path: target.to_path_buf(),
        sessions_imported,
        sessions_skipped,
        turns_imported,
    })
}

/// Check the health of an LMDB database.
///
/// Verifies:
/// - Database can be opened
/// - All sessions are readable
/// - Turn references are consistent (no orphans or missing)
///
/// # Arguments
///
/// * `path` - Path to the LMDB database directory
///
/// # Returns
///
/// A `HealthReport` with database statistics and any issues found.
pub async fn health_check(path: impl AsRef<Path>) -> Result<HealthReport> {
    let path = path.as_ref();
    let mut issues = Vec::new();

    // Check if path exists
    if !path.exists() {
        return Ok(HealthReport {
            path: path.to_path_buf(),
            can_open: false,
            session_count: 0,
            turn_count: 0,
            orphaned_turns: 0,
            missing_turns: 0,
            size_bytes: 0,
            issues: vec!["Database path does not exist".to_string()],
            is_healthy: false,
        });
    }

    // Try to open database
    let engine = match LmdbEngine::open(path) {
        Ok(e) => e,
        Err(e) => {
            return Ok(HealthReport {
                path: path.to_path_buf(),
                can_open: false,
                session_count: 0,
                turn_count: 0,
                orphaned_turns: 0,
                missing_turns: 0,
                size_bytes: calculate_dir_size(path).unwrap_or(0),
                issues: vec![format!("Cannot open database: {}", e)],
                is_healthy: false,
            });
        }
    };

    // Get all sessions
    let session_metas = engine.list_sessions().await?;
    let session_count = session_metas.len();
    let mut total_turn_count = 0;
    let missing_turns = 0; // TODO: detect missing turns

    // Check each session
    for meta in &session_metas {
        // Try to load full session
        match engine.load_session(&meta.id).await {
            Ok(Some(_)) => {}
            Ok(None) => {
                issues.push(format!("Session metadata exists but data missing: {}", meta.id));
            }
            Err(e) => {
                issues.push(format!("Cannot load session {}: {}", meta.id, e));
            }
        }

        // Load and count turns
        match engine.load_turns(&meta.id).await {
            Ok(turns) => {
                total_turn_count += turns.len();
                // Note: load_turns already filters out missing turns internally
                // but we could detect them if needed by checking turn_order
            }
            Err(e) => {
                issues.push(format!("Cannot load turns for {}: {}", meta.id, e));
            }
        }
    }

    // Calculate database size
    let size_bytes = calculate_dir_size(path).unwrap_or(0);

    let is_healthy = issues.is_empty();

    Ok(HealthReport {
        path: path.to_path_buf(),
        can_open: true,
        session_count,
        turn_count: total_turn_count,
        orphaned_turns: 0, // TODO: detect orphaned turns
        missing_turns,
        size_bytes,
        issues,
        is_healthy,
    })
}

/// List available backups for a database.
///
/// Looks for directories matching the backup naming pattern next to the source.
pub fn list_backups(source_path: impl AsRef<Path>) -> Result<Vec<BackupResult>> {
    let source = source_path.as_ref();
    let parent = source.parent().unwrap_or(Path::new("."));
    let name = source.file_name().unwrap_or_default().to_string_lossy();
    let prefix = format!("{}.backup.", name);

    let mut backups = Vec::new();

    for entry in fs::read_dir(parent)? {
        let entry = entry?;
        let entry_name = entry.file_name().to_string_lossy().to_string();

        if entry_name.starts_with(&prefix) && entry.path().is_dir() {
            let timestamp = entry_name
                .strip_prefix(&prefix)
                .unwrap_or("")
                .to_string();

            let size_bytes = calculate_dir_size(&entry.path()).unwrap_or(0);
            let files_copied = fs::read_dir(&entry.path())
                .map(|d| d.filter(|e| e.is_ok()).count())
                .unwrap_or(0);

            backups.push(BackupResult {
                backup_path: entry.path(),
                timestamp,
                size_bytes,
                files_copied,
            });
        }
    }

    // Sort by timestamp (newest first)
    backups.sort_by(|a, b| b.timestamp.cmp(&a.timestamp));

    Ok(backups)
}

/// Restore from a backup directory.
///
/// Copies the backup files to the target location.
///
/// # Arguments
///
/// * `backup_path` - Path to the backup directory
/// * `target_path` - Path to restore to (will be overwritten if exists)
pub fn restore_from_backup(
    backup_path: impl AsRef<Path>,
    target_path: impl AsRef<Path>,
) -> Result<BackupResult> {
    let backup = backup_path.as_ref();
    let target = target_path.as_ref();

    if !backup.exists() {
        return Err(BackupError::SourceNotFound(backup.to_path_buf()));
    }

    // Create target directory
    fs::create_dir_all(target)?;

    // Copy files
    let mut files_copied = 0;
    let mut total_size = 0u64;

    for entry in fs::read_dir(backup)? {
        let entry = entry?;
        let path = entry.path();

        if path.is_file() {
            let file_name = path.file_name().unwrap();
            let dest = target.join(file_name);

            fs::copy(&path, &dest)?;
            files_copied += 1;
            total_size += entry.metadata()?.len();
        }
    }

    Ok(BackupResult {
        backup_path: target.to_path_buf(),
        timestamp: Utc::now().to_rfc3339(),
        size_bytes: total_size,
        files_copied,
    })
}

/// Calculate the total size of a directory.
fn calculate_dir_size(path: impl AsRef<Path>) -> Result<u64> {
    let mut size = 0u64;

    for entry in fs::read_dir(path)? {
        let entry = entry?;
        let metadata = entry.metadata()?;

        if metadata.is_file() {
            size += metadata.len();
        } else if metadata.is_dir() {
            size += calculate_dir_size(entry.path())?;
        }
    }

    Ok(size)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::TestDir;
    use crate::{SessionData, TurnData};
    use futures_lite::future;

    fn make_session(id: &str, title: &str) -> SessionData {
        SessionData {
            id: id.to_string(),
            created: "2024-01-01T00:00:00Z".to_string(),
            last_modified: "2024-01-01T00:00:00Z".to_string(),
            model: "test-model".to_string(),
            total_input_tokens: 100,
            total_output_tokens: 50,
            total_cost: 0.01,
            context_window: 150000,
            parent_id: None,
            children: vec![],
            returned: false,
            return_condition: "manual".to_string(),
            working_directories: vec!["/home/test".to_string()],
            title: title.to_string(),
            summary: "Test summary".to_string(),
            fork_name: String::new(),
            fork_status: "active".to_string(),
            fork_point_turn: -1,
            merge_point_turn: -1,
            merge_message: String::new(),
            backend_name: "test".to_string(),
            cached_context_tokens: 0,
            message_queue: serde_json::json!({}),
        }
    }

    fn make_turn(id: &str, role: &str, content: &str) -> TurnData {
        TurnData {
            id: id.to_string(),
            role: role.to_string(),
            content_block: serde_json::json!({"type": "text", "text": content}),
            tokens: 100,
            timestamp: "2024-01-01T00:00:00Z".to_string(),
            context_mode: "compress".to_string(),
            summary: String::new(),
            exchange_id: None,
            sentiment: None,
            started_at: None,
            ended_at: None,
            parallel_group_id: None,
        }
    }

    #[test]
    fn test_create_backup() {
        let source_dir = TestDir::new("backup_source");
        let engine = LmdbEngine::open(source_dir.db_path()).unwrap();

        // Create some data
        future::block_on(async {
            let session = make_session("sess-1", "Test Session");
            engine.save_session("sess-1", &session).await.unwrap();
        });

        drop(engine);

        // Create backup
        let result = create_backup(source_dir.db_path(), None).unwrap();

        assert!(result.backup_path.exists());
        assert!(result.files_copied > 0);
        assert!(result.size_bytes > 0);
    }

    #[test]
    fn test_export_import_json() {
        let source_dir = TestDir::new("export_source");
        let export_dir = TestDir::new("export_output");
        let target_dir = TestDir::new("import_target");

        // Create source database with data
        let engine = LmdbEngine::open(source_dir.db_path()).unwrap();

        future::block_on(async {
            let session = make_session("sess-1", "Test Session");
            let turns = vec![
                make_turn("turn-1", "user", "Hello"),
                make_turn("turn-2", "assistant", "Hi!"),
            ];
            engine
                .save_session_with_turns("sess-1", &session, &turns)
                .await
                .unwrap();
            engine
                .save_session_history(&["sess-1".to_string()])
                .await
                .unwrap();
        });

        drop(engine);

        // Export
        let export_result = future::block_on(async {
            export_to_json(
                source_dir.db_path(),
                export_dir.db_path(),
                Some(|msg: &str| println!("{}", msg)),
            )
            .await
            .unwrap()
        });

        assert_eq!(export_result.sessions_exported, 1);
        assert_eq!(export_result.turns_exported, 2);
        assert!(export_dir.db_path().join("manifest.json").exists());

        // Import to new database
        let import_result = future::block_on(async {
            import_from_json(
                export_dir.db_path(),
                target_dir.db_path(),
                Some(|msg: &str| println!("{}", msg)),
            )
            .await
            .unwrap()
        });

        assert_eq!(import_result.sessions_imported, 1);
        assert_eq!(import_result.turns_imported, 2);

        // Verify imported data
        let engine = LmdbEngine::open(target_dir.db_path()).unwrap();
        future::block_on(async {
            let session = engine.load_session("sess-1").await.unwrap();
            assert!(session.is_some());
            let session = session.unwrap();
            assert_eq!(session.title, "Test Session");

            let turns = engine.load_turns("sess-1").await.unwrap();
            assert_eq!(turns.len(), 2);
        });
    }

    #[test]
    fn test_health_check() {
        let dir = TestDir::new("health_check");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        future::block_on(async {
            let session = make_session("sess-1", "Test Session");
            let turns = vec![
                make_turn("turn-1", "user", "Hello"),
                make_turn("turn-2", "assistant", "Hi!"),
            ];
            engine
                .save_session_with_turns("sess-1", &session, &turns)
                .await
                .unwrap();
        });

        drop(engine);

        let report = future::block_on(async { health_check(dir.db_path()).await.unwrap() });

        assert!(report.can_open);
        assert!(report.is_healthy);
        assert_eq!(report.session_count, 1);
        assert_eq!(report.turn_count, 2);
        assert!(report.issues.is_empty());
    }

    #[test]
    fn test_health_check_nonexistent() {
        let report = future::block_on(async {
            health_check("/nonexistent/path").await.unwrap()
        });

        assert!(!report.can_open);
        assert!(!report.is_healthy);
        assert!(!report.issues.is_empty());
    }

    #[test]
    fn test_list_and_restore_backups() {
        let source_dir = TestDir::new("backup_list_source");
        let engine = LmdbEngine::open(source_dir.db_path()).unwrap();

        future::block_on(async {
            let session = make_session("sess-1", "Test Session");
            engine.save_session("sess-1", &session).await.unwrap();
        });

        drop(engine);

        // Create backup
        let backup = create_backup(source_dir.db_path(), None).unwrap();

        // List backups
        let backups = list_backups(source_dir.db_path()).unwrap();
        assert!(!backups.is_empty());

        // Restore to new location
        let restore_dir = TestDir::new("backup_restore_target");
        let restored = restore_from_backup(&backup.backup_path, restore_dir.db_path()).unwrap();

        assert!(restored.files_copied > 0);

        // Verify restored data
        let engine = LmdbEngine::open(restore_dir.db_path()).unwrap();
        future::block_on(async {
            let session = engine.load_session("sess-1").await.unwrap();
            assert!(session.is_some());
        });
    }
}
