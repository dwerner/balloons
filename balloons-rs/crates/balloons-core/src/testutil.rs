//! Test utilities for balloons-core.
//!
//! Provides isolated test directories that can optionally be preserved
//! for debugging by setting BALLOONS_PRESERVE_TEST_RUNS=1.

use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use tempfile::TempDir;

static TEST_COUNTER: AtomicU64 = AtomicU64::new(0);

/// A test directory that is either temporary (deleted on drop) or preserved
/// in `.test-runs/` for debugging.
pub struct TestDir {
    /// The path to use for test data
    pub path: PathBuf,
    /// Holds the TempDir if we're not preserving - dropping it cleans up
    _temp: Option<TempDir>,
}

impl TestDir {
    /// Create a new test directory.
    ///
    /// If `BALLOONS_PRESERVE_TEST_RUNS=1` is set, creates a timestamped directory
    /// in `.test-runs/` that persists after the test. Otherwise uses a temp
    /// directory that is cleaned up on drop.
    pub fn new(test_name: &str) -> Self {
        let preserve = std::env::var("BALLOONS_PRESERVE_TEST_RUNS")
            .map(|v| v == "1" || v.to_lowercase() == "true")
            .unwrap_or(false);

        if preserve {
            Self::preserved(test_name)
        } else {
            Self::temporary()
        }
    }

    /// Create a temporary directory that is cleaned up on drop.
    fn temporary() -> Self {
        let temp = TempDir::new().expect("failed to create temp dir");
        let path = temp.path().to_path_buf();
        Self {
            path,
            _temp: Some(temp),
        }
    }

    /// Create a preserved directory in `.test-runs/`.
    fn preserved(test_name: &str) -> Self {
        let workspace_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .parent()
            .unwrap()
            .to_path_buf();

        let test_runs_dir = workspace_root.join(".test-runs");
        std::fs::create_dir_all(&test_runs_dir).expect("failed to create .test-runs");

        // Create unique directory with timestamp and counter
        let timestamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs();
        let counter = TEST_COUNTER.fetch_add(1, Ordering::Relaxed);
        let dir_name = format!("{}-{}-{}", test_name, timestamp, counter);
        let path = test_runs_dir.join(dir_name);

        std::fs::create_dir_all(&path).expect("failed to create test dir");

        Self { path, _temp: None }
    }

    /// Get the path to the database file within this test directory.
    pub fn db_path(&self) -> PathBuf {
        self.path.join("balloons.redb")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_dir_creates_path() {
        let dir = TestDir::new("test_dir_creates_path");
        assert!(dir.path.exists());
    }

    #[test]
    fn test_dir_db_path() {
        let dir = TestDir::new("test_dir_db_path");
        let db_path = dir.db_path();
        assert!(db_path.ends_with("balloons.redb"));
    }
}
