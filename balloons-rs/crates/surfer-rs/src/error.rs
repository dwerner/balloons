//! Error types for the surfer crate.

use thiserror::Error;

/// Main error type for surfer operations.
#[derive(Error, Debug)]
pub enum SurferError {
    /// Failed to connect to WebDriver.
    #[error("failed to connect to WebDriver at {url}: {message}")]
    ConnectionFailed { url: String, message: String },

    /// WebDriver session error.
    #[error("WebDriver session error: {0}")]
    SessionError(String),

    /// Navigation error.
    #[error("navigation failed: {0}")]
    NavigationFailed(String),

    /// Element not found.
    #[error("element not found: {selector}")]
    ElementNotFound { selector: String },

    /// Element index out of range.
    #[error("element index {index} out of range (0-{max})")]
    IndexOutOfRange { index: usize, max: usize },

    /// Invalid selector.
    #[error("invalid selector: {0}")]
    InvalidSelector(String),

    /// JavaScript execution error.
    #[error("JavaScript error: {0}")]
    JavaScriptError(String),

    /// Element interaction failed.
    #[error("interaction failed on element: {0}")]
    InteractionFailed(String),

    /// Browser not running.
    #[error("browser not running")]
    BrowserNotRunning,

    /// Browser already running.
    #[error("browser already running (pid {pid}, port {port})")]
    BrowserAlreadyRunning { pid: u32, port: u16 },

    /// Failed to start browser.
    #[error("failed to start browser: {0}")]
    BrowserStartFailed(String),

    /// Failed to stop browser.
    #[error("failed to stop browser: {0}")]
    BrowserStopFailed(String),

    /// Browser binary not found.
    #[error("browser binary not found: tried {tried:?}")]
    BrowserNotFound { tried: Vec<String> },

    /// State file error.
    #[error("state file error: {0}")]
    StateError(String),

    /// IO error.
    #[error("IO error: {0}")]
    IoError(#[from] std::io::Error),

    /// JSON serialization/deserialization error.
    #[error("JSON error: {0}")]
    JsonError(#[from] serde_json::Error),

    /// URL parsing error.
    #[error("invalid URL: {0}")]
    UrlError(#[from] url::ParseError),

    /// Timeout waiting for operation.
    #[error("timeout: {0}")]
    Timeout(String),

    /// Screenshot error.
    #[error("screenshot failed: {0}")]
    ScreenshotFailed(String),

    /// Form not found.
    #[error("no form found on page")]
    FormNotFound,

    /// Search input not found.
    #[error("no search input found on page")]
    SearchInputNotFound,

    /// Element is not the expected type.
    #[error("element at index {index} is not a {expected}, got {actual}")]
    WrongElementType {
        index: usize,
        expected: String,
        actual: String,
    },
}

/// Result type alias for surfer operations.
pub type Result<T> = std::result::Result<T, SurferError>;
