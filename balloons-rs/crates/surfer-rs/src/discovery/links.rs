//! Link element discovery.

use serde::{Deserialize, Serialize};

/// Information about a link element.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LinkInfo {
    /// Index in the links list.
    pub index: usize,

    /// Visible text content.
    pub text: String,

    /// href attribute.
    pub href: String,

    /// Target attribute (_blank, _self, etc.).
    pub target: Option<String>,

    /// Title attribute.
    pub title: Option<String>,
}

impl std::fmt::Display for LinkInfo {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let truncated = if self.text.len() > 50 {
            format!("{}...", &self.text[..50])
        } else {
            self.text.clone()
        };
        write!(f, "[{}] {:?} -> {}", self.index, truncated, self.href)
    }
}
