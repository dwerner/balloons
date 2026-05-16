//! Input element discovery.

use serde::{Deserialize, Serialize};

/// Information about an input element.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InputInfo {
    /// Index in the inputs list.
    pub index: usize,

    /// Tag name (input, textarea, select).
    pub tag: String,

    /// Input type (text, password, email, etc.).
    pub input_type: String,

    /// Name attribute.
    pub name: Option<String>,

    /// ID attribute.
    pub id: Option<String>,

    /// Placeholder text.
    pub placeholder: Option<String>,

    /// Current value.
    pub value: Option<String>,

    /// Whether the input is required.
    pub required: bool,

    /// Whether the input is disabled.
    pub disabled: bool,

    /// Aria-label attribute.
    pub aria_label: Option<String>,
}

impl InputInfo {
    /// Get a descriptive label for the input.
    pub fn description(&self) -> String {
        // Priority: placeholder > name > id > type
        let base = self
            .placeholder
            .as_deref()
            .or(self.name.as_deref())
            .or(self.id.as_deref())
            .unwrap_or(&self.input_type);

        if let Some(value) = &self.value {
            if !value.is_empty() && value != base {
                let truncated = if value.len() > 20 {
                    format!("{}...", &value[..20])
                } else {
                    value.clone()
                };
                return format!("{base} [{truncated}]");
            }
        }

        base.to_string()
    }
}

impl std::fmt::Display for InputInfo {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "[{}] {}", self.index, self.description())
    }
}
