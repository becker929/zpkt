"""Steps: a pattern on the Song. The app's commands for the step sequencer (the Song tab's Steps and Paint).

A pattern is an Arrangement MIDI clip of 1, 2 or 4 bars on a MIDI track (zpkt.live.steps; never a Session clip).
The page, the API and later the MiniLab all pass this one door:

    steps.tracks                                   the set's MIDI tracks (read)
    steps.sounds {track}                           a Drum Rack's filled pads (read)
    steps.read {track, bar, bars}                  the pattern, its clip, what is in the way, and which bars of the
                                                   track hold a clip of that length (read)
    steps.kits                                     the Drum Rack presets Live's browser offers (read; kept)
    steps.toggle {track, bar, bars, pitch, step}   flip one step
    steps.new_track {name, kit}                    a MIDI track with that kit, in front of the monitor tracks

The changing ones are moves (zpkt.app.effects): the bus holds them to the page's set and to the lock, and refuses
them from an agent. None of them ever names a monitor track ("mon ..."): `the_track` is the rail.
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
    swing = number(cmd.args, "swing", 0.0)
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
                swing=number(cmd.args, "swing", 0.0),
            )
        )
    if (refused := in_the_way(did)) is not None:
        return refused
    return 200, {"ok": True, "on": did["on"], "velocity": did["velocity"], "created": did["created"]}


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
    return 200, {
        "ok": True,
        "track": made["name"],
        "index": made["index"],
        "kit": made["kit"],
        "device": made["device"],
    }


# ---- the table -----------------------------------------------------------------------------------------------------

COMMANDS = {
    "steps.tracks": tracks,
    "steps.sounds": sounds,
    "steps.read": read,
    "steps.kits": kits,
    "steps.toggle": toggle,
    "steps.new_track": new_track,
}


def register(bus: Bus, desk: Desk) -> None:
    """Put the step sequencer's commands on the bus. Each calls Live, so each takes the lock."""
    for kind, handler in COMMANDS.items():

        def run(cmd: Command, handler: Any = handler) -> Reply:
            reply: Reply = handler(desk, cmd)
            return reply

        effects.register(bus, kind, run, touches_live=True)
