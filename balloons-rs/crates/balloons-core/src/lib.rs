pub mod backup;
pub mod generated;
pub mod recovery;
pub mod storage;

#[cfg(test)]
mod testutil;

// Re-export schema types from generated module
pub use generated::{
    BoardData, ColumnData, EdgeData, GoalData, PlanData, SessionBinding, SessionData,
    SessionMetadata, TaskData, TodoData, TodoDependency, TodoPlanLink, TurnData, TurnOrder,
    UserData, UserPrefs, WatcherRelation,
};

// Re-export storage types
pub use storage::{Error, LmdbEngine, Result, StorageClient, StorageEngine};

// Re-export recovery utilities
pub use recovery::{recover_database, RecoveryResult};

// Re-export backup utilities
pub use backup::{
    create_backup, export_to_json, health_check, import_from_json, list_backups,
    restore_from_backup, BackupError, BackupResult, ExportResult, HealthReport, ImportResult,
};
