//! Git-aware file browsing with status integration.
//!
//! This crate provides file system listing with git status information,
//! designed for use in the Balloons file browser UI.

mod listing;
mod repo;
mod status;

pub use listing::{list_directory, DirectoryListing, FileEntry};
pub use repo::{CommitResult, GitRepo};
pub use status::FileStatus;

use thiserror::Error;

/// Errors that can occur during git/file operations.
#[derive(Debug, Error)]
pub enum GitError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("Git error: {0}")]
    Git(#[from] git2::Error),

    #[error("Path not found: {0}")]
    PathNotFound(String),

    #[error("Not a directory: {0}")]
    NotADirectory(String),
}

pub type Result<T> = std::result::Result<T, GitError>;
