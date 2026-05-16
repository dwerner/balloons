//! Core Surfer trait for browser automation.

use crate::discovery::{ButtonInfo, ElementContext, InputInfo, LinkInfo, PageVision, Selector};
use crate::error::SurferError;
use crate::webdriver::client::NewWindowResponse;
use crate::webdriver::cookies::Cookie;
use crate::webdriver::wd::WindowHandle;
use async_trait::async_trait;

/// Core trait for browser automation.
///
/// This trait defines all the operations that can be performed on a browser,
/// including navigation, discovery, and interaction.
#[async_trait]
pub trait Surfer: Send + Sync {
    /// The element type returned by find operations.
    type Element: crate::traits::Element;

    // -------------------------------------------------------------------------
    // Navigation
    // -------------------------------------------------------------------------

    /// Navigate to a URL.
    ///
    /// If the URL doesn't start with a scheme, `https://` is prepended.
    async fn goto(&self, url: &str) -> Result<(), SurferError>;

    /// Go back in browser history.
    async fn back(&self) -> Result<(), SurferError>;

    /// Go forward in browser history.
    async fn forward(&self) -> Result<(), SurferError>;

    /// Refresh the current page.
    async fn refresh(&self) -> Result<(), SurferError>;

    /// Get the current URL.
    async fn url(&self) -> Result<String, SurferError>;

    /// Get the current page title.
    async fn title(&self) -> Result<String, SurferError>;

    // -------------------------------------------------------------------------
    // Discovery
    // -------------------------------------------------------------------------

    /// Find elements matching a selector.
    async fn find(
        &self,
        selector: impl Into<Selector> + Send,
    ) -> Result<Vec<Self::Element>, SurferError>;

    /// List all input, textarea, and select elements.
    async fn inputs(&self) -> Result<Vec<InputInfo>, SurferError>;

    /// List all buttons (including styled links).
    async fn buttons(&self) -> Result<Vec<ButtonInfo>, SurferError>;

    /// List all links.
    async fn links(&self, limit: Option<usize>) -> Result<Vec<LinkInfo>, SurferError>;

    /// Get DOM context for elements matching a selector.
    async fn context(
        &self,
        selector: impl Into<Selector> + Send,
    ) -> Result<Vec<ElementContext>, SurferError>;

    /// Get a structured view of visible page content.
    ///
    /// Returns sections (navigation, sidebar, main, forms, etc.) with their
    /// visible items. Useful for LLM understanding of page state.
    async fn see(&self) -> Result<PageVision, SurferError>;

    // -------------------------------------------------------------------------
    // Interaction by index
    // -------------------------------------------------------------------------

    /// Click a button by its index from `buttons()`.
    async fn click_button(&self, index: usize) -> Result<(), SurferError>;

    /// Set an input's value by its index from `inputs()`.
    ///
    /// Uses React-compatible value setting with input event dispatch.
    async fn set_input(&self, index: usize, value: &str) -> Result<(), SurferError>;

    /// Select an option from a dropdown by input index and option text.
    async fn select_option(&self, index: usize, value: &str) -> Result<(), SurferError>;

    /// Press Enter on an input by its index from `inputs()`.
    async fn press_enter(&self, index: usize) -> Result<(), SurferError>;

    // -------------------------------------------------------------------------
    // Interaction by selector
    // -------------------------------------------------------------------------

    /// Click an element by selector.
    async fn click(&self, selector: impl Into<Selector> + Send) -> Result<(), SurferError>;

    /// Type text into an element by selector.
    ///
    /// Clears the element first, then sends keystrokes.
    async fn type_text(
        &self,
        selector: impl Into<Selector> + Send,
        text: &str,
    ) -> Result<(), SurferError>;

    /// Fill a form field by name or id.
    async fn fill(&self, name: &str, value: &str) -> Result<(), SurferError>;

    /// Submit the first form on the page.
    async fn submit(&self) -> Result<(), SurferError>;

    /// Find a search input, type query, and submit.
    async fn search(&self, query: &str) -> Result<(), SurferError>;

    // -------------------------------------------------------------------------
    // Utilities
    // -------------------------------------------------------------------------

    /// Take a screenshot and return PNG bytes.
    async fn screenshot(&self) -> Result<Vec<u8>, SurferError>;

    /// Execute JavaScript and return the result.
    async fn execute_js(&self, script: &str) -> Result<serde_json::Value, SurferError>;

    /// Get the page HTML source.
    async fn html(&self) -> Result<String, SurferError>;

    // -------------------------------------------------------------------------
    // Cookies
    // -------------------------------------------------------------------------

    /// Get all cookies for the current page.
    async fn get_cookies(&self) -> Result<Vec<Cookie<'static>>, SurferError>;

    /// Get a specific cookie by name.
    async fn get_cookie(&self, name: &str) -> Result<Option<Cookie<'static>>, SurferError>;

    /// Set a cookie.
    async fn set_cookie(&self, cookie: Cookie<'static>) -> Result<(), SurferError>;

    /// Delete a specific cookie by name.
    async fn delete_cookie(&self, name: &str) -> Result<(), SurferError>;

    /// Delete all cookies.
    async fn delete_all_cookies(&self) -> Result<(), SurferError>;

    // -------------------------------------------------------------------------
    // Frames
    // -------------------------------------------------------------------------

    /// Enter an iframe by index.
    async fn enter_frame(&self, index: u16) -> Result<(), SurferError>;

    /// Return to the parent frame.
    async fn enter_parent_frame(&self) -> Result<(), SurferError>;

    // -------------------------------------------------------------------------
    // Windows/Tabs
    // -------------------------------------------------------------------------

    /// Get the current window handle.
    async fn current_window(&self) -> Result<WindowHandle, SurferError>;

    /// Get all window handles.
    async fn windows(&self) -> Result<Vec<WindowHandle>, SurferError>;

    /// Switch to a different window/tab.
    async fn switch_to_window(&self, handle: WindowHandle) -> Result<(), SurferError>;

    /// Open a new window or tab.
    async fn new_window(&self, as_tab: bool) -> Result<NewWindowResponse, SurferError>;

    /// Close the current window/tab.
    async fn close_window(&self) -> Result<(), SurferError>;

    // -------------------------------------------------------------------------
    // Storage
    // -------------------------------------------------------------------------

    /// Get a value from localStorage.
    async fn local_storage_get(&self, key: &str) -> Result<Option<String>, SurferError>;

    /// Set a value in localStorage.
    async fn local_storage_set(&self, key: &str, value: &str) -> Result<(), SurferError>;

    /// Get a value from sessionStorage.
    async fn session_storage_get(&self, key: &str) -> Result<Option<String>, SurferError>;

    /// Set a value in sessionStorage.
    async fn session_storage_set(&self, key: &str, value: &str) -> Result<(), SurferError>;
}
