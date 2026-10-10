"""Arrangement time edits through the Edit menu, each checked by where the song ends.

The LOM cannot insert or remove time, so these select a range and click Edit > Delete, Duplicate,
Copy or Paste Time. `select` sets the loop brace in one LOM call (a call costs ~0.85 s whatever it
does), then Edit > Select Loop turns the brace into a time selection. Each edit is checked by
song.last_event_time: Delete Time moves the end back by the length, Duplicate and Paste forward,
Copy not at all. An automation breakpoint just past the edited range can shift the end by up to a
beat, so callers that know the absolute end, or that clips must double, can check that instead
(docs/probe-packing-findings.md, "Duplicate Time quirks").

Positions are beats on the current (edited) timeline. Each edit takes 7-8 s in Live.
"""

from __future__ import annotations

import time

from hands import steps
from hands.live import ui
from hands.live.session import stop
from hands.live.transport import McpTransport

_SELECT = """song.stop_playing()
view = Live.Application.get_application().view
view.show_view("Arranger")
view.focus_view("Arranger")
song.loop_start = {start!r}
song.loop_length = {length!r}"""


def song_end(client: McpTransport) -> float:
    return client.run("result = song.last_event_time")


def clips_after(client: McpTransport, beat: float) -> int:
    """Arrangement clips that end after `beat` (group tracks hold none)."""
    return client.run(f"result = sum(len([c for c in t.arrangement_clips if c.end_time > {float(beat)!r}]) "
                      "for t in song.tracks if not t.is_foldable)")


def select(client: McpTransport, start: float, length: float) -> None:
    """Make [start, start + length) the arrangement's time selection."""
    client.run(_SELECT.format(start=float(start), length=float(length)))
    if not ui.menu("Edit", "Select Loop", tries=10):
        stop(f"Edit > Select Loop stayed disabled for {start:g}+{length:g}")
    time.sleep(0.3)


def check_end(item: str, where: str, before: float, after: float, *, delta: float | None = None,
              end: float | None = None, tol: float = 1e-6) -> float:
    """Stop unless the song end moved by `delta` (or now sits at `end`); return the move."""
    moved = after - before
    if delta is not None and abs(moved - delta) > tol:
        stop(f"{item} at {where}: the song end moved {moved:+g} beats, expected {delta:+g}")
    if end is not None and abs(after - end) > tol:
        stop(f"{item} at {where}: the song ends at {after:g}, expected {end:g}")
    return moved


def _edit(client: McpTransport, item: str, start: float, length: float, *, delta: float | None,
          end: float | None = None, tol: float = 1e-6, tries: int = 4) -> float:
    where = f"{start:g}+{length:g}"
    before = song_end(client)
    for _ in range(tries):
        select(client, start, length)
        if ui.menu("Edit", item, tries=3):
            time.sleep(1.0)  # Live finishes the edit after the click returns
            moved = check_end(item, where, before, song_end(client), delta=delta, end=end, tol=tol)
            steps.report(f"Edit > {item} {where}", "minor")
            return moved
    stop(f"Edit > {item} stayed disabled at {where}")


def delete(client: McpTransport, start: float, length: float, *, tol: float = 1e-6) -> float:
    """Remove [start, start + length); later material moves earlier."""
    return _edit(client, "Delete Time", start, length, delta=-length, tol=tol)


def duplicate(client: McpTransport, start: float, length: float, *, end: float | None = None,
              clips_from: float | None = None, tol: float = 1e-6) -> float:
    """Insert a copy of [start, start + length) right after it.

    By default the song end must move by `length`. With `end`, check the absolute end instead;
    with `clips_from`, also check that the clips ending after that beat doubled.
    """
    clips = clips_after(client, clips_from) if clips_from is not None else None
    moved = _edit(client, "Duplicate Time", start, length, delta=None if end is not None else length,
                  end=end, tol=tol)
    if clips is not None and (now := clips_after(client, clips_from)) != 2 * clips:
        stop(f"Duplicate Time at {start:g}+{length:g}: {now} clips after {clips_from:g}, expected {2 * clips}")
    return moved


def copy(client: McpTransport, start: float, length: float) -> float:
    """Copy [start, start + length) for a later paste; the arrangement does not change."""
    return _edit(client, "Copy Time", start, length, delta=0.0)


def paste(client: McpTransport, at: float, length: float) -> float:
    """Insert the copied time at `at`; `length` must be the copied length."""
    return _edit(client, "Paste Time", at, length, delta=length)
