"""Timing marks for one turn (plan V1: measure every stage before tuning any), and the report over them.

A turn starts when the mic is offered. Marks taken on the Mac are milliseconds since then; marks taken on the phone
(mic open, first sound played) are durations the phone measured itself, so the two clocks never need syncing.

`harness timings` groups the turns by what V1 compares: the first turn after a start against later ones, Safari
against Chrome, and the phone's own mic and speaker against a Bluetooth route (from the mic's device label).
"""

from __future__ import annotations

import re
import statistics
import time
from typing import Any

from .store import Store

# Mac marks are ms since the mic was offered; these are the stages a turn passes, in order.
MAC_STAGES = ["first_words", "stop_word", "turn_ended", "first_narration", "first_text", "agent_done", "first_audio",
              "music_ready", "responded"]
# Phone marks are durations the phone measured.
PHONE_STAGES = ["mic_open", "route_settle", "first_speech_audio", "music_first_play"]


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


def browser(ua: str) -> str:
    """Safari, Chrome, Firefox or other, from a user agent. Chrome on iOS is WebKit underneath, so it counts as
    Safari: the audio session and the mic behave as Safari's do."""
    if re.search(r"iPhone|iPad|iPod", ua):
        return "safari"
    if "Firefox/" in ua:
        return "firefox"
    if re.search(r"Chrome/|Chromium/|Edg/", ua):
        return "chrome"
    if "Safari/" in ua:
        return "safari"
    return "other"


def route(input_label: str) -> str:
    """'phone' for the device's own mic, 'bluetooth' for a headset or a car, '' when the page did not say."""
    label = input_label.lower()
    if not label:
        return ""
    if re.search(r"iphone|ipad|built-in|macbook|default|internal|fake", label):
        return "phone"
    return "bluetooth"


def _groups(turn: dict[str, Any]) -> dict[str, str]:
    marks = {m["name"]: m for m in turn["marks"]}
    listen = marks.get("listen", {})
    n = listen.get("n")
    return {
        "turn": "" if n is None else ("first" if n == 1 else "later"),
        "browser": listen.get("browser", ""),
        "route": route(str(marks.get("mic_open", {}).get("input", ""))),
    }


def report(turns: list[dict[str, Any]]) -> str:
    """A markdown table per comparison: the median ms (and count) of each stage, per group."""
    rows = [(t, _groups(t)) for t in turns]
    out = [f"{len(turns)} turns\n"]
    for key, title in (("turn", "first turn after a start vs later"), ("browser", "Safari vs Chrome"),
                       ("route", "phone mic and speaker vs Bluetooth")):
        values = sorted({g[key] for _, g in rows if g[key]})
        if not values:
            continue
        out.append(f"### {title}\n")
        out.append("| stage | " + " | ".join(values) + " |")
        out.append("|---|" + "---|" * len(values))
        for stage in MAC_STAGES + PHONE_STAGES:
            cells, any_value = [], False
            for v in values:
                ms = [m["ms"] for t, g in rows if g[key] == v for m in t["marks"]
                      if m["name"] == stage and isinstance(m.get("ms"), (int, float))]
                cells.append(f"{statistics.median(ms):.0f} ({len(ms)})" if ms else "-")
                any_value |= bool(ms)
            if any_value:
                where = "phone" if stage in PHONE_STAGES else "mac"
                out.append(f"| {stage} ({where}) | " + " | ".join(cells) + " |")
        out.append("")
    return "\n".join(out)
