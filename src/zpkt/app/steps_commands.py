"""Steps: a pattern on the Song. The app's commands for the step sequencer (the Song tab's Steps and Paint).

A pattern is an Arrangement MIDI clip of 1, 2 or 4 bars on a MIDI track (zpkt.live.steps; never a Session clip).
The page, the API and later the MiniLab all pass this one door:

    steps.tracks                                   the set's MIDI tracks (read)
    steps.sounds {track}                           a Drum Rack's filled pads (read)
    steps.read {track, bar, bars}                  the pattern, its clip, what is in the way, and which bars of the
                                                   track hold a clip of that length (read)
    steps.kits                                     the Drum Rack presets Live's browser offers (read; kept)
    steps.toggle {track, bar, bars, pitch, step}   flip one step
    steps.set {track, bar, bars, pitch, step, ..}  another velocity or length for a step's note
    steps.write {track, bar, pattern}              the span holds exactly this pattern (swing, clear, another length)
    steps.paint {track, from_bar, bars, to: [..]}  stamp the pattern's clip onto other bars
    steps.erase {track, bars: [..], length}        delete the clips of that length that start on those bars
    steps.new_track {name, kit}                    a MIDI track with that kit, in front of the monitor tracks
    steps.focus {track, bar, bars, pitch, ...}     what the sequencer is editing now ({}: nothing)
    steps.loop {bar, bars}                         loop those bars in Live; what the loop was comes back

The changing ones are moves (zpkt.app.effects): the bus holds them to the page's set and to the lock, and refuses
them from an agent. None of them ever names a monitor track ("mon ..."): `the_track` is the rail.

Undo: every changing command is one History row (an entry of kind "steps", zpkt.app.history) that keeps what each
span of the Arrangement held before; undo and redo write that back (`swap`, over zpkt.live.steps.restore). A run
of edits to one pattern is one row. A new track is not undone: its row says so.

The focus is the one piece of state here (`Desk.steps_focus`, in `/api/state`, in the agents' `desk.state`, and
pushed to every page and adapter as {"t": "steps", "focus": {...} | null}): which pattern and which sound the
sequencer has in hand, the values a new step gets, and that sound's steps. It is what a controller needs to light
16 pads and to turn a pad press into `steps.toggle` (see `focus`).
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Any

from zpkt.app import effects
from zpkt.app.bus import BadRequest, Bus, Command, Refused, Reply
from zpkt.live import steps as live_steps
from zpkt.live.transport import LiveError

if TYPE_CHECKING:
    from zpkt.app.desk import Desk

MONITOR_PREFIX = live_steps.MONITOR_PREFIX
STEPS_PER_BAR = 16  # what the page and the MiniLab's two banks of 8 pads show of a bar
DEFAULT_PITCHES = tuple(range(36, 44))  # C1 to G1: what a track with no Drum Rack and no notes offers
MAX_TOTAL_BARS = 4096
MAX_NAME = 40
IN_THE_WAY = 409  # clips are in the way, or the step holds no note: nothing changed, and the answer says why

# What Live says when the track is not there or takes no MIDI: the caller's mistake, not a Live that is down.
_ASKED_WRONG = re.compile(r"(no track, return or Main named '[^']*'|'[^']*' is not a MIDI track)")


@contextlib.contextmanager
def asking() -> Iterator[None]:
    """Around a zpkt.live.steps call: a value it refuses, or a track the set lacks, is the caller's 400."""
    try:
        yield
    except ValueError as exc:
        raise BadRequest(str(exc)) from None
    except LiveError as exc:
        wrong = _ASKED_WRONG.search(str(exc))
        if wrong is None:
            raise
        raise BadRequest(wrong.group(1)) from None


# ---- reading the arguments -----------------------------------------------------------------------------------------


def the_track(args: Any, name: str = "track") -> str:
    """The track a command names, by its name. The rail: never one of the monitor's own tracks."""
    track = args.get(name)
    if not isinstance(track, str) or not track.strip():
        raise BadRequest(f"the body needs {name!r}, a track's name")
    if track.startswith(MONITOR_PREFIX):
        raise Refused(f"{track!r} is one of the monitor's tracks: no pattern is read or written there")
    return track


def whole(args: Any, name: str, default: int | None = None) -> int:
    value = args.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise BadRequest(f"the body needs {name!r}, a whole number")
    return value


def number(args: Any, name: str, default: float) -> float:
    value = args.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise BadRequest(f"{name!r} must be a number")
    return float(value)


def swing_for(desk: Desk, args: Any, track: str, bar: int, bars: int) -> float:
    """The swing a pattern's notes were written with: what the command says, else what the last `steps.write` of
    that pattern said (kept while the app runs: Live's notes do not say it), else none."""
    if "swing" in args:
        return number(args, "swing", 0.0)
    with desk.lock:
        return desk.steps_swing.get((track, bar, bars), 0.0)


def the_span(args: Any) -> tuple[str, int, int, int]:
    """(track, bar, bars, steps per bar) of the pattern a command is about."""
    return (
        the_track(args),
        whole(args, "bar"),
        whole(args, "bars", 1),
        whole(args, "steps_per_bar", STEPS_PER_BAR),
    )


def plain(answer: Mapping[str, object]) -> dict[str, Any]:
    """An answer of zpkt.live.steps (one of several typed shapes) as a plain dict."""
    return dict(answer)


def in_the_way(did: Mapping[str, object]) -> Reply | None:
    """The 409 for an answer of zpkt.live.steps that says nothing was changed ({"error", "blocked"?}); None for
    one that did its work."""
    if "error" not in did:
        return None
    return IN_THE_WAY, {"error": str(did["error"]), "blocked": did.get("blocked", [])}


# ---- reads ---------------------------------------------------------------------------------------------------------


def tracks(desk: Desk, cmd: Command) -> Reply:
    """The set's MIDI tracks, in the set's order, without the monitor's own: [{"name", "index", "color",
    "drum_rack"}]."""
    found = [t for t in live_steps.midi_tracks(desk.conn) if not t["name"].startswith(MONITOR_PREFIX)]
    return 200, {"ok": True, "tracks": found}


def sounds(desk: Desk, cmd: Command) -> Reply:
    """A Drum Rack track's filled pads, lowest first: [{"pitch", "name"}]; empty for another instrument."""
    track = the_track(cmd.args)
    with asking():
        return 200, {"ok": True, "track": track, "sounds": live_steps.sounds(desk.conn, track)}


def read(desk: Desk, cmd: Command) -> Reply:
    """Everything the Steps and Paint screens draw, in one command: {"track", "bar", "bars", "pattern" (a row per
    sound), "sounds", "drum_rack", "clip", "blocked" (clips in the way of writing the span), "off_grid", "hash",
    "beats_per_bar", "painted": [{"bar", "hash", "name"}] (the bars of the track on which a clip of this length
    starts: the ones with the pattern's "hash" hold this pattern), "total_bars"}.

    The rows are the Drum Rack's sounds. A track with another instrument (or none) has a row for each pitch that
    has a note, and for C1 to G1 when it has none. Three short calls to Live."""
    track, bar, bars, per_bar = the_span(cmd.args)
    swing = swing_for(desk, cmd.args, track, bar, bars)
    total = max(1, min(MAX_TOTAL_BARS, whole(cmd.args, "total_bars", max(64, bar + bars))))
    with asking():
        kit = live_steps.sounds(desk.conn, track)
        named = {s["pitch"]: s["name"] for s in kit}
        found = live_steps.read(
            desk.conn, track, bar, bars, per_bar, [s["pitch"] for s in kit] or None, swing=swing, names=named
        )
        pattern = found["pattern"]
        if not pattern["rows"]:
            pattern = {**live_steps.blank(bars, per_bar, DEFAULT_PITCHES, swing=swing), "off_grid": found["off_grid"]}
        painted = live_steps.painted(desk.conn, track, bars, total)
    rows = [{"pitch": r["pitch"], "name": r["name"]} for r in pattern["rows"]]
    return 200, {
        "ok": True,
        "track": track,
        "bar": bar,
        "bars": bars,
        "pattern": pattern,
        "sounds": rows,
        "drum_rack": bool(kit),
        "clip": found["clip"],
        "blocked": found["blocked"],
        "off_grid": found["off_grid"],
        "hash": found["hash"],
        "beats_per_bar": found["beats_per_bar"],
        "painted": painted,
        "total_bars": total,
    }


def kits(desk: Desk, cmd: Command) -> Reply:
    """The Drum Rack presets Live's browser offers, by name (60 at most). Asked of Live once and kept while the app
    runs; {"fresh": true} asks again."""
    with desk.lock:
        kept = None if cmd.args.get("fresh") else desk.steps_kits
    if kept is None:
        kept = live_steps.kits(desk.conn)
        with desk.lock:
            desk.steps_kits = kept
    return 200, {"ok": True, "kits": kept}


# ---- the focus: what the sequencer is editing now -------------------------------------------------------------------

FOCUS_KEYS = ("track", "bar", "bars", "steps_per_bar", "view", "pitch", "name", "velocity", "length", "swing")
PATTERN_KEYS = ("track", "bar", "bars", "steps_per_bar", "pitch", "swing")  # another value of one: other steps


def source_of(args: Any) -> str | None:
    """`src`: a short word a page sends with its commands, so that it knows its own changes when they come back."""
    src = args.get("src")
    return str(src)[:40] if isinstance(src, str) and src else None


def say(desk: Desk, edit: dict[str, Any] | None = None, src: str | None = None) -> dict[str, Any] | None:
    """Tell every page and adapter what the focus is now: {"t": "steps", "focus": {...} | None}, with "src" (who
    asked, if it said) and, after a change to a pattern, "edit": {"track", "bar", "bars", "what"}. Returns the
    focus as sent."""
    focus = desk.steps_now()
    message: dict[str, Any] = {"t": "steps", "focus": focus}
    if src:
        message["src"] = src
    if edit:
        message["edit"] = edit
    desk.push(message)
    return focus


def focused_steps(desk: Desk, focus: dict[str, Any]) -> tuple[list[int], bool, str]:
    """The focused sound's steps as Live has them, whether clips are in the way, and the sound's name. One call."""
    found = live_steps.read(
        desk.conn,
        focus["track"],
        focus["bar"],
        focus["bars"],
        focus["steps_per_bar"],
        [focus["pitch"]],
        swing=focus["swing"],
    )
    row = found["pattern"]["rows"][0]
    return list(row["steps"]), bool(found["blocked"]), row["name"]


def focus(desk: Desk, cmd: Command) -> Reply:
    """Say what the sequencer is editing: {"track", "bar", "bars", "pitch", "velocity"?, "length"?, "swing"?,
    "view"?, "name"?, "steps_per_bar"?}; {} says it is editing nothing. With a focus in place a part is enough
    ({"pitch": 38}, {"velocity": 90}): the rest stays.

    The focus that is kept and pushed ({"t": "steps", "focus": ...}):

        track, bar, bars, steps_per_bar   the pattern: `bars` bars of `track` from bar `bar` (counted from 1)
        pitch, name                       the sound in hand
        velocity, length, swing           what a new step gets (length in steps, swing as a part of a step)
        view                              which bar of the pattern the 16 pads show, from 0
        steps                             that sound's steps over the whole pattern: 0, or the note's velocity
        blocked                           clips are in the way of this span: nothing can be written
        rev                               counts up with every change of the focus

    So the 16 pads are steps[view * steps_per_bar + k] for k from 0 to 15 (pads A: 0 to 7, pads B: 8 to 15), and
    a press of pad k is `steps.toggle {track, bar, bars, pitch, step: view * steps_per_bar + k, velocity, length,
    swing}`. `steps` is read from Live when the pattern or the sound changes (one short call; a page that has
    just read the pattern may hand "steps" and "blocked" over instead), and kept up by every command here that
    changes the pattern."""
    src = source_of(cmd.args)
    asked = {k: v for k, v in cmd.args.items() if k != "src"}
    if not asked:
        with desk.lock:
            was, desk.steps_focus = desk.steps_focus, None
            desk.steps_rev += was is not None
        return 200, {"ok": True, "focus": say(desk, src=src)}
    with desk.lock:
        now = desk.steps_focus
    merged = {**(now or {}), **asked}
    with asking():
        total = live_steps.check_grid(whole(merged, "bars", 1), whole(merged, "steps_per_bar", STEPS_PER_BAR))
        new: dict[str, Any] = {
            "track": the_track(merged),
            "bar": live_steps.check_bar(whole(merged, "bar")),
            "bars": merged.get("bars", 1),
            "steps_per_bar": merged.get("steps_per_bar", STEPS_PER_BAR),
            "view": whole(merged, "view", 0),
            "pitch": live_steps.check_pitch(whole(merged, "pitch")),
            "velocity": live_steps.check_velocity(whole(merged, "velocity", 100)),
            "length": live_steps.check_length(number(merged, "length", 1.0), total),
            "swing": live_steps.check_swing(number(merged, "swing", 0.0)),
        }
        if not 0 <= new["view"] < new["bars"]:
            raise BadRequest(f"'view' is a bar of the pattern, 0 to {new['bars'] - 1}")
        same = now is not None and all(now[k] == new[k] for k in PATTERN_KEYS)
        name = asked.get("name") or (now["name"] if same and now else None)
        given = asked.get("steps")
        if isinstance(given, list) and len(given) == total and all(type(v) is int and 0 <= v <= 127 for v in given):
            steps_now, blocked = list(given), bool(asked.get("blocked"))
        elif same and now is not None:
            steps_now, blocked = list(now["steps"]), bool(now["blocked"])
        else:
            steps_now, blocked, read_name = focused_steps(desk, new)
            name = name or read_name
    new.update(name=str(name or live_steps.note_name(new["pitch"])), steps=steps_now, blocked=blocked)
    with desk.lock:
        desk.steps_rev += 1
        new["rev"] = desk.steps_rev
        desk.steps_focus = new
    return 200, {"ok": True, "focus": say(desk, src=src)}


def edited(
    desk: Desk,
    span: tuple[str, int, int],
    what: str,
    src: str | None = None,
    step: tuple[int, int, int] | None = None,
    clips: bool = True,
) -> None:
    """A command changed the pattern `span` (track, bar, bars): keep the focus's steps true and tell the pages.
    `step` is (pitch, step, velocity or 0) when one step is all that changed, which needs no call to Live;
    otherwise the focused row is read again when the change was to the focused span. `clips`: a clip came or
    went, so what the app read of the song is stale and the pages are told to read it again ({"t": "arr"}; the
    pager says so too, but drops a second change within a third of a second)."""
    track, bar, bars = span
    if clips:
        desk.forget_arrangement()
        desk.push({"t": "arr"})
    with desk.lock:
        focus_now = desk.steps_focus
        ours = focus_now is not None and focus_now["track"] == track
        hit = (
            ours
            and focus_now is not None
            and bar < focus_now["bar"] + focus_now["bars"]
            and focus_now["bar"] < bar + bars
        )
    if hit and focus_now is not None:
        same_span = (focus_now["bar"], focus_now["bars"]) == (bar, bars)
        if step is not None and same_span:
            fresh, blocked = list(focus_now["steps"]), False
            if step[0] == focus_now["pitch"] and 0 <= step[1] < len(fresh):
                fresh[step[1]] = step[2]
        else:
            fresh, blocked, _ = focused_steps(desk, focus_now)
        with desk.lock:
            if desk.steps_focus is focus_now:
                desk.steps_rev += 1
                desk.steps_focus = {**focus_now, "steps": fresh, "blocked": blocked, "rev": desk.steps_rev}
    say(desk, {"track": track, "bar": bar, "bars": bars, "what": what}, src)


# ---- History: one row a change, and the way back ---------------------------------------------------------------------


def held(notes: Any, name: str | None = None) -> dict[str, Any]:
    """What a span held, as the history keeps it: its clip's name (None: not known, and not changed when it is
    put back) and notes."""
    return {"name": name, "notes": [list(n) for n in notes]}


Before = list[tuple[int, int, dict[str, Any] | None]]  # per span changed: its bar, its bars, what it held


def row(
    desk: Desk,
    cmd: Command,
    track: str,
    what: str,
    span: tuple[int, int],
    before: Before,
    count: int = 1,
    more: dict[str, Any] | None = None,
) -> int:
    """Write the History row of a change Live has made. `before` is, in the order they were changed, each span's
    (bar, bars, what it held: None for a free span). Returns the entry's id."""
    spans = [{"track": track, "bar": bar, "bars": bars, "state": state} for bar, bars, state in before]
    entry = desk.history.steps_change(cmd.who, track, what, span[0], span[1], spans, count, more)
    desk.push(desk.history.view())
    return int(entry["id"])


def swap(desk: Desk, entry: dict[str, Any], forward: bool) -> list[str]:
    """Undo (`forward` false) or redo a History entry's step patterns: each span gets the state the entry keeps
    for it, and the entry keeps what the span held instead, so the next swap goes the other way. Undo takes the
    spans last one first. A span that cannot be put back (clips are in the way now, the track is gone) is left as
    it is and named in the answer; the others still go back. One short call to Live a span."""
    spans = entry.get("spans") or []
    notes: list[str] = []
    touched: dict[str, list[int]] = {}
    for span in spans if forward else list(reversed(spans)):
        track, bar, bars, state = span["track"], span["bar"], span["bars"], span["state"]
        try:
            did = plain(
                live_steps.restore(
                    desk.conn,
                    track,
                    bar,
                    bars,
                    None if state is None else state["notes"],
                    None if state is None else state.get("name") or None,
                )
            )
        except LiveError as exc:
            if exc.result is None:  # Live does not answer at all: that is the caller's to say
                raise
            wrong = _ASKED_WRONG.search(str(exc))
            notes.append(f"{track}, bar {bar}: {wrong.group(1) if wrong else 'Live did not put it back'}")
            continue
        if "error" in did:
            notes.append(f"{track}, bar {bar}: {did['error']}")
            continue
        was = did["was"]
        span["state"] = None if was is None else held(was["notes"], was["name"])
        touched.setdefault(track, []).extend([bar, bar + bars])
    desk.history.steps_swapped(entry)
    for track, edges in touched.items():
        edited(desk, (track, min(edges), max(edges) - min(edges)), "undo")
    return notes


# ---- the loop ------------------------------------------------------------------------------------------------------


def loop(desk: Desk, cmd: Command) -> Reply:
    """Loop a pattern's bars in Live, so it is heard going round with the song: {"bar", "bars"}; the answer's "was"
    is the loop as it was ({"on", "start", "length"}, in beats). {"was": {...}} puts that back. A move of the
    transport: never a History row. Live reports the loop itself ({"t": "loop"})."""
    with asking():
        if "was" in cmd.args:
            was = cmd.args["was"]
            if not isinstance(was, dict):
                raise BadRequest("'was' is the loop as steps.loop gave it: {on, start, length}")
            return 200, {"ok": True, "was": live_steps.loop_put(desk.conn, was)}
        return 200, {"ok": True, "was": live_steps.loop(desk.conn, whole(cmd.args, "bar"), whole(cmd.args, "bars", 1))}


# ---- moves ---------------------------------------------------------------------------------------------------------


def toggle(desk: Desk, cmd: Command) -> Reply:
    """Flip one step (counted from 0) of the pattern: {"track", "bar", "bars", "pitch", "step", "velocity"?,
    "length"? (in steps), "swing"?}. A free span gets its clip. The answer is {"on", "velocity", "created"}; with
    clips in the way it is 409 with "blocked" and nothing has changed. One call to Live."""
    track, bar, bars, per_bar = the_span(cmd.args)
    with asking():
        did = plain(
            live_steps.toggle(
                desk.conn,
                track,
                bar,
                bars,
                per_bar,
                whole(cmd.args, "pitch"),
                whole(cmd.args, "step"),
                whole(cmd.args, "velocity", 100),
                number(cmd.args, "length", 1.0),
                swing=swing_for(desk, cmd.args, track, bar, bars),
            )
        )
    if (refused := in_the_way(did)) is not None:
        return refused
    edited(
        desk,
        (track, bar, bars),
        "toggle",
        source_of(cmd.args),
        (whole(cmd.args, "pitch"), whole(cmd.args, "step"), did["velocity"] if did["on"] else 0),
        clips=bool(did["created"]),
    )
    entry = row(desk, cmd, track, "edit", (bar, bars), [(bar, bars, None if did["created"] else held(did["before"]))])
    return 200, {"ok": True, "on": did["on"], "velocity": did["velocity"], "created": did["created"], "entry": entry}


def set_step(desk: Desk, cmd: Command) -> Reply:
    """Give the note on a step another velocity, another length (in steps) or both: {"track", "bar", "bars",
    "pitch", "step", "velocity"?, "length"?, "swing"?}. The answer is {"on": true, "velocity", "length"}; 409 when
    the step holds no note, or clips are in the way. One call to Live."""
    track, bar, bars, per_bar = the_span(cmd.args)
    velocity = whole(cmd.args, "velocity") if "velocity" in cmd.args else None
    length = number(cmd.args, "length", 1.0) if "length" in cmd.args else None
    pitch, step = whole(cmd.args, "pitch"), whole(cmd.args, "step")
    with asking():
        did = plain(
            live_steps.set_step(
                desk.conn,
                track,
                bar,
                bars,
                per_bar,
                pitch,
                step,
                velocity,
                length,
                swing=swing_for(desk, cmd.args, track, bar, bars),
            )
        )
    if (refused := in_the_way(did)) is not None:
        return refused
    edited(desk, (track, bar, bars), "set", source_of(cmd.args), (pitch, step, did["velocity"]), clips=False)
    entry = row(desk, cmd, track, "edit", (bar, bars), [(bar, bars, held(did["before"]))])
    return 200, {"ok": True, "on": True, "velocity": did["velocity"], "length": did["length"], "entry": entry}


def replaces(desk: Desk, track: str, bar: int, pattern: Mapping[str, Any], old_bars: int) -> bool:
    """Is the clip of `old_bars` bars at `bar` all that is in the way of the pattern's span? Then the caller
    deletes it and writes the pattern (of another length) in its place. False when no clip needs to go (the span
    is free, or holds a clip of the new length) and when other clips are in the way too: the write then answers
    for itself, and nothing has been deleted. One short read."""
    found = live_steps.read(
        desk.conn, track, bar, int(pattern["bars"]), int(pattern.get("steps_per_bar", STEPS_PER_BAR))
    )
    per = found["beats_per_bar"]
    start, end = (bar - 1) * per, (bar - 1 + old_bars) * per
    in_way = found["blocked"]
    return len(in_way) == 1 and abs(in_way[0]["start"] - start) < 1e-6 and abs(in_way[0]["end"] - end) < 1e-6


def write(desk: Desk, cmd: Command) -> Reply:
    """Make the span hold exactly this pattern: {"track", "bar", "pattern": {"bars", "steps_per_bar"?, "rows":
    [{"pitch", "name"?, "steps", "lengths"?}], "length"?, "swing"?}}. For what is not one step: swing, clearing a
    sound or the whole pattern, and another length. With "from_bars" the pattern takes the place of the clip of
    that many bars at "bar" (1 bar becomes 2: the clip is deleted and a longer one made), when that clip is all
    that is in the way. The answer is what `steps.read` gives of the span after the write ({"pattern", "clip",
    "hash", "off_grid", "blocked", "beats_per_bar"}) and "created"; 409 with "blocked" when clips are in the way
    (nothing has changed)."""
    track, bar = the_track(cmd.args), whole(cmd.args, "bar")
    pattern = cmd.args.get("pattern")
    if not isinstance(pattern, dict):
        raise BadRequest("the body needs 'pattern': {bars, rows: [{pitch, steps}], length?, swing?}")
    old_bars = whole(cmd.args, "from_bars") if "from_bars" in cmd.args else None
    with asking():
        checked = live_steps.check(pattern)
        bars = checked["bars"]
        took = None  # the clip of the old length, deleted to make room
        if old_bars is not None and old_bars != bars and replaces(desk, track, bar, checked, old_bars):
            took = live_steps.erase(desk.conn, track, [bar], old_bars)["erased"]
        did = plain(live_steps.write(desk.conn, track, bar, checked))
        if "error" in did and took:  # it should not happen: the old clip goes back where it was
            live_steps.restore(desk.conn, track, bar, old_bars or bars, took[0]["notes"], took[0]["name"] or None)
    if (refused := in_the_way(did)) is not None:
        return refused
    with desk.lock:
        desk.steps_swing[(track, bar, bars)] = checked.get("swing", 0.0)
    edited(
        desk, (track, bar, max(bars, old_bars or 0)), "write", source_of(cmd.args), clips=bool(did["created"] or took)
    )
    here = None if did["created"] else held(did["before"])
    if took and old_bars is not None:  # another length: the old clip went, then the new one came
        gone = (bar, old_bars, held(took[0]["notes"], took[0]["name"]))
        entry = row(desk, cmd, track, "length", (bar, bars), [gone, (bar, bars, here)], more={"from_bars": old_bars})
    else:
        entry = row(desk, cmd, track, "edit", (bar, bars), [(bar, bars, here)])
    return 200, {
        "ok": True,
        "entry": entry,
        "track": track,
        "bar": bar,
        "bars": bars,
        "pattern": did["pattern"],
        "clip": did["clip"],
        "hash": did["hash"],
        "off_grid": did["off_grid"],
        "blocked": did["blocked"],
        "beats_per_bar": did["beats_per_bar"],
        "created": did["created"],
    }


def bar_list(args: Any, name: str) -> list[int]:
    bars = args.get(name)
    if not isinstance(bars, list) or not bars or not all(type(b) is int for b in bars):
        raise BadRequest(f"the body needs {name!r}, a list of bars (counted from 1)")
    return list(bars)


def clips_now(desk: Desk, track: str, bars: int, args: Any, reach: int) -> list[dict[str, Any]]:
    """The bars of the track that start a clip of `bars` bars now, with their hashes: what the Paint lane draws."""
    total = max(1, min(MAX_TOTAL_BARS, whole(args, "total_bars", max(64, reach))))
    return [dict(c) for c in live_steps.painted(desk.conn, track, bars, total)]


def paint(desk: Desk, cmd: Command) -> Reply:
    """Stamp the pattern's clip onto other bars: {"track", "from_bar", "bars", "to": [the first bar of each copy]}.
    A bar that holds a clip of the same length is replaced; one that a clip of another length reaches into is
    skipped and named, as is the pattern's own bar. The answer is {"painted": [bars], "skipped": [{"bar", "why"}],
    "replaced": [bars], "clips": [{"bar", "hash", "name"}] (every clip of that length on the track now)}; 409 when
    no clip covers exactly the bars to paint from. 64 bars at most; Live copies 16 to a call."""
    track, source, length = the_track(cmd.args), whole(cmd.args, "from_bar"), whole(cmd.args, "bars", 1)
    targets = bar_list(cmd.args, "to")
    with asking():
        did = live_steps.paint(desk.conn, track, source, length, targets)
        if did["painted"]:
            edited(
                desk,
                (track, min(did["painted"]), max(did["painted"]) - min(did["painted"]) + length),
                "paint",
                source_of(cmd.args),
            )
        if "error" in did and not did["painted"]:
            return IN_THE_WAY, {"error": did["error"], "blocked": did.get("blocked", [])}
        clips = clips_now(desk, track, length, cmd.args, max(targets) + length)
    entry = None
    if did["painted"]:
        over = {k["bar"]: held(k["notes"], k["name"]) for k in did["replaced"]}
        before: Before = [(b, length, over.get(b)) for b in did["painted"]]
        entry = row(desk, cmd, track, "paint", (source, length), before, count=len(did["painted"]))
    return 200, {
        "ok": True,
        "entry": entry,
        "painted": did["painted"],
        "skipped": did["skipped"],
        "replaced": [k["bar"] for k in did["replaced"]],
        "clips": clips,
    }


def erase(desk: Desk, cmd: Command) -> Reply:
    """Delete the MIDI clips of "length" bars that start on "bars": {"track", "bars": [...], "length"}. A bar with
    a clip of another length, or with none, is skipped and named. The answer is {"erased": [bars], "skipped",
    "clips"}. One call to Live."""
    track, length = the_track(cmd.args), whole(cmd.args, "length", 1)
    targets = bar_list(cmd.args, "bars")
    with asking():
        did = live_steps.erase(desk.conn, track, targets, length)
        gone = [k["bar"] for k in did["erased"]]
        if gone:
            edited(desk, (track, min(gone), max(gone) - min(gone) + length), "erase", source_of(cmd.args))
        clips = clips_now(desk, track, length, cmd.args, max(targets) + length)
    entry = None
    if gone:
        was: Before = [(k["bar"], length, held(k["notes"], k["name"])) for k in did["erased"]]
        entry = row(desk, cmd, track, "erase", (gone[0], length), was, count=len(gone))
    return 200, {"ok": True, "entry": entry, "erased": gone, "skipped": did["skipped"], "clips": clips}


def track_name(args: Any) -> str:
    """A new track's name: short, no "/", and never a name the desk keeps for itself."""
    name = args.get("name")
    if not isinstance(name, str) or not name.strip():
        raise BadRequest("the body needs 'name', the new track's name")
    name = name.strip()
    if len(name) > MAX_NAME or "/" in name:
        raise BadRequest(f"a track's name is at most {MAX_NAME} characters and has no '/'")
    if name.startswith(MONITOR_PREFIX) or name.lower() in ("main", "master"):
        raise Refused(f"{name!r} is a name the desk keeps for itself")
    return name


def new_track(desk: Desk, cmd: Command) -> Reply:
    """Make a MIDI track called "name" with the kit "kit" (one of `steps.kits`) on it, in front of the first monitor
    track (last, in a set with none). The answer is {"track", "index", "kit", "device"}. Nothing is made when the
    browser has no such kit or the set has a track of that name (400). The app does not undo a new track."""
    name = track_name(cmd.args)
    kit = cmd.args.get("kit")
    if not isinstance(kit, str) or not kit.strip():
        raise BadRequest("the body needs 'kit', a kit's name (steps.kits lists them)")
    try:
        with asking():
            made = live_steps.new_drum_track(desk.conn, name, kit)
    except live_steps.StepsError as exc:
        return 502, {"error": str(exc)}
    finally:
        desk.forget_arrangement()
    words = f"New drum track {made['name']} ({made['kit']})"
    stays = [{"op": "track", "kind": "midi", "name": made["name"], "words": words}]
    entry = row(desk, cmd, made["name"], "track", (1, 1), [], more={"stays": stays, "kit": made["kit"]})
    return 200, {
        "ok": True,
        "entry": entry,
        "track": made["name"],
        "index": made["index"],
        "kit": made["kit"],
        "device": made["device"],
        "no_undo": [words],
    }


# ---- the table -----------------------------------------------------------------------------------------------------

COMMANDS = {
    "steps.tracks": tracks,
    "steps.sounds": sounds,
    "steps.read": read,
    "steps.kits": kits,
    "steps.toggle": toggle,
    "steps.set": set_step,
    "steps.write": write,
    "steps.paint": paint,
    "steps.erase": erase,
    "steps.new_track": new_track,
    "steps.focus": focus,
    "steps.loop": loop,
}


def register(bus: Bus, desk: Desk) -> None:
    """Put the step sequencer's commands on the bus. Each calls Live, so each takes the lock."""
    for kind, handler in COMMANDS.items():

        def run(cmd: Command, handler: Any = handler) -> Reply:
            reply: Reply = handler(desk, cmd)
            return reply

        effects.register(bus, kind, run, touches_live=True)
