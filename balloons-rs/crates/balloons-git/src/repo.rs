//! Git repository wrapper.

use std::collections::HashMap;
use std::path::Path;

use git2::{IndexAddOption, Repository, Signature};
use tracing::debug;

use crate::status::FileStatus;
use crate::Result;

/// Result of a git commit operation.
#[derive(Debug, Clone)]
pub struct CommitResult {
    /// Short commit hash (first 8 chars).
    pub short_hash: String,
    /// Full commit hash.
    pub full_hash: String,
}

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

    /// Stage specific files for commit.
    ///
    /// Paths should be relative to the repository root.
    /// Handles both additions/modifications (file exists) and deletions (file doesn't exist).
    pub fn stage_files(&self, paths: &[&str]) -> Result<usize> {
        let mut index = self.repo.index()?;
        let mut staged = 0;

        let workdir = self.repo.workdir().ok_or_else(|| {
            git2::Error::from_str("Repository has no working directory")
        })?;

        for path in paths {
            let full_path = workdir.join(path);
            if full_path.exists() {
                // File exists - stage it (add or modify)
                debug!(?path, "Staging file (add/modify)");
                index.add_path(Path::new(path))?;
            } else {
                // File doesn't exist - stage as deletion
                debug!(?path, "Staging file deletion");
                index.remove_path(Path::new(path))?;
            }
            staged += 1;
        }

        index.write()?;
        debug!(count = staged, "Staged files");
        Ok(staged)
    }

    /// Stage all changes (tracked modified files and untracked files).
    pub fn stage_all(&self) -> Result<usize> {
        let mut index = self.repo.index()?;

        // Add all changes using a callback (similar to `git add -A`)
        index.add_all(["*"].iter(), IndexAddOption::DEFAULT, None)?;
        index.write()?;

        // Return count of entries
        let count = index.len();
        debug!(count, "Staged all changes");
        Ok(count)
    }

    /// Unstage specific files (remove from index, keeping working tree changes).
    ///
    /// Paths should be relative to the repository root.
    pub fn unstage_files(&self, paths: &[&str]) -> Result<usize> {
        let mut index = self.repo.index()?;
        let head = self.repo.head()?.peel_to_commit()?;
        let head_tree = head.tree()?;
        let mut unstaged = 0;

        for path in paths {
            debug!(?path, "Unstaging file");
            // Reset to HEAD for this path
            if head_tree.get_path(Path::new(path)).is_ok() {
                // File exists in HEAD - reset to that version
                let entry = head_tree.get_path(Path::new(path))?;
                let index_entry = git2::IndexEntry {
                    ctime: git2::IndexTime::new(0, 0),
                    mtime: git2::IndexTime::new(0, 0),
                    dev: 0,
                    ino: 0,
                    mode: entry.filemode() as u32,
                    uid: 0,
                    gid: 0,
                    file_size: 0,
                    id: entry.id(),
                    flags: 0,
                    flags_extended: 0,
                    path: path.as_bytes().to_vec(),
                };
                index.add(&index_entry)?;
            } else {
                // File doesn't exist in HEAD - remove from index entirely
                index.remove_path(Path::new(path))?;
            }
            unstaged += 1;
        }

        index.write()?;
        debug!(count = unstaged, "Unstaged files");
        Ok(unstaged)
    }

    /// Create a commit with the currently staged changes.
    ///
    /// Returns the commit hash on success.
    pub fn commit(&self, message: &str) -> Result<CommitResult> {
        let mut index = self.repo.index()?;
        let tree_id = index.write_tree()?;
        let tree = self.repo.find_tree(tree_id)?;

        // Get signature from git config or use defaults
        let sig = self.repo.signature().unwrap_or_else(|_| {
            Signature::now("Balloons User", "user@balloons.local").unwrap()
        });

        // Get parent commit (HEAD)
        let parent = match self.repo.head() {
            Ok(head) => Some(head.peel_to_commit()?),
            Err(e) if e.code() == git2::ErrorCode::UnbornBranch => None,
            Err(e) => return Err(e.into()),
        };

        let parents: Vec<&git2::Commit> = parent.as_ref().map(|p| vec![p]).unwrap_or_default();

        let commit_id = self.repo.commit(
            Some("HEAD"),
            &sig,
            &sig,
            message,
            &tree,
            &parents,
        )?;

        let full_hash = commit_id.to_string();
        let short_hash = full_hash[..8.min(full_hash.len())].to_string();

        debug!(?short_hash, "Created commit");
        Ok(CommitResult {
            short_hash,
            full_hash,
        })
    }

    /// Check if there are staged changes ready to commit.
    pub fn has_staged_changes(&self) -> Result<bool> {
        let statuses = self.status_all()?;
        Ok(statuses.values().any(|s| s.is_staged))
    }

    /// Get a list of staged file paths.
    pub fn staged_files(&self) -> Result<Vec<String>> {
        let statuses = self.status_all()?;
        Ok(statuses
            .into_iter()
            .filter(|(_, s)| s.is_staged)
            .map(|(path, _)| path)
            .collect())
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
