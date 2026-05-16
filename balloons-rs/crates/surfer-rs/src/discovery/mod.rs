//! Element discovery and DOM context analysis.

mod buttons;
pub mod context;
mod inputs;
mod links;
pub mod vision;

pub use buttons::ButtonInfo;
pub use context::{ElementContext, RawContext};
pub use inputs::InputInfo;
pub use links::LinkInfo;
pub use vision::{PageItem, PageSection, PageVision, detect_state, has_class_pattern, truncate};

/// Selector for finding elements.
#[derive(Debug, Clone)]
pub enum Selector {
    /// CSS selector.
    Css(String),
    /// XPath selector.
    XPath(String),
}

impl Selector {
    /// Create a CSS selector.
    pub fn css(s: impl Into<String>) -> Self {
        Self::Css(s.into())
    }

    /// Create an XPath selector.
    pub fn xpath(s: impl Into<String>) -> Self {
        Self::XPath(s.into())
    }
}

impl From<&str> for Selector {
    fn from(s: &str) -> Self {
        Self::Css(s.to_string())
    }
}

impl From<String> for Selector {
    fn from(s: String) -> Self {
        Self::Css(s)
    }
}

/// CSS selector for buttons (including styled links).
pub const BUTTON_SELECTOR: &str = concat!(
    "button, ",
    "input[type='submit'], ",
    "input[type='button'], ",
    "[role='button'], ",
    "a[class*='btn'], ",
    "a[class*='button']"
);

/// CSS selector for input elements.
pub const INPUT_SELECTOR: &str = "input:not([type=hidden]), textarea, select";

/// JavaScript for DOM context analysis.
///
/// Walks up the DOM tree to find semantic context for an element,
/// including forms, ARIA landmarks, and meaningful text trails.
pub const CONTEXT_JS: &str = r#"
let el = arguments[0];
let context = [];
let contextContainer = null;
let current = el.parentElement;
let depth = 0;

while (current && depth < 10) {
    let info = null;

    // Check for form
    if (current.tagName === 'FORM') {
        let name = current.getAttribute('name') || current.getAttribute('id') || current.getAttribute('action') || '';
        info = 'form' + (name ? ':' + name : '');
        if (!contextContainer) contextContainer = current;
    }
    // Check for semantic elements
    else if (['SECTION', 'ARTICLE', 'NAV', 'MAIN', 'ASIDE', 'HEADER', 'FOOTER', 'DIALOG'].includes(current.tagName)) {
        let label = current.getAttribute('aria-label') || current.getAttribute('id') || '';
        info = current.tagName.toLowerCase() + (label ? ':' + label : '');
        if (!contextContainer) contextContainer = current;
    }
    // Check for aria landmarks/labels
    else if (current.getAttribute('role') || current.getAttribute('aria-label')) {
        let role = current.getAttribute('role') || 'div';
        let label = current.getAttribute('aria-label') || current.getAttribute('id') || '';
        info = role + (label ? ':' + label : '');
        if (!contextContainer) contextContainer = current;
    }
    // Check for divs with meaningful id/class
    else if (current.id && !current.id.match(/^[a-f0-9-]{20,}$/i)) {
        info = '#' + current.id;
        if (!contextContainer) contextContainer = current;
    }

    if (info) context.push(info);
    current = current.parentElement;
    depth++;
}

// Get visible text between context container and element
let textTrail = [];
if (contextContainer) {
    let walker = document.createTreeWalker(
        contextContainer,
        NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT,
        null,
        false
    );

    let node;
    let foundEl = false;
    while ((node = walker.nextNode()) && !foundEl) {
        if (node === el) {
            foundEl = true;
        } else if (node.nodeType === Node.TEXT_NODE) {
            let text = node.textContent.trim();
            if (text && text.length > 1 && text.length < 100) {
                textTrail.push(text);
            }
        } else if (node.nodeType === Node.ELEMENT_NODE) {
            // Check for headings, labels, legends
            if (node.tagName.match(/^(H[1-6]|LABEL|LEGEND|P)$/)) {
                let text = node.textContent.trim();
                if (text && text.length < 100) {
                    textTrail.push(text);
                }
            }
        }
        // Limit trail length
        if (textTrail.length > 10) textTrail = textTrail.slice(-10);
    }
}

return JSON.stringify({
    context: context.slice(0, 4),
    textTrail: textTrail.slice(-5)
});
"#;

/// Selectors for finding search inputs.
pub const SEARCH_SELECTORS: &[&str] = &[
    "input[type='search']",
    "input[name*='search' i]",
    "input[placeholder*='search' i]",
    "input[aria-label*='search' i]",
    "input[id*='search' i]",
];
