pub mod backup;
pub mod generated;
pub mod recovery;
pub mod storage;

#[cfg(test)]
mod testutil;

pub use generated::{
    ReviewData, SessionData, SessionMetadata, TurnData, TurnOrder, UserData, UserPrefs,
    WatcherRelation,
};

pub use storage::{Error, LmdbEngine, Result, StorageClient, StorageEngine};
pub use recovery::{recover_database, RecoveryResult};
pub use backup::{
    create_backup, export_to_json, health_check, import_from_json, list_backups,
    restore_from_backup, BackupError, BackupResult, ExportResult, HealthReport, ImportResult,
};
