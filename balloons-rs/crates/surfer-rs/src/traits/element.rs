//! Element trait for interacting with DOM elements.

use crate::error::SurferError;
use async_trait::async_trait;

/// Trait for interacting with DOM elements.
#[async_trait]
pub trait Element: Send + Sync + Clone {
    /// Get the element's tag name (e.g., "input", "button").
    async fn tag_name(&self) -> Result<String, SurferError>;

    /// Get the element's visible text content.
    async fn text(&self) -> Result<String, SurferError>;

    /// Get an attribute value by name.
    async fn attr(&self, name: &str) -> Result<Option<String>, SurferError>;

    /// Click the element.
    async fn click(&self) -> Result<(), SurferError>;

    /// Send keystrokes to the element.
    async fn send_keys(&self, text: &str) -> Result<(), SurferError>;

    /// Clear the element's value (for inputs).
    async fn clear(&self) -> Result<(), SurferError>;

    /// Check if the element is displayed/visible.
    async fn is_displayed(&self) -> Result<bool, SurferError>;

    /// Check if the element is enabled.
    async fn is_enabled(&self) -> Result<bool, SurferError>;

    /// Get the element's value attribute.
    async fn value(&self) -> Result<Option<String>, SurferError> {
        self.attr("value").await
    }
}
