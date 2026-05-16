//! # Surfer
//!
//! Async browser automation crate with runtime agnosticism.
//!
//! ## Features
//!
//! - `smol-runtime` - Use the built-in smol runtime support (default)
//! - `cli` - Build the CLI binary
//!
//! ## Example
//!
//! ```rust,ignore
//! use surfer_rs::{WebDriverSurfer, Surfer, BrowserConfig};
//!
//! # smol::block_on(async {
//! let result: Result<(), surfer_rs::SurferError> = async {
//!     let config = BrowserConfig::default();
//!     let browser = WebDriverSurfer::connect(&config).await?;
//!
//!     browser.goto("https://example.com").await?;
//!     let inputs = browser.inputs().await?;
//!
//!     Ok(())
//! }.await;
//! # result
//! # });
//! ```

pub mod discovery;
pub mod driver;
pub mod error;
pub mod lifecycle;
pub mod runtime;
pub mod state;
pub mod traits;
pub mod webdriver;

// Re-exports for convenience
pub use discovery::{
    ButtonInfo, ElementContext, InputInfo, LinkInfo, PageItem, PageSection, PageVision,
};
pub use driver::{BrowserConfig, BrowserType, WebDriverElement, WebDriverSurfer};
pub use error::SurferError;
pub use lifecycle::{
    driver_status_by_pid, find_driver, is_driver_running, start_driver, stop_driver_by_pid,
};
pub use state::BrowserState;
pub use traits::lifecycle::BrowserStatus;
pub use traits::{BrowserLifecycle, Element, Surfer};

// Re-export WebDriver client types used in the public API
pub use webdriver::client::NewWindowResponse;
pub use webdriver::cookies::Cookie;
pub use webdriver::wd::WindowHandle;
