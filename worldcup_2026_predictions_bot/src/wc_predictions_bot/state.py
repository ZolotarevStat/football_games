from __future__ import annotations

import time
from dataclasses import dataclass

from .models import PredictionDraft


@dataclass
class DraftState:
    step: str
    draft: PredictionDraft
    expires_at: float


class DraftStore:
    def __init__(self, ttl_seconds: int) -> None:
        self.ttl_seconds = ttl_seconds
        self._states: dict[str, DraftState] = {}

    def set(self, telegram_id: str, step: str, draft: PredictionDraft) -> None:
        self._states[telegram_id] = DraftState(
            step=step,
            draft=draft,
            expires_at=time.monotonic() + self.ttl_seconds,
        )

    def get(self, telegram_id: str) -> DraftState | None:
        state = self._states.get(telegram_id)
        if not state:
            return None
        if state.expires_at < time.monotonic():
            self._states.pop(telegram_id, None)
            return None
        return state

    def clear(self, telegram_id: str) -> None:
        self._states.pop(telegram_id, None)

