"""State machine for automation workflow."""

from datetime import datetime
from enum import Enum


class State(str, Enum):
    IDLE = "idle"
    GENERATING = "generating"
    QUEUED = "queued"
    POSTING = "posting"
    POSTED = "posted"
    ERROR = "error"


TRANSITIONS = {
    State.IDLE: {State.GENERATING},
    State.GENERATING: {State.QUEUED, State.ERROR, State.IDLE},
    State.QUEUED: {State.POSTING, State.ERROR, State.IDLE},
    State.POSTING: {State.POSTED, State.ERROR, State.IDLE},
    State.POSTED: {State.IDLE, State.GENERATING},
    State.ERROR: {State.IDLE, State.GENERATING},
}


class StateMachine:
    def __init__(self):
        from .db import state_get, state_set
        current = state_get()
        self._state = State(current.get("state", "idle"))
        self._running = bool(current.get("running", False))
        self._error_count = int(current.get("error_count", 0))
        self._last_error = current.get("last_error")

    @property
    def state(self) -> State:
        return self._state

    @property
    def running(self) -> bool:
        return self._running

    @property
    def error_count(self) -> int:
        return self._error_count

    def can_transition(self, target: State) -> bool:
        return target in TRANSITIONS.get(self._state, set())

    def transition(self, target: State, reason: str | None = None):
        if not self.can_transition(target):
            raise ValueError(f"Invalid transition: {self._state.value} → {target.value}")
        self._state = target
        self._persist()

    def set_running(self, running: bool):
        self._running = running
        self._persist()

    def record_error(self, error_msg: str):
        self._error_count += 1
        self._last_error = error_msg[:500]
        self._state = State.ERROR
        self._persist()

    def reset(self):
        self._state = State.IDLE
        self._error_count = 0
        self._last_error = None
        self._running = False
        self._persist()

    def _persist(self):
        from .db import state_set
        state_set(
            state=self._state.value,
            running=self._running,
            error_count=self._error_count,
            last_error=self._last_error,
        )
