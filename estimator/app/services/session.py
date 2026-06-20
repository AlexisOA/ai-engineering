import uuid
from dataclasses import dataclass, field
from datetime import datetime

# Each turn = 1 user message + 1 assistant message.
# The window keeps the last WINDOW_SIZE turns (2 * WINDOW_SIZE messages).
WINDOW_SIZE = 10


@dataclass
class SessionState:
    session_id: str
    history: list[dict] = field(default_factory=list)
    project_metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def add_turn(self, user_content: str, assistant_content: str) -> None:
        self.history.append({"role": "user", "content": user_content})
        self.history.append({"role": "assistant", "content": assistant_content})
        max_messages = WINDOW_SIZE * 2
        if len(self.history) > max_messages:
            self.history = self.history[-max_messages:]

    def get_history(self) -> list[dict]:
        return list(self.history)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def create(self) -> SessionState:
        session_id = str(uuid.uuid4())
        state = SessionState(session_id=session_id)
        self._sessions[session_id] = state
        return state

    def get(self, session_id: str) -> SessionState | None:
        return self._sessions.get(session_id)


# In-process singleton — no DB required by the exercise.
session_store = SessionStore()
