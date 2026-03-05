#!/usr/bin/env python3
"""Test the async Browser API."""

import asyncio
import sys
sys.path.insert(0, '/home/dan/Development/balloons/balloons-rs/target/release')

import balloons_storage as bs

async def main():
    print("Creating browser config...")
    config = bs.BrowserConfig.chrome()
    # Note: headless is True by default for chrome()

    print("Creating browser...")
    browser = bs.Browser(config)

    print("Connecting (this uses the async API)...")
    import time
    start = time.time()
    try:
        await asyncio.wait_for(browser.connect(), timeout=20.0)
        print(f"Connect took {time.time() - start:.2f}s")
    except asyncio.TimeoutError:
        print(f"Connect timed out after {time.time() - start:.2f}s")
        return

    print("Checking connection...")
    connected = await browser.is_connected()
    print(f"Connected: {connected}")

    print("Navigating to example.com...")
    await browser.goto("https://example.com")

    print("Getting title...")
    title = await browser.title()
    print(f"Title: {title}")

    print("Getting URL...")
    url = await browser.url()
    print(f"URL: {url}")

    print("Disconnecting...")
    await browser.disconnect()

    print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
