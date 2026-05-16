//! Page vision - extract visible structure for LLM/human understanding.

use serde::{Deserialize, Serialize};
use std::fmt;

/// A section of visible content on the page.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PageSection {
    /// Section type (Navigation, Sidebar, Main, Form, Input, etc.)
    pub kind: String,
    /// Section label/heading if present
    pub label: Option<String>,
    /// Items within this section
    pub items: Vec<PageItem>,
}

impl PageSection {
    pub fn new(kind: impl Into<String>) -> Self {
        Self {
            kind: kind.into(),
            label: None,
            items: Vec::new(),
        }
    }

    pub fn with_label(mut self, label: impl Into<String>) -> Self {
        self.label = Some(label.into());
        self
    }

    pub fn with_items(mut self, items: Vec<PageItem>) -> Self {
        self.items = items;
        self
    }

    pub fn push(&mut self, item: PageItem) {
        self.items.push(item);
    }

    pub fn is_empty(&self) -> bool {
        self.items.is_empty()
    }
}

/// An item within a section.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PageItem {
    /// Item type (link, button, text, input, item, heading, etc.)
    pub kind: String,
    /// Visible text
    pub text: String,
    /// Index for interactive elements (links, buttons, inputs) - used with click(index), set_input(index), etc.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub index: Option<usize>,
    /// Additional state info (selected, active, disabled, etc.)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub state: Option<String>,
    /// For links: the href
    #[serde(skip_serializing_if = "Option::is_none")]
    pub href: Option<String>,
    /// For inputs: the input type and current value
    #[serde(skip_serializing_if = "Option::is_none")]
    pub input_type: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub value: Option<String>,
}

impl PageItem {
    pub fn new(kind: impl Into<String>, text: impl Into<String>) -> Self {
        Self {
            kind: kind.into(),
            text: text.into(),
            index: None,
            state: None,
            href: None,
            input_type: None,
            value: None,
        }
    }

    pub fn with_index(mut self, index: usize) -> Self {
        self.index = Some(index);
        self
    }

    pub fn with_state(mut self, state: impl Into<String>) -> Self {
        self.state = Some(state.into());
        self
    }

    pub fn with_href(mut self, href: impl Into<String>) -> Self {
        self.href = Some(href.into());
        self
    }

    pub fn with_input_type(mut self, input_type: impl Into<String>) -> Self {
        self.input_type = Some(input_type.into());
        self
    }

    pub fn with_value(mut self, value: impl Into<String>) -> Self {
        self.value = Some(value.into());
        self
    }
}

/// Complete visible page structure.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PageVision {
    /// Page title
    pub title: String,
    /// Current URL
    pub url: String,
    /// Main sections of the page
    pub sections: Vec<PageSection>,
}

impl PageVision {
    pub fn new(title: String, url: String) -> Self {
        Self {
            title,
            url,
            sections: Vec::new(),
        }
    }

    pub fn push(&mut self, section: PageSection) {
        if !section.is_empty() {
            self.sections.push(section);
        }
    }
}

impl fmt::Display for PageVision {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{}",
            serde_json::to_string_pretty(self).unwrap_or_default()
        )
    }
}

/// Truncate text to max length, adding ellipsis if needed.
pub fn truncate(text: &str, max: usize) -> String {
    let text = text.trim();
    if text.len() <= max {
        text.to_string()
    } else {
        format!("{}...", &text[..max.saturating_sub(3)])
    }
}

/// Check if classes contain any of the given patterns.
pub fn has_class_pattern(classes: &str, patterns: &[&str]) -> bool {
    let classes_lower = classes.to_lowercase();
    patterns.iter().any(|p| classes_lower.contains(p))
}

/// Detect element state from classes and attributes.
pub fn detect_state(
    classes: Option<&str>,
    aria_selected: Option<&str>,
    aria_current: Option<&str>,
    disabled: bool,
) -> Option<String> {
    let mut states = Vec::new();

    if disabled {
        states.push("disabled");
    }

    if let Some(sel) = aria_selected {
        if sel == "true" {
            states.push("selected");
        }
    }

    if aria_current.is_some() {
        states.push("current");
    }

    if let Some(cls) = classes {
        let cls = cls.to_lowercase();
        if (cls.contains("active") || cls.contains("selected") || cls.contains("current"))
            && !states.contains(&"selected")
            && !states.contains(&"current")
        {
            states.push("selected");
        }
    }

    if states.is_empty() {
        None
    } else {
        Some(states.join(", "))
    }
}
