#!/usr/bin/env python3
"""
Trace stack for a specific function to understand call context.

Usage:
    python trace_stack.py <profile.json.gz> <function_name>

Example:
    python trace_stack.py profile.json.gz addObjectDiffToProperties
"""

import json
import gzip
import sys
from pathlib import Path


def analyze_profile(profile_path: str, target_func_name: str):
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

    # Find the target function index
    target_funcs = []
    for i, name_idx in enumerate(func_names):
        name = get_string(name_idx)
        if target_func_name in name:
            res = get_resource(i)
            target_funcs.append((i, name, res))

    print(f"=== Searching for '{target_func_name}' ===")
    print(f"Found {len(target_funcs)} matching functions:")
    for idx, name, res in target_funcs[:10]:
        print(f"  [{idx}] {name} ({res})")

    if not target_funcs:
        print("No matching functions found!")
        return

    target_func_indices = {idx for idx, _, _ in target_funcs}

    # Find samples where target is on top of stack
    print(f"\n=== Stack Traces ===")
    found = 0

    for thread_idx, thread in enumerate(profile['threads']):
        thread_name = thread.get('name', '')
        samples = thread.get('samples', {})
        stacks = samples.get('stack', [])

        for i, stack_idx in enumerate(stacks):
            if stack_idx is None or stack_idx < 0:
                continue

            if stack_idx < len(stack_frames):
                frame_idx = stack_frames[stack_idx]
                if frame_idx < len(frame_funcs):
                    func_idx = frame_funcs[frame_idx]
                    if func_idx in target_func_indices:
                        found += 1
                        if found <= 3:  # Show first 3 stack traces
                            print(f"\n--- Stack #{found} (sample {i} in thread {thread_idx} '{thread_name}') ---")
                            current = stack_idx
                            depth = 0
                            seen = set()
                            while current is not None and depth < 30 and current not in seen:
                                seen.add(current)
                                if current < len(stack_frames):
                                    fr_idx = stack_frames[current]
                                    if fr_idx < len(frame_funcs):
                                        fn_idx = frame_funcs[fr_idx]
                                        name = get_string(func_names[fn_idx]) if fn_idx < len(func_names) else "?"
                                        res = get_resource(fn_idx)
                                        short_res = res.split('/')[-1][:30] if res else ""
                                        marker = ">>> " if fn_idx in target_func_indices else "    "
                                        print(f"{marker}{depth:2d}: {name[:50]} ({short_res})")
                                if current < len(stack_prefix):
                                    current = stack_prefix[current]
                                else:
                                    break
                                depth += 1

    print(f"\n=== Summary ===")
    print(f"Total samples with '{target_func_name}' on top: {found}")


def main():
    if len(sys.argv) < 3:
        print("Usage: python trace_stack.py <profile.json.gz> <function_name>")
        print("Example: python trace_stack.py profile.json.gz addObjectDiffToProperties")
        sys.exit(1)

    analyze_profile(sys.argv[1], sys.argv[2])


if __name__ == '__main__':
    main()
