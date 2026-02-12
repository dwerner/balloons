pub mod generated;
pub mod recovery;
pub mod storage;

#[cfg(test)]
mod testutil;

// Re-export schema types from generated module
pub use generated::{SessionData, SessionMetadata, TurnData, TurnOrder};

// Re-export storage types
pub use storage::{Error, LmdbEngine, Result, StorageClient, StorageEngine};

// Re-export recovery utilities
pub use recovery::{recover_database, RecoveryResult};
