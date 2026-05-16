//! Browser state data structure.

use crate::driver::BrowserType;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

/// Persistent state for a managed browser instance.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BrowserState {
    /// Process ID of the WebDriver or browser.
    pub pid: u32,

    /// Port the WebDriver is listening on.
    pub port: u16,

    /// Type of browser.
    pub browser_type: BrowserType,

    /// URL to connect to WebDriver.
    pub webdriver_url: String,

    /// When the browser was started.
    pub started_at: DateTime<Utc>,

    /// Whether running in headless mode.
    #[serde(default)]
    pub headless: bool,
}

impl BrowserState {
    /// Create a new browser state.
    pub fn new(pid: u32, port: u16, browser_type: BrowserType, headless: bool) -> Self {
        Self {
            pid,
            port,
            browser_type,
            webdriver_url: format!("http://localhost:{port}"),
            started_at: Utc::now(),
            headless,
        }
    }
}
