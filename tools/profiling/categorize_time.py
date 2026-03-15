#!/usr/bin/env python3
"""
Categorize CPU time by source (Balloons app, React internals, DevTools, etc.)

Usage:
    python categorize_time.py <profile.json.gz>
"""

import json
import gzip
import sys
from collections import defaultdict
from pathlib import Path


# Known DevTools-injected functions (they run in app context but are from DevTools)
DEVTOOLS_FUNCS = {
    'addObjectDiffToProperties',
    'addValueToProperties',
    'updateProperties',
    'logComponentRender',
    'crawlToInitializeContextsMap',
    'recordMount',
    'recordUnmount',
    'recordProfilingDurations',
    'logCommitDetails',
}

# React internal function patterns
REACT_INTERNAL_PATTERNS = [
    'commit', 'reconcile', 'begin', 'complete', 'Fiber', 'Work',
    'perform', 'dispatch', 'update', 'schedule', 'process', 'flush',
]


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

    def get_resource(func_idx):
        if 0 <= func_idx < len(func_resources):
            res_idx = func_resources[func_idx]
            if 0 <= res_idx < len(resource_names):
                return get_string(resource_names[res_idx])
        return ""

    def is_react_internal(name):
        return any(name.startswith(p) or p in name for p in REACT_INTERNAL_PATTERNS)

    print("=== Profile Time Categorization ===\n")

    for thread_idx, thread in enumerate(profile['threads']):
        thread_name = thread.get('name', '')
        pid = thread.get('pid', '')

        samples = thread.get('samples', {})
        stacks = samples.get('stack', [])
        time_deltas = samples.get('timeDeltas', [])

        if not stacks or len(stacks) < 100:
            continue

        # Calculate time
        categories = defaultdict(float)
        balloons_funcs = defaultdict(float)

        for stack_idx, delta in zip(stacks, time_deltas):
            if delta is None:
                delta = 1

            if stack_idx is not None and 0 <= stack_idx < len(stack_frames):
                frame_idx = stack_frames[stack_idx]
                if 0 <= frame_idx < len(frame_funcs):
                    func_idx = frame_funcs[frame_idx]
                    name = get_string(func_names[func_idx]) if func_idx < len(func_names) else ""
                    res = get_resource(func_idx)

                    if name in DEVTOOLS_FUNCS:
                        categories['React DevTools (injected)'] += delta
                    elif ':3030' in res or 'localhost' in res:
                        if is_react_internal(name):
                            categories['React Internals'] += delta
                        else:
                            categories['Balloons App'] += delta
                            balloons_funcs[name] += delta
                    elif 'self-hosted' in res:
                        categories['JS Builtins'] += delta
                    elif 'devtools' in res.lower():
                        categories['Firefox DevTools'] += delta
                    elif res:
                        categories['Other Native/Browser'] += delta
                    else:
                        categories['Unknown'] += delta

        total = sum(categories.values())
        if total < 100:  # Skip threads with minimal activity
            continue

        print(f"\n{'='*60}")
        print(f"Thread [{thread_idx}] {thread_name} (pid={pid})")
        print(f"{'='*60}")
        print(f"\nTime by Category (Self Time):")
        for cat, t in sorted(categories.items(), key=lambda x: -x[1]):
            pct = 100 * t / total if total else 0
            bar = '*' * int(pct / 2)
            print(f"  {t:10.1f}ms ({pct:5.1f}%)  {cat[:35]:35} {bar}")

        print(f"\n  Total: {total:.1f}ms")

        # Show Balloons app functions if significant
        if categories['Balloons App'] > 10:
            print(f"\nTop Balloons App Functions:")
            for name, t in sorted(balloons_funcs.items(), key=lambda x: -x[1])[:15]:
                print(f"    {t:8.1f}ms  {name[:55]}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python categorize_time.py <profile.json.gz>")
        sys.exit(1)

    analyze_profile(sys.argv[1])


if __name__ == '__main__':
    main()
