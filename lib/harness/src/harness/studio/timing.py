"""Timing marks for one turn (plan V1: measure every stage before tuning any).

A turn starts when the mic is offered. Marks taken on the Mac are milliseconds since then; marks taken on the phone
(mic open, first sound played) are durations the phone measured itself, so the two clocks never need syncing.
"""

from __future__ import annotations

import time
from typing import Any

from .store import Store


class TurnClock:
    def __init__(self, store: Store, conversation: str, turn: str):
        self.store, self.conversation, self.turn = store, conversation, turn
        self.t0 = time.monotonic()
        self._once: set[str] = set()

    def elapsed_ms(self) -> float:
        return (time.monotonic() - self.t0) * 1000

    def mark(self, name: str, once: bool = False, **extra: Any) -> float:
        """Record `name` at the time since the turn started; with once=True only its first occurrence."""
        ms = self.elapsed_ms()
        if once:
            if name in self._once:
                return ms
            self._once.add(name)
        self.store.mark(self.conversation, self.turn, name, round(ms, 1), "mac", extra or None)
        return ms

    def phone(self, name: str, ms: float | None, **extra: Any) -> None:
        self.store.mark(self.conversation, self.turn, name, None if ms is None else round(float(ms), 1), "phone",
                        extra or None)
