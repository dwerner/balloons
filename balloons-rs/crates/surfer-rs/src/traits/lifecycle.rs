//! Browser lifecycle management trait.

use crate::driver::BrowserConfig;
use crate::error::SurferError;
use crate::state::BrowserState;
use async_trait::async_trait;

/// Status of the browser.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BrowserStatus {
    /// Browser is running.
    Running { pid: u32, port: u16 },
    /// State file exists but process is dead.
    Stale,
    /// No browser running.
    NotRunning,
}

/// Trait for managing browser lifecycle.
#[async_trait]
pub trait BrowserLifecycle: Send + Sync {
    /// Start a new browser instance.
    async fn start(config: &BrowserConfig) -> Result<BrowserState, SurferError>;

    /// Stop the running browser instance.
    async fn stop() -> Result<(), SurferError>;

    /// Get the current browser status.
    async fn status() -> Result<BrowserStatus, SurferError>;

    /// Check if a browser is currently running.
    async fn is_running() -> Result<bool, SurferError> {
        Ok(matches!(
            Self::status().await?,
            BrowserStatus::Running { .. }
        ))
    }
}
