//! Core traits for browser automation.

mod element;
pub mod lifecycle;
mod surfer;

pub use element::Element;
pub use lifecycle::BrowserLifecycle;
pub use surfer::Surfer;
