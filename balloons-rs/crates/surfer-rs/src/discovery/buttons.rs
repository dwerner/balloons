//! Button element discovery.

use serde::{Deserialize, Serialize};

/// Information about a button element.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ButtonInfo {
    /// Index in the buttons list.
    pub index: usize,

    /// Tag name (button, input, a).
    pub tag: String,

    /// Button type (submit, button, reset) for button/input elements.
    pub button_type: Option<String>,

    /// Visible text content.
    pub text: String,

    /// Value attribute (for input buttons).
    pub value: Option<String>,

    /// Whether the button is disabled.
    pub disabled: bool,

    /// ARIA role if present.
    pub role: Option<String>,

    /// CSS classes (for styled links).
    pub classes: Option<String>,
}

impl ButtonInfo {
    /// Get the display text for the button.
    pub fn display_text(&self) -> &str {
        if !self.text.is_empty() {
            &self.text
        } else if let Some(value) = &self.value {
            value
        } else {
            ""
        }
    }
}

impl std::fmt::Display for ButtonInfo {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let text = self.display_text();
        let truncated = if text.len() > 60 {
            format!("{}...", &text[..60])
        } else {
            text.replace('\n', " ")
        };
        write!(f, "[{}] <{}> {:?}", self.index, self.tag, truncated)
    }
}
