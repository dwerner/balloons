//! WebDriver Element implementation.

use crate::error::SurferError;
use crate::traits::Element;
use crate::webdriver::elements::Element as WaveElement;
use async_trait::async_trait;

/// WebDriver element wrapper.
#[derive(Clone)]
pub struct WebDriverElement {
    inner: WaveElement,
}

impl WebDriverElement {
    /// Create a new WebDriverElement from a webdriver element.
    pub fn new(element: WaveElement) -> Self {
        Self { inner: element }
    }

    /// Get the inner webdriver element.
    pub fn inner(&self) -> &WaveElement {
        &self.inner
    }
}

impl std::fmt::Debug for WebDriverElement {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("WebDriverElement").finish_non_exhaustive()
    }
}

#[async_trait]
impl Element for WebDriverElement {
    async fn tag_name(&self) -> Result<String, SurferError> {
        self.inner
            .tag_name()
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))
    }

    async fn text(&self) -> Result<String, SurferError> {
        self.inner
            .text()
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))
    }

    async fn attr(&self, name: &str) -> Result<Option<String>, SurferError> {
        self.inner
            .attr(name)
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))
    }

    async fn click(&self) -> Result<(), SurferError> {
        self.inner
            .click()
            .await
            .map_err(|e| SurferError::InteractionFailed(e.to_string()))
    }

    async fn send_keys(&self, text: &str) -> Result<(), SurferError> {
        self.inner
            .send_keys(text)
            .await
            .map_err(|e| SurferError::InteractionFailed(e.to_string()))
    }

    async fn clear(&self) -> Result<(), SurferError> {
        self.inner
            .clear()
            .await
            .map_err(|e| SurferError::InteractionFailed(e.to_string()))
    }

    async fn is_displayed(&self) -> Result<bool, SurferError> {
        self.inner
            .is_displayed()
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))
    }

    async fn is_enabled(&self) -> Result<bool, SurferError> {
        self.inner
            .is_enabled()
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))
    }
}
