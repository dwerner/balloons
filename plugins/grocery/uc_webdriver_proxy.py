#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "undetected-chromedriver>=3.5.5",
#     "setuptools",
#     "flask",
# ]
# ///
"""
WebDriver proxy server using undetected-chromedriver.

This exposes a WebDriver-compatible HTTP API that clients like fantoccini/surfer-rs
can connect to, but internally uses undetected-chromedriver to bypass bot detection.

Usage:
    DISPLAY=:0 uv run uc_webdriver_proxy.py --port 4444

Then connect surfer-rs to http://localhost:4444
"""

import argparse
import base64
import json
import os
import sys
import threading
import time
import uuid
from typing import Any

from flask import Flask, request, jsonify, Response

import undetected_chromedriver as uc

app = Flask(__name__)

# Store active sessions
sessions: dict[str, uc.Chrome] = {}
session_lock = threading.Lock()


def make_response(value: Any = None, session_id: str = None) -> dict:
    """Create a WebDriver response."""
    return {"value": value, "sessionId": session_id}


def make_error(error: str, message: str) -> tuple[dict, int]:
    """Create a WebDriver error response."""
    return {
        "value": {
            "error": error,
            "message": message,
            "stacktrace": ""
        }
    }, 500


@app.route("/status", methods=["GET"])
def status():
    """WebDriver status endpoint."""
    return jsonify({
        "value": {
            "ready": True,
            "message": "undetected-chromedriver proxy ready"
        }
    })


@app.route("/session", methods=["POST"])
def new_session():
    """Create a new browser session."""
    global sessions

    try:
        data = request.get_json() or {}
        caps = data.get("capabilities", {}).get("alwaysMatch", {})

        options = uc.ChromeOptions()
        options.add_argument('--no-sandbox')
        options.add_argument('--start-maximized')

        # Check for headless
        chrome_opts = caps.get("goog:chromeOptions", {})
        args = chrome_opts.get("args", [])
        headless = any("headless" in arg for arg in args)

        print(f"[proxy] Creating new session (headless={headless})...")

        driver = uc.Chrome(options=options, headless=headless)

        # Set geolocation (Victoria, BC area)
        driver.execute_cdp_cmd("Emulation.setGeolocationOverride", {
            "latitude": 48.4516,
            "longitude": -123.5023,
            "accuracy": 100
        })
        driver.execute_cdp_cmd("Browser.grantPermissions", {
            "permissions": ["geolocation"]
        })

        session_id = driver.session_id

        with session_lock:
            sessions[session_id] = driver

        print(f"[proxy] Session created: {session_id}")

        return jsonify({
            "value": {
                "sessionId": session_id,
                "capabilities": {
                    "browserName": "chrome",
                    "browserVersion": driver.capabilities.get("browserVersion", ""),
                    "platformName": driver.capabilities.get("platformName", ""),
                    "acceptInsecureCerts": False,
                    "pageLoadStrategy": "normal",
                    "proxy": {},
                    "timeouts": {"implicit": 0, "pageLoad": 300000, "script": 30000},
                    "strictFileInteractability": False,
                    "unhandledPromptBehavior": "dismiss and notify",
                }
            }
        })
    except Exception as e:
        print(f"[proxy] Error creating session: {e}")
        return make_error("session not created", str(e))


@app.route("/session/<session_id>", methods=["DELETE"])
def delete_session(session_id: str):
    """Close a browser session."""
    with session_lock:
        driver = sessions.pop(session_id, None)

    if driver:
        try:
            driver.quit()
            print(f"[proxy] Session closed: {session_id}")
        except:
            pass
        return jsonify(make_response(None, session_id))

    return make_error("invalid session id", f"Session {session_id} not found")


@app.route("/session/<session_id>/url", methods=["POST"])
def navigate(session_id: str):
    """Navigate to a URL."""
    driver = sessions.get(session_id)
    if not driver:
        return make_error("invalid session id", f"Session {session_id} not found")

    data = request.get_json()
    url = data.get("url")

    try:
        driver.get(url)
        return jsonify(make_response(None, session_id))
    except Exception as e:
        return make_error("unknown error", str(e))


@app.route("/session/<session_id>/url", methods=["GET"])
def get_url(session_id: str):
    """Get current URL."""
    driver = sessions.get(session_id)
    if not driver:
        return make_error("invalid session id", f"Session {session_id} not found")

    try:
        return jsonify(make_response(driver.current_url, session_id))
    except Exception as e:
        return make_error("unknown error", str(e))


@app.route("/session/<session_id>/title", methods=["GET"])
def get_title(session_id: str):
    """Get page title."""
    driver = sessions.get(session_id)
    if not driver:
        return make_error("invalid session id", f"Session {session_id} not found")

    try:
        return jsonify(make_response(driver.title, session_id))
    except Exception as e:
        return make_error("unknown error", str(e))


@app.route("/session/<session_id>/execute/sync", methods=["POST"])
def execute_script(session_id: str):
    """Execute JavaScript synchronously."""
    driver = sessions.get(session_id)
    if not driver:
        return make_error("invalid session id", f"Session {session_id} not found")

    data = request.get_json()
    script = data.get("script", "")
    args = data.get("args", [])

    try:
        result = driver.execute_script(script, *args)
        return jsonify(make_response(result, session_id))
    except Exception as e:
        return make_error("javascript error", str(e))


@app.route("/session/<session_id>/screenshot", methods=["GET"])
def screenshot(session_id: str):
    """Take a screenshot (returns base64)."""
    driver = sessions.get(session_id)
    if not driver:
        return make_error("invalid session id", f"Session {session_id} not found")

    try:
        png_base64 = driver.get_screenshot_as_base64()
        return jsonify(make_response(png_base64, session_id))
    except Exception as e:
        return make_error("unknown error", str(e))


@app.route("/session/<session_id>/element", methods=["POST"])
def find_element(session_id: str):
    """Find an element."""
    driver = sessions.get(session_id)
    if not driver:
        return make_error("invalid session id", f"Session {session_id} not found")

    data = request.get_json()
    using = data.get("using")
    value = data.get("value")

    try:
        if using == "css selector":
            element = driver.find_element("css selector", value)
        elif using == "xpath":
            element = driver.find_element("xpath", value)
        elif using == "id":
            element = driver.find_element("id", value)
        elif using == "tag name":
            element = driver.find_element("tag name", value)
        else:
            return make_error("invalid argument", f"Unknown locator: {using}")

        # Return element reference
        elem_id = element.id
        return jsonify(make_response({"element-6066-11e4-a52e-4f735466cecf": elem_id}, session_id))
    except Exception as e:
        return make_error("no such element", str(e))


@app.route("/session/<session_id>/elements", methods=["POST"])
def find_elements(session_id: str):
    """Find multiple elements."""
    driver = sessions.get(session_id)
    if not driver:
        return make_error("invalid session id", f"Session {session_id} not found")

    data = request.get_json()
    using = data.get("using")
    value = data.get("value")

    try:
        if using == "css selector":
            elements = driver.find_elements("css selector", value)
        elif using == "xpath":
            elements = driver.find_elements("xpath", value)
        elif using == "id":
            elements = driver.find_elements("id", value)
        elif using == "tag name":
            elements = driver.find_elements("tag name", value)
        else:
            return make_error("invalid argument", f"Unknown locator: {using}")

        # Return element references
        result = [{"element-6066-11e4-a52e-4f735466cecf": e.id} for e in elements]
        return jsonify(make_response(result, session_id))
    except Exception as e:
        return make_error("unknown error", str(e))


@app.route("/session/<session_id>/element/<element_id>/click", methods=["POST"])
def element_click(session_id: str, element_id: str):
    """Click an element."""
    driver = sessions.get(session_id)
    if not driver:
        return make_error("invalid session id", f"Session {session_id} not found")

    try:
        # Find element by internal ID
        element = driver.execute_script(
            "return document.querySelector(`[data-element-id='${arguments[0]}']`)",
            element_id
        )
        if element:
            element.click()
        return jsonify(make_response(None, session_id))
    except Exception as e:
        return make_error("unknown error", str(e))


@app.route("/session/<session_id>/source", methods=["GET"])
def page_source(session_id: str):
    """Get page source."""
    driver = sessions.get(session_id)
    if not driver:
        return make_error("invalid session id", f"Session {session_id} not found")

    try:
        return jsonify(make_response(driver.page_source, session_id))
    except Exception as e:
        return make_error("unknown error", str(e))


@app.route("/session/<session_id>/window/rect", methods=["GET"])
def get_window_rect(session_id: str):
    """Get window size and position."""
    driver = sessions.get(session_id)
    if not driver:
        return make_error("invalid session id", f"Session {session_id} not found")

    try:
        rect = driver.get_window_rect()
        return jsonify(make_response(rect, session_id))
    except Exception as e:
        return make_error("unknown error", str(e))


@app.route("/session/<session_id>/cookie", methods=["GET"])
def get_cookies(session_id: str):
    """Get all cookies."""
    driver = sessions.get(session_id)
    if not driver:
        return make_error("invalid session id", f"Session {session_id} not found")

    try:
        cookies = driver.get_cookies()
        return jsonify(make_response(cookies, session_id))
    except Exception as e:
        return make_error("unknown error", str(e))


# Catch-all for unimplemented endpoints
@app.route("/session/<session_id>/<path:subpath>", methods=["GET", "POST", "DELETE"])
def unimplemented(session_id: str, subpath: str):
    """Handle unimplemented WebDriver endpoints."""
    print(f"[proxy] Unimplemented: {request.method} /session/{session_id}/{subpath}")
    return make_error("unknown command", f"Endpoint not implemented: {subpath}")


def main():
    parser = argparse.ArgumentParser(description="WebDriver proxy using undetected-chromedriver")
    parser.add_argument("--port", type=int, default=4444, help="Port to listen on")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--display", default=":0", help="X11 display")
    args = parser.parse_args()

    os.environ["DISPLAY"] = args.display

    print(f"Starting undetected-chromedriver WebDriver proxy on {args.host}:{args.port}")
    print(f"DISPLAY={args.display}")
    print(f"Connect surfer-rs to: http://{args.host}:{args.port}")

    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
