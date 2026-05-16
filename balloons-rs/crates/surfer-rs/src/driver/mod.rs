//! WebDriver implementation using the internal webdriver module.

mod config;
mod element_impl;
mod webdriver;

pub use config::{BrowserConfig, BrowserType};
pub use element_impl::WebDriverElement;
pub use webdriver::WebDriverSurfer;
