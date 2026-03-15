#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "undetected-chromedriver>=3.5.5",
#     "setuptools",
# ]
# ///
"""
SaveOn Foods browser with anti-detection.

Run with uv:
    DISPLAY=:0 uv run saveon_browser.py

This uses undetected-chromedriver to bypass Cloudflare/bot detection.
"""

import sys
import time
import json

import undetected_chromedriver as uc


def main():
    print("Starting undetected Chrome...")

    options = uc.ChromeOptions()
    options.add_argument('--no-sandbox')
    options.add_argument('--start-maximized')

    # Let undetected-chromedriver auto-download matching chromedriver
    driver = uc.Chrome(options=options, headless=False)

    # Set geolocation to Victoria, BC area (Langford)
    # This auto-grants location permission and sets coordinates
    driver.execute_cdp_cmd("Emulation.setGeolocationOverride", {
        "latitude": 48.4516,
        "longitude": -123.5023,
        "accuracy": 100
    })
    # Grant geolocation permission
    driver.execute_cdp_cmd("Browser.grantPermissions", {
        "permissions": ["geolocation"]
    })

    print("Navigating to SaveOn Foods...")
    driver.get('https://www.saveonfoods.com/')

    # Wait for page to load
    time.sleep(5)

    print(f"\nTitle: {driver.title}")
    print(f"URL: {driver.current_url}")

    # Check detection status
    try:
        result = driver.execute_script('''
            return {
                webdriver: navigator.webdriver,
                cdc_vars: Object.keys(window).filter(k => k.startsWith('cdc_')).length,
                automation: !!window.navigator.webdriver
            }
        ''')
        print(f"\nDetection check:")
        print(f"  navigator.webdriver: {result.get('webdriver')}")
        print(f"  cdc_* variables: {result.get('cdc_vars')}")
    except Exception as e:
        print(f"Detection check failed: {e}")

    # Check if page loaded or is blocked
    try:
        body_text = driver.execute_script("return document.body.innerText.substring(0, 500)")
        if "Cloudflare" in body_text or len(body_text.strip()) < 50:
            print("\n  Page appears blocked or loading...")
        else:
            print("\n Page loaded successfully!")
    except:
        pass

    print("\n" + "="*50)
    print("Browser is running. Commands:")
    print("  search <query>  - Search for products")
    print("  stores <postal> - Find stores near postal code")
    print("  screenshot      - Save screenshot")
    print("  quit            - Close browser")
    print("="*50 + "\n")

    try:
        while True:
            cmd = input("> ").strip()

            if not cmd:
                continue

            if cmd == "quit" or cmd == "exit":
                break

            if cmd == "screenshot":
                path = f"/tmp/saveon_{int(time.time())}.png"
                driver.save_screenshot(path)
                print(f"Saved: {path}")
                continue

            if cmd.startswith("search "):
                query = cmd[7:]
                driver.get(f"https://www.saveonfoods.com/sm/pickup/rsid/6605/results?q={query}")
                time.sleep(3)
                print(f"Searched for: {query}")
                print(f"URL: {driver.current_url}")
                continue

            if cmd.startswith("stores "):
                postal = cmd[7:]
                # Navigate to store locator
                driver.get("https://www.saveonfoods.com/sm/pickup/rsid/6605/store-locator")
                time.sleep(2)
                print(f"Store locator opened. Enter postal code: {postal}")
                continue

            if cmd.startswith("js "):
                js = cmd[3:]
                try:
                    result = driver.execute_script(f"return {js}")
                    print(json.dumps(result, indent=2))
                except Exception as e:
                    print(f"Error: {e}")
                continue

            if cmd == "url":
                print(driver.current_url)
                continue

            if cmd == "title":
                print(driver.title)
                continue

            print(f"Unknown command: {cmd}")

    except (KeyboardInterrupt, EOFError):
        print("\nInterrupted")
    finally:
        print("Closing browser...")
        driver.quit()


if __name__ == "__main__":
    main()
