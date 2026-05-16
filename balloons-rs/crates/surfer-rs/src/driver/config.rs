//! Browser configuration.

use serde::{Deserialize, Serialize};

/// Type of browser to use.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum BrowserType {
    /// Mozilla Firefox (via geckodriver).
    #[default]
    Firefox,
    /// Google Chrome (via chromedriver).
    Chrome,
}

impl BrowserType {
    /// Get the WebDriver binary name for this browser.
    pub fn driver_binary(&self) -> &'static str {
        match self {
            BrowserType::Firefox => "geckodriver",
            BrowserType::Chrome => "chromedriver",
        }
    }

    /// Get the browser binary names to search for.
    pub fn browser_binaries(&self) -> &'static [&'static str] {
        match self {
            BrowserType::Firefox => &["firefox", "librewolf", "firefox-esr"],
            BrowserType::Chrome => &["google-chrome", "chromium", "chromium-browser"],
        }
    }
}

impl std::fmt::Display for BrowserType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            BrowserType::Firefox => write!(f, "firefox"),
            BrowserType::Chrome => write!(f, "chrome"),
        }
    }
}

impl std::str::FromStr for BrowserType {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "firefox" | "ff" => Ok(BrowserType::Firefox),
            "chrome" | "chromium" => Ok(BrowserType::Chrome),
            _ => Err(format!("unknown browser: {s}")),
        }
    }
}

/// Configuration for browser automation.
#[derive(Debug, Clone)]
pub struct BrowserConfig {
    /// Type of browser to use.
    pub browser_type: BrowserType,

    /// Port for WebDriver.
    pub port: u16,

    /// Run browser in headless mode.
    pub headless: bool,

    /// WebDriver URL to connect to.
    /// If set, assumes WebDriver is already running.
    pub webdriver_url: Option<String>,
}

impl Default for BrowserConfig {
    fn default() -> Self {
        Self {
            browser_type: BrowserType::Firefox,
            port: 4444,
            headless: false,
            webdriver_url: None,
        }
    }
}

impl BrowserConfig {
    /// Create a new config with the specified browser type.
    pub fn new(browser_type: BrowserType) -> Self {
        Self {
            browser_type,
            ..Default::default()
        }
    }

    /// Set the port.
    pub fn with_port(mut self, port: u16) -> Self {
        self.port = port;
        self
    }

    /// Set headless mode.
    pub fn with_headless(mut self, headless: bool) -> Self {
        self.headless = headless;
        self
    }

    /// Set WebDriver URL (for connecting to existing instance).
    pub fn with_webdriver_url(mut self, url: impl Into<String>) -> Self {
        self.webdriver_url = Some(url.into());
        self
    }

    /// Get the WebDriver URL.
    pub fn webdriver_url(&self) -> String {
        self.webdriver_url
            .clone()
            .unwrap_or_else(|| format!("http://localhost:{}", self.port))
    }
}
