#!/usr/bin/env python3
"""
Find JS functions that are causing memory allocations.
Looks for samples where the allocator is on top of stack and traces back to find the JS caller.

Usage:
    python find_allocation_sources.py <profile.json.gz>
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
    func_resources = func_table.get('resource', [])
    frame_funcs = frame_table.get('func', [])
    stack_frames = stack_table.get('frame', [])
    stack_prefix = stack_table.get('prefix', [])
    resource_names = shared.get('resourceTable', {}).get('name', [])

    def get_string(idx):
        return stringArray[idx] if 0 <= idx < len(stringArray) else f"<{idx}>"

    # Find the allocator function indices
    alloc_funcs = set()
    print("=== Allocator Functions Found ===")
    for i, name_idx in enumerate(func_names):
        name = get_string(name_idx)
        if 'arena' in name.lower() or 'malloc' in name.lower() or 'alloc' in name.lower():
            alloc_funcs.add(i)
            if len(alloc_funcs) <= 10:
                print(f"  {i}: {name[:60]}")

    print(f"\nTotal allocator functions: {len(alloc_funcs)}")

    # For each thread, find samples where allocator is on top and trace to JS caller
    print("\n=== JS Functions Causing Allocations ===")

    for thread_idx, thread in enumerate(profile['threads']):
        name = thread.get('name', '')
        pid = thread.get('pid', '')

        samples = thread.get('samples', {})
        stacks = samples.get('stack', [])
        time_deltas = samples.get('timeDeltas', [])

        if not stacks or len(stacks) < 100:
            continue

        js_callers = defaultdict(float)

        for stack_idx, delta in zip(stacks, time_deltas):
            if delta is None:
                delta = 1

            if stack_idx is None or stack_idx < 0:
                continue

            # Check if top is allocator
            if stack_idx < len(stack_frames):
                frame_idx = stack_frames[stack_idx]
                if frame_idx < len(frame_funcs):
                    func_idx = frame_funcs[frame_idx]
                    if func_idx in alloc_funcs:
                        # Walk down to find first JS function
                        current = stack_prefix[stack_idx] if stack_idx < len(stack_prefix) else None
                        while current is not None and current >= 0:
                            if current < len(stack_frames):
                                fr_idx = stack_frames[current]
                                if fr_idx < len(frame_funcs):
                                    fn_idx = frame_funcs[fr_idx]
                                    is_js = func_table.get('isJS', [])[fn_idx] if fn_idx < len(func_table.get('isJS', [])) else False
                                    if is_js:
                                        fn_name = get_string(func_names[fn_idx])
                                        js_callers[fn_name] += delta
                                        break
                            if current < len(stack_prefix):
                                current = stack_prefix[current]
                            else:
                                break

        if js_callers:
            total_alloc_time = sum(js_callers.values())
            print(f"\nThread [{thread_idx}] {name} (pid={pid}):")
            print(f"  Total allocation time attributed to JS: {total_alloc_time:.1f}ms")
            for fn_name, t in sorted(js_callers.items(), key=lambda x: -x[1])[:25]:
                print(f"    {t:8.1f}ms  {fn_name[:60]}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python find_allocation_sources.py <profile.json.gz>")
        sys.exit(1)

    analyze_profile(sys.argv[1])


if __name__ == '__main__':
    main()
