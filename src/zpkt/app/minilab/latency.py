"""Knob-to-Live timings: the numbers the rig gate reads before the pager retires.

CHANGE-app-gateway.md: "Gate before the pager is retired: knob-to-Live latency measured on the rig, and Anthony
turning knobs." A `LatencyProbe` watches an adapter and keeps, for each batch a knob sent, three durations:

    queue   the knob moved -> the batch went to the bus (coalescing and the wait for the last batch)
    bus     the bus call: checks, the lock, Live's answer
    echo    the batch went out -> Live reported the value back (the pager's, or the Remote Script's push)

`summary` turns the samples into counts and percentiles; `zpkt app midi latency` prints it. The probe never talks to
anything: it is told times. It is run on the rig by a person, never by a test against hardware.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Sample:
    slot: str
    queue_s: float
    bus_s: float
    echo_s: float | None  # None: Live never reported it back (a value it already had)
    status: int


def percentile(values: list[float], p: float) -> float:
    """The p-th percentile (0..100) of a non-empty list, by nearest rank."""
    if not values:
        raise ValueError("there are no samples")
    ordered = sorted(values)
    rank = max(1, round(p / 100.0 * len(ordered)))
    return ordered[min(len(ordered), rank) - 1]


def stage_summary(values: list[float]) -> dict[str, float]:
    """count, median, p95 and max of one stage, in milliseconds; empty for no values."""
    if not values:
        return {}
    ms = [v * 1000.0 for v in values]
    return {
        "count": float(len(ms)),
        "median_ms": round(percentile(ms, 50), 2),
        "p95_ms": round(percentile(ms, 95), 2),
        "max_ms": round(max(ms), 2),
    }


def summary(samples: list[Sample]) -> dict[str, dict[str, float]]:
    """Each stage's summary: queue, bus, echo (only batches Live reported back) and the total (queue + bus + echo)."""
    echoed = [s for s in samples if s.echo_s is not None]
    return {
        "queue": stage_summary([s.queue_s for s in samples]),
        "bus": stage_summary([s.bus_s for s in samples]),
        "echo": stage_summary([s.echo_s for s in echoed if s.echo_s is not None]),
        "total": stage_summary([s.queue_s + s.bus_s + (s.echo_s or 0.0) for s in echoed]),
    }


def format_summary(result: dict[str, dict[str, float]]) -> str:
    """The summary as lines a person reads: one per stage."""
    lines = []
    for stage in ("queue", "bus", "echo", "total"):
        s = result.get(stage) or {}
        if not s:
            lines.append(f"{stage:>6}: no samples")
            continue
        lines.append(
            f"{stage:>6}: {int(s['count'])} samples, median {s['median_ms']} ms, "
            f"p95 {s['p95_ms']} ms, max {s['max_ms']} ms"
        )
    return "\n".join(lines)


@dataclass
class LatencyProbe:
    """Collects the timings. The adapter calls `batch` when it sends one and `echo` when Live reports a control."""

    samples: list[Sample] = field(default_factory=list)
    _waiting: dict[str, tuple[float, float, float, int]] = field(default_factory=dict)  # slot -> times of its batch
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def batch(self, slots: list[str], moved_at: float, sent_at: float, replied_at: float, status: int) -> None:
        """A batch for `slots` went out: the oldest move in it was at `moved_at`."""
        with self._lock:
            for slot in slots:
                self._finish(slot, None)  # an older batch for this slot was never echoed
                self._waiting[slot] = (moved_at, sent_at, replied_at, status)

    def echo(self, slot: str, at: float) -> None:
        """Live reported `slot`'s value back."""
        with self._lock:
            self._finish(slot, at)

    def close(self) -> None:
        """Count every batch still waiting as not echoed."""
        with self._lock:
            for slot in list(self._waiting):
                self._finish(slot, None)

    def _finish(self, slot: str, echoed_at: float | None) -> None:
        wait = self._waiting.pop(slot, None)
        if wait is None:
            return
        moved, sent, replied, status = wait
        self.samples.append(
            Sample(
                slot, sent - moved, replied - sent, None if echoed_at is None else max(0.0, echoed_at - replied), status
            )
        )

    def report(self) -> dict[str, dict[str, float]]:
        with self._lock:
            return summary(list(self.samples))
