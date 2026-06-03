import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Config
from core.runner_factory import create_runner
from models import Message


async def main() -> int:
    backend_name = sys.argv[1] if len(sys.argv) > 1 else 'freeserver'
    prompt = sys.argv[2] if len(sys.argv) > 2 else 'please say hi'

    cfg = Config.load()
    backend = cfg.get_backend(backend_name)
    runner = create_runner(backend)

    print(json.dumps({
        'backend_name': backend.name,
        'backend_type': backend.type,
        'base_url': backend.base_url,
        'model': backend.model,
        'runner_cls': runner.__class__.__name__,
    }, default=str), flush=True)

    messages = [Message(role='user', content=prompt)]

    seen = 0
    try:
        async for event in runner.stream_response(messages, prompt, allowed_tools=[]):
            payload = event
            if hasattr(event, '__dict__'):
                payload = event.__dict__
            print(json.dumps({'event_cls': event.__class__.__name__, 'payload': payload}, default=str), flush=True)
            seen += 1
            if seen >= 50:
                break
    except Exception as e:
        print(json.dumps({'error': type(e).__name__, 'message': str(e)}, default=str), flush=True)
        return 1

    print(json.dumps({'done': True, 'seen': seen}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
