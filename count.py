#!/usr/bin/env python3
import sys
import time

n = int(sys.argv[1]) if len(sys.argv) > 1 else 10

for i in range(1, n + 1):
    print(f"Count: {i}")
    time.sleep(1)
