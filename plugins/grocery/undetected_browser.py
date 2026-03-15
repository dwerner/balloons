"""
Undetected browser wrapper for SaveOn Foods and other bot-protected sites.

This wraps undetected-chromedriver to provide the same interface as surfer-rs Browser,
allowing the grocery plugin to use it interchangeably.
"""

import asyncio
import json
from typing import Any

try:
    import undetected_chromedriver as uc
except ImportError:
    uc = None


class UndetectedBrowser:
    """Browser wrapper using undetected-chromedriver for bot-protected sites."""

    def __init__(self, headless: bool = False, display: str = ":0"):
        if uc is None:
            raise ImportError("undetected-chromedriver not installed. Run: pip install undetected-chromedriver setuptools")

        self._driver = None
        self._headless = headless
        self._display = display

    async def connect(self) -> None:
        """Start Chrome with anti-detection patches."""
        import os

        # Set display for GUI mode
        if not self._headless and self._display:
            os.environ["DISPLAY"] = self._display

        options = uc.ChromeOptions()
        options.add_argument('--no-sandbox')
        if not self._headless:
            options.add_argument('--start-maximized')

        # Run in thread pool since uc.Chrome is blocking
        loop = asyncio.get_event_loop()
        self._driver = await loop.run_in_executor(
            None,
            lambda: uc.Chrome(options=options, headless=self._headless)
        )

        # Set geolocation to Victoria, BC area
        self._driver.execute_cdp_cmd("Emulation.setGeolocationOverride", {
            "latitude": 48.4516,
            "longitude": -123.5023,
            "accuracy": 100
        })
        self._driver.execute_cdp_cmd("Browser.grantPermissions", {
            "permissions": ["geolocation"]
        })

    async def goto(self, url: str) -> None:
        """Navigate to URL."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._driver.get, url)

    async def url(self) -> str:
        """Get current URL."""
        return self._driver.current_url

    async def title(self) -> str:
        """Get page title."""
        return self._driver.title

    async def execute_js(self, script: str) -> Any:
        """Execute JavaScript and return result."""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._driver.execute_script(f"return {script}")
        )
        return json.dumps(result) if result is not None else None

    async def screenshot(self, path: str) -> None:
        """Save screenshot to file."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._driver.save_screenshot, path)

    async def close(self) -> None:
        """Close browser."""
        if self._driver:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._driver.quit)
            self._driver = None

    def __del__(self):
        """Cleanup on deletion."""
        if self._driver:
            try:
                self._driver.quit()
            except:
                pass
