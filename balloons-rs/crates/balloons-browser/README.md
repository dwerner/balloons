# balloons-browser

Browser automation for Balloons using [surfer-rs](https://github.com/dwerner/surfer-rs).

## Overview

This crate provides browser automation capabilities via the WebDriver protocol,
wrapping surfer-rs with the smol async runtime for compatibility with core-executor.

## Python Usage

The browser classes are exposed via the `balloons_py` Python module:

```python
from balloons_py import Browser, BrowserConfig

# Create a config
config = BrowserConfig.firefox()  # or BrowserConfig.chrome()
# Or with options:
config = BrowserConfig(
    browser_type="firefox",  # or "chrome"
    headless=True,           # run without GUI
    port=4444,               # WebDriver port
    webdriver_url=None       # optional: connect to existing WebDriver
)

# Create and connect browser
browser = Browser(config)
browser.connect()  # starts geckodriver/chromedriver and browser

# Navigate
browser.goto("https://example.com")
print(browser.title())
print(browser.url())

# Interact with elements
browser.click("#button-id")
browser.fill("#input-id", "some text")
browser.type_text("#search", "query")

# Discover elements
inputs = browser.inputs()   # JSON array of input elements
buttons = browser.buttons() # JSON array of button elements
links = browser.links()     # JSON array of link elements

# Click by index (from discovery)
browser.click_button(0)     # click first discovered button
browser.set_input(0, "val") # set first discovered input

# Get page content
html = browser.html()
screenshot_png = browser.screenshot()  # PNG bytes

# Execute JavaScript
result = browser.execute_js("return document.title")

# Cleanup
browser.disconnect()
```

## Requirements

- geckodriver (for Firefox) or chromedriver (for Chrome) must be installed and in PATH
- The WebDriver server is started automatically when you call `connect()`

## Architecture

```
Python (balloons_py)
    ↓
PyO3 bindings (balloons-py)
    ↓
balloons-browser (this crate)
    ↓
surfer-rs (smol runtime)
    ↓
fantoccini (WebDriver client)
    ↓
geckodriver/chromedriver
    ↓
Firefox/Chrome
```

The smol runtime is used for async operations, which integrates well with
core-executor used elsewhere in Balloons.
