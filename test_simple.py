#!/usr/bin/env python3
import sys
print("Script starting", flush=True)
sys.path.insert(0, '/home/dan/Development/balloons/balloons-rs/target/release')
import balloons_py as bs
import asyncio

async def main():
    print("In async main", flush=True)
    config = bs.BrowserConfig.chrome()
    browser = bs.Browser(config)

    connected = await browser.is_connected()
    print(f"is_connected: {connected}", flush=True)

    print("Connecting...", flush=True)
    try:
        await asyncio.wait_for(browser.connect(), timeout=15.0)
        print("Connected!", flush=True)
    except asyncio.TimeoutError:
        print("TIMEOUT!", flush=True)
        return
    except Exception as e:
        print(f"Connect ERROR: {e}", flush=True)
        return

    print("Navigating to example.com...", flush=True)
    try:
        await asyncio.wait_for(browser.goto("https://example.com"), timeout=15.0)
        print("Navigated!", flush=True)
    except asyncio.TimeoutError:
        print("TIMEOUT on goto!", flush=True)
        return
    except Exception as e:
        print(f"Goto ERROR: {e}", flush=True)
        return

    print("Getting title...", flush=True)
    try:
        title = await asyncio.wait_for(browser.title(), timeout=10.0)
        print(f"Title: {title}", flush=True)
    except asyncio.TimeoutError:
        print("TIMEOUT on title!", flush=True)
        return
    except Exception as e:
        print(f"Title ERROR: {e}", flush=True)
        return

    print("Getting URL...", flush=True)
    try:
        url = await asyncio.wait_for(browser.url(), timeout=10.0)
        print(f"URL: {url}", flush=True)
    except asyncio.TimeoutError:
        print("TIMEOUT on url!", flush=True)
        return
    except Exception as e:
        print(f"URL ERROR: {e}", flush=True)
        return

    print("Disconnecting...", flush=True)
    try:
        await asyncio.wait_for(browser.disconnect(), timeout=10.0)
        print("Disconnected!", flush=True)
    except asyncio.TimeoutError:
        print("TIMEOUT on disconnect!", flush=True)
        return
    except Exception as e:
        print(f"Disconnect ERROR: {e}", flush=True)
        return

    print("SUCCESS!", flush=True)

asyncio.run(main())
print("Finished", flush=True)
