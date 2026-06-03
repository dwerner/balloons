import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from session import Session
from core.runner import SessionRunner
from core.runner_factory import create_runner
from config import Config, BackendConfig


async def main() -> int:
    if len(sys.argv) < 3:
        print("usage: python scripts/debug_session_runner.py <session_id> <prompt> [seconds]", file=sys.stderr)
        return 2

    session_id = sys.argv[1]
    prompt = sys.argv[2]
    max_seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 20.0

    session = await Session.load(session_id)
    if not session:
        print(json.dumps({"error": f"session not found: {session_id}"}, indent=2))
        return 1

    config = Config.load()
    backend_name = session.backend_name or config.default_backend
    backend = config.get_backend(backend_name)

    session.set_working_directory(session.working_directory or os.getcwd())
    user_turn = session.add_message("user", prompt)
    await session.save()

    print(json.dumps({
        "session_id": session.id,
        "resolved_backend_name": backend_name,
        "resolved_backend_type": backend.type,
        "resolved_backend_model": backend.model,
        "resolved_backend_base_url": backend.base_url,
    }, default=str), flush=True)

    runner = SessionRunner(session, runner=create_runner(backend))
    runner.start_background(prompt, list(session.turns))

    started = asyncio.get_event_loop().time()
    captured = []
    final_result = None

    while True:
        event = await runner.wait_for_event(timeout=1.0)
        now = asyncio.get_event_loop().time()
        if event is not None:
            payload = event.data
            if hasattr(payload, "__dict__"):
                try:
                    payload = payload.__dict__
                except Exception:
                    payload = str(payload)
            record = {
                "t": round(now - started, 3),
                "event_type": event.event_type,
                "data": payload,
            }
            captured.append(record)
            print(json.dumps(record, default=str), flush=True)
            if event.event_type == "done":
                final_result = payload
                break
        if now - started > max_seconds:
            print(json.dumps({"timeout_after": max_seconds, "runner_status": runner.status.value}, default=str), flush=True)
            break
        if runner.is_done and event is None:
            final_result = runner.get_result()
            break

    print(json.dumps({
        "summary": {
            "captured_events": len(captured),
            "runner_status": runner.status.value,
            "result_present": final_result is not None,
            "result_error": getattr(final_result, "error", None) if final_result is not None else None,
            "result_turns": len(getattr(final_result, "turns", []) or []) if final_result is not None else 0,
        }
    }, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
