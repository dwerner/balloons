"""Browser automation tools for LLM web interactions.

Provides tools for browser automation via the surfer-rs bindings.
The Browser class from balloons_storage provides async web automation.

Tools are defined in prompts/tools/openai/browser_*.json and loaded
via the tool_schemas module.

Browser instances are managed by BrowserStateService for multi-browser support.
Tools support an optional `browser_name` parameter to target a specific browser.
If not specified, the default browser is used.
"""

import json
from typing import TYPE_CHECKING, Optional

from .debug_log import debug_log, Category
from .tool_schemas import get_balloon_tool_schema

if TYPE_CHECKING:
    from session import Session

# Browser tool names for routing in tool_executor
BROWSER_TOOL_NAMES = {
    "browser_list",
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
        "browser_list",
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

    Note:
        Tools support an optional `browser_name` argument to target a specific
        browser instance. If not specified, the default browser is used.
    """
    debug_log.info(
        f"Executing browser tool: {name}",
        category=Category.RUNNER,
        details={"args": args},
    )

    # Extract browser_name from args (optional targeting)
    browser_name = args.pop("browser_name", None)

    try:
        # Get browser instance (from registry or session)
        browser = await _get_browser(session, browser_name)

        if name == "browser_list":
            return await _browser_list(session), False
        elif name == "browser_start":
            return await _browser_start(args, session, browser_name)
        elif name == "browser_stop":
            return await _browser_stop(session, browser_name)

        # All other tools require an active browser
        if browser is None:
            if browser_name:
                return f"Error: Browser '{browser_name}' not found. Call browser_start first.", True
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


def _get_browser_instance(name: Optional[str] = None):
    """Get a browser instance by name from the global registry.

    Args:
        name: Browser name (uses default if not specified)

    Returns:
        BrowserInstance or None
    """
    try:
        from service.browser_state_service import get_browser_by_name
        return get_browser_by_name(name)
    except ImportError:
        return None


async def _get_browser(session: "Session", browser_name: Optional[str] = None):
    """Get the browser instance.

    First checks the global browser registry (BrowserStateService).
    Falls back to session._browser for backwards compatibility.

    Args:
        session: The session (legacy fallback)
        browser_name: Optional browser name to target

    Returns:
        Browser instance or None
    """
    # Try global registry first
    instance = _get_browser_instance(browser_name)
    if instance:
        return instance.browser

    # Fall back to session browser (legacy)
    if browser_name is None:
        return getattr(session, "_browser", None)

    return None


async def _browser_list(session: "Session") -> str:
    """List all browser sessions from the global registry, with legacy fallback."""
    try:
        from service.browser_state_service import _service_instance

        if _service_instance is not None:
            result = _service_instance.list_browsers()
            payload = {
                "default_browser": result.default_browser,
                "browsers": [
                    {
                        "name": b.name,
                        "browser_id": b.browser_id,
                        "browser_type": b.browser_type,
                        "headless": b.headless,
                        "status": b.status,
                        "current_url": b.current_url,
                        "current_title": b.current_title,
                        "created_at": b.created_at,
                        "error": b.error,
                        "is_default": b.name == result.default_browser,
                    }
                    for b in result.browsers
                ],
            }
            return json.dumps(payload, indent=2, ensure_ascii=False)
    except ImportError:
        pass

    browser = getattr(session, "_browser", None)
    if browser is None:
        return json.dumps({"default_browser": None, "browsers": []}, indent=2, ensure_ascii=False)

    browser_id = ""
    current_url = None
    current_title = None

    try:
        browser_id = await browser.id()
    except Exception:
        pass

    try:
        current_url = await browser.url()
    except Exception:
        pass

    try:
        current_title = await browser.title()
    except Exception:
        pass

    payload = {
        "default_browser": "default",
        "browsers": [
            {
                "name": "default",
                "browser_id": browser_id,
                "browser_type": None,
                "headless": None,
                "status": "connected",
                "current_url": current_url,
                "current_title": current_title,
                "created_at": None,
                "error": None,
                "is_default": True,
            }
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


async def _browser_start(
    args: dict,
    session: "Session",
    browser_name: Optional[str] = None,
) -> tuple[str, bool]:
    """Start a new browser session.

    Uses BrowserStateService if available, falls back to session storage.
    """
    browser_type = args.get("browser_type", "chrome")
    requested_headless = args.get("headless")
    headless = True if requested_headless is None else bool(requested_headless)
    webdriver_url = args.get("webdriver_url")
    port = args.get("port")

    # Try using BrowserStateService first
    try:
        from service.browser_state_service import _service_instance

        if _service_instance is not None:
            result = await _service_instance.create_browser(
                name=browser_name,
                browser_type=browser_type,
                headless=headless,
                webdriver_url=webdriver_url,
                port=port,
                set_as_default=browser_name is None,  # Set as default if no name specified
            )

            if result.success and result.browser:
                details = [
                    f"name: {result.browser.name}",
                    f"ID: {result.browser.browser_id[:8]}...",
                    f"type: {browser_type}",
                    f"headless: {headless}",
                ]
                if webdriver_url:
                    details.append(f"webdriver_url: {webdriver_url}")
                elif port is not None:
                    details.append(f"port: {port}")
                return f"Browser started ({', '.join(details)})", False
            else:
                return f"Error starting browser: {result.error}", True
    except ImportError:
        pass  # Fall back to legacy session storage

    # Legacy fallback: store browser on session
    try:
        from balloons_storage import Browser, BrowserConfig

        # X11 display detection is handled by surfer-rs when spawning the WebDriver process.
        # It will auto-detect DISPLAY and XAUTHORITY for non-headless mode.

        config_kwargs = {
            "browser_type": browser_type,
            "headless": headless,
        }
        if port is not None:
            config_kwargs["port"] = port
        elif not webdriver_url:
            # Use a unique port from the service if available
            try:
                from service.browser_state_service import _get_next_port
                config_kwargs["port"] = _get_next_port()
            except ImportError:
                pass  # Use default port
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


async def _browser_stop(
    session: "Session",
    browser_name: Optional[str] = None,
) -> tuple[str, bool]:
    """Stop a browser session.

    Uses BrowserStateService if available, falls back to session storage.
    """
    # Try using BrowserStateService first
    try:
        from service.browser_state_service import (
            _service_instance,
            get_browser_by_name,
            get_default_browser_name,
        )

        if _service_instance is not None:
            # Determine which browser to stop
            name_to_stop = browser_name or get_default_browser_name()
            if name_to_stop:
                result = await _service_instance.destroy_browser(name_to_stop)
                if result.success:
                    debug_log.info(f"Browser stopped: {name_to_stop}", category=Category.RUNNER)
                    return f"Browser '{name_to_stop}' stopped", False
                else:
                    return f"Error stopping browser: {result.error}", True
    except ImportError:
        pass  # Fall back to legacy session storage

    # Legacy fallback: use session browser
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
