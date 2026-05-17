//! Database recovery utilities.
//!
//! Provides tools for migrating and recovering data between LMDB databases.

use crate::storage::{LmdbEngine, StorageEngine};
use std::collections::HashSet;
use std::path::Path;

/// Result of a recovery operation.
#[derive(Debug, Default)]
pub struct RecoveryResult {
    /// Number of sessions successfully recovered.
    pub recovered: usize,
    /// Number of sessions skipped (already existed in target).
    pub skipped: usize,
    /// Number of sessions that failed to recover.
    pub failed: usize,
    /// Session history entries recovered.
    pub history_entries: usize,
}

/// Recover all sessions from a source database to a target database.
///
/// This function copies sessions and their turns from the source database
/// to the target database. Sessions that already exist in the target are skipped.
///
/// # Arguments
///
/// * `source_path` - Path to the source LMDB database directory
/// * `target_path` - Path to the target LMDB database directory
/// * `on_progress` - Optional callback for progress updates
///
/// # Returns
///
/// A `RecoveryResult` with statistics about the operation.
pub async fn recover_database<F>(
    source_path: impl AsRef<Path>,
    target_path: impl AsRef<Path>,
    mut on_progress: Option<F>,
) -> crate::storage::Result<RecoveryResult>
where
    F: FnMut(&str),
{
    let source = LmdbEngine::open(source_path)?;
    let target = LmdbEngine::open(target_path)?;

    let mut result = RecoveryResult::default();

    // Get all sessions from source
    let source_sessions = source.list_sessions().await?;

    // Get existing sessions in target
    let target_sessions = target.list_sessions().await?;
    let existing_ids: HashSet<_> = target_sessions.iter()
        .map(|s| s.id.as_str())
        .collect();

    // Recover each session
    for meta in &source_sessions {
        if existing_ids.contains(meta.id.as_str()) {
            if let Some(ref mut progress) = on_progress {
                progress(&format!("Skipping {} (already exists)", meta.name));
            }
            result.skipped += 1;
            continue;
        }

        // Load full session from source
        match source.load_session(&meta.id).await {
            Ok(Some(session)) => {
                // Load turns
                let turns = source.load_turns(&meta.id).await?;

                // Save to target
                match target.save_session_with_turns(&meta.id, &session, &turns).await {
                    Ok(()) => {
                        if let Some(ref mut progress) = on_progress {
                            progress(&format!("Recovered {} ({} turns)", meta.name, turns.len()));
                        }
                        result.recovered += 1;
                    }
                    Err(e) => {
                        if let Some(ref mut progress) = on_progress {
                            progress(&format!("Failed to save {}: {}", meta.name, e));
                        }
                        result.failed += 1;
                    }
                }
            }
            Ok(None) => {
                if let Some(ref mut progress) = on_progress {
                    progress(&format!("Session {} not found in source", meta.id));
                }
                result.failed += 1;
            }
            Err(e) => {
                if let Some(ref mut progress) = on_progress {
                    progress(&format!("Failed to load {}: {}", meta.id, e));
                }
                result.failed += 1;
            }
        }
    }

    // Recover session history
    let history = source.load_session_history().await?;
    if !history.is_empty() {
        target.save_session_history(&history).await?;
        result.history_entries = history.len();
        if let Some(ref mut progress) = on_progress {
            progress(&format!("Recovered session history ({} entries)", history.len()));
        }
    }

    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::TestDir;
    use crate::SessionData;
    use futures_lite::future;

    fn make_session(id: &str, title: &str) -> SessionData {
        SessionData {
            id: id.to_string(),
            created: "2024-01-01T00:00:00Z".to_string(),
            last_modified: "2024-01-01T00:00:00Z".to_string(),
            model: "test-model".to_string(),
            total_input_tokens: 0,
            total_output_tokens: 0,
            total_cost: 0.0,
            context_window: 150000,
            parent_id: None,
            children: vec![],
            returned: false,
            return_condition: "manual".to_string(),
            working_directories: vec![],
            title: title.to_string(),
            summary: String::new(),
            fork_name: String::new(),
            fork_status: "active".to_string(),
            fork_point_turn: -1,
            merge_point_turn: -1,
            merge_message: String::new(),
            backend_name: String::new(),
            cached_context_tokens: 0,
            prompt_files: vec![],
            enabled_tools: vec![],
            concluded: false,
            concluded_at: None,
            concluded_reason: String::new(),
            message_queue: serde_json::json!({}),
            loaded_domains: vec![],
        }
    }

    #[test]
    fn test_recover_database() {
        let source_dir = TestDir::new("recovery_source");
        let target_dir = TestDir::new("recovery_target");

        let source = LmdbEngine::open(source_dir.db_path()).unwrap();
        let target = LmdbEngine::open(target_dir.db_path()).unwrap();

        // Create sessions in source
        future::block_on(async {
            source.save_session("sess-1", &make_session("sess-1", "Session 1")).await.unwrap();
            source.save_session("sess-2", &make_session("sess-2", "Session 2")).await.unwrap();
            source.save_session_history(&["sess-2".to_string(), "sess-1".to_string()]).await.unwrap();

            // Create one session in target (should be skipped)
            target.save_session("sess-1", &make_session("sess-1", "Session 1")).await.unwrap();
        });

        drop(source);
        drop(target);

        // Run recovery
        let result = future::block_on(async {
            recover_database(
                source_dir.db_path(),
                target_dir.db_path(),
                Some(|msg: &str| println!("{}", msg)),
            ).await.unwrap()
        });

        assert_eq!(result.recovered, 1);
        assert_eq!(result.skipped, 1);
        assert_eq!(result.failed, 0);
        assert_eq!(result.history_entries, 2);

        // Verify target has both sessions
        let target = LmdbEngine::open(target_dir.db_path()).unwrap();
        future::block_on(async {
            let sessions = target.list_sessions().await.unwrap();
            assert_eq!(sessions.len(), 2);
        });
    }
}
