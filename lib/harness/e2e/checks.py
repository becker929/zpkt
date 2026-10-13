"""The rules every run is held to, whatever Claude chose to do: checked from the recording, the socket and the chat.

Times are on the page's clock (performance.now, ms in the wire log and the mic spans, s for the ear via Ear.perf).
"""

from __future__ import annotations

import re
import sqlite3
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

COUNT_IN = re.compile(r"\bthree\b[\s,.:;-]*\btwo\b[\s,.:;-]*\bone\b", re.I)
EARCON_S = 0.4          # the ready cue may sound this long after the mic opens
OVERLAP_SLACK_S = 0.05  # render quanta and clock mapping


@dataclass
class Result:
    name: str
    ok: bool
    detail: str
    evidence: list[str] = field(default_factory=list)


@dataclass
class Run:
    """Everything a run gathered."""
    page: dict[str, Any]                 # Phone.collect()
    engine: list[dict[str, Any]]         # every item the page played or dropped
    ears: list[Any]                      # heard.Ear per audio context
    events: list[Any]                    # phone.Event: what the user did and saw
    errors: list[str]
    db: Path                             # the run's studio.sqlite3

    def messages(self) -> dict[int, dict[str, Any]]:
        import json
        with sqlite3.connect(self.db) as c:
            rows = c.execute("select seq, kind, turn, created, data from messages order by seq").fetchall()
        return {s: {"seq": s, "kind": k, "turn": t, "created": cr, "data": json.loads(d)} for s, k, t, cr, d in rows}

    def timings(self) -> list[dict[str, Any]]:
        import json
        with sqlite3.connect(self.db) as c:
            rows = c.execute("select turn, name, ms, source, at, extra from timings order by at").fetchall()
        return [{"turn": t, "name": n, "ms": ms, "source": s, "at": at, "extra": json.loads(x) if x else {}}
                for t, n, ms, s, at, x in rows]

    def wire_in(self, type_: str) -> list[dict[str, Any]]:
        return [e for e in self.page["wire"] if e["dir"] == "in" and e["msg"].get("type") == type_]


def all_checks(run: Run) -> list[Result]:
    return [go_ahead_is_honest(run), nothing_heard_while_the_mic_is_open(run), one_sound_at_a_time(run),
            music_is_introduced(run),
            no_narration_after_music(run), every_line_heard_from_its_first_word(run), every_turn_got_audio(run),
            no_errors(run)]


def mic_spans(run: Run) -> list[tuple[float, float]]:
    """When the page's mic was open (s), from its own `mic` messages to the Mac; one still open ends at the run's end."""
    spans, opened = [], None
    for e in run.page["wire"]:
        m = e["msg"]
        if e["dir"] != "out" or m.get("type") != "mic":
            continue
        if m.get("state") == "open" and opened is None:
            opened = e["t"] / 1000
        elif m.get("state") == "closed" and opened is not None:
            spans.append((opened, e["t"] / 1000))
            opened = None
    if opened is not None:
        spans.append((opened, run.page["now"] / 1000))
    return spans


def go_ahead_is_honest(run: Run) -> Result:
    """The page says "Go ahead" only while the mic's frames reach the Mac."""
    lies = [e for e in run.events if e.what == "Go ahead with no mic frames"]
    waits = [e.data.get("since_listen_ms") for e in run.events if e.what == "listening"
             and e.data.get("since_listen_ms") is not None]
    stat = (f"; it said so {statistics.median(waits) / 1000:.1f} s (median), {max(waits) / 1000:.1f} s (max) "
            "after the Mac gave the turn") if waits else ""
    return Result("'Go ahead' only while the mic is heard", not lies,
                  f"{len(waits)} times, {len(lies)} with no mic frames{stat}",
                  [f"at {e.t / 1000:.1f} s: {e.data}" for e in lies])


def nothing_heard_while_the_mic_is_open(run: Run) -> Result:
    spans = [(a + EARCON_S, b) for a, b in mic_spans(run)]
    sound = [(ear.perf(a), ear.perf(b)) for ear in run.ears for a, b in ear.loud(hold=0.02)]
    both = [(max(a1, b1), min(a2, b2)) for a1, a2 in sound for b1, b2 in spans if max(a1, b1) < min(a2, b2)]
    total = sum(b - a for a, b in both)
    worst = sorted(both, key=lambda x: x[0] - x[1])[:5]
    return Result("Nothing plays while the mic is open", total <= OVERLAP_SLACK_S,
                  f"{total * 1000:.0f} ms of sound with the mic open (after the first {EARCON_S * 1000:.0f} ms)",
                  [f"{a:.2f}-{b:.2f} s" for a, b in worst])


def one_sound_at_a_time(run: Run) -> Result:
    items = [e for e in run.engine if e.get("t0") is not None and e.get("endedAt") is not None]
    bad = []
    for a, b in zip(items, items[1:]):
        if b["t0"] < a["t0"]:                  # a new audio context (after an app switch): a new clock
            continue
        end_a = min(a["endedAt"], a["stopAt"] or a["endedAt"])
        if end_a - b["t0"] > OVERLAP_SLACK_S:
            bad.append(f"{a['kind']} #{a['seq']} still playing {(end_a - b['t0']) * 1000:.0f} ms into "
                       f"{b['kind']} #{b['seq']}")
    return Result("One sound at a time", not bad, f"{len(items)} items played, {len(bad)} overlapping", bad)


def music_is_introduced(run: Run) -> Result:
    """Every render the Mac plays is preceded by speech that names it and counts in."""
    msgs = run.messages()
    wire = run.page["wire"]
    bad, seen = [], []
    for i, e in enumerate(wire):
        m = e["msg"]
        if e["dir"] != "in" or m.get("type") != "play":
            continue
        music = msgs.get(m["seq"], {})
        before = [w for w in wire[:i] if w["dir"] == "in" and w["msg"].get("type") == "speech"
                  and w["msg"].get("state") == "begin"]
        intro = msgs.get(before[-1]["msg"]["seq"], {}).get("data", {}).get("text", "") if before else ""
        gap = (e["t"] - before[-1]["t"]) / 1000 if before else None
        title = music.get("data", {}).get("title", "?")
        line = f"#{m['seq']} {title!r}: last speech before it {intro[-90:]!r}"
        seen.append(line)
        if not COUNT_IN.search(intro or ""):
            bad.append(line + " (no count-in)")
        elif gap is not None and gap > 60:
            bad.append(line + f" (it began {gap:.0f} s earlier)")
    return Result("Music is introduced with a count-in", not bad,
                  f"{len(seen)} plays from the Mac, {len(bad)} without an intro and count-in" if seen else
                  "the Mac played no music", bad or seen)


def no_narration_after_music(run: Run) -> Result:
    msgs = run.messages()
    bad = []
    by_turn: dict[str, list[dict[str, Any]]] = {}
    for m in msgs.values():
        by_turn.setdefault(m["turn"] or "", []).append(m)
    for turn, ms in by_turn.items():
        music = [m for m in ms if m["kind"] == "music"]
        if not music:
            continue
        first = music[0]["seq"]
        late = [m for m in ms if m["kind"] == "agent" and m["data"].get("role") == "narration" and m["seq"] > first]
        bad += [f"turn {turn}: narration #{m['seq']} {m['data'].get('text', '')[:80]!r} after music #{first}"
                for m in late]
    return Result("No narration once music is ready", not bad, f"{len(bad)} narrations after a render", bad)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def every_line_heard_from_its_first_word(run: Run) -> Result:
    """The user starts talking the moment the page says it is listening; the Mac must hear the start of the line."""
    said = [e for e in run.events if e.what == "said"]
    heard = [e for e in run.events if e.what == "heard"]
    bad, lines = [], []
    for i, s in enumerate(said):
        h = heard[i].data["text"] if i < len(heard) else None
        lines.append(f"said {s.data['text']!r} -> heard {h!r}")
        if h is None or _words(h)[:1] != _words(s.data["text"])[:1]:
            bad.append(lines[-1])
    waits = [e.data.get("since_listen_ms") for e in run.events if e.what == "listening" and
             e.data.get("since_listen_ms") is not None]
    stat = (f"; the page said 'listening' {statistics.median(waits) / 1000:.1f} s (median), "
            f"{max(waits) / 1000:.1f} s (max) after the Mac gave the turn") if waits else ""
    return Result("Every line is heard from its first word", not bad,
                  f"{len(said)} lines, {len(bad)} not heard or lost their start{stat}", bad or lines)


def every_turn_got_audio(run: Run) -> Result:
    empty = [t for t in run.timings() if t["name"] == "turn_ended" and not (t["extra"] or {}).get("audio_s")]
    return Result("Every turn the Mac offered got the user's audio", not empty,
                  f"{len(empty)} turns ended with no audio", [f"turn {t['turn']}" for t in empty])


def no_errors(run: Run) -> Result:
    logs = [e["msg"].get("text", "") for e in run.page["wire"] if e["dir"] == "out" and e["msg"].get("type") == "log"]
    notices = [m["data"].get("text", "") for m in run.messages().values()
               if m["kind"] == "notice" and m["data"].get("level") == "error"]
    found = run.errors + [f"page log: {t}" for t in logs] + [f"notice: {t}" for t in notices]
    return Result("No errors on the page or in the chat", not found, f"{len(found)} errors", found[:20])
