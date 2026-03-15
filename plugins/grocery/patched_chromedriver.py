#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "undetected-chromedriver>=3.5.5",
#     "setuptools",
# ]
# ///
"""
Patch and start chromedriver with anti-detection.

This patches the chromedriver binary to remove cdc_* variable injection,
then starts it on a specified port. surfer-rs can then connect to it.

Usage:
    uv run patched_chromedriver.py [--port PORT] [--display DISPLAY]

The patched chromedriver will run on the specified port (default 4444).
Connect surfer-rs to http://localhost:PORT
"""

import argparse
import os
import subprocess
import sys
import time
import signal

from undetected_chromedriver.patcher import Patcher


def main():
    parser = argparse.ArgumentParser(description="Start patched chromedriver")
    parser.add_argument("--port", type=int, default=4444, help="Port to run on (default: 4444)")
    parser.add_argument("--display", default=":0", help="X11 display (default: :0)")
    parser.add_argument("--allowed-ips", default="", help="Allowed IPs (default: all)")
    args = parser.parse_args()

    # Set display
    os.environ["DISPLAY"] = args.display

    # Create patcher - this will download and patch chromedriver if needed
    print("Checking/patching chromedriver...")
    patcher = Patcher()

    # auto() downloads if missing and patches
    patcher.auto()

    print(f"Patched chromedriver at: {patcher.executable_path}")
    print(f"Starting on port {args.port}...")

    # Start chromedriver
    cmd = [
        patcher.executable_path,
        f"--port={args.port}",
        f"--allowed-ips={args.allowed_ips}",
    ]

    print(f"Running: {' '.join(cmd)}")

    # Run chromedriver
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def signal_handler(sig, frame):
        print("\nShutting down...")
        proc.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print(f"\nPatched chromedriver running on port {args.port}")
    print(f"Connect surfer-rs to: http://localhost:{args.port}")
    print("Press Ctrl+C to stop\n")

    # Stream output
    try:
        for line in proc.stdout:
            print(line.decode().rstrip())
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
