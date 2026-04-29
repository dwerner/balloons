"""Browser automation tools for LLM web interactions.

Provides tools for browser automation via the surfer-rs bindings.
The Browser class from balloons_storage provides async web automation.

Tools are defined in prompts/tools/openai/browser_*.json and loaded
via the tool_schemas module.
"""

import json
from typing import TYPE_CHECKING

from .debug_log import debug_log, Category
from .tool_schemas import get_balloon_tool_schema

if TYPE_CHECKING:
    from session import Session

# Browser tool names for routing in tool_executor
BROWSER_TOOL_NAMES = {
    "browser_start",
    "browser_stop",
    "browser_goto",
    "browser_see",
    "browser_inputs",
    "browser_buttons",
    "browser_links",
    "browser_click",
    "browser_click_button",
    "browser_fill",
    "browser_set_input",
    "browser_screenshot",
    "browser_execute_js",
    # Additional tools that map to Python bindings
    "browser_back",
    "browser_forward",
    "browser_refresh",
    "browser_url",
    "browser_title",
    "browser_html",
    "browser_type_text",
    "browser_submit",
    "browser_select_option",
    "browser_press_enter",
    "browser_search",
    "browser_get_cookies",
    "browser_set_cookie",
    "browser_delete_cookie",
}


def get_browser_tools() -> list[dict]:
    """Get browser tool schemas, loading from JSON files.

    Returns:
        List of OpenAI function calling schema dicts
    """
    # Core browser tools (have JSON schemas)
    core_tools = [
        "browser_start",
        "browser_stop",
        "browser_goto",
        "browser_see",
        "browser_inputs",
        "browser_buttons",
        "browser_links",
        "browser_click",
        "browser_click_button",
        "browser_fill",
        "browser_set_input",
        "browser_screenshot",
        "browser_execute_js",
    ]

    result = []
    for name in core_tools:
        schema = get_balloon_tool_schema(name)
        if schema:
            result.append(schema)
        else:
            debug_log.warning(
                f"Browser tool schema not found: {name}",
                category=Category.RUNNER,
            )
    return result


async def execute_browser_tool(
    name: str,
    args: dict,
    session: "Session",
    working_dir: str,
) -> tuple[str, bool]:
    """Execute a browser tool.

    Args:
        name: Tool name (browser_start, browser_goto, etc.)
        args: Tool arguments from the model
        session: The session (holds browser instance)
        working_dir: Working directory (for screenshot saving, etc.)

    Returns:
        Tuple of (result_string, is_error)
    """
    debug_log.info(
        f"Executing browser tool: {name}",
        category=Category.RUNNER,
        details={"args": args},
    )

    try:
        # Get or create browser instance from session
        browser = await _get_browser(session)

        if name == "browser_start":
            return await _browser_start(args, session)
        elif name == "browser_stop":
            return await _browser_stop(session)

        # All other tools require an active browser
        if browser is None:
            return "Error: No browser session. Call browser_start first.", True

        if name == "browser_goto":
            url = args.get("url")
            if not url:
                return "Error: url is required", True
            await browser.goto(url)
            return f"Navigated to {url}", False

        elif name == "browser_see":
            result = await browser.see()
            return _format_browser_json(result), False

        elif name == "browser_inputs":
            result = await browser.inputs()
            return _format_browser_json(result), False

        elif name == "browser_buttons":
            result = await browser.buttons()
            return _format_browser_json(result), False

        elif name == "browser_links":
            limit = args.get("limit")
            result = await browser.links(limit)
            return _format_browser_links(result), False

        elif name == "browser_click":
            selector = args.get("selector")
            if not selector:
                return "Error: selector is required", True
            await browser.click(selector)
            return f"Clicked element: {selector}", False

        elif name == "browser_click_button":
            index = args.get("index")
            if index is None:
                return "Error: index is required", True
            await browser.click_button(index)
            return f"Clicked button at index {index}", False

        elif name == "browser_fill":
            selector = args.get("selector")
            text = args.get("text")
            if not selector:
                return "Error: selector is required", True
            if text is None:
                return "Error: text is required", True
            await browser.fill(selector, text)
            return f"Filled input {selector}", False

        elif name == "browser_set_input":
            index = args.get("index")
            value = args.get("value")
            if index is None:
                return "Error: index is required", True
            if value is None:
                return "Error: value is required", True
            await browser.set_input(index, value)
            return f"Set input at index {index}", False

        elif name == "browser_screenshot":
            png_data = await browser.screenshot()
            # Return as base64 for transport
            import base64
            b64 = base64.b64encode(png_data).decode("ascii")
            return f"data:image/png;base64,{b64}", False

        elif name == "browser_execute_js":
            script = args.get("script")
            if not script:
                return "Error: script is required", True
            result = await browser.execute_js(script)
            return result, False

        # Additional tools
        elif name == "browser_back":
            await browser.back()
            return "Navigated back", False

        elif name == "browser_forward":
            await browser.forward()
            return "Navigated forward", False

        elif name == "browser_refresh":
            await browser.refresh()
            return "Page refreshed", False

        elif name == "browser_url":
            result = await browser.url()
            return result, False

        elif name == "browser_title":
            result = await browser.title()
            return result, False

        elif name == "browser_html":
            result = await browser.html()
            # Truncate large HTML
            if len(result) > 50000:
                result = result[:50000] + "\n... [truncated]"
            return result, False

        elif name == "browser_type_text":
            selector = args.get("selector")
            text = args.get("text")
            if not selector:
                return "Error: selector is required", True
            if text is None:
                return "Error: text is required", True
            await browser.type_text(selector, text)
            return f"Typed text into {selector}", False

        elif name == "browser_submit":
            await browser.submit()
            return "Form submitted", False

        elif name == "browser_select_option":
            index = args.get("index")
            value = args.get("value")
            if index is None:
                return "Error: index is required", True
            if value is None:
                return "Error: value is required", True
            await browser.select_option(index, value)
            return f"Selected option at index {index}", False

        elif name == "browser_press_enter":
            index = args.get("index")
            if index is None:
                return "Error: index is required", True
            await browser.press_enter(index)
            return f"Pressed Enter on input at index {index}", False

        elif name == "browser_search":
            query = args.get("query")
            if not query:
                return "Error: query is required", True
            await browser.search(query)
            return f"Searched for: {query}", False

        elif name == "browser_get_cookies":
            result = await browser.get_cookies()
            return result, False

        elif name == "browser_set_cookie":
            cookie_json = args.get("cookie")
            if not cookie_json:
                return "Error: cookie is required", True
            if isinstance(cookie_json, dict):
                cookie_json = json.dumps(cookie_json)
            await browser.set_cookie(cookie_json)
            return "Cookie set", False

        elif name == "browser_delete_cookie":
            name_arg = args.get("name")
            if not name_arg:
                return "Error: name is required", True
            await browser.delete_cookie(name_arg)
            return f"Deleted cookie: {name_arg}", False

        else:
            return f"Unknown browser tool: {name}", True

    except Exception as e:
        debug_log.error(
            f"Browser tool error: {e}",
            category=Category.RUNNER,
        )
        return f"Browser error: {str(e)}", True


def _format_browser_json(result) -> str:
    """Pretty-print JSON strings returned by the Rust browser bindings."""
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
            return json.dumps(parsed, indent=2, ensure_ascii=False)
        except Exception:
            return result
    try:
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception:
        return str(result)


def _format_browser_links(result) -> str:
    """Format links with lightweight filtering so search results are more useful."""
    parsed = result
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except Exception:
            return result

    if not isinstance(parsed, list):
        return _format_browser_json(parsed)

    def is_useful_link(item: dict) -> bool:
        href = (item.get("href") or "").strip()
        text = (item.get("text") or "").strip()
        if not href:
            return False
        if href.startswith("javascript:"):
            return False
        if href.startswith("/"):
            return False
        if "duckduckgo.com/?" in href:
            return False
        if "duck.ai" in href:
            return False
        if "start.duckduckgo.com" in href:
            return False
        if not text:
            return False
        return True

    useful = [item for item in parsed if isinstance(item, dict) and is_useful_link(item)]
    payload = {
        "useful_links": useful,
        "all_links": parsed,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


async def _get_browser(session: "Session"):
    """Get the browser instance from session, if any."""
    return getattr(session, "_browser", None)


async def _browser_start(args: dict, session: "Session") -> tuple[str, bool]:
    """Start a new browser session."""
    try:
        from balloons_storage import Browser, BrowserConfig

        browser_type = args.get("browser_type", "chrome")
        requested_headless = args.get("headless")
        headless = True if requested_headless is None else bool(requested_headless)
        webdriver_url = args.get("webdriver_url")
        port = args.get("port")

        # If the caller wants a visible browser but this process has no display,
        # prefer using the system X server when available.
        if not headless and not webdriver_url:
            import os
            display = os.environ.get("DISPLAY")
            if not display and os.path.exists("/tmp/.X11-unix/X0"):
                display = ":0"
            if display:
                os.environ["DISPLAY"] = display
            else:
                return (
                    "Error starting browser: non-headless browser requested but no DISPLAY is available. "
                    "Either run with headless=true, start Balloons with DISPLAY=:0, or provide webdriver_url to an existing GUI WebDriver.",
                    True,
                )

        config_kwargs = {
            "browser_type": browser_type,
            "headless": headless,
        }
        if port is not None:
            config_kwargs["port"] = port
        if webdriver_url:
            config_kwargs["webdriver_url"] = webdriver_url

        config = BrowserConfig(**config_kwargs)

        # Create and connect browser
        browser = Browser(config)
        await browser.connect()

        # Store on session
        session._browser = browser

        browser_id = await browser.id()
        debug_log.info(
            f"Browser started: {browser_id}",
            category=Category.RUNNER,
        )

        details = [f"ID: {browser_id[:8]}...", f"type: {browser_type}", f"headless: {headless}"]
        if webdriver_url:
            details.append(f"webdriver_url: {webdriver_url}")
        elif port is not None:
            details.append(f"port: {port}")
        return f"Browser started ({', '.join(details)})", False

    except ImportError as e:
        return f"Error: Browser bindings not available ({e})", True
    except Exception as e:
        return f"Error starting browser: {str(e)}", True


async def _browser_stop(session: "Session") -> tuple[str, bool]:
    """Stop the browser session."""
    browser = getattr(session, "_browser", None)
    if browser is None:
        return "No browser session to stop", False

    try:
        await browser.disconnect()
        session._browser = None
        debug_log.info("Browser stopped", category=Category.RUNNER)
        return "Browser stopped", False
    except Exception as e:
        return f"Error stopping browser: {str(e)}", True
