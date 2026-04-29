"""WebSocket-exposed service for browser instance management.

This service provides:
- Browser lifecycle management (create, destroy, list)
- Named browser instances with rename capability
- Browser control operations (goto, click, screenshot, etc.)
- Real-time events for browser state changes

Browsers are global (not tied to sessions) and identified by name.
A 'default' browser exists for backwards compatibility with existing tools.
"""

import asyncio
import base64
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from codegen import ws_service, ws_expose, ws_event, ws_type
from core.debug_log import debug_log, Category


@ws_type
@dataclass
class BrowserInfo:
    """Information about a browser instance."""

    name: str
    browser_id: str  # Internal ID from surfer-rs
    browser_type: str  # "chrome", "firefox", etc.
    headless: bool
    status: str  # "connecting", "connected", "disconnected", "error"
    current_url: Optional[str] = None
    current_title: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    error: Optional[str] = None


@ws_type
@dataclass
class BrowserListResult:
    """Result of list_browsers."""

    browsers: list[BrowserInfo]
    default_browser: Optional[str] = None  # Name of the default browser


@ws_type
@dataclass
class BrowserCreateRequest:
    """Request to create a new browser."""

    name: Optional[str] = None  # Auto-generated if not provided
    browser_type: str = "chrome"
    headless: bool = True
    webdriver_url: Optional[str] = None
    port: Optional[int] = None
    set_as_default: bool = False


@ws_type
@dataclass
class BrowserResult:
    """Generic result for browser operations."""

    success: bool
    browser: Optional[BrowserInfo] = None
    error: Optional[str] = None
    data: Optional[str] = None  # For operations that return data


@ws_type
@dataclass
class BrowserNavigateResult:
    """Result of navigation operations."""

    success: bool
    url: Optional[str] = None
    title: Optional[str] = None
    error: Optional[str] = None


@ws_type
@dataclass
class BrowserScreenshotResult:
    """Result of screenshot operation."""

    success: bool
    data_url: Optional[str] = None  # data:image/png;base64,...
    error: Optional[str] = None


@ws_type
@dataclass
class BrowserSeeResult:
    """Result of browser_see - structured page content."""

    success: bool
    content: Optional[str] = None  # JSON string of page structure
    error: Optional[str] = None


@ws_type
@dataclass
class BrowserEvent:
    """Event data for browser state changes."""

    browser_name: str
    event_type: str  # "created", "destroyed", "navigated", "status_changed"
    browser: Optional[BrowserInfo] = None
    url: Optional[str] = None
    title: Optional[str] = None
    ts: float = field(default_factory=time.time)


class BrowserInstance:
    """Internal wrapper around a browser instance."""

    def __init__(
        self,
        name: str,
        browser: Any,  # balloons_storage.Browser
        browser_type: str,
        headless: bool,
    ):
        self.name = name
        self.browser = browser
        self.browser_type = browser_type
        self.headless = headless
        self.status = "connecting"
        self.browser_id: Optional[str] = None
        self.current_url: Optional[str] = None
        self.current_title: Optional[str] = None
        self.created_at = time.time()
        self.error: Optional[str] = None

    def to_info(self) -> BrowserInfo:
        """Convert to BrowserInfo for API responses."""
        return BrowserInfo(
            name=self.name,
            browser_id=self.browser_id or "",
            browser_type=self.browser_type,
            headless=self.headless,
            status=self.status,
            current_url=self.current_url,
            current_title=self.current_title,
            created_at=self.created_at,
            error=self.error,
        )


# Global registry and service instance
_browser_registry: dict[str, BrowserInstance] = {}
_default_browser_name: Optional[str] = None
_service_instance: Optional["BrowserStateService"] = None
_name_counter = 0
_port_counter = 9515  # Start above default chromedriver port


def _generate_browser_name() -> str:
    """Generate a unique browser name."""
    global _name_counter
    _name_counter += 1
    return f"browser-{_name_counter}"


def _get_next_port() -> int:
    """Get the next available port for WebDriver."""
    global _port_counter
    _port_counter += 1
    return _port_counter


def get_browser_by_name(name: Optional[str] = None) -> Optional[BrowserInstance]:
    """Get a browser instance by name.

    If name is None, returns the default browser.
    Used by browser_tools.py for tool integration.
    """
    if name is None:
        name = _default_browser_name
    if name is None:
        return None
    return _browser_registry.get(name)


def get_default_browser_name() -> Optional[str]:
    """Get the name of the default browser."""
    return _default_browser_name


def set_default_browser_name(name: Optional[str]) -> None:
    """Set the default browser name."""
    global _default_browser_name
    _default_browser_name = name


@ws_service
class BrowserStateService:
    """WebSocket-exposed service for browser management.

    Provides:
    - Browser lifecycle: create, destroy, list, rename
    - Browser control: goto, see, click, fill, screenshot
    - Real-time events for browser state changes
    """

    def __init__(self) -> None:
        """Initialize the browser state service."""
        global _service_instance
        _service_instance = self

        # Event handlers for WebSocket broadcasting
        self._event_handlers: list[Callable[[str, dict], None]] = []

        # Lock for browser operations
        self._lock = asyncio.Lock()

    def add_event_handler(self, handler: Callable[[str, dict], None]) -> None:
        """Register an event handler for WebSocket broadcasting."""
        self._event_handlers.append(handler)

    def remove_event_handler(self, handler: Callable[[str, dict], None]) -> None:
        """Unregister an event handler."""
        if handler in self._event_handlers:
            self._event_handlers.remove(handler)

    def _emit_event(self, event_name: str, data: dict) -> None:
        """Emit an event to all registered handlers."""
        for handler in self._event_handlers:
            try:
                handler(event_name, data)
            except Exception as e:
                debug_log.error(f"Event handler error: {e}", category=Category.RUNNER)

    def _emit_browser_event(self, event_type: str, browser: BrowserInstance, **kwargs) -> None:
        """Emit a browser event."""
        event = BrowserEvent(
            browser_name=browser.name,
            event_type=event_type,
            browser=browser.to_info(),
            ts=time.time(),
            **kwargs,
        )
        self._emit_event("browserEvent", {
            "browserName": event.browser_name,
            "eventType": event.event_type,
            "browser": {
                "name": event.browser.name,
                "browserId": event.browser.browser_id,
                "browserType": event.browser.browser_type,
                "headless": event.browser.headless,
                "status": event.browser.status,
                "currentUrl": event.browser.current_url,
                "currentTitle": event.browser.current_title,
                "createdAt": event.browser.created_at,
                "error": event.browser.error,
            } if event.browser else None,
            "url": event.url,
            "title": event.title,
            "ts": event.ts,
        })

    @ws_expose
    async def create_browser(
        self,
        name: Optional[str] = None,
        browser_type: str = "chrome",
        headless: bool = True,
        webdriver_url: Optional[str] = None,
        port: Optional[int] = None,
        set_as_default: bool = False,
    ) -> BrowserResult:
        """Create a new browser instance.

        Args:
            name: Browser name (auto-generated if not provided)
            browser_type: Browser type ("chrome", "firefox")
            headless: Run in headless mode
            webdriver_url: Optional WebDriver URL
            port: Optional port for WebDriver
            set_as_default: Set this browser as the default

        Returns:
            BrowserResult with the created browser info
        """
        global _default_browser_name

        try:
            from balloons_storage import Browser, BrowserConfig

            # Generate name if not provided
            if not name:
                name = _generate_browser_name()

            # Check for duplicate names
            if name in _browser_registry:
                return BrowserResult(
                    success=False,
                    error=f"Browser '{name}' already exists",
                )

            # Build config - use auto-incrementing port to avoid conflicts
            config_kwargs = {
                "browser_type": browser_type,
                "headless": headless,
            }
            if port is not None:
                config_kwargs["port"] = port
            elif not webdriver_url:
                # Auto-assign a unique port to avoid conflicts
                config_kwargs["port"] = _get_next_port()
            if webdriver_url:
                config_kwargs["webdriver_url"] = webdriver_url

            config = BrowserConfig(**config_kwargs)

            # Create browser instance
            browser = Browser(config)
            instance = BrowserInstance(
                name=name,
                browser=browser,
                browser_type=browser_type,
                headless=headless,
            )

            # Register before connecting (so UI sees it in "connecting" state)
            async with self._lock:
                _browser_registry[name] = instance

            # Emit created event
            self._emit_browser_event("created", instance)

            # Connect
            try:
                await browser.connect()
                instance.browser_id = await browser.id()
                instance.status = "connected"

                debug_log.info(
                    f"Browser created: {name} (ID: {instance.browser_id[:8]}...)",
                    category=Category.RUNNER,
                )

                # Set as default if requested or if it's the first browser
                if set_as_default or _default_browser_name is None:
                    _default_browser_name = name

                # Emit status change
                self._emit_browser_event("status_changed", instance)

                return BrowserResult(
                    success=True,
                    browser=instance.to_info(),
                )

            except Exception as e:
                instance.status = "error"
                instance.error = str(e)
                self._emit_browser_event("status_changed", instance)

                # Clean up failed browser
                async with self._lock:
                    if name in _browser_registry:
                        del _browser_registry[name]

                return BrowserResult(
                    success=False,
                    error=f"Failed to connect browser: {e}",
                )

        except ImportError as e:
            return BrowserResult(
                success=False,
                error=f"Browser bindings not available: {e}",
            )
        except Exception as e:
            debug_log.error(f"Error creating browser: {e}", category=Category.RUNNER)
            return BrowserResult(
                success=False,
                error=str(e),
            )

    @ws_expose
    def list_browsers(self) -> BrowserListResult:
        """List all browser instances.

        Returns:
            BrowserListResult with all browsers and default browser name
        """
        browsers = [instance.to_info() for instance in _browser_registry.values()]
        return BrowserListResult(
            browsers=browsers,
            default_browser=_default_browser_name,
        )

    @ws_expose
    def get_browser(self, name: str) -> BrowserResult:
        """Get a specific browser by name.

        Args:
            name: Browser name

        Returns:
            BrowserResult with the browser info
        """
        instance = _browser_registry.get(name)
        if not instance:
            return BrowserResult(
                success=False,
                error=f"Browser '{name}' not found",
            )
        return BrowserResult(
            success=True,
            browser=instance.to_info(),
        )

    @ws_expose
    async def destroy_browser(self, name: str) -> BrowserResult:
        """Destroy a browser instance.

        Args:
            name: Browser name to destroy

        Returns:
            BrowserResult indicating success/failure
        """
        global _default_browser_name

        async with self._lock:
            instance = _browser_registry.get(name)
            if not instance:
                return BrowserResult(
                    success=False,
                    error=f"Browser '{name}' not found",
                )

            try:
                await instance.browser.disconnect()
            except Exception as e:
                debug_log.warning(
                    f"Error disconnecting browser {name}: {e}",
                    category=Category.RUNNER,
                )

            del _browser_registry[name]

            # Update default if we destroyed it
            if _default_browser_name == name:
                _default_browser_name = next(iter(_browser_registry.keys()), None)

            debug_log.info(f"Browser destroyed: {name}", category=Category.RUNNER)

            # Emit destroyed event
            self._emit_browser_event("destroyed", instance)

            return BrowserResult(success=True)

    @ws_expose
    async def rename_browser(self, old_name: str, new_name: str) -> BrowserResult:
        """Rename a browser instance.

        Args:
            old_name: Current browser name
            new_name: New browser name

        Returns:
            BrowserResult with updated browser info
        """
        global _default_browser_name

        async with self._lock:
            if old_name not in _browser_registry:
                return BrowserResult(
                    success=False,
                    error=f"Browser '{old_name}' not found",
                )

            if new_name in _browser_registry:
                return BrowserResult(
                    success=False,
                    error=f"Browser '{new_name}' already exists",
                )

            instance = _browser_registry[old_name]
            instance.name = new_name
            del _browser_registry[old_name]
            _browser_registry[new_name] = instance

            # Update default if we renamed it
            if _default_browser_name == old_name:
                _default_browser_name = new_name

            debug_log.info(
                f"Browser renamed: {old_name} -> {new_name}",
                category=Category.RUNNER,
            )

            # Emit status change with new name
            self._emit_browser_event("status_changed", instance)

            return BrowserResult(
                success=True,
                browser=instance.to_info(),
            )

    @ws_expose
    def set_default(self, name: str) -> BrowserResult:
        """Set the default browser.

        Args:
            name: Browser name to set as default

        Returns:
            BrowserResult indicating success/failure
        """
        global _default_browser_name

        if name not in _browser_registry:
            return BrowserResult(
                success=False,
                error=f"Browser '{name}' not found",
            )

        _default_browser_name = name
        return BrowserResult(
            success=True,
            browser=_browser_registry[name].to_info(),
        )

    # Browser control methods

    @ws_expose
    async def goto(self, url: str, name: Optional[str] = None) -> BrowserNavigateResult:
        """Navigate to a URL.

        Args:
            url: URL to navigate to
            name: Browser name (uses default if not specified)

        Returns:
            BrowserNavigateResult with current URL and title
        """
        instance = get_browser_by_name(name)
        if not instance:
            return BrowserNavigateResult(
                success=False,
                error=f"Browser '{name or 'default'}' not found",
            )

        try:
            await instance.browser.goto(url)
            instance.current_url = url

            # Try to get title
            try:
                instance.current_title = await instance.browser.title()
            except Exception:
                pass

            # Emit navigated event
            self._emit_browser_event(
                "navigated",
                instance,
                url=instance.current_url,
                title=instance.current_title,
            )

            return BrowserNavigateResult(
                success=True,
                url=instance.current_url,
                title=instance.current_title,
            )
        except Exception as e:
            return BrowserNavigateResult(
                success=False,
                error=str(e),
            )

    @ws_expose
    async def see(self, name: Optional[str] = None) -> BrowserSeeResult:
        """Get structured page content.

        Args:
            name: Browser name (uses default if not specified)

        Returns:
            BrowserSeeResult with page structure as JSON
        """
        instance = get_browser_by_name(name)
        if not instance:
            return BrowserSeeResult(
                success=False,
                error=f"Browser '{name or 'default'}' not found",
            )

        try:
            result = await instance.browser.see()
            # Format the result
            if isinstance(result, str):
                try:
                    parsed = json.loads(result)
                    content = json.dumps(parsed, indent=2, ensure_ascii=False)
                except Exception:
                    content = result
            else:
                content = json.dumps(result, indent=2, ensure_ascii=False)

            return BrowserSeeResult(
                success=True,
                content=content,
            )
        except Exception as e:
            return BrowserSeeResult(
                success=False,
                error=str(e),
            )

    @ws_expose
    async def screenshot(self, name: Optional[str] = None) -> BrowserScreenshotResult:
        """Take a screenshot.

        Args:
            name: Browser name (uses default if not specified)

        Returns:
            BrowserScreenshotResult with base64-encoded PNG data URL
        """
        instance = get_browser_by_name(name)
        if not instance:
            return BrowserScreenshotResult(
                success=False,
                error=f"Browser '{name or 'default'}' not found",
            )

        try:
            png_data = await instance.browser.screenshot()
            b64 = base64.b64encode(png_data).decode("ascii")
            return BrowserScreenshotResult(
                success=True,
                data_url=f"data:image/png;base64,{b64}",
            )
        except Exception as e:
            return BrowserScreenshotResult(
                success=False,
                error=str(e),
            )

    @ws_expose
    async def click(self, selector: str, name: Optional[str] = None) -> BrowserResult:
        """Click an element.

        Args:
            selector: CSS selector for element to click
            name: Browser name (uses default if not specified)

        Returns:
            BrowserResult indicating success/failure
        """
        instance = get_browser_by_name(name)
        if not instance:
            return BrowserResult(
                success=False,
                error=f"Browser '{name or 'default'}' not found",
            )

        try:
            await instance.browser.click(selector)
            return BrowserResult(success=True)
        except Exception as e:
            return BrowserResult(
                success=False,
                error=str(e),
            )

    @ws_expose
    async def fill(
        self,
        selector: str,
        text: str,
        name: Optional[str] = None,
    ) -> BrowserResult:
        """Fill an input field.

        Args:
            selector: CSS selector for input
            text: Text to fill
            name: Browser name (uses default if not specified)

        Returns:
            BrowserResult indicating success/failure
        """
        instance = get_browser_by_name(name)
        if not instance:
            return BrowserResult(
                success=False,
                error=f"Browser '{name or 'default'}' not found",
            )

        try:
            await instance.browser.fill(selector, text)
            return BrowserResult(success=True)
        except Exception as e:
            return BrowserResult(
                success=False,
                error=str(e),
            )

    @ws_expose
    async def get_url(self, name: Optional[str] = None) -> BrowserResult:
        """Get current URL.

        Args:
            name: Browser name (uses default if not specified)

        Returns:
            BrowserResult with URL in data field
        """
        instance = get_browser_by_name(name)
        if not instance:
            return BrowserResult(
                success=False,
                error=f"Browser '{name or 'default'}' not found",
            )

        try:
            url = await instance.browser.url()
            instance.current_url = url
            return BrowserResult(
                success=True,
                data=url,
            )
        except Exception as e:
            return BrowserResult(
                success=False,
                error=str(e),
            )

    @ws_expose
    async def get_title(self, name: Optional[str] = None) -> BrowserResult:
        """Get page title.

        Args:
            name: Browser name (uses default if not specified)

        Returns:
            BrowserResult with title in data field
        """
        instance = get_browser_by_name(name)
        if not instance:
            return BrowserResult(
                success=False,
                error=f"Browser '{name or 'default'}' not found",
            )

        try:
            title = await instance.browser.title()
            instance.current_title = title
            return BrowserResult(
                success=True,
                data=title,
            )
        except Exception as e:
            return BrowserResult(
                success=False,
                error=str(e),
            )

    @ws_expose
    async def back(self, name: Optional[str] = None) -> BrowserResult:
        """Navigate back.

        Args:
            name: Browser name (uses default if not specified)

        Returns:
            BrowserResult indicating success/failure
        """
        instance = get_browser_by_name(name)
        if not instance:
            return BrowserResult(
                success=False,
                error=f"Browser '{name or 'default'}' not found",
            )

        try:
            await instance.browser.back()
            return BrowserResult(success=True)
        except Exception as e:
            return BrowserResult(
                success=False,
                error=str(e),
            )

    @ws_expose
    async def forward(self, name: Optional[str] = None) -> BrowserResult:
        """Navigate forward.

        Args:
            name: Browser name (uses default if not specified)

        Returns:
            BrowserResult indicating success/failure
        """
        instance = get_browser_by_name(name)
        if not instance:
            return BrowserResult(
                success=False,
                error=f"Browser '{name or 'default'}' not found",
            )

        try:
            await instance.browser.forward()
            return BrowserResult(success=True)
        except Exception as e:
            return BrowserResult(
                success=False,
                error=str(e),
            )

    @ws_expose
    async def refresh(self, name: Optional[str] = None) -> BrowserResult:
        """Refresh the page.

        Args:
            name: Browser name (uses default if not specified)

        Returns:
            BrowserResult indicating success/failure
        """
        instance = get_browser_by_name(name)
        if not instance:
            return BrowserResult(
                success=False,
                error=f"Browser '{name or 'default'}' not found",
            )

        try:
            await instance.browser.refresh()
            return BrowserResult(success=True)
        except Exception as e:
            return BrowserResult(
                success=False,
                error=str(e),
            )

    @ws_expose
    async def execute_js(self, script: str, name: Optional[str] = None) -> BrowserResult:
        """Execute JavaScript.

        Args:
            script: JavaScript code to execute
            name: Browser name (uses default if not specified)

        Returns:
            BrowserResult with result in data field
        """
        instance = get_browser_by_name(name)
        if not instance:
            return BrowserResult(
                success=False,
                error=f"Browser '{name or 'default'}' not found",
            )

        try:
            result = await instance.browser.execute_js(script)
            return BrowserResult(
                success=True,
                data=result,
            )
        except Exception as e:
            return BrowserResult(
                success=False,
                error=str(e),
            )

    @ws_expose
    async def inputs(self, name: Optional[str] = None) -> BrowserResult:
        """Get all input elements.

        Args:
            name: Browser name (uses default if not specified)

        Returns:
            BrowserResult with input elements as JSON in data field
        """
        instance = get_browser_by_name(name)
        if not instance:
            return BrowserResult(
                success=False,
                error=f"Browser '{name or 'default'}' not found",
            )

        try:
            result = await instance.browser.inputs()
            if isinstance(result, str):
                try:
                    parsed = json.loads(result)
                    data = json.dumps(parsed, indent=2, ensure_ascii=False)
                except Exception:
                    data = result
            else:
                data = json.dumps(result, indent=2, ensure_ascii=False)

            return BrowserResult(
                success=True,
                data=data,
            )
        except Exception as e:
            return BrowserResult(
                success=False,
                error=str(e),
            )

    @ws_expose
    async def buttons(self, name: Optional[str] = None) -> BrowserResult:
        """Get all button elements.

        Args:
            name: Browser name (uses default if not specified)

        Returns:
            BrowserResult with button elements as JSON in data field
        """
        instance = get_browser_by_name(name)
        if not instance:
            return BrowserResult(
                success=False,
                error=f"Browser '{name or 'default'}' not found",
            )

        try:
            result = await instance.browser.buttons()
            if isinstance(result, str):
                try:
                    parsed = json.loads(result)
                    data = json.dumps(parsed, indent=2, ensure_ascii=False)
                except Exception:
                    data = result
            else:
                data = json.dumps(result, indent=2, ensure_ascii=False)

            return BrowserResult(
                success=True,
                data=data,
            )
        except Exception as e:
            return BrowserResult(
                success=False,
                error=str(e),
            )

    @ws_expose
    async def links(
        self,
        limit: Optional[int] = None,
        name: Optional[str] = None,
    ) -> BrowserResult:
        """Get all links.

        Args:
            limit: Maximum number of links to return
            name: Browser name (uses default if not specified)

        Returns:
            BrowserResult with links as JSON in data field
        """
        instance = get_browser_by_name(name)
        if not instance:
            return BrowserResult(
                success=False,
                error=f"Browser '{name or 'default'}' not found",
            )

        try:
            result = await instance.browser.links(limit)
            if isinstance(result, str):
                try:
                    parsed = json.loads(result)
                    data = json.dumps(parsed, indent=2, ensure_ascii=False)
                except Exception:
                    data = result
            else:
                data = json.dumps(result, indent=2, ensure_ascii=False)

            return BrowserResult(
                success=True,
                data=data,
            )
        except Exception as e:
            return BrowserResult(
                success=False,
                error=str(e),
            )

    @ws_expose
    async def click_button(self, index: int, name: Optional[str] = None) -> BrowserResult:
        """Click a button by index.

        Args:
            index: Button index (from buttons() result)
            name: Browser name (uses default if not specified)

        Returns:
            BrowserResult indicating success/failure
        """
        instance = get_browser_by_name(name)
        if not instance:
            return BrowserResult(
                success=False,
                error=f"Browser '{name or 'default'}' not found",
            )

        try:
            await instance.browser.click_button(index)
            return BrowserResult(success=True)
        except Exception as e:
            return BrowserResult(
                success=False,
                error=str(e),
            )

    @ws_expose
    async def set_input(
        self,
        index: int,
        value: str,
        name: Optional[str] = None,
    ) -> BrowserResult:
        """Set an input value by index.

        Args:
            index: Input index (from inputs() result)
            value: Value to set
            name: Browser name (uses default if not specified)

        Returns:
            BrowserResult indicating success/failure
        """
        instance = get_browser_by_name(name)
        if not instance:
            return BrowserResult(
                success=False,
                error=f"Browser '{name or 'default'}' not found",
            )

        try:
            await instance.browser.set_input(index, value)
            return BrowserResult(success=True)
        except Exception as e:
            return BrowserResult(
                success=False,
                error=str(e),
            )

    # Events

    @ws_event
    def browser_event(self, event: BrowserEvent) -> BrowserEvent:
        """Fired when browser state changes (created, destroyed, navigated, etc)."""
        pass

    @ws_event
    def browser_created(self, browser: BrowserInfo) -> BrowserInfo:
        """Fired when a new browser is created."""
        pass

    @ws_event
    def browser_destroyed(self, browser: BrowserInfo) -> BrowserInfo:
        """Fired when a browser is destroyed."""
        pass

    @ws_event
    def browser_navigated(self, browser: BrowserInfo) -> BrowserInfo:
        """Fired when a browser navigates to a new URL."""
        pass
