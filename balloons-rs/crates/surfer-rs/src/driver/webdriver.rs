//! WebDriver implementation of the Surfer trait.

use crate::webdriver::client::NewWindowResponse;
use crate::webdriver::cookies::Cookie;
use crate::webdriver::elements::Element as WaveElement;
use crate::webdriver::wd::WindowHandle;
use crate::webdriver::{Client, ClientBuilder, Locator};
use async_trait::async_trait;
use serde_json::json;
use std::sync::Arc;

use crate::discovery::context::RawContext;
use crate::discovery::{
    BUTTON_SELECTOR, ButtonInfo, CONTEXT_JS, ElementContext, INPUT_SELECTOR, InputInfo, LinkInfo,
    PageItem, PageSection, PageVision, SEARCH_SELECTORS, Selector,
};
use crate::driver::{BrowserConfig, WebDriverElement};
use crate::error::{Result, SurferError};
use crate::traits::Surfer;

/// Helper to serialize an element for use with execute().
fn element_to_json(el: &WaveElement) -> serde_json::Value {
    serde_json::to_value(el).unwrap_or(json!(null))
}

/// WebDriver-based browser automation.
pub struct WebDriverSurfer {
    client: Arc<Client>,
}

impl WebDriverSurfer {
    /// Connect to a WebDriver instance.
    pub async fn connect(config: &BrowserConfig) -> Result<Self> {
        let url = config.webdriver_url();

        let mut caps = serde_json::Map::new();

        match config.browser_type {
            crate::driver::BrowserType::Firefox => {
                let mut firefox_opts = serde_json::Map::new();
                if config.headless {
                    firefox_opts.insert("args".into(), json!(["-headless"]));
                }
                caps.insert("moz:firefoxOptions".into(), json!(firefox_opts));
            }
            crate::driver::BrowserType::Chrome => {
                let mut chrome_opts = serde_json::Map::new();
                let mut args = vec![
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ];
                if config.headless {
                    args.push("--headless=new");
                    args.push("--disable-gpu");
                }
                chrome_opts.insert("args".into(), json!(args));
                // Disable automation flags that sites detect
                chrome_opts.insert("excludeSwitches".into(), json!(["enable-automation"]));
                chrome_opts.insert("useAutomationExtension".into(), json!(false));
                caps.insert("goog:chromeOptions".into(), json!(chrome_opts));
            }
        }

        // Use smol-compatible connector for runtime-agnostic operation
        let client = ClientBuilder::smol()
            .capabilities(caps)
            .connect(&url)
            .await
            .map_err(|e| SurferError::ConnectionFailed {
                url: url.clone(),
                message: e.to_string(),
            })?;

        Ok(Self {
            client: Arc::new(client),
        })
    }

    /// Get a reference to the inner webdriver client.
    pub fn client(&self) -> &Client {
        &self.client
    }

    /// Close the browser session.
    pub async fn close(self) -> Result<()> {
        // Need to get ownership of the client
        let client = Arc::try_unwrap(self.client)
            .map_err(|_| SurferError::SessionError("cannot close: client still in use".into()))?;

        client
            .close()
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))
    }
}

#[async_trait]
impl Surfer for WebDriverSurfer {
    type Element = WebDriverElement;

    // -------------------------------------------------------------------------
    // Navigation
    // -------------------------------------------------------------------------

    async fn goto(&self, url: &str) -> Result<()> {
        let url = if url.starts_with("http://") || url.starts_with("https://") {
            url.to_string()
        } else {
            format!("https://{url}")
        };

        self.client
            .goto(&url)
            .await
            .map_err(|e| SurferError::NavigationFailed(e.to_string()))
    }

    async fn back(&self) -> Result<()> {
        self.client
            .back()
            .await
            .map_err(|e| SurferError::NavigationFailed(e.to_string()))
    }

    async fn forward(&self) -> Result<()> {
        self.client
            .forward()
            .await
            .map_err(|e| SurferError::NavigationFailed(e.to_string()))
    }

    async fn refresh(&self) -> Result<()> {
        self.client
            .refresh()
            .await
            .map_err(|e| SurferError::NavigationFailed(e.to_string()))
    }

    async fn url(&self) -> Result<String> {
        self.client
            .current_url()
            .await
            .map(|u| u.to_string())
            .map_err(|e| SurferError::SessionError(e.to_string()))
    }

    async fn title(&self) -> Result<String> {
        self.client
            .title()
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))
    }

    // -------------------------------------------------------------------------
    // Discovery
    // -------------------------------------------------------------------------

    async fn find(&self, selector: impl Into<Selector> + Send) -> Result<Vec<Self::Element>> {
        let selector = selector.into();
        let locator = match &selector {
            Selector::Css(s) => Locator::Css(s),
            Selector::XPath(s) => Locator::XPath(s),
        };

        let elements = self
            .client
            .find_all(locator)
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))?;

        Ok(elements.into_iter().map(WebDriverElement::new).collect())
    }

    async fn inputs(&self) -> Result<Vec<InputInfo>> {
        let elements = self
            .client
            .find_all(Locator::Css(INPUT_SELECTOR))
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))?;

        let mut inputs = Vec::with_capacity(elements.len());

        for (index, el) in elements.into_iter().enumerate() {
            let tag = el.tag_name().await.unwrap_or_default();
            let input_type = el
                .attr("type")
                .await
                .ok()
                .flatten()
                .unwrap_or_else(|| "text".to_string());
            let name = el.attr("name").await.ok().flatten();
            let id = el.attr("id").await.ok().flatten();
            let placeholder = el.attr("placeholder").await.ok().flatten();
            let value = el.attr("value").await.ok().flatten();
            let aria_label = el.attr("aria-label").await.ok().flatten();
            let required = el.attr("required").await.ok().flatten().is_some();
            let disabled = el.attr("disabled").await.ok().flatten().is_some();

            inputs.push(InputInfo {
                index,
                tag,
                input_type,
                name,
                id,
                placeholder,
                value,
                required,
                disabled,
                aria_label,
            });
        }

        Ok(inputs)
    }

    async fn buttons(&self) -> Result<Vec<ButtonInfo>> {
        let elements = self
            .client
            .find_all(Locator::Css(BUTTON_SELECTOR))
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))?;

        let mut buttons = Vec::with_capacity(elements.len());

        for (index, el) in elements.into_iter().enumerate() {
            let tag = el.tag_name().await.unwrap_or_default();
            let text = el.text().await.unwrap_or_default().replace('\n', " ");
            let text = if text.len() > 60 {
                text[..60].to_string()
            } else {
                text
            };
            let value = el.attr("value").await.ok().flatten();
            let button_type = el.attr("type").await.ok().flatten();
            let role = el.attr("role").await.ok().flatten();
            let classes = el.attr("class").await.ok().flatten();
            let disabled = el.attr("disabled").await.ok().flatten().is_some();

            buttons.push(ButtonInfo {
                index,
                tag,
                text,
                value,
                button_type,
                role,
                classes,
                disabled,
            });
        }

        Ok(buttons)
    }

    async fn links(&self, limit: Option<usize>) -> Result<Vec<LinkInfo>> {
        let elements = self
            .client
            .find_all(Locator::Css("a[href]"))
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))?;

        let limit = limit.unwrap_or(50);
        let mut links = Vec::with_capacity(limit.min(elements.len()));

        for (index, el) in elements.into_iter().take(limit).enumerate() {
            let text = el.text().await.unwrap_or_default();
            let text = if text.len() > 50 {
                text[..50].to_string()
            } else {
                text
            };
            let href = el.attr("href").await.ok().flatten().unwrap_or_default();
            let target = el.attr("target").await.ok().flatten();
            let title = el.attr("title").await.ok().flatten();

            links.push(LinkInfo {
                index,
                text,
                href,
                target,
                title,
            });
        }

        Ok(links)
    }

    async fn context(&self, selector: impl Into<Selector> + Send) -> Result<Vec<ElementContext>> {
        let selector = selector.into();
        let locator = match &selector {
            Selector::Css(s) => Locator::Css(s),
            Selector::XPath(s) => Locator::XPath(s),
        };

        let elements = self
            .client
            .find_all(locator)
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))?;

        let mut contexts = Vec::with_capacity(elements.len());

        for (index, el) in elements.into_iter().enumerate() {
            let tag = el.tag_name().await.unwrap_or_default().to_lowercase();
            let text = el.text().await.unwrap_or_default();
            let text = if text.len() > 50 {
                text[..50].to_string()
            } else {
                text
            };

            // Execute context JS
            let result = self
                .client
                .execute(CONTEXT_JS, vec![element_to_json(&el)])
                .await
                .ok();

            let raw = result
                .and_then(|v| v.as_str().map(String::from))
                .and_then(|s| serde_json::from_str::<RawContext>(&s).ok())
                .unwrap_or(RawContext {
                    context: vec![],
                    text_trail: vec![],
                });

            contexts.push(ElementContext::from_raw(index, tag, text, raw));
        }

        Ok(contexts)
    }

    // -------------------------------------------------------------------------
    // Interaction by index
    // -------------------------------------------------------------------------

    async fn click_button(&self, index: usize) -> Result<()> {
        let elements = self
            .client
            .find_all(Locator::Css(BUTTON_SELECTOR))
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))?;

        let el = elements
            .into_iter()
            .nth(index)
            .ok_or(SurferError::IndexOutOfRange {
                index,
                max: index.saturating_sub(1),
            })?;

        el.click()
            .await
            .map_err(|e| SurferError::InteractionFailed(e.to_string()))
    }

    async fn set_input(&self, index: usize, value: &str) -> Result<()> {
        let elements = self
            .client
            .find_all(Locator::Css(INPUT_SELECTOR))
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))?;

        let count = elements.len();
        let el = elements
            .into_iter()
            .nth(index)
            .ok_or(SurferError::IndexOutOfRange {
                index,
                max: count.saturating_sub(1),
            })?;

        // React-compatible value setting
        let script = r#"
            arguments[0].value = arguments[1];
            arguments[0].dispatchEvent(new Event('input', {bubbles: true}));
        "#;

        self.client
            .execute(script, vec![element_to_json(&el), json!(value)])
            .await
            .map_err(|e| SurferError::InteractionFailed(e.to_string()))?;

        Ok(())
    }

    async fn select_option(&self, index: usize, value: &str) -> Result<()> {
        let elements = self
            .client
            .find_all(Locator::Css(INPUT_SELECTOR))
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))?;

        let count = elements.len();
        let el = elements
            .into_iter()
            .nth(index)
            .ok_or(SurferError::IndexOutOfRange {
                index,
                max: count.saturating_sub(1),
            })?;

        let tag = el.tag_name().await.unwrap_or_default().to_lowercase();
        if tag != "select" {
            return Err(SurferError::WrongElementType {
                index,
                expected: "select".to_string(),
                actual: tag,
            });
        }

        // Find and click matching option
        let script = r#"
            const select = arguments[0];
            const value = arguments[1].toLowerCase();
            for (const option of select.options) {
                if (option.text.toLowerCase().includes(value)) {
                    option.selected = true;
                    select.dispatchEvent(new Event('change', {bubbles: true}));
                    return option.text;
                }
            }
            return null;
        "#;

        let result = self
            .client
            .execute(script, vec![element_to_json(&el), json!(value)])
            .await
            .map_err(|e| SurferError::InteractionFailed(e.to_string()))?;

        if result.is_null() {
            return Err(SurferError::ElementNotFound {
                selector: format!("option matching '{value}'"),
            });
        }

        Ok(())
    }

    async fn press_enter(&self, index: usize) -> Result<()> {
        let elements = self
            .client
            .find_all(Locator::Css(INPUT_SELECTOR))
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))?;

        let count = elements.len();
        let el = elements
            .into_iter()
            .nth(index)
            .ok_or(SurferError::IndexOutOfRange {
                index,
                max: count.saturating_sub(1),
            })?;

        el.send_keys("\u{E007}") // Enter key
            .await
            .map_err(|e| SurferError::InteractionFailed(e.to_string()))
    }

    // -------------------------------------------------------------------------
    // Interaction by selector
    // -------------------------------------------------------------------------

    async fn click(&self, selector: impl Into<Selector> + Send) -> Result<()> {
        let selector = selector.into();
        let locator = match &selector {
            Selector::Css(s) => Locator::Css(s),
            Selector::XPath(s) => Locator::XPath(s),
        };

        let selector_str = match &selector {
            Selector::Css(s) | Selector::XPath(s) => s.clone(),
        };

        let el = self
            .client
            .find(locator)
            .await
            .map_err(|_| SurferError::ElementNotFound {
                selector: selector_str,
            })?;

        el.click()
            .await
            .map_err(|e| SurferError::InteractionFailed(e.to_string()))
    }

    async fn type_text(&self, selector: impl Into<Selector> + Send, text: &str) -> Result<()> {
        let selector = selector.into();
        let locator = match &selector {
            Selector::Css(s) => Locator::Css(s),
            Selector::XPath(s) => Locator::XPath(s),
        };

        let selector_str = match &selector {
            Selector::Css(s) | Selector::XPath(s) => s.clone(),
        };

        let el = self
            .client
            .find(locator)
            .await
            .map_err(|_| SurferError::ElementNotFound {
                selector: selector_str,
            })?;

        el.clear().await.ok();
        el.send_keys(text)
            .await
            .map_err(|e| SurferError::InteractionFailed(e.to_string()))
    }

    async fn fill(&self, name: &str, value: &str) -> Result<()> {
        let selector = format!("[name='{name}'], #{name}");

        let el = self
            .client
            .find(Locator::Css(&selector))
            .await
            .map_err(|_| SurferError::ElementNotFound {
                selector: format!("name or id '{name}'"),
            })?;

        el.clear().await.ok();
        el.send_keys(value)
            .await
            .map_err(|e| SurferError::InteractionFailed(e.to_string()))
    }

    async fn submit(&self) -> Result<()> {
        let form = self
            .client
            .find(Locator::Css("form"))
            .await
            .map_err(|_| SurferError::FormNotFound)?;

        self.client
            .execute("arguments[0].submit()", vec![element_to_json(&form)])
            .await
            .map_err(|e| SurferError::InteractionFailed(e.to_string()))?;

        Ok(())
    }

    async fn search(&self, query: &str) -> Result<()> {
        // Try each search selector
        let mut el = None;
        for selector in SEARCH_SELECTORS {
            if let Ok(found) = self.client.find(Locator::Css(selector)).await {
                el = Some(found);
                break;
            }
        }

        let el = el.ok_or(SurferError::SearchInputNotFound)?;

        el.clear().await.ok();
        el.send_keys(query)
            .await
            .map_err(|e| SurferError::InteractionFailed(e.to_string()))?;
        el.send_keys("\u{E007}") // Enter key
            .await
            .map_err(|e| SurferError::InteractionFailed(e.to_string()))
    }

    // -------------------------------------------------------------------------
    // Utilities
    // -------------------------------------------------------------------------

    async fn screenshot(&self) -> Result<Vec<u8>> {
        let data = self
            .client
            .screenshot()
            .await
            .map_err(|e| SurferError::ScreenshotFailed(e.to_string()))?;

        Ok(data)
    }

    async fn execute_js(&self, script: &str) -> Result<serde_json::Value> {
        let script = format!("return {script}");

        self.client
            .execute(&script, vec![])
            .await
            .map_err(|e| SurferError::JavaScriptError(e.to_string()))
    }

    async fn html(&self) -> Result<String> {
        self.client
            .source()
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))
    }

    async fn see(&self) -> Result<PageVision> {
        let title = self.title().await.unwrap_or_default();
        let url = self.url().await.unwrap_or_default();
        let mut vision = PageVision::new(title, url);

        // JavaScript that extracts visible interactive elements and text
        // Simpler approach: query specific element types directly
        let js = r#"(function() {
            var result = [];
            var linkIndex = 0;
            var buttonIndex = 0;
            var inputIndex = 0;

            var isVisible = function(el) {
                if (!el) return false;
                var style = window.getComputedStyle(el);
                if (style.display === 'none') return false;
                if (style.visibility === 'hidden') return false;
                var rect = el.getBoundingClientRect();
                return rect.width > 0 || rect.height > 0;
            };

            var getSection = function(el) {
                var node = el;
                while (node && node !== document.body) {
                    var tag = node.tagName ? node.tagName.toLowerCase() : '';
                    if (tag === 'nav') return 'navigation';
                    if (tag === 'aside') return 'sidebar';
                    if (tag === 'main') return 'main';
                    if (tag === 'form') return 'form';
                    if (tag === 'header') return 'header';
                    if (tag === 'footer') return 'footer';
                    node = node.parentElement;
                }
                return 'content';
            };

            // Links
            var links = document.querySelectorAll('a[href]');
            for (var i = 0; i < links.length; i++) {
                var el = links[i];
                if (!isVisible(el)) continue;
                var text = el.innerText.trim();
                if (!text) continue;
                result.push({
                    kind: 'link',
                    text: text,
                    index: linkIndex++,
                    href: el.href,
                    section: getSection(el)
                });
            }

            // Buttons
            var buttons = document.querySelectorAll('button, input[type="submit"], input[type="button"]');
            for (var i = 0; i < buttons.length; i++) {
                var el = buttons[i];
                if (!isVisible(el)) continue;
                var text = (el.innerText || el.value || '').trim();
                if (!text) continue;
                result.push({
                    kind: 'button',
                    text: text,
                    index: buttonIndex++,
                    section: getSection(el)
                });
            }

            // Inputs
            var inputs = document.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="button"]), textarea, select');
            for (var i = 0; i < inputs.length; i++) {
                var el = inputs[i];
                if (!isVisible(el)) continue;
                var label = el.getAttribute('aria-label') || el.placeholder || el.name || el.id || 'input';
                var inputType = el.tagName.toLowerCase() === 'select' ? 'select' : (el.tagName.toLowerCase() === 'textarea' ? 'textarea' : (el.type || 'text'));
                var value = el.tagName.toLowerCase() === 'select' && el.selectedIndex >= 0 ? el.options[el.selectedIndex].text : (el.value || '');
                result.push({
                    kind: 'input',
                    text: label,
                    index: inputIndex++,
                    inputType: inputType,
                    value: value,
                    section: getSection(el)
                });
            }

            // Headings
            var headings = document.querySelectorAll('h1, h2, h3, h4, h5, h6');
            for (var i = 0; i < headings.length; i++) {
                var el = headings[i];
                if (!isVisible(el)) continue;
                var text = el.innerText.trim();
                if (!text) continue;
                result.push({
                    kind: 'heading',
                    text: text,
                    section: getSection(el)
                });
            }

            // Images with alt text
            var images = document.querySelectorAll('img[alt]');
            for (var i = 0; i < images.length; i++) {
                var el = images[i];
                if (!isVisible(el)) continue;
                if (!el.alt) continue;
                result.push({
                    kind: 'image',
                    text: '[image: ' + el.alt + ']',
                    section: getSection(el)
                });
            }

            return JSON.stringify(result);
        })()"#;

        let result = self.execute_js(js).await?;
        let items_json = result.as_str().unwrap_or("[]");

        #[derive(serde::Deserialize)]
        struct RawItem {
            kind: String,
            text: String,
            #[serde(default)]
            index: Option<usize>,
            #[serde(default)]
            href: Option<String>,
            #[serde(default)]
            section: Option<String>,
            #[serde(default)]
            input_type: Option<String>,
            #[serde(rename = "inputType")]
            #[serde(default)]
            input_type_alt: Option<String>,
            #[serde(default)]
            value: Option<String>,
        }

        let raw_items: Vec<RawItem> = serde_json::from_str(items_json).unwrap_or_default();

        // Group items by section
        let mut sections: std::collections::HashMap<String, Vec<PageItem>> =
            std::collections::HashMap::new();

        for raw in raw_items {
            let section_name = raw.section.unwrap_or_else(|| "content".to_string());

            let mut item = PageItem::new(&raw.kind, &raw.text);

            if let Some(idx) = raw.index {
                item = item.with_index(idx);
            }
            if let Some(href) = raw.href {
                item = item.with_href(href);
            }
            let input_type = raw.input_type.or(raw.input_type_alt);
            if let Some(it) = input_type {
                item = item.with_input_type(it);
            }
            if let Some(val) = raw.value {
                if !val.is_empty() {
                    item = item.with_value(val);
                }
            }

            sections.entry(section_name).or_default().push(item);
        }

        // Add sections in a logical order
        let section_order = [
            "header",
            "navigation",
            "sidebar",
            "main",
            "content",
            "form",
            "footer",
        ];

        for section_name in section_order {
            if let Some(items) = sections.remove(section_name) {
                if !items.is_empty() {
                    let mut section = PageSection::new(section_name);
                    for item in items {
                        section.push(item);
                    }
                    vision.push(section);
                }
            }
        }

        // Add any remaining sections
        for (section_name, items) in sections {
            if !items.is_empty() {
                let mut section = PageSection::new(section_name);
                for item in items {
                    section.push(item);
                }
                vision.push(section);
            }
        }

        Ok(vision)
    }

    // -------------------------------------------------------------------------
    // Cookies
    // -------------------------------------------------------------------------

    async fn get_cookies(&self) -> Result<Vec<Cookie<'static>>> {
        self.client
            .get_all_cookies()
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))
    }

    async fn get_cookie(&self, name: &str) -> Result<Option<Cookie<'static>>> {
        self.client
            .get_named_cookie(name)
            .await
            .map(Some)
            .or_else(|e| {
                // Cookie not found is not an error, return None
                if e.to_string().contains("no such cookie") {
                    Ok(None)
                } else {
                    Err(SurferError::SessionError(e.to_string()))
                }
            })
    }

    async fn set_cookie(&self, cookie: Cookie<'static>) -> Result<()> {
        self.client
            .add_cookie(cookie)
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))
    }

    async fn delete_cookie(&self, name: &str) -> Result<()> {
        self.client
            .delete_cookie(name)
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))
    }

    async fn delete_all_cookies(&self) -> Result<()> {
        self.client
            .delete_all_cookies()
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))
    }

    // -------------------------------------------------------------------------
    // Frames
    // -------------------------------------------------------------------------

    async fn enter_frame(&self, index: u16) -> Result<()> {
        self.client
            .enter_frame(index)
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))
    }

    async fn enter_parent_frame(&self) -> Result<()> {
        self.client
            .enter_parent_frame()
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))
    }

    // -------------------------------------------------------------------------
    // Windows/Tabs
    // -------------------------------------------------------------------------

    async fn current_window(&self) -> Result<WindowHandle> {
        self.client
            .window()
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))
    }

    async fn windows(&self) -> Result<Vec<WindowHandle>> {
        self.client
            .windows()
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))
    }

    async fn switch_to_window(&self, handle: WindowHandle) -> Result<()> {
        self.client
            .switch_to_window(handle)
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))
    }

    async fn new_window(&self, as_tab: bool) -> Result<NewWindowResponse> {
        self.client
            .new_window(as_tab)
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))
    }

    async fn close_window(&self) -> Result<()> {
        self.client
            .close_window()
            .await
            .map_err(|e| SurferError::SessionError(e.to_string()))
    }

    // -------------------------------------------------------------------------
    // Storage
    // -------------------------------------------------------------------------

    async fn local_storage_get(&self, key: &str) -> Result<Option<String>> {
        let escaped_key = key.replace('\\', "\\\\").replace('\'', "\\'");
        let script = format!("return localStorage.getItem('{escaped_key}')");
        let result = self
            .client
            .execute(&script, vec![])
            .await
            .map_err(|e| SurferError::JavaScriptError(e.to_string()))?;

        match result {
            serde_json::Value::Null => Ok(None),
            serde_json::Value::String(s) => Ok(Some(s)),
            _ => Ok(result.as_str().map(String::from)),
        }
    }

    async fn local_storage_set(&self, key: &str, value: &str) -> Result<()> {
        let escaped_key = key.replace('\\', "\\\\").replace('\'', "\\'");
        let escaped_value = value.replace('\\', "\\\\").replace('\'', "\\'");
        let script = format!("localStorage.setItem('{escaped_key}', '{escaped_value}')");
        self.client
            .execute(&script, vec![])
            .await
            .map_err(|e| SurferError::JavaScriptError(e.to_string()))?;
        Ok(())
    }

    async fn session_storage_get(&self, key: &str) -> Result<Option<String>> {
        let escaped_key = key.replace('\\', "\\\\").replace('\'', "\\'");
        let script = format!("return sessionStorage.getItem('{escaped_key}')");
        let result = self
            .client
            .execute(&script, vec![])
            .await
            .map_err(|e| SurferError::JavaScriptError(e.to_string()))?;

        match result {
            serde_json::Value::Null => Ok(None),
            serde_json::Value::String(s) => Ok(Some(s)),
            _ => Ok(result.as_str().map(String::from)),
        }
    }

    async fn session_storage_set(&self, key: &str, value: &str) -> Result<()> {
        let escaped_key = key.replace('\\', "\\\\").replace('\'', "\\'");
        let escaped_value = value.replace('\\', "\\\\").replace('\'', "\\'");
        let script = format!("sessionStorage.setItem('{escaped_key}', '{escaped_value}')");
        self.client
            .execute(&script, vec![])
            .await
            .map_err(|e| SurferError::JavaScriptError(e.to_string()))?;
        Ok(())
    }
}
