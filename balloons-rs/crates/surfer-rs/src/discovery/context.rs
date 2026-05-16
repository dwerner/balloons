//! DOM context analysis.

use serde::{Deserialize, Serialize};

/// DOM context for an element.
///
/// Provides semantic context by walking up the DOM tree
/// and collecting meaningful text leading to the element.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ElementContext {
    /// Index in the result list.
    pub index: usize,

    /// Tag name of the element.
    pub tag: String,

    /// Element's text content.
    pub text: String,

    /// Semantic path from ancestors (e.g., ["form:login", "#content", "main"]).
    pub path: Vec<String>,

    /// Text trail leading to the element.
    pub text_trail: Vec<String>,
}

/// Raw context result from JavaScript.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RawContext {
    /// Semantic context path from ancestors.
    pub context: Vec<String>,
    /// Text trail leading to the element.
    #[serde(rename = "textTrail")]
    pub text_trail: Vec<String>,
}

impl ElementContext {
    /// Create from raw JavaScript result.
    pub fn from_raw(index: usize, tag: String, text: String, raw: RawContext) -> Self {
        Self {
            index,
            tag,
            text,
            path: raw.context.into_iter().rev().collect(),
            text_trail: raw.text_trail,
        }
    }

    /// Format the path as a string.
    pub fn path_str(&self) -> String {
        self.path.join(" > ")
    }
}

impl std::fmt::Display for ElementContext {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        // Path
        if !self.path.is_empty() {
            writeln!(f, "[{}] {}", self.index, self.path_str())?;
        } else {
            writeln!(f, "[{}]", self.index)?;
        }

        // Text trail
        for text in &self.text_trail {
            writeln!(f, "    \"{text}\"")?;
        }

        // The element itself
        let truncated = if self.text.len() > 50 {
            format!("{}...", &self.text[..50])
        } else {
            self.text.clone()
        };
        writeln!(f, "    -> <{}> {:?}", self.tag, truncated)?;

        Ok(())
    }
}
