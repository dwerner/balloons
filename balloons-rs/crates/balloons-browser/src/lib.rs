//! Browser automation for Balloons using surfer-rs.
//!
//! This crate wraps surfer-rs with the smol runtime, providing browser
//! automation capabilities that integrate with core-executor.

use serde::{Deserialize, Serialize};
use surfer_rs::{
    BrowserConfig as SurferConfig, BrowserType, ButtonInfo, InputInfo, LinkInfo, Surfer,
    SurferError, WebDriverSurfer, start_driver, stop_driver,
};
use thiserror::Error;
use uuid::Uuid;

pub use surfer_rs::BrowserType as BrowserKind;
// Re-export types needed for public API
pub use surfer_rs::Cookie;
pub use surfer_rs::NewWindowResponse;
pub use surfer_rs::{PageItem, PageSection, PageVision};
pub use surfer_rs::WindowHandle;

/// Browser automation errors
#[derive(Error, Debug)]
pub enum BrowserError {
    #[error("Surfer error: {0}")]
    Surfer(#[from] SurferError),

    #[error("Browser not connected")]
    NotConnected,

    #[error("Invalid selector: {0}")]
    InvalidSelector(String),

    #[error("Element not found: {0}")]
    ElementNotFound(String),

    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),
}

/// Configuration for browser instances
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BrowserConfig {
    /// Browser type (Firefox, Chrome, etc.)
    pub browser_type: String,

    /// WebDriver URL (e.g., http://localhost:4444)
    pub webdriver_url: Option<String>,

    /// Run in headless mode
    pub headless: bool,

    /// WebDriver port (defaults to 4444)
    pub port: u16,
}

impl Default for BrowserConfig {
    fn default() -> Self {
        Self {
            browser_type: "firefox".to_string(),
            webdriver_url: None,
            headless: false,
            port: 4444,
        }
    }
}

impl BrowserConfig {
    /// Create config for Firefox
    pub fn firefox() -> Self {
        Self {
            browser_type: "firefox".to_string(),
            ..Default::default()
        }
    }

    /// Create config for Chrome
    pub fn chrome() -> Self {
        Self {
            browser_type: "chrome".to_string(),
            ..Default::default()
        }
    }

    /// Set headless mode
    pub fn with_headless(mut self, headless: bool) -> Self {
        self.headless = headless;
        self
    }

    /// Set WebDriver port
    pub fn with_port(mut self, port: u16) -> Self {
        self.port = port;
        self
    }

    /// Set WebDriver URL
    pub fn with_webdriver_url(mut self, url: impl Into<String>) -> Self {
        self.webdriver_url = Some(url.into());
        self
    }

    /// Convert to surfer-rs config
    fn to_surfer_config(&self) -> SurferConfig {
        let browser_type = match self.browser_type.to_lowercase().as_str() {
            "chrome" | "chromium" => BrowserType::Chrome,
            _ => BrowserType::Firefox,
        };

        let mut config = SurferConfig::new(browser_type)
            .with_port(self.port)
            .with_headless(self.headless);

        if let Some(ref url) = self.webdriver_url {
            config = config.with_webdriver_url(url);
        }

        config
    }
}

/// Information about a discovered input element
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Input {
    pub index: usize,
    pub tag: String,
    pub input_type: String,
    pub name: Option<String>,
    pub id: Option<String>,
    pub placeholder: Option<String>,
    pub value: Option<String>,
    pub required: bool,
    pub disabled: bool,
    pub aria_label: Option<String>,
}

impl From<InputInfo> for Input {
    fn from(info: InputInfo) -> Self {
        Self {
            index: info.index,
            tag: info.tag,
            input_type: info.input_type,
            name: info.name,
            id: info.id,
            placeholder: info.placeholder,
            value: info.value,
            required: info.required,
            disabled: info.disabled,
            aria_label: info.aria_label,
        }
    }
}

/// Information about a discovered button element
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Button {
    pub index: usize,
    pub tag: String,
    pub button_type: Option<String>,
    pub text: String,
    pub value: Option<String>,
    pub disabled: bool,
    pub role: Option<String>,
    pub classes: Option<String>,
}

impl From<ButtonInfo> for Button {
    fn from(info: ButtonInfo) -> Self {
        Self {
            index: info.index,
            tag: info.tag,
            button_type: info.button_type,
            text: info.text,
            value: info.value,
            disabled: info.disabled,
            role: info.role,
            classes: info.classes,
        }
    }
}

/// Information about a discovered link element
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Link {
    pub index: usize,
    pub text: String,
    pub href: String,
    pub target: Option<String>,
    pub title: Option<String>,
}

impl From<LinkInfo> for Link {
    fn from(info: LinkInfo) -> Self {
        Self {
            index: info.index,
            text: info.text,
            href: info.href,
            target: info.target,
            title: info.title,
        }
    }
}

/// A browser instance for automation
pub struct Browser {
    id: String,
    config: BrowserConfig,
    surfer: Option<WebDriverSurfer>,
}

impl Browser {
    /// Create a new browser instance (not yet connected)
    pub fn new(config: BrowserConfig) -> Self {
        Self {
            id: Uuid::new_v4().to_string(),
            config,
            surfer: None,
        }
    }

    /// Get the browser ID
    pub fn id(&self) -> &str {
        &self.id
    }

    /// Get the browser config
    pub fn config(&self) -> &BrowserConfig {
        &self.config
    }

    /// Check if browser is connected
    pub fn is_connected(&self) -> bool {
        self.surfer.is_some()
    }

    /// Connect to the browser (starts webdriver and browser)
    pub async fn connect(&mut self) -> Result<(), BrowserError> {
        let surfer_config = self.config.to_surfer_config();
        // Only start the WebDriver process if we're not connecting to a remote one
        if self.config.webdriver_url.is_none() {
            start_driver(&surfer_config).await?;
        }
        // Then connect to it
        let surfer = WebDriverSurfer::connect(&surfer_config).await?;
        self.surfer = Some(surfer);
        Ok(())
    }

    /// Disconnect and close the browser
    pub async fn disconnect(&mut self) -> Result<(), BrowserError> {
        if let Some(surfer) = self.surfer.take() {
            surfer.close().await?;
        }
        // Only stop the WebDriver process if we started it locally
        if self.config.webdriver_url.is_none() {
            stop_driver().await?;
        }
        Ok(())
    }

    /// Get the surfer instance (for internal use)
    fn surfer(&self) -> Result<&WebDriverSurfer, BrowserError> {
        self.surfer.as_ref().ok_or(BrowserError::NotConnected)
    }

    /// Navigate to a URL
    pub async fn goto(&self, url: &str) -> Result<(), BrowserError> {
        self.surfer()?.goto(url).await?;
        Ok(())
    }

    /// Go back in history
    pub async fn back(&self) -> Result<(), BrowserError> {
        self.surfer()?.back().await?;
        Ok(())
    }

    /// Go forward in history
    pub async fn forward(&self) -> Result<(), BrowserError> {
        self.surfer()?.forward().await?;
        Ok(())
    }

    /// Refresh the page
    pub async fn refresh(&self) -> Result<(), BrowserError> {
        self.surfer()?.refresh().await?;
        Ok(())
    }

    /// Get the current URL
    pub async fn url(&self) -> Result<String, BrowserError> {
        let url = self.surfer()?.url().await?;
        Ok(url.to_string())
    }

    /// Get the page title
    pub async fn title(&self) -> Result<String, BrowserError> {
        let title = self.surfer()?.title().await?;
        Ok(title)
    }

    /// Get the page HTML
    pub async fn html(&self) -> Result<String, BrowserError> {
        let html = self.surfer()?.html().await?;
        Ok(html)
    }

    /// Take a screenshot (returns PNG bytes)
    pub async fn screenshot(&self) -> Result<Vec<u8>, BrowserError> {
        let bytes = self.surfer()?.screenshot().await?;
        Ok(bytes)
    }

    /// Click an element by CSS selector
    pub async fn click(&self, selector: &str) -> Result<(), BrowserError> {
        self.surfer()?.click(selector).await?;
        Ok(())
    }

    /// Fill an input by CSS selector
    pub async fn fill(&self, selector: &str, text: &str) -> Result<(), BrowserError> {
        self.surfer()?.fill(selector, text).await?;
        Ok(())
    }

    /// Type text into an element (without clearing first)
    pub async fn type_text(&self, selector: &str, text: &str) -> Result<(), BrowserError> {
        self.surfer()?.type_text(selector, text).await?;
        Ok(())
    }

    /// Submit the currently focused form
    pub async fn submit(&self) -> Result<(), BrowserError> {
        self.surfer()?.submit().await?;
        Ok(())
    }

    /// Discover all input elements on the page
    pub async fn inputs(&self) -> Result<Vec<Input>, BrowserError> {
        let inputs = self.surfer()?.inputs().await?;
        Ok(inputs.into_iter().map(Input::from).collect())
    }

    /// Discover all button elements on the page
    pub async fn buttons(&self) -> Result<Vec<Button>, BrowserError> {
        let buttons = self.surfer()?.buttons().await?;
        Ok(buttons.into_iter().map(Button::from).collect())
    }

    /// Discover all link elements on the page (optionally limited)
    pub async fn links(&self, limit: Option<usize>) -> Result<Vec<Link>, BrowserError> {
        let links = self.surfer()?.links(limit).await?;
        Ok(links.into_iter().map(Link::from).collect())
    }

    /// Click a button by index (from buttons() discovery)
    pub async fn click_button(&self, index: usize) -> Result<(), BrowserError> {
        self.surfer()?.click_button(index).await?;
        Ok(())
    }

    /// Set an input by index (from inputs() discovery)
    pub async fn set_input(&self, index: usize, value: &str) -> Result<(), BrowserError> {
        self.surfer()?.set_input(index, value).await?;
        Ok(())
    }

    /// Execute JavaScript and return the result as JSON
    pub async fn execute_js(&self, script: &str) -> Result<serde_json::Value, BrowserError> {
        let result = self.surfer()?.execute_js(script).await?;
        Ok(result)
    }

    /// Get a structured view of visible page content (PageVision)
    ///
    /// Returns semantic sections (Navigation, Sidebar, Content, Form, Messages, etc.)
    /// with their visible items. Useful for LLM understanding of page state.
    pub async fn see(&self) -> Result<surfer_rs::PageVision, BrowserError> {
        let vision = self.surfer()?.see().await?;
        Ok(vision)
    }

    // -------------------------------------------------------------------------
    // Additional Interaction Methods
    // -------------------------------------------------------------------------

    /// Select an option from a dropdown by input index and option text
    pub async fn select_option(&self, index: usize, value: &str) -> Result<(), BrowserError> {
        self.surfer()?.select_option(index, value).await?;
        Ok(())
    }

    /// Press Enter on an input by its index from inputs()
    pub async fn press_enter(&self, index: usize) -> Result<(), BrowserError> {
        self.surfer()?.press_enter(index).await?;
        Ok(())
    }

    /// Find a search input, type query, and submit
    pub async fn search(&self, query: &str) -> Result<(), BrowserError> {
        self.surfer()?.search(query).await?;
        Ok(())
    }

    // -------------------------------------------------------------------------
    // Cookies
    // -------------------------------------------------------------------------

    /// Get all cookies for the current page
    pub async fn get_cookies(&self) -> Result<Vec<Cookie<'static>>, BrowserError> {
        let cookies = self.surfer()?.get_cookies().await?;
        Ok(cookies)
    }

    /// Get a specific cookie by name
    pub async fn get_cookie(&self, name: &str) -> Result<Option<Cookie<'static>>, BrowserError> {
        let cookie = self.surfer()?.get_cookie(name).await?;
        Ok(cookie)
    }

    /// Set a cookie
    pub async fn set_cookie(&self, cookie: Cookie<'static>) -> Result<(), BrowserError> {
        self.surfer()?.set_cookie(cookie).await?;
        Ok(())
    }

    /// Delete a specific cookie by name
    pub async fn delete_cookie(&self, name: &str) -> Result<(), BrowserError> {
        self.surfer()?.delete_cookie(name).await?;
        Ok(())
    }

    /// Delete all cookies
    pub async fn delete_all_cookies(&self) -> Result<(), BrowserError> {
        self.surfer()?.delete_all_cookies().await?;
        Ok(())
    }

    // -------------------------------------------------------------------------
    // Frames
    // -------------------------------------------------------------------------

    /// Enter an iframe by index
    pub async fn enter_frame(&self, index: u16) -> Result<(), BrowserError> {
        self.surfer()?.enter_frame(index).await?;
        Ok(())
    }

    /// Return to the parent frame
    pub async fn enter_parent_frame(&self) -> Result<(), BrowserError> {
        self.surfer()?.enter_parent_frame().await?;
        Ok(())
    }

    // -------------------------------------------------------------------------
    // Windows/Tabs
    // -------------------------------------------------------------------------

    /// Get the current window handle
    pub async fn current_window(&self) -> Result<WindowHandle, BrowserError> {
        let handle = self.surfer()?.current_window().await?;
        Ok(handle)
    }

    /// Get all window handles
    pub async fn windows(&self) -> Result<Vec<WindowHandle>, BrowserError> {
        let handles = self.surfer()?.windows().await?;
        Ok(handles)
    }

    /// Switch to a different window/tab
    pub async fn switch_to_window(&self, handle: WindowHandle) -> Result<(), BrowserError> {
        self.surfer()?.switch_to_window(handle).await?;
        Ok(())
    }

    /// Open a new window or tab
    pub async fn new_window(&self, as_tab: bool) -> Result<NewWindowResponse, BrowserError> {
        let response = self.surfer()?.new_window(as_tab).await?;
        Ok(response)
    }

    /// Close the current window/tab
    pub async fn close_window(&self) -> Result<(), BrowserError> {
        self.surfer()?.close_window().await?;
        Ok(())
    }

    // -------------------------------------------------------------------------
    // Storage
    // -------------------------------------------------------------------------

    /// Get a value from localStorage
    pub async fn local_storage_get(&self, key: &str) -> Result<Option<String>, BrowserError> {
        let value = self.surfer()?.local_storage_get(key).await?;
        Ok(value)
    }

    /// Set a value in localStorage
    pub async fn local_storage_set(&self, key: &str, value: &str) -> Result<(), BrowserError> {
        self.surfer()?.local_storage_set(key, value).await?;
        Ok(())
    }

    /// Get a value from sessionStorage
    pub async fn session_storage_get(&self, key: &str) -> Result<Option<String>, BrowserError> {
        let value = self.surfer()?.session_storage_get(key).await?;
        Ok(value)
    }

    /// Set a value in sessionStorage
    pub async fn session_storage_set(&self, key: &str, value: &str) -> Result<(), BrowserError> {
        self.surfer()?.session_storage_set(key, value).await?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_config_defaults() {
        let config = BrowserConfig::default();
        assert_eq!(config.browser_type, "firefox");
        assert!(!config.headless);
        assert_eq!(config.port, 4444);
    }

    #[test]
    fn test_config_builder() {
        let config = BrowserConfig::chrome()
            .with_headless(true)
            .with_port(9515);
        assert_eq!(config.browser_type, "chrome");
        assert!(config.headless);
        assert_eq!(config.port, 9515);
    }
}
