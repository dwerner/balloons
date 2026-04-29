# Browser Tooling Notes

This file captures practical knowledge for building a useful browser interaction suite on top of surfer/balloons browser tools.

## Current working baseline

Confirmed working in this environment:
- `browser_start` with Chrome headless
- `browser_goto`
- `browser_title`
- `browser_url`
- `browser_see`
- `browser_links`
- `browser_execute_js`
- `browser_search` with JS fallback

## Key observations

### 1. Headless Chrome is currently the reliable default
- Firefox is not reliable here because `geckodriver` is not installed.
- Chrome works with `chromedriver` and `chromium`.
- GUI mode requires `DISPLAY` to be set or attaching to an existing GUI webdriver.

### 2. `browser_search` needs fallback logic
Generic search helpers can fail on modern sites because:
- the detected element is not interactable
- sites use custom search widgets
- Enter key submission may not work reliably

Reliable fallback pattern:
- locate likely search box via JS
- set `.value`
- dispatch `input` and `change`
- submit the enclosing form if present
- otherwise synthesize Enter key events

### 3. `browser_see` is the main semantic inspection primitive
`browser_see` returns a structured page summary and should be preferred over raw HTML for:
- discussing page contents with the agent
- finding visible sections and important UI
- interpreting navigation state

Use raw HTML only when:
- diagnosing extractor failures
- reverse engineering a site-specific interaction
- building a new higher-level helper

### 4. Search engine result pages need specialized extraction
On DuckDuckGo, plain `browser_links` includes a lot of chrome/navigation links:
- tabs like All / Images / Videos
- settings links
- internal site chrome

So useful SERP extraction likely needs:
- section-aware parsing from `browser_see`
- result-like link filtering
- maybe a dedicated tool like `browser_search_results`

### 5. Tooling should separate primitives from helpers
Good primitives:
- start/stop browser
- goto
- see
- links/buttons/inputs
- execute_js
- screenshot

Good helpers built on top:
- search query on current engine
- extract organic search results
- click nth organic result
- wait for visible text/selector
- summarize current page for discussion

## Recommended next additions

1. `browser_search_results`
   - returns normalized organic results with title, url, snippet
   - first try `browser_see`
   - then fallback to JS heuristics

2. `browser_click_link`
   - click discovered link by index from `browser_links`

3. `browser_wait_for`
   - wait for selector/text/url pattern after navigation

4. `browser_screenshot_file`
   - save screenshot to a real file instead of only returning base64

5. result ranking/filtering heuristics
   - prefer http(s) links
   - exclude internal engine chrome
   - require non-empty text/title

## Usage guidance

### Best inspection flow
1. `browser_start(headless=true)`
2. `browser_goto(url)`
3. `browser_see()`
4. `browser_inputs()` / `browser_buttons()` / `browser_links()`
5. if interaction fails, use `browser_execute_js()` for diagnosis or fallback

### Best search flow
1. `browser_goto(search_engine_home)`
2. `browser_search(query)`
3. `browser_title()` + `browser_url()` to confirm landing on results page
4. `browser_see()`
5. specialized result extraction (`browser_search_results`, to be added)

## Philosophy

The suite should aim for:
- semantic tools first
- raw DOM/JS as escape hatch
- helpers for common workflows
- enough observability that the agent can explain what it is seeing and doing
