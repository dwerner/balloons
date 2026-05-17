#!/usr/bin/env python3
"""Test the async Browser API.

Examples:
    python test_browser_async.py --browser chrome --headless
    DISPLAY=:0 python test_browser_async.py --browser chrome
    python test_browser_async.py --browser chrome --webdriver-url http://localhost:9515
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, '/home/dan/Development/balloons/balloons-rs/target/release')

import balloons_py as bs


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', default='chrome', choices=['chrome', 'firefox'])
    parser.add_argument('--headless', action='store_true', help='Run headless')
    parser.add_argument('--webdriver-url', help='Connect to existing WebDriver instead of starting one')
    parser.add_argument('--port', type=int, default=None, help='Local WebDriver port override')
    parser.add_argument('--url', default='https://example.com')
    args = parser.parse_args()

    print('Creating browser config...')
    kwargs = {
        'browser_type': args.browser,
        'headless': args.headless,
    }
    if args.port is not None:
        kwargs['port'] = args.port
    if args.webdriver_url:
        kwargs['webdriver_url'] = args.webdriver_url
    config = bs.BrowserConfig(**kwargs)

    print('Creating browser...')
    browser = bs.Browser(config)

    print('Connecting (this uses the async API)...')
    print(f"DISPLAY={os.environ.get('DISPLAY')!r}")
    import time
    start = time.time()
    try:
        await asyncio.wait_for(browser.connect(), timeout=20.0)
        print(f'Connect took {time.time() - start:.2f}s')
    except asyncio.TimeoutError:
        print(f'Connect timed out after {time.time() - start:.2f}s')
        return

    print('Checking connection...')
    connected = await browser.is_connected()
    print(f'Connected: {connected}')

    print(f'Navigating to {args.url}...')
    await browser.goto(args.url)

    print('Getting title...')
    title = await browser.title()
    print(f'Title: {title}')

    print('Getting URL...')
    url = await browser.url()
    print(f'URL: {url}')

    print('Disconnecting...')
    await browser.disconnect()

    print('Done!')


if __name__ == '__main__':
    asyncio.run(main())
