//! Directory listing with git status.

use std::fs;
use std::path::Path;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use tracing::debug;

use crate::repo::GitRepo;
use crate::status::FileStatus;
use crate::{GitError, Result};

/// A single file or directory entry with git status.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileEntry {
    /// File or directory name (not full path).
    pub name: String,

    /// Absolute path to the file.
    pub path: String,

    /// Path relative to the listing root.
    pub relative_path: String,

    /// Whether this is a directory.
    pub is_directory: bool,

    /// File size in bytes (0 for directories).
    pub size: u64,

    /// Last modified time.
    pub modified: DateTime<Utc>,

    /// Git status character: ' '=clean, 'M'=modified, 'A'=added, '?'=untracked, '!'=ignored
    pub git_status: char,

    /// Whether the file is staged for commit.
    pub is_staged: bool,

    /// Whether the file is ignored by .gitignore.
    pub is_ignored: bool,

    /// Number of children (for directories only).
    pub children_count: Option<usize>,
}

/// Result of listing a directory.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DirectoryListing {
    /// Absolute path of the listed directory.
    pub path: String,

    /// Entries in the directory.
    pub entries: Vec<FileEntry>,

    /// Git repository root (if in a git repo).
    pub git_root: Option<String>,

    /// Path relative to git root (if in a git repo).
    pub git_path: Option<String>,
}

/// List a directory with git status information.
///
/// This function reads the directory contents and enriches each entry
/// with git status information if the directory is within a git repository.
pub fn list_directory(path: impl AsRef<Path>) -> Result<DirectoryListing> {
    let path = path.as_ref();

    if !path.exists() {
        return Err(GitError::PathNotFound(path.display().to_string()));
    }

    if !path.is_dir() {
        return Err(GitError::NotADirectory(path.display().to_string()));
    }

    let abs_path = path.canonicalize()?;
    debug!(?abs_path, "Listing directory");

    // Try to open git repo (may not exist)
    let git_repo = GitRepo::open(&abs_path).ok();
    let git_statuses = git_repo
        .as_ref()
        .and_then(|r| r.status_all().ok())
        .unwrap_or_default();

    let git_root = git_repo.as_ref().and_then(|r| r.root_path_string());
    let git_path = git_repo.as_ref().and_then(|r| r.relativize(&abs_path));

    let mut entries = Vec::new();

    for entry in fs::read_dir(&abs_path)? {
        let entry = entry?;
        let metadata = entry.metadata()?;
        let entry_path = entry.path();
        let name = entry.file_name().to_string_lossy().into_owned();

        // Skip hidden files (starting with .)
        if name.starts_with('.') {
            continue;
        }

        let relative_path = name.clone();

        // Get git status for this file
        let file_status = if let Some(ref repo) = git_repo {
            // Get the path relative to the git root
            if let Some(git_rel_path) = repo.relativize(&entry_path) {
                // Check in status map
                git_statuses.get(&git_rel_path).copied().unwrap_or_else(|| {
                    // If not in status map, check if ignored
                    if repo.is_ignored(&entry_path) {
                        FileStatus::ignored()
                    } else {
                        FileStatus::clean()
                    }
                })
            } else {
                FileStatus::clean()
            }
        } else {
            FileStatus::default()
        };

        // Count children for directories
        let children_count = if metadata.is_dir() {
            fs::read_dir(&entry_path)
                .map(|iter| iter.filter(|e| {
                    e.as_ref()
                        .map(|e| !e.file_name().to_string_lossy().starts_with('.'))
                        .unwrap_or(false)
                }).count())
                .ok()
        } else {
            None
        };

        // Get modified time
        let modified = metadata
            .modified()
            .map(DateTime::<Utc>::from)
            .unwrap_or_else(|_| Utc::now());

        entries.push(FileEntry {
            name,
            path: entry_path.to_string_lossy().into_owned(),
            relative_path,
            is_directory: metadata.is_dir(),
            size: metadata.len(),
            modified,
            git_status: file_status.status,
            is_staged: file_status.is_staged,
            is_ignored: file_status.is_ignored,
            children_count,
        });
    }

    // Sort: directories first, then by name
    entries.sort_by(|a, b| {
        match (a.is_directory, b.is_directory) {
            (true, false) => std::cmp::Ordering::Less,
            (false, true) => std::cmp::Ordering::Greater,
            _ => a.name.to_lowercase().cmp(&b.name.to_lowercase()),
        }
    });

    Ok(DirectoryListing {
        path: abs_path.to_string_lossy().into_owned(),
        entries,
        git_root,
        git_path,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::TempDir;

    #[test]
    fn test_list_empty_directory() {
        let dir = TempDir::new().unwrap();
        let listing = list_directory(dir.path()).unwrap();

        assert_eq!(listing.path, dir.path().canonicalize().unwrap().to_string_lossy());
        assert!(listing.entries.is_empty());
        assert!(listing.git_root.is_none());
    }

    #[test]
    fn test_list_with_files() {
        let dir = TempDir::new().unwrap();

        fs::write(dir.path().join("file1.txt"), "hello").unwrap();
        fs::write(dir.path().join("file2.txt"), "world").unwrap();
        fs::create_dir(dir.path().join("subdir")).unwrap();

        let listing = list_directory(dir.path()).unwrap();

        assert_eq!(listing.entries.len(), 3);

        // Directory should come first
        assert!(listing.entries[0].is_directory);
        assert_eq!(listing.entries[0].name, "subdir");

        // Files should be sorted alphabetically
        assert!(!listing.entries[1].is_directory);
        assert_eq!(listing.entries[1].name, "file1.txt");
        assert_eq!(listing.entries[2].name, "file2.txt");
    }

    #[test]
    fn test_hidden_files_excluded() {
        let dir = TempDir::new().unwrap();

        fs::write(dir.path().join("visible.txt"), "hello").unwrap();
        fs::write(dir.path().join(".hidden"), "secret").unwrap();

        let listing = list_directory(dir.path()).unwrap();

        assert_eq!(listing.entries.len(), 1);
        assert_eq!(listing.entries[0].name, "visible.txt");
    }

    #[test]
    fn test_path_not_found() {
        let result = list_directory("/nonexistent/path");
        assert!(matches!(result, Err(GitError::PathNotFound(_))));
    }

    #[test]
    fn test_not_a_directory() {
        let dir = TempDir::new().unwrap();
        let file_path = dir.path().join("file.txt");
        fs::write(&file_path, "hello").unwrap();

        let result = list_directory(&file_path);
        assert!(matches!(result, Err(GitError::NotADirectory(_))));
    }
}
