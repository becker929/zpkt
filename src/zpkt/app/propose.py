"""`live.propose`: a batch that changes the set's structure or runs code. You see it first; it runs after your tap.

    {"why": "parallel drive on the hats", "steps": [
        {"new_track": "return", "name": "Drive"},
        {"add": "Saturator", "track": "Drive"},
        {"set": "Hats bus/send Drive", "to": 0.6},
        {"remove": "desk Sat", "track": "Hats bus"},
        {"code": "find_track('hats').output_routing_type = ...", "does": "Routes hats to the Drive return only."}]}

Anthony, 26 November 2026: values and devices are "act, then undo" (`live.change`, zpkt.app.change); structure and
code are "ask first". A step here is any `live.change` step, or one of three more:

    {"remove": DEVICE, "track": TRACK}                       take a device off a chain
    {"new_track": "audio" | "midi" | "return", "name": NAME}  make a track
    {"code": PYTHON, "does": ONE SENTENCE}                    anything else (routing, clips): code for Live

Two commands, and the Ask tool gate (zpkt.app.ask.tools) between them:

1. `live.propose.check` (a read) checks the batch whole, as `live.change` does: shape, limits (MAX_CODE code steps
   of CODE_MAX characters, MAX_TRACKS tracks), the rails, Live's own names and ranges. A batch with a problem
   answers 400 with every problem, and nobody is asked. A batch that passes answers with its card: `why` and one
   short line per step in plain words ("Remove desk Sat from Hats bus", "Set Kick bus volume to -3.0 dB").
2. The gate shows the card in the chat and waits for the tap. Nothing in Live is held or changed meanwhile.
3. `live.propose` (a move) runs the batch. From an agent it needs your word (`approval`), which only the gate can
   give, after "Do it". It checks the whole batch again (the set may have changed while the card waited), saves a
   version, then runs the steps in order, each its own short call, stopping at the first that fails.

The rails are `live.change`'s, and: no device is removed on Main, and no new track is named "mon ...". Code cannot
be checked against them: it is screened for the names it spells out (a monitor track's, the two devices that are
only the desk's on Main), which guards against an accident and is not a wall. The card shows the code itself.

History: the batch is one row. Undo takes back its values, added devices and moves, as for `live.change`. It does
NOT take back a removed device (its settings are gone), a new track, or code (the app cannot know what code did):
those are the entry's "stays" (zpkt.app.history), the row marks them, and undo's reply names them. Code is recorded
as soon as it was sent, also when Live reported an error: part of it may have run.

Code runs as `live.run` does (zpkt.app.jobs): the string as it is, one call, under the bus's lock.
"""

from __future__ import annotations

import ast
import json
from typing import TYPE_CHECKING, Any

from zpkt.app import change, effects, jobs
from zpkt.app.bus import Bus, Command, Reply
from zpkt.app.change import Batch, Step, StepFailed
from zpkt.live import chain, describe, monitor_tracks, newtrack, page_layout
from zpkt.live.describe import Description
from zpkt.live.inlive import keys as live_keys
from zpkt.live.transport import LiveError

if TYPE_CHECKING:
    from zpkt.app.desk import Desk

KIND = "live.propose"
CHECK = "live.propose.check"
MAX_CODE = 3  # code steps in one batch: each is read by a person on a phone
CODE_MAX = 2000  # characters of one code step
DOES_MAX = 140  # characters of the sentence that says what the code does
MAX_TRACKS = 8
NAME_MAX = 40  # characters of a new track's name
RESULT_MAX = 1000  # characters of a code step's result kept in the reply
LIVE_PYTHON = (3, 11)  # Live's own Python: code is parsed as that version reads it, as far as `ast` can tell
OWN_KINDS = ("remove", "new_track", "code")
STEP_KINDS = ("set", "add", "device", "move", *OWN_KINDS)
NO_UNDO = ("remove", "track", "code")  # the ops undo does not take back
# The devices that are only the desk's own on Main: code that names one is refused. (Main's "desk Glue" has
# namesakes on the buses, so a name alone does not say which is meant.)
ONLY_ON_MAIN = tuple(n for n in change.RAILED_ON_MAIN if n not in monitor_tracks.MAIN_DEVICES)


# ---- reading the ask -----------------------------------------------------------------------------------------------


def screened(tree: ast.AST) -> str | None:
    """Why the rails hold this code, by the names it spells out, or None. A guard against accidents, not a wall."""
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if node.value.casefold().startswith(monitor_tracks.PREFIX):
            return f'the code names "{node.value}": that is a monitor track, and the app never changes those'
        if node.value in ONLY_ON_MAIN:
            return f'the code names "{node.value}", one of the desk\'s own devices on Main: the app never changes those'
    return None


def read_step(n: int, step: Any) -> Step | str:
    """One step as a Step, or what is wrong with its shape. The four kinds of `live.change` are read by its reader."""
    if not isinstance(step, dict):
        return 'a step is an object: {"remove": device, "track": name}, {"new_track": "audio", "name": name}, ...'
    kinds = [k for k in STEP_KINDS if k in step]
    if len(kinds) != 1:
        return "a step has exactly one of " + ", ".join(f'"{k}"' for k in STEP_KINDS)
    kind = kinds[0]
    if kind not in OWN_KINDS:
        return change.read_step(n, step)
    value = step[kind]
    if not isinstance(value, str) or not value.strip():
        return f'"{kind}" must be text'
    if kind == "remove":
        track = step.get("track")
        if not isinstance(track, str) or not track.strip():
            return f'remove "{value.strip()}" needs "track": the track\'s name'
        name, track = value.strip(), track.strip()
        return Step(n, "remove", track, f'remove "{name}" from "{track}"', device=name)
    if kind == "new_track":
        if value not in newtrack.KINDS:
            return '"new_track" is "audio", "midi" or "return"'
        called = step.get("name")
        if not isinstance(called, str) or not called.strip():
            return f'new_track "{value}" needs "name": what to call the track'
        called = " ".join(called.split())
        if len(called) > NAME_MAX or "/" in called:
            return f'a new track\'s name is at most {NAME_MAX} characters and has no "/" (state keys are TRACK/VALUE)'
        return Step(n, "track", called, f'new {value} track "{called}"', kind=value)
    does = step.get("does")
    if not isinstance(does, str) or not does.strip():
        return 'code needs "does": one plain sentence that says what it does, for the person who decides'
    does = " ".join(does.split())
    if len(does) > DOES_MAX:
        return f'"does" is {len(does)} characters: say it in one sentence of at most {DOES_MAX}'
    words = f'code "{does}"'
    if len(value) > CODE_MAX:
        return f"{words} is {len(value)} characters of code, more than {CODE_MAX}: a person has to read it"
    try:
        tree = ast.parse(value, feature_version=LIVE_PYTHON)
    except SyntaxError as exc:
        return f"{words} is not Python that parses: {exc.msg} (line {exc.lineno})"
    if why := screened(tree):
        return f"{words}: {why}"
    return Step(n, "code", "", words, code=value, does=does)


def read(args: Any) -> tuple[str, list[Step], list[str]]:
    """(why, the steps that have a shape, the problems so far), with this command's own limits."""
    why, steps, problems = change.read(args, read_step)
    codes = sum(1 for s in steps if s.op == "code")
    if codes > MAX_CODE:
        problems.append(f"{codes} code steps is more than {MAX_CODE} in one batch: send the rest as a second one")
    tracks = sum(1 for s in steps if s.op == "track")
    if tracks > MAX_TRACKS:
        problems.append(f"{tracks} new tracks is more than {MAX_TRACKS} in one batch: send the rest as a second one")
    return why, steps, problems


def checked(desk: Desk, args: Any) -> tuple[str, list[Step], dict[str, Description], list[str]]:
    """The batch read and checked whole: (why, steps, the descriptions of the values to be set, every problem)."""
    why, steps, problems = read(args)
    found: dict[str, Description] = {}
    if steps:
        more, found = change.check(desk, steps)
        problems += more
    return why, steps, found, problems


def refused(problems: list[str], asked: bool) -> Reply:
    error = (
        "the set changed while the card waited, so the batch no longer passes its checks: nothing changed. Read "
        "the state again and propose it afresh"
        if asked
        else "the proposal was not shown: nothing changed and nobody was asked. Fix every problem below and send "
        "the whole proposal again"
    )
    return 400, {"error": error, "problems": problems}


# ---- the card ------------------------------------------------------------------------------------------------------

_FLAGS = {("mute", True): "Mute", ("mute", False): "Unmute", ("solo", True): "Solo", ("solo", False): "Unsolo"}


def line(s: Step, shown: str | None = None) -> str:
    """One step in plain words, as the card says it. `shown` is what Live would show for a value to be set."""
    if s.op == "add":
        where = "" if s.at is None else " as the first device" if s.at == 0 else f" as device {s.at + 1}"
        return f"Add {s.device} to {s.track}{where}"
    if s.op == "move":
        return f"Move {s.device} on {s.track} to place {int(s.to) + 1}"
    if s.op == "remove":
        return f"Remove {s.device} from {s.track}"
    if s.op == "track":
        return f"New {s.kind} track: {s.track}"
    if s.op == "code":
        return s.does
    param = page_layout.key_parts(s.key)["param"]
    if s.device and param == "Device On":
        return f"Turn {'on' if s.to else 'off'} {s.device} on {s.track}"
    if not s.device and param in ("mute", "solo"):
        return f"{_FLAGS[param, bool(s.to)]} {s.track}"
    value = shown or f"{s.to:g}"
    if s.device:
        return f"Set {s.device} {param} on {s.track} to {value}"
    ret = live_keys.send_return(param)
    return f"Set {s.track} {'send ' + ret if ret is not None else param} to {value}"


def card(desk: Desk, steps: list[Step], found: dict[str, Description]) -> list[dict[str, Any]]:
    """The steps as the chat's card shows them: {"n", "text"}, with "no_undo" for a step undo cannot take back and
    "code" for a code step. One short read gives the values as Live would show them; without it, the raw numbers."""
    sets = [s for s in steps if s.op == "set" and s.key in found]
    shown: dict[int, str | None] = {}
    try:
        texts = describe.shown_for(desk.conn, [(s.key, s.to) for s in sets])
        shown = {s.n: text for s, text in zip(sets, texts, strict=True)}
    except (LiveError, OSError, ValueError):
        pass
    out = []
    for s in steps:
        row: dict[str, Any] = {"n": s.n, "text": line(s, shown.get(s.n))}
        if s.op in NO_UNDO:
            row["no_undo"] = True
        if s.op == "code":
            row["code"] = s.code
        out.append(row)
    return out


# ---- running the three kinds of step that undo does not take back ------------------------------------------------


def _remove(desk: Desk, batch: Batch, s: Step) -> None:
    names = chain.names(desk.conn, s.track)
    index = change.resolve(names, s.device)
    if index is None:
        raise StepFailed(f'"{s.track}" has no device "{s.device}" any more')
    name, label = names[index], change.label_at(names, index)
    if not chain.delete(desk.conn, s.track, index, name):
        raise StepFailed(f'the chain of "{s.track}" changed while the step ran')
    step = {"op": "remove", "track": s.track, "device": name, "at": index, "words": f"Removed {label} from {s.track}"}
    desk.history.change_removed(batch.entry, step, names[: index + 1].count(name))
    batch.extra.setdefault("removed", []).append({"track": s.track, "device": label})


def _track(desk: Desk, batch: Batch, s: Step) -> None:
    try:
        index = newtrack.create(desk.conn, s.kind)
    except newtrack.NewTrackError as exc:
        raise StepFailed(str(exc)) from None
    # it exists from here on, named or not: the row says so even if the next call fails
    words = f"New {s.kind} track: {s.track}"
    desk.history.change_stays(batch.entry, {"op": "track", "kind": s.kind, "name": s.track, "words": words})
    batch.extra.setdefault("made", []).append({"track": s.track, "kind": s.kind})
    newtrack.set_name(desk.conn, s.kind, index, s.track)


def _brief(result: Any) -> Any:
    """A code step's result, small enough for the reply."""
    text = result if isinstance(result, str) else json.dumps(result, default=str)
    return result if len(text) <= RESULT_MAX else text[:RESULT_MAX] + "…"


def _code(desk: Desk, batch: Batch, s: Step) -> None:
    kept = {"op": "code", "does": s.does, "code": s.code, "words": s.does}
    broken = {**kept, "failed": True, "words": f"{s.does} (Live reported an error: part of it may have run)"}
    try:
        res = desk.conn.execute(s.code)
    except (LiveError, OSError):
        desk.history.change_stays(batch.entry, broken)  # sent, and no answer: it may have run
        raise
    ok = res.status == "ok"
    desk.history.change_stays(batch.entry, kept if ok else broken)
    batch.extra.setdefault("ran", []).append({"step": s.n, "ok": ok, "result": _brief(res.result)})
    if not ok:
        raise StepFailed(f"Live reported an error, and part of the code may have run: {res.error or 'no message'}")


RUNNERS: dict[str, change.Runner] = {**change.RUNNERS, "remove": _remove, "track": _track, "code": _code}


# ---- the two commands ----------------------------------------------------------------------------------------------


def propose_check(desk: Desk, cmd: Command) -> Reply:
    """Check the batch whole and answer with its card. Nothing changes; a batch with a problem gets no card."""
    if desk.bus.guard is not None:
        desk.bus.guard.check()  # a read is not held to the set, but a card for the wrong set would be a lie
    why, steps, found, problems = checked(desk, cmd.args)
    if problems:
        return refused(problems, asked=False)
    return 200, {"ok": True, "why": why, "steps": card(desk, steps, found)}


def live_propose(desk: Desk, cmd: Command) -> Reply:
    """Run a batch the person said yes to: check it whole again, save a version, run the steps in order."""
    why, steps, found, problems = checked(desk, cmd.args)
    if problems:
        return refused(problems, asked=True)
    code, reply = change.run(desk, cmd, why, steps, found, KIND, RUNNERS)
    reply.setdefault("no_undo", [])
    return code, reply


def register(bus: Bus, desk: Desk) -> None:
    """Put the two commands on the bus. Running one is for the API's callers (zpkt.app.jobs), as running code is:
    the web page may not. An agent's needs your word, which the Ask gate gives after the tap."""

    def check(cmd: Command) -> Reply:
        return propose_check(desk, cmd)

    def run(cmd: Command) -> Reply:
        return live_propose(desk, cmd)

    effects.register(bus, CHECK, check, touches_live=True)
    effects.register(bus, KIND, run, touches_live=True, checks_first=True, callers=jobs.API_CALLERS)
