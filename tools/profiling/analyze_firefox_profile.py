#!/usr/bin/env python3
"""
Analyze Firefox performance profiles for Balloons web UI.

Usage:
    python analyze_firefox_profile.py <profile.json.gz>

Or import and use programmatically:
    from analyze_firefox_profile import FirefoxProfile
    profile = FirefoxProfile.load('profile.json.gz')
    profile.print_summary()
"""

import json
import gzip
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class FunctionTime:
    name: str
    self_time_ms: float
    total_time_ms: float
    resource: str = ""
    is_js: bool = False


class FirefoxProfile:
    def __init__(self, data: dict):
        self.data = data
        self.shared = data.get('shared', {})
        self.strings = self.shared.get('stringArray', [])
        self.threads = data.get('threads', [])
        self.counters = data.get('counters', [])
        self.meta = data.get('meta', {})

        # Parse tables
        self.func_table = self.shared.get('funcTable', {})
        self.frame_table = self.shared.get('frameTable', {})
        self.stack_table = self.shared.get('stackTable', {})
        self.resource_table = self.shared.get('resourceTable', {})

    @classmethod
    def load(cls, path: str) -> 'FirefoxProfile':
        """Load a Firefox profile from a .json or .json.gz file."""
        path = Path(path)
        if path.suffix == '.gz':
            with gzip.open(path, 'rt') as f:
                data = json.load(f)
        else:
            with open(path) as f:
                data = json.load(f)
        return cls(data)

    def get_string(self, idx: int) -> str:
        """Get a string from the shared string table."""
        if 0 <= idx < len(self.strings):
            return self.strings[idx]
        return f"<idx:{idx}>"

    def get_func_name(self, func_idx: int) -> str:
        """Get function name by index."""
        names = self.func_table.get('name', [])
        if 0 <= func_idx < len(names):
            return self.get_string(names[func_idx])
        return f"<func:{func_idx}>"

    def get_func_resource(self, func_idx: int) -> str:
        """Get function's source file/resource."""
        resources = self.func_table.get('resource', [])
        res_names = self.resource_table.get('name', [])
        if 0 <= func_idx < len(resources):
            res_idx = resources[func_idx]
            if 0 <= res_idx < len(res_names):
                return self.get_string(res_names[res_idx])
        return ""

    def is_js_func(self, func_idx: int) -> bool:
        """Check if function is JavaScript."""
        is_js = self.func_table.get('isJS', [])
        if 0 <= func_idx < len(is_js):
            return is_js[func_idx]
        return False

    def calculate_function_times(self, thread_idx: int = 0) -> dict[int, FunctionTime]:
        """Calculate self and total time for each function in a thread."""
        thread = self.threads[thread_idx]
        samples = thread.get('samples', {})
        stacks = samples.get('stack', [])
        time_deltas = samples.get('timeDeltas', [])

        stack_frames = self.stack_table.get('frame', [])
        stack_prefix = self.stack_table.get('prefix', [])
        frame_funcs = self.frame_table.get('func', [])

        func_self_time = defaultdict(float)
        func_total_time = defaultdict(float)

        for stack_idx, delta in zip(stacks, time_deltas):
            if delta is None:
                delta = 1  # Default 1ms interval

            # Self time = top of stack only
            if stack_idx is not None and 0 <= stack_idx < len(stack_frames):
                frame_idx = stack_frames[stack_idx]
                if 0 <= frame_idx < len(frame_funcs):
                    func_idx = frame_funcs[frame_idx]
                    func_self_time[func_idx] += delta

            # Total time = walk entire stack
            current = stack_idx
            seen = set()
            while current is not None and current >= 0 and current not in seen:
                seen.add(current)
                if current < len(stack_frames):
                    frame_idx = stack_frames[current]
                    if frame_idx < len(frame_funcs):
                        func_idx = frame_funcs[frame_idx]
                        func_total_time[func_idx] += delta
                if current < len(stack_prefix):
                    current = stack_prefix[current]
                else:
                    break

        result = {}
        for func_idx in set(func_self_time) | set(func_total_time):
            result[func_idx] = FunctionTime(
                name=self.get_func_name(func_idx),
                self_time_ms=func_self_time[func_idx],
                total_time_ms=func_total_time[func_idx],
                resource=self.get_func_resource(func_idx),
                is_js=self.is_js_func(func_idx),
            )
        return result

    def find_balloons_functions(self) -> list[tuple[int, str, str]]:
        """Find functions from Balloons (localhost:3030 or known component names)."""
        funcs = []
        func_names = self.func_table.get('name', [])
        func_resources = self.func_table.get('resource', [])
        res_names = self.resource_table.get('name', [])

        balloons_patterns = [
            'Session', 'session', 'Sidebar', 'AppContent', 'Hierarchy',
            'handleSelect', 'Turn', 'Conversation', 'zustand', 'Message',
            'useSession', 'useTurn', 'useConversation'
        ]

        for i, name_idx in enumerate(func_names):
            name = self.get_string(name_idx)
            res_idx = func_resources[i] if i < len(func_resources) else -1
            res = ""
            if 0 <= res_idx < len(res_names):
                res = self.get_string(res_names[res_idx])

            # Match by resource (localhost:3030) or function name patterns
            if ':3030' in res or 'localhost' in res.lower():
                funcs.append((i, name, res))
            elif any(p in name for p in balloons_patterns):
                funcs.append((i, name, res))

        return funcs

    def get_gc_events(self, thread_idx: int = 0) -> list[dict]:
        """Extract GC events from markers."""
        thread = self.threads[thread_idx]
        markers = thread.get('markers', {})
        marker_names = markers.get('name', [])
        start_times = markers.get('startTime', [])
        end_times = markers.get('endTime', [])
        data_list = markers.get('data', [])

        events = []
        for i, (name_idx, start, end) in enumerate(zip(marker_names, start_times, end_times)):
            name = self.get_string(name_idx) if name_idx < len(self.strings) else ""
            if 'GC' in name:
                duration = (end - start) if (start and end) else 0
                data = data_list[i] if i < len(data_list) else {}
                events.append({
                    'name': name,
                    'start_ms': start,
                    'duration_ms': duration,
                    'data': data if isinstance(data, dict) else {},
                })

        return sorted(events, key=lambda x: -x['duration_ms'])

    def get_memory_counters(self) -> list[dict]:
        """Get memory allocation counters."""
        result = []
        for c in self.counters:
            name = c.get('name', '')
            if 'malloc' in name.lower() or 'memory' in name.lower() or 'heap' in name.lower():
                samples = c.get('samples', {})
                counts = samples.get('count', [])
                times = samples.get('time', [])
                if counts:
                    result.append({
                        'name': name,
                        'pid': c.get('pid', ''),
                        'description': c.get('description', ''),
                        'sample_count': len(counts),
                        'min_bytes': min(counts),
                        'max_bytes': max(counts),
                        'times': times,
                        'counts': counts,
                    })
        return result

    def print_summary(self):
        """Print a summary of the profile."""
        print("=" * 60)
        print("FIREFOX PROFILE SUMMARY")
        print("=" * 60)

        # Meta
        print(f"\nProduct: {self.meta.get('product', 'unknown')}")
        print(f"Sample interval: {self.meta.get('interval', '?')}ms")

        # Threads
        print(f"\nThreads: {len(self.threads)}")
        for i, t in enumerate(self.threads[:5]):
            name = t.get('name', 'unnamed')
            samples = t.get('samples', {})
            sample_count = len(samples.get('stack', []))
            markers = t.get('markers', {})
            marker_count = len(markers.get('name', []))
            print(f"  [{i}] {name}: {sample_count} samples, {marker_count} markers")
        if len(self.threads) > 5:
            print(f"  ... and {len(self.threads) - 5} more threads")

        # Calculate main thread function times
        print("\n" + "-" * 60)
        print("MAIN THREAD FUNCTION TIME")
        print("-" * 60)

        func_times = self.calculate_function_times(0)

        # Top by self time
        print("\nTop 15 by Self Time:")
        sorted_self = sorted(func_times.values(), key=lambda x: -x.self_time_ms)[:15]
        for ft in sorted_self:
            js_marker = "[JS]" if ft.is_js else ""
            print(f"  {ft.self_time_ms:8.1f}ms  {ft.name[:50]} {js_marker}")

        # Top by total time
        print("\nTop 15 by Total Time:")
        sorted_total = sorted(func_times.values(), key=lambda x: -x.total_time_ms)[:15]
        for ft in sorted_total:
            js_marker = "[JS]" if ft.is_js else ""
            print(f"  {ft.total_time_ms:8.1f}ms  {ft.name[:50]} {js_marker}")

        # Balloons functions
        print("\n" + "-" * 60)
        print("BALLOONS FUNCTIONS")
        print("-" * 60)

        balloons = self.find_balloons_functions()
        print(f"\nFound {len(balloons)} Balloons-related functions")

        balloons_times = []
        for idx, name, res in balloons:
            if idx in func_times:
                ft = func_times[idx]
                if ft.total_time_ms > 0:
                    balloons_times.append(ft)

        if balloons_times:
            print("\nBalloons functions with execution time:")
            for ft in sorted(balloons_times, key=lambda x: -x.total_time_ms)[:20]:
                short_res = ft.resource.split('/')[-1][:25] if ft.resource else ""
                print(f"  {ft.self_time_ms:6.1f}ms / {ft.total_time_ms:6.1f}ms  {ft.name[:40]} ({short_res})")
        else:
            print("  No Balloons functions with significant execution time found")
            print("  (This may indicate the profile was captured during idle time)")

        # GC events
        print("\n" + "-" * 60)
        print("GC EVENTS")
        print("-" * 60)

        gc_events = self.get_gc_events()
        print(f"\nTotal GC events: {len(gc_events)}")
        print("\nLongest GC pauses:")
        for ev in gc_events[:10]:
            print(f"  {ev['duration_ms']:7.1f}ms @ {ev['start_ms']/1000:7.1f}s - {ev['name']}")

        # Memory
        print("\n" + "-" * 60)
        print("MEMORY COUNTERS")
        print("-" * 60)

        mem = self.get_memory_counters()
        for m in mem:
            if m['sample_count'] > 100:
                min_mb = m['min_bytes'] / (1024*1024)
                max_mb = m['max_bytes'] / (1024*1024)
                print(f"\n{m['name']} (pid={m['pid']}):")
                print(f"  Samples: {m['sample_count']}")
                print(f"  Range: {min_mb:.1f}MB - {max_mb:.1f}MB")

        print("\n" + "=" * 60)


def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_firefox_profile.py <profile.json.gz>")
        sys.exit(1)

    profile_path = sys.argv[1]
    print(f"Loading profile: {profile_path}")
    profile = FirefoxProfile.load(profile_path)
    profile.print_summary()


if __name__ == '__main__':
    main()
