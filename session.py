import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from models import Message


SESSIONS_DIR = Path.home() / ".baloons" / "sessions"


@dataclass
class Session:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created: str = field(default_factory=lambda: datetime.now().isoformat())
    model: str = ""
    messages: list[Message] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost: float = 0.0
    context_window: int = 200000

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    def add_message(self, role: str, content: str, tokens: int = 0) -> Message:
        msg = Message(role=role, content=content, tokens=tokens)
        self.messages.append(msg)
        return msg

    def update_usage(self, input_tokens: int, output_tokens: int, cost: float, context_window: int = 0):
        self.total_input_tokens = input_tokens
        self.total_output_tokens = output_tokens
        self.total_cost = cost
        if context_window:
            self.context_window = context_window

    def save(self):
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        path = SESSIONS_DIR / f"{self.id}.json"
        data = {
            "id": self.id,
            "created": self.created,
            "model": self.model,
            "messages": [asdict(m) for m in self.messages],
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost": self.total_cost,
            "context_window": self.context_window,
        }
        path.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, session_id: str) -> Optional["Session"]:
        path = SESSIONS_DIR / f"{session_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        session = cls(
            id=data["id"],
            created=data["created"],
            model=data.get("model", ""),
            total_input_tokens=data.get("total_input_tokens", 0),
            total_output_tokens=data.get("total_output_tokens", 0),
            total_cost=data.get("total_cost", 0.0),
            context_window=data.get("context_window", 200000),
        )
        for m in data.get("messages", []):
            session.messages.append(Message(
                role=m["role"],
                content=m["content"],
                tokens=m.get("tokens", 0),
                timestamp=m.get("timestamp", ""),
            ))
        return session

    @classmethod
    def list_sessions(cls) -> list[tuple[str, str, str]]:
        """Return list of (id, created, model) for all sessions."""
        if not SESSIONS_DIR.exists():
            return []
        sessions = []
        for path in SESSIONS_DIR.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                sessions.append((data["id"], data["created"], data.get("model", "")))
            except (json.JSONDecodeError, KeyError):
                continue
        return sorted(sessions, key=lambda x: x[1], reverse=True)
