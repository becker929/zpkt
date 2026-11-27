"""`live.change`: a batch of changes to Live as one ask, checked whole, run one short step at a time, undone as one.

    {"why": "warmer kick", "steps": [
        {"set": "Kick bus/volume", "to": 0.8},
        {"add": "Saturator", "track": "Kick bus", "at": 0},
        {"set": "Kick bus/Saturator/Drive", "to": 6.0},
        {"device": "desk Glue", "track": "Kick bus", "on": false},
        {"move": "desk EQ", "track": "Kick bus", "to": 2},
        {"use": "route_track_to_return", "args": {"track": "kick", "to": "Drive"}}]}

This is the one move an agent may make with no word of yours (zpkt.app.effects, AGENT_MAY), and all it can do is
this: set values (the state keys and raw numbers `desk.state` gives), add an audio effect to an existing track,
switch a device on or off, and move a device along its chain. It cannot remove a device, make a track, change
routing or clips, or run code: those are `live.propose` (zpkt.app.propose), which shows the batch to you and runs
it only after your tap. That command is built on this one: its steps are read by its own reader, checked by `check`
here (which also knows a removed device, a new track and a code step, the three kinds `read_step` never lets in),
and run by `run` here with more runners.

A `use` step runs an ability: code you allowed for good with "Always" on a proposal's card (zpkt.app.abilities).
That tap is the standing yes, so the step needs no word here. It is checked with the batch (the ability is there,
the arguments fit its parameters, the rails), runs in its place among the other steps as one call to Live
(zpkt.app.coderun), and History treats it as code: undo does not take it back, unless the ability only reads, which
leaves nothing to take back.

The rules, in the order they act:

1. The whole batch is checked before anything moves: the shape of every step, the limits (MAX_STEPS steps, MAX_ADDS
   adds), the rails, and against Live itself every track, device, effect name, range and step of a list. Every
   problem is listed in one 400, in words the asker can act on. A value on a device the same batch adds cannot be
   checked yet: it is checked when its step comes.
2. The rails: never a monitor track ("mon ..."), never Main's desk devices (RAILED_ON_MAIN), and no device is added
   to or moved on Main (its chain is the desk's: what sits there is heard under every monitor track too). The
   wrong-set guard is the bus's, as for every move.
3. A version (checkpoint) is saved, then the steps run in order, each as its own short call to Live. A step that
   fails stops the batch; the reply says what was done and what was not.
4. The batch is one History entry (kind "change", zpkt.app.history), so one undo takes back what was done: values
   first, then the device steps last one first (an added device is deleted, a moved one goes back). `replay` is how
   undo, redo and going back run an entry's device steps.

The Live calls are zpkt.live.chain's (the device chain) and zpkt.live.describe's (ranges); values go through the
desk's own write. Nothing here opens a connection: the desk hands its own in.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from zpkt.app import abilities, coderun, effects
from zpkt.app.bus import BadRequest, Bus, Command, Reply
from zpkt.app.history import left_by, same
from zpkt.live import chain, describe, monitor_tracks, page_layout
from zpkt.live.describe import Description
from zpkt.live.inlive import keys as live_keys
from zpkt.live.inlive import tracks as live_tracks
from zpkt.live.transport import LiveError

if TYPE_CHECKING:
    from zpkt.app.desk import Desk

KIND = "live.change"
MAX_STEPS = 40
MAX_ADDS = 8  # a load takes Live's browser a second or two: eight is already a long ask
MAX_USES = 8  # abilities run in one batch: each is a call to Live
WHY_MAX = 80
# Main's devices that are the desk's own: its mix chain (bypassed while a monitor track plays), the capture that
# sends Live's sound to the page, and the spectrum's meter.
RAILED_ON_MAIN = (*monitor_tracks.MAIN_DEVICES, *coderun.ONLY_ON_MAIN)
FAILED = 502  # a step failed in Live after the checks passed: part of the batch may be done


class StepFailed(RuntimeError):
    """A step that passed the checks did not work in Live."""


@dataclass
class Step:
    """One step of a batch, as checked. `n` counts from 1, as the problems name it."""

    n: int
    op: str  # "set", "add", "move", "use"; from live.propose only (zpkt.app.propose): "remove", "track", "code"
    track: str  # the track the step is on; track: the new track's name; code, use: ""
    words: str  # the step as the reply names it: set "Kick bus/volume"
    key: str = ""  # set: the state key
    to: float = 0.0  # set: the raw value; move: the index
    device: str = ""  # add: the browser's name; move, remove: the device's label on the chain; set: its label, "" for a mixer value
    at: int | None = None  # add: the index asked for
    later: bool = False  # set: on a device or a track this batch makes, so it is checked when its step comes
    kind: str = ""  # track: audio, midi or return
    code: str = ""  # code: the Python for Live
    does: str = ""  # code: the sentence that says what it does
    name: str = ""  # code: the name it would be kept under as an ability (zpkt.app.abilities); use: the ability
    params: abilities.Params = field(default_factory=dict)  # code, use: the declared parameters
    args: dict[str, Any] = field(default_factory=dict)  # code, use: this run's values for them
    program: str = ""  # code, use: the text of the one call to Live, once checked (zpkt.app.coderun)
    uses: list[str] = field(default_factory=list)  # code, use: the abilities sent along with it
    reads: bool = False  # code, use: it only reads, and so does all it uses


# ---- reading the ask -----------------------------------------------------------------------------------------------


def _text(step: dict[str, Any], name: str) -> str | None:
    value = step.get(name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _index(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or value != int(value) or value < 0:
        return None
    return int(value)


def read_step(n: int, step: Any) -> Step | str:
    """One step as a Step, or what is wrong with its shape."""
    if not isinstance(step, dict):
        return 'a step is an object: {"set": key, "to": number}, {"add": device, "track": name}, ...'
    kinds = [k for k in ("set", "add", "device", "move", "use") if k in step]
    if len(kinds) != 1:
        return 'a step has exactly one of "set", "add", "device", "move" or "use"'
    kind = kinds[0]
    name = _text(step, kind)
    if name is None:
        return f'"{kind}" must be text'
    if kind == "use":
        if not abilities.NAME.match(name):
            return f'use "{name}": an ability\'s name is {abilities.NAME_RULE} (without "{abilities.TOOL_PREFIX}")'
        args = step.get("args")
        if args is not None and not isinstance(args, dict):
            return f'use "{name}": "args" is an object, a value for each of its parameters'
        return Step(n, "use", "", f'use "{name}"', name=name, args=dict(args or {}))
    if kind == "set":
        to = step.get("to")
        if isinstance(to, bool):
            to = float(to)
        if not isinstance(to, int | float) or not math.isfinite(float(to)):
            return f'set "{name}" needs "to": the raw number, as read_state gives it (r)'
        on = name.partition("/")[0]
        if "/" not in name or not on:
            return f'"{name}" is not a state key: it is TRACK/VALUE, such as "Kick bus/volume"'
        device = page_layout.key_parts(name).get("device", "")
        return Step(n, "set", on, f'set "{name}"', key=name, to=float(to), device=device)
    track = _text(step, "track")
    if track is None:
        return f'{kind} "{name}" needs "track": the track\'s name'
    if kind == "device":
        if not isinstance(step.get("on"), bool):
            return f'device "{name}" needs "on": true or false'
        key = live_keys.device_key(track, name, "Device On")
        words = f'switch "{name}" on "{track}" {"on" if step["on"] else "off"}'
        return Step(n, "set", track, words, key=key, to=1.0 if step["on"] else 0.0, device=name)
    if kind == "add":
        at = None
        if step.get("at") is not None:
            at = _index(step["at"])
            if at is None:
                return f'add "{name}": "at" is an index in the chain, 0 for first; leave it out for last'
        return Step(n, "add", track, f'add "{name}" on "{track}"', device=name, at=at)
    to = _index(step.get("to"))
    if to is None:
        return f'move "{name}" needs "to": the index in the chain it should end at, 0 for first'
    return Step(n, "move", track, f'move "{name}" on "{track}"', device=name, to=to)


def read(args: Any, reader: Callable[[int, Any], Step | str] = read_step) -> tuple[str, list[Step], list[str]]:
    """(why, the steps that have a shape, the problems so far). BadRequest when there is no batch to look at.
    `reader` reads one step (live.propose has its own, which knows three more kinds)."""
    why = args.get("why")
    steps = args.get("steps")
    if not isinstance(steps, list) or not steps:
        raise BadRequest(
            'the body needs "steps", a list of steps such as {"set": "Kick bus/volume", "to": 0.8}, and "why", a '
            "few words for the History row"
        )
    problems: list[str] = []
    if not isinstance(why, str) or not why.strip():
        problems.append('"why" is missing: a few words for the History row, such as "warmer kick"')
    if len(steps) > MAX_STEPS:
        problems.append(f"{len(steps)} steps is more than {MAX_STEPS}: send the rest as a second batch")
    out: list[Step] = []
    for n, raw in enumerate(steps[:MAX_STEPS], start=1):
        got = reader(n, raw)
        if isinstance(got, str):
            problems.append(f"step {n}: {got}")
        else:
            out.append(got)
    adds = sum(1 for s in out if s.op == "add")
    if adds > MAX_ADDS:
        problems.append(f"{adds} devices added is more than {MAX_ADDS} in one batch: send the rest as a second batch")
    uses = sum(1 for s in out if s.op == "use")
    if uses > MAX_USES:
        problems.append(f"{uses} abilities used is more than {MAX_USES} in one batch: send the rest as a second batch")
    return " ".join(str(why or "").split())[:WHY_MAX], out, problems


# ---- the rails -----------------------------------------------------------------------------------------------------


def base_name(label: str) -> str:
    """A device label without its count: "Saturator#2" is a "Saturator"."""
    name, hash_, nth = label.rpartition("#")
    return name if hash_ and nth.isdigit() else label


def railed(step: Step) -> str | None:
    """Why the rails hold this step, or None. A code step is not looked at here: zpkt.app.propose screens it."""
    if step.op in ("code", "use"):
        return None
    if step.op == "track":
        if step.track.casefold().startswith(monitor_tracks.PREFIX):
            return (
                f'a new track cannot be named "{step.track}": "mon ..." names a monitor track, and those are the app\'s'
            )
        if live_tracks.is_main(step.track):
            return f'a new track cannot be named "{step.track}": that names the master track'
        return None
    if step.track.startswith(monitor_tracks.PREFIX):
        return f'"{step.track}" is a monitor track: the app never changes those'
    if live_tracks.is_main(step.track):
        if step.op in ("add", "move", "remove"):
            return "no device is added to, moved on or removed from Main: its chain is the desk's own"
        if base_name(step.device) in RAILED_ON_MAIN:
            return f'"{step.device}" on Main is one of the desk\'s own devices: the app never changes those'
    return None


# ---- checking against Live ----------------------------------------------------------------------------------------


def resolve(names: list[str], label: str) -> int | None:
    """The index a device label names in a chain: the first of that name, or NAME#N the Nth (as state keys do)."""
    found = [k for k, n in enumerate(names) if n == label]
    if found:
        return found[0]
    name, hash_, nth = label.rpartition("#")
    if hash_ and nth.isdigit() and int(nth) >= 1:
        found = [k for k, n in enumerate(names) if n == name]
        if len(found) >= int(nth):
            return found[int(nth) - 1]
    return None


def label_at(names: list[str], index: int) -> str:
    """The label state keys give the device at `index`: its name, with #N for the Nth of that name."""
    return live_keys.device_label(names[index], names[: index + 1].count(names[index]))


def _g(x: float) -> str:
    return f"{x:g}"


def value_problem(d: Description, to: float) -> str | None:
    """Why `to` cannot be written to the value `d` describes, or None."""
    now = f'it shows "{d["now"][0]}" now, raw {_g(float(d["now"][1]))}'
    if not d["enabled"]:
        return "Live has this parameter switched off (something else controls it), so it cannot be set"
    lo, hi = d["min"], d["max"]
    if not lo - 1e-6 <= to <= hi + 1e-6:
        return f"{_g(to)} is outside its range, {_g(lo)} to {_g(hi)} ({now})"
    if d["kind"] != "continuous" and not math.isclose(to, round(to), abs_tol=1e-6):
        items = ", ".join(f"{_g(lo + k)} = {item}" for k, item in enumerate(d["items"][:12]))
        return f"{_g(to)} is between two steps: it takes whole numbers from {_g(lo)} to {_g(hi)} ({items or now})"
    return None


def check(desk: Desk, steps: list[Step]) -> tuple[list[str], dict[str, Description]]:
    """The problems Live's own names and ranges give, and the descriptions of the values to be set. A few short
    reads: the chains of the tracks named, the browser for each effect, the values' ranges. The steps are walked in
    order on a picture of the chains, so a step may rely on a device or a track an earlier step makes, and may not
    name a device an earlier step removes. A code step and a `use` step are passed over on that picture: nothing
    here can say what they will do, so no later step may rely on them. They are made ready to send (`ready`)."""
    problems: list[str] = []
    live_steps = []
    library = desk.abilities.library() if any(s.op in ("code", "use") for s in steps) else {}
    for s in steps:
        why = railed(s) or (ready(s, library) if s.op in ("code", "use") else None)
        if why:
            problems.append(f"step {s.n} ({s.words}): {why}")
        elif s.op not in ("code", "use"):
            live_steps.append(s)
    with_chain = [s for s in live_steps if s.op != "set" or s.device]
    chains = chain.look(desk.conn, [s.track for s in with_chain])
    has = chain.has_effect(desk.conn, [s.device for s in live_steps if s.op == "add"])
    sim: dict[str, list[tuple[str, bool]]] = {
        t: [(n, False) for n in names] for t, names in chains.items() if names is not None
    }
    made: set[str] = set()  # the tracks this batch makes, once their step has come
    to_describe: list[Step] = []
    for s in live_steps:

        def bad(why: str, s: Step = s) -> None:
            problems.append(f"step {s.n} ({s.words}): {why}")

        if s.op == "track":
            if s.track in sim:
                bad(f'the set already has a track or return named "{s.track}": a second one could not be told apart')
            else:
                sim[s.track] = []
                made.add(s.track)
            continue
        if s.op == "set" and not s.device:
            to = live_keys.send_return(page_layout.key_parts(s.key)["param"])  # a send: the return it goes to
            if s.track in made or to in made:
                s.later = True  # on, or to, a track this batch makes: Live cannot say its range yet
            else:
                to_describe.append(s)
            continue
        if s.track not in sim:
            bad(f'the set has no track, return or Main named "{s.track}"')
            continue
        line = sim[s.track]
        names = [n for n, _ in line]
        on_chain = ", ".join(label_at(names, k) for k in range(len(names))) or "no devices"
        if s.op == "add":
            if not has.get(s.device):
                bad(f'Live\'s browser has no audio effect called "{s.device}" (give the name as the browser shows it)')
            elif s.at is not None and s.at > len(line):
                bad(
                    f'"at" {s.at} is past the end: "{s.track}" has {len(line)} devices ({on_chain}), so at most {len(line)}'
                )
            else:
                line.insert(len(line) if s.at is None else s.at, (s.device, True))
            continue
        index = resolve(names, s.device)
        if index is None:
            bad(f'"{s.track}" has no device "{s.device}"; it has: {on_chain}')
        elif s.op == "remove":
            line.pop(index)
        elif s.op == "move":
            if s.to >= len(line):
                bad(
                    f'"to" {int(s.to)} is past the end: "{s.track}" has {len(line)} devices, so at most {len(line) - 1}'
                )
            else:
                line.insert(int(s.to), line.pop(index))
        elif line[index][1]:
            s.later = True  # on a device this batch adds: Live cannot say its range yet
        else:
            to_describe.append(s)
    found, missing = describe.look(desk.conn, [s.key for s in to_describe])
    for s in to_describe:
        if s.key in missing:
            problems.append(f"step {s.n} ({s.words}): {missing[s.key]}")
        elif why := value_problem(found[s.key], s.to):
            problems.append(f"step {s.n} ({s.words}): {why}")
    problems.sort(key=lambda p: int(p.split()[1].rstrip(":")))
    return problems, found


def ready(s: Step, library: dict[str, dict[str, Any]]) -> str | None:
    """Make a code step or a `use` step ready to send (its `program`, what it `uses`, whether it only `reads`), or
    say why it cannot be. A `use` step takes its code and parameters from the ability it names."""
    if s.op == "use":
        a = library.get(s.name)
        if a is None:
            have = ", ".join(sorted(library)) or "none yet"
            return f'there is no ability "{s.name}" (the abilities: {have}). Propose its code with propose_live'
        if why := abilities.args_problem(a["params"], s.args):
            return why
        s.args = abilities.typed(a["params"], s.args)
        if why := coderun.screened_args(s.args):
            return why
        s.code, s.does, s.params = a["code"], a["does"], a["params"]
        s.words = f"use {abilities.call_words(s.name, s.args)}"
    made = coderun.prepare(s.code, s.args, library, top=s.name)
    if isinstance(made, str):
        return made
    s.program, s.uses, s.reads = made.program, made.uses, made.reads
    return None


# ---- running -------------------------------------------------------------------------------------------------------


@dataclass
class Batch:
    """A batch while it runs: its History entry, and what its reply will say."""

    entry: dict[str, Any]
    added: list[dict[str, Any]] = field(default_factory=list)  # the devices added: {"track", "device", "at"}
    extra: dict[str, Any] = field(default_factory=dict)  # what another kind of step puts in the reply


# How one kind of step is run: it does the step in Live and records it in the batch's entry, or raises StepFailed.
Runner = Callable[["Desk", Batch, Step], None]


def _set(desk: Desk, batch: Batch, s: Step, d: Description | None) -> None:
    entry = batch.entry
    if d is None:  # a value on a device or a track this batch made
        found, missing = describe.look(desk.conn, [s.key])
        if s.key in missing:
            raise StepFailed(missing[s.key])
        d = found[s.key]
        if why := value_problem(d, s.to):
            raise StepFailed(why)
    before = [d["now"][0], d["now"][1]]
    recorded = next((m for m in entry["moves"] if m["key"] == s.key), None)
    if recorded is not None:
        before = recorded["to"]
    if same(before[1], s.to):
        return
    desk.history.expect_writes([[s.key, s.to]])
    if desk.write_anywhere([[s.key, s.to]]):
        raise StepFailed("Live did not take the value")
    desk.history.change_value(entry, s.key, before, s.to)


def _add(desk: Desk, batch: Batch, s: Step) -> None:
    entry, added = batch.entry, batch.added
    before, after = chain.load_effect(desk.conn, s.track, s.device)
    index = chain.landed(before, after)
    name = after[index]
    desk.history.change_device(entry, {"op": "add", "track": s.track, "device": name, "load": s.device, "at": index})
    added.append({"track": s.track, "device": label_at(after, index), "at": index})
    if s.at is not None and s.at != index:
        now = chain.move(desk.conn, s.track, index, s.at)
        if now != index:
            desk.history.change_device(
                entry, {"op": "move", "track": s.track, "device": name, "from": index, "to": now}
            )
            names = chain.names(desk.conn, s.track)
            added[-1].update(device=label_at(names, now), at=now)
        if now != s.at:
            raise StepFailed(f"the device is on the track, but Live put it at index {now}, not {s.at}")


def _move_step(desk: Desk, batch: Batch, s: Step) -> None:
    names = chain.names(desk.conn, s.track)
    index = resolve(names, s.device)
    if index is None:
        raise StepFailed(f'"{s.track}" has no device "{s.device}" any more')
    now = chain.move(desk.conn, s.track, index, int(s.to))
    if now != index:
        desk.history.change_device(
            batch.entry, {"op": "move", "track": s.track, "device": names[index], "from": index, "to": now}
        )
    if now != int(s.to):
        raise StepFailed(f"Live put the device at index {now}, not {int(s.to)}")


def _code(desk: Desk, batch: Batch, s: Step) -> None:
    """Send a code step, or the code of the ability a `use` step names: one call. It is kept in the entry as
    something undo leaves, as soon as it was sent, also when Live reported an error (part of it may have run).
    An ability that only reads leaves nothing in the entry."""
    used = s.op == "use"
    words = f"Ran {abilities.call_words(s.name, s.args)}" if used else s.does
    kept: dict[str, Any] = {"op": "code", "does": s.does, "code": s.code, "words": words}
    for key, value in (("args", s.args), ("uses", s.uses), ("ability", s.name if used else "")):
        if value:
            kept[key] = value
    broken = {**kept, "failed": True, "words": f"{words} (Live reported an error: part of it may have run)"}
    record = not (used and s.reads)
    try:
        res = desk.conn.execute(s.program)
    except (LiveError, OSError):
        if record:
            desk.history.change_stays(batch.entry, broken)  # sent, and no answer: it may have run
        raise
    ok = res.status == "ok"
    if used:
        desk.abilities.ran(s.name)
    if record:
        desk.history.change_stays(batch.entry, kept if ok else broken)
    told = {"step": s.n, "ok": ok, "result": coderun.brief(res.result)}
    batch.extra.setdefault("ran", []).append({**told, "ability": s.name} if used else told)
    if not ok:
        may = ", and part of the code may have run" if record else ""
        raise StepFailed(f"Live reported an error{may}: {res.error or 'no message'}")


# "code" is here for live.propose (zpkt.app.propose): the reader of live.change never lets a code step in.
RUNNERS: dict[str, Runner] = {"add": _add, "move": _move_step, "use": _code, "code": _code}


def count_words(entry: dict[str, Any]) -> str:
    """ "3 controls, 1 device": what a batch's entry holds that undo takes back. The page's History row says the
    same."""
    controls = len(entry.get("moves", []))
    devices = len({(d["track"], d["device"]) for d in entry.get("devices", [])})
    parts = [f"{controls} control{'' if controls == 1 else 's'}"] if controls else []
    parts += [f"{devices} device{'' if devices == 1 else 's'}"] if devices else []
    return ", ".join(parts) or "nothing"


def refused(problems: list[str], what: str = "batch") -> Reply:
    """The 400 of a batch that did not pass its checks: nothing has changed."""
    return 400, {
        "error": f"the {what} was not run: nothing changed. Fix every problem below and send the whole {what} again",
        "problems": problems,
    }


def run(
    desk: Desk,
    cmd: Command,
    why: str,
    steps: list[Step],
    found: dict[str, Description],
    kind: str = KIND,
    runners: Mapping[str, Runner] = RUNNERS,
) -> Reply:
    """Run a batch that passed its checks: save a version, run the steps in order (each its own short call, by its
    kind's runner), stop at the first that fails, and answer small. One History entry, whatever was done."""
    todo = any(
        (s.op == "use" and not s.reads)  # an ability that only reads needs no version before it
        or s.op not in ("set", "use")
        or (s.op == "set" and (s.later or not same(found[s.key]["now"][1], s.to)))
        for s in steps
    )
    batch = Batch(desk.history.new_change(cmd.who, why, cmd.group))
    entry = batch.entry
    done, failed = 0, None
    if todo or any(s.op == "use" for s in steps):
        if todo:
            desk.monitor.leave_pin()  # a change made while the Pin is heard starts from Now
            desk.version_before(cmd.group or kind)
        for s in steps:
            try:
                if s.op == "set":
                    _set(desk, batch, s, None if s.later else found[s.key])
                else:
                    runners[s.op](desk, batch, s)
            except (StepFailed, chain.ChainError, LiveError, OSError) as exc:
                failed = {"step": s.n, "what": s.words, "why": str(exc)[:300]}
                break
            done += 1
    else:
        done = len(steps)
    wrote = [m["key"] for m in entry["moves"]]
    shown: dict[str, list[Any]] = {}
    try:
        got, _ = describe.look(desk.conn, wrote)
        shown = {k: [d["now"][0], d["now"][1]] for k, d in got.items()}
    except (LiveError, OSError):  # the values are written; only their shown texts are not known
        pass
    asked = {s.key for s in steps[:done] if s.op == "set"}
    now = {k: shown.get(k) or list(m["to"]) for m in entry["moves"] if (k := m["key"]) in asked}
    kept = desk.history.change_done(entry, shown)
    if entry["devices"] or entry.get("stays"):
        with desk.lock:
            desk.descriptions.clear()  # a chain changed: a kept range may belong to another device now
    desk.history.flush_changes()
    desk.push(desk.history.view())
    desk.push_app(desk.monitor.message())
    reply: dict[str, Any] = {
        "ok": failed is None,
        "done": done,
        "undo": f"{why} ({count_words(kept)})" if kept and (kept["moves"] or kept["devices"]) else None,
        "now": now,
        "added": batch.added,
        **batch.extra,
    }
    if left := left_by(kept):
        reply["no_undo"] = left
    if failed is None:
        return 200, reply
    reply["error"] = (
        f"step {failed['step']} ({failed['what']}) failed in Live: {failed['why']}. The {done} step(s) before it "
        f"are done and are one step in History; step {failed['step']} and the {len(steps) - done - 1} after it "
        "were not run"
    )
    reply["failed"] = failed
    reply["not_done"] = [s.n for s in steps[done:]]
    return FAILED, reply


def live_change(desk: Desk, cmd: Command) -> Reply:
    """Check the batch whole, save a version, run the steps in order, answer small."""
    why, steps, problems = read(cmd.args)
    found: dict[str, Description] = {}
    if steps:
        more, found = check(desk, steps)
        problems += more
    if problems:
        return refused(problems)
    return run(desk, cmd, why, steps, found)


# ---- undo, redo, going back ----------------------------------------------------------------------------------------


def run_devices(desk: Desk, steps: list[dict[str, Any]]) -> list[str]:
    """Run an entry's device steps in Live, in order, each a short call. Returns what could not be done, in words:
    a device that is no longer there is passed over, since the rest of an undo is still worth doing."""
    notes: list[str] = []
    for s in steps:
        track, name = s["track"], s["device"]
        try:
            if s["op"] == "add":
                chain.add(desk.conn, track, s.get("load") or name, s.get("at"))
            elif s["op"] == "remove":
                if not chain.delete(desk.conn, track, int(s["at"]), name):
                    notes.append(f'"{track}" has no "{name}" to take off')
            else:
                index = chain.index_of(chain.names(desk.conn, track), name, int(s["from"]))
                if index is None:
                    notes.append(f'"{track}" has no "{name}" to move back')
                else:
                    chain.move(desk.conn, track, index, int(s["to"]))
        except chain.ChainError as exc:
            notes.append(str(exc))
    return notes


def replay(desk: Desk, pairs: list[list[Any]], steps: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Write `pairs` and run the device `steps` of a history step (an undo, a redo, a going back), in the order that
    reaches every value: a value of a device that is about to go is written first, one of a device that is about
    to come is written after. Returns (the keys Live did not take, what a device step could not do)."""
    adds = any(s["op"] == "add" for s in steps)
    others = any(s["op"] != "add" for s in steps)
    missing: list[str] = []
    if pairs and (others or not adds):
        missing = desk.write_anywhere(pairs)
    notes = run_devices(desk, steps)
    if pairs and adds:
        missing = desk.write_anywhere(pairs)
    if steps:
        with desk.lock:
            desk.descriptions.clear()
    return missing, notes


def register(bus: Bus, desk: Desk) -> None:
    """Put live.change on the bus. It checks first and saves its own version, so a refused batch leaves nothing."""

    def run(cmd: Command) -> Reply:
        return live_change(desk, cmd)

    effects.register(bus, KIND, run, touches_live=True, checks_first=True)
