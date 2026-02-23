//! Git repository wrapper.

use std::collections::HashMap;
use std::path::Path;

use git2::Repository;
use tracing::debug;

use crate::status::FileStatus;
use crate::Result;

/// Wrapper around a git repository providing file status operations.
pub struct GitRepo {
    repo: Repository,
}

impl GitRepo {
    /// Open a git repository at or containing the given path.
    ///
    /// This will search upward from the given path to find a git repository.
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let path = path.as_ref();
        debug!(?path, "Opening git repository");

        let repo = Repository::discover(path)?;
        Ok(Self { repo })
    }

    /// Get the root path of the repository (workdir).
    pub fn root_path(&self) -> Option<&Path> {
        self.repo.workdir()
    }

    /// Get the root path as a string.
    pub fn root_path_string(&self) -> Option<String> {
        self.root_path()
            .map(|p| p.to_string_lossy().into_owned())
    }

    /// Get status for all files in the repository.
    ///
    /// Returns a map from relative path to file status.
    pub fn status_all(&self) -> Result<HashMap<String, FileStatus>> {
        let mut opts = git2::StatusOptions::new();
        opts.include_untracked(true)
            .recurse_untracked_dirs(true)
            .include_ignored(false) // Don't include ignored files in status
            .exclude_submodules(true);

        let statuses = self.repo.statuses(Some(&mut opts))?;
        let mut result = HashMap::new();

        for entry in statuses.iter() {
            if let Some(path) = entry.path() {
                let status = FileStatus::from_git2(entry.status());
                result.insert(path.to_string(), status);
            }
        }

        debug!(count = result.len(), "Got status for files");
        Ok(result)
    }

    /// Check if a path is ignored by .gitignore.
    pub fn is_ignored(&self, path: impl AsRef<Path>) -> bool {
        let path = path.as_ref();
        self.repo.is_path_ignored(path).unwrap_or(false)
    }

    /// Get the path relative to the repository root.
    pub fn relativize(&self, path: impl AsRef<Path>) -> Option<String> {
        let path = path.as_ref();
        let root = self.root_path()?;

        path.strip_prefix(root)
            .ok()
            .map(|p| p.to_string_lossy().into_owned())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::TempDir;

    fn create_git_repo() -> (TempDir, GitRepo) {
        let dir = TempDir::new().unwrap();
        Repository::init(dir.path()).unwrap();
        let repo = GitRepo::open(dir.path()).unwrap();
        (dir, repo)
    }

    #[test]
    fn test_open_repo() {
        let (dir, repo) = create_git_repo();
        assert_eq!(repo.root_path(), Some(dir.path()));
    }

    #[test]
    fn test_status_empty_repo() {
        let (_dir, repo) = create_git_repo();
        let statuses = repo.status_all().unwrap();
        assert!(statuses.is_empty());
    }

    #[test]
    fn test_status_untracked_file() {
        let (dir, repo) = create_git_repo();

        // Create an untracked file
        fs::write(dir.path().join("test.txt"), "hello").unwrap();

        let statuses = repo.status_all().unwrap();
        assert_eq!(statuses.len(), 1);

        let status = statuses.get("test.txt").unwrap();
        assert_eq!(status.status, '?');
        assert!(!status.is_staged);
    }

    #[test]
    fn test_is_ignored() {
        let (dir, repo) = create_git_repo();

        // Create .gitignore
        fs::write(dir.path().join(".gitignore"), "*.log\n").unwrap();

        assert!(repo.is_ignored("test.log"));
        assert!(!repo.is_ignored("test.txt"));
    }

    #[test]
    fn test_relativize() {
        let (dir, repo) = create_git_repo();
        let subdir = dir.path().join("src").join("main.rs");

        assert_eq!(
            repo.relativize(&subdir),
            Some("src/main.rs".to_string())
        );
    }
}
