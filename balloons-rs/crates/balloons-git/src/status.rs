//! Git file status types.

use serde::{Deserialize, Serialize};

/// Git status for a single file.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct FileStatus {
    /// Status character: ' '=clean, 'M'=modified, 'A'=added, 'D'=deleted, '?'=untracked, '!'=ignored
    pub status: char,
    /// Whether the file is staged for commit
    pub is_staged: bool,
    /// Whether the file is ignored by .gitignore
    pub is_ignored: bool,
}

impl Default for FileStatus {
    fn default() -> Self {
        Self {
            status: ' ',
            is_staged: false,
            is_ignored: false,
        }
    }
}

impl FileStatus {
    /// Create a new clean file status.
    pub fn clean() -> Self {
        Self::default()
    }

    /// Create a modified (unstaged) file status.
    pub fn modified() -> Self {
        Self {
            status: 'M',
            is_staged: false,
            is_ignored: false,
        }
    }

    /// Create a staged file status.
    pub fn staged(status: char) -> Self {
        Self {
            status,
            is_staged: true,
            is_ignored: false,
        }
    }

    /// Create an untracked file status.
    pub fn untracked() -> Self {
        Self {
            status: '?',
            is_staged: false,
            is_ignored: false,
        }
    }

    /// Create an ignored file status.
    pub fn ignored() -> Self {
        Self {
            status: '!',
            is_staged: false,
            is_ignored: true,
        }
    }

    /// Convert from git2 status flags.
    pub fn from_git2(status: git2::Status) -> Self {
        // Check index (staged) status first
        let is_staged = status.intersects(
            git2::Status::INDEX_NEW
                | git2::Status::INDEX_MODIFIED
                | git2::Status::INDEX_DELETED
                | git2::Status::INDEX_RENAMED
                | git2::Status::INDEX_TYPECHANGE,
        );

        // Determine the display character
        let status_char = if status.contains(git2::Status::IGNORED) {
            '!'
        } else if status.contains(git2::Status::WT_NEW) {
            '?'
        } else if status.contains(git2::Status::INDEX_NEW) {
            'A'
        } else if status.contains(git2::Status::INDEX_DELETED)
            || status.contains(git2::Status::WT_DELETED)
        {
            'D'
        } else if status.contains(git2::Status::INDEX_RENAMED)
            || status.contains(git2::Status::WT_RENAMED)
        {
            'R'
        } else if status.contains(git2::Status::INDEX_MODIFIED)
            || status.contains(git2::Status::WT_MODIFIED)
        {
            'M'
        } else if status.contains(git2::Status::INDEX_TYPECHANGE)
            || status.contains(git2::Status::WT_TYPECHANGE)
        {
            'T'
        } else {
            ' '
        };

        Self {
            status: status_char,
            is_staged,
            is_ignored: status.contains(git2::Status::IGNORED),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_is_clean() {
        let status = FileStatus::default();
        assert_eq!(status.status, ' ');
        assert!(!status.is_staged);
        assert!(!status.is_ignored);
    }

    #[test]
    fn test_from_git2_untracked() {
        let status = FileStatus::from_git2(git2::Status::WT_NEW);
        assert_eq!(status.status, '?');
        assert!(!status.is_staged);
    }

    #[test]
    fn test_from_git2_staged_new() {
        let status = FileStatus::from_git2(git2::Status::INDEX_NEW);
        assert_eq!(status.status, 'A');
        assert!(status.is_staged);
    }

    #[test]
    fn test_from_git2_modified() {
        let status = FileStatus::from_git2(git2::Status::WT_MODIFIED);
        assert_eq!(status.status, 'M');
        assert!(!status.is_staged);
    }
}
