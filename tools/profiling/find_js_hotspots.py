#!/usr/bin/env python3
"""
Find JS functions with highest self-time across all threads.

Usage:
    python find_js_hotspots.py <profile.json.gz>
"""

import json
import gzip
import sys
from collections import defaultdict
from pathlib import Path


def analyze_profile(profile_path: str):
    path = Path(profile_path)
    if path.suffix == '.gz':
        with gzip.open(path, 'rt') as f:
            profile = json.load(f)
    else:
        with open(path) as f:
            profile = json.load(f)

    shared = profile.get('shared', {})
    stringArray = shared.get('stringArray', [])
    func_table = shared.get('funcTable', {})
    frame_table = shared.get('frameTable', {})
    stack_table = shared.get('stackTable', {})

    func_names = func_table.get('name', [])
    func_is_js = func_table.get('isJS', [])
    func_resources = func_table.get('resource', [])

    frame_funcs = frame_table.get('func', [])
    stack_frames = stack_table.get('frame', [])
    stack_prefix = stack_table.get('prefix', [])

    resource_table = shared.get('resourceTable', {})
    resource_names = resource_table.get('name', [])

    def get_string(idx):
        return stringArray[idx] if 0 <= idx < len(stringArray) else f"<{idx}>"

    def get_resource(func_idx):
        if 0 <= func_idx < len(func_resources):
            res_idx = func_resources[func_idx]
            if 0 <= res_idx < len(resource_names):
                return get_string(resource_names[res_idx])
        return ""

    print("=== Profile Overview ===")
    meta = profile.get('meta', {})
    print(f"Product: {meta.get('product')}")
    print(f"Threads: {len(profile['threads'])}")

    # Find all JS functions with self-time across all threads
    print("\n=== JS Functions by Self Time (ALL threads) ===")
    all_js_times = []

    for thread_idx, thread in enumerate(profile['threads']):
        name = thread.get('name', '')
        pid = thread.get('pid', '')

        samples = thread.get('samples', {})
        stacks = samples.get('stack', [])
        time_deltas = samples.get('timeDeltas', [])

        if not stacks or len(stacks) < 10:
            continue

        func_self_time = defaultdict(float)

        for stack_idx, delta in zip(stacks, time_deltas):
            if delta is None:
                delta = 1

            if stack_idx is not None and 0 <= stack_idx < len(stack_frames):
                frame_idx = stack_frames[stack_idx]
                if 0 <= frame_idx < len(frame_funcs):
                    func_idx = frame_funcs[frame_idx]
                    is_js = func_is_js[func_idx] if func_idx < len(func_is_js) else False
                    if is_js:
                        func_self_time[func_idx] += delta

        for func_idx, t in func_self_time.items():
            if t > 1:  # >1ms
                fname = get_string(func_names[func_idx])
                res = get_resource(func_idx)
                all_js_times.append((t, fname, res, thread_idx, name, pid))

    # Sort and show top
    all_js_times.sort(reverse=True)
    print(f"\nTop 50 JS functions by self time:")
    for t, fname, res, tidx, tname, pid in all_js_times[:50]:
        short_res = res.split('/')[-1][:20] if res else ""
        print(f"  {t:8.1f}ms  {fname[:45]} ({short_res}) [T{tidx}:{tname[:15]}]")


def main():
    if len(sys.argv) < 2:
        print("Usage: python find_js_hotspots.py <profile.json.gz>")
        sys.exit(1)

    analyze_profile(sys.argv[1])


if __name__ == '__main__':
    main()
