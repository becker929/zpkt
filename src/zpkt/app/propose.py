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

Code runs as `live.run` does (zpkt.app.jobs): one call, under the bus's lock, with `args` defined in front of it
(zpkt.app.coderun).

Abilities (zpkt.app.abilities) start here. A code step may say what makes it reusable: "name", "params" and "args"
(this run's values; in the code they are the dict `args`). The card then offers a third answer, "Always": the
gate sends `live.propose` with `always`, the batch runs as after "Do it", and each code step that ran without an
error is kept as an ability under its name (a step with no name gets one made from `does`, which never takes an
ability's place). The same name as an ability means a replacement: the card says so, and it happens only after
"Always". More is checked for such steps, and refused before anybody is asked: arguments that do not fit the
parameters, a parameter that is declared and never read, a `use("x", ...)` of an ability that is not there, a
circle, a chain deeper than 5. `hints` (an ability that already looks like this one; a track or device of the set
spelled out in code with no text parameter) go to the agent in the reply and never onto the card.

Three more commands: `ability.run` runs one with new arguments and no card (an agent may: the "Always" was the
word; code that only reads leaves no History row), `ability.list` lists them, `ability.remove` takes one away at
once and is the person's only. A `use` step of a batch (`live.change` too) runs one in its place among the steps.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Any

from zpkt.app import abilities, change, coderun, effects, jobs
from zpkt.app.bus import Bus, Command, Reply
from zpkt.app.change import Batch, Step, StepFailed
from zpkt.live import chain, describe, newtrack, page_layout
from zpkt.live.describe import Description
from zpkt.live.inlive import keys as live_keys
from zpkt.live.transport import LiveError

if TYPE_CHECKING:
    from zpkt.app.desk import Desk

KIND = "live.propose"
CHECK = "live.propose.check"
RUN, LIST, REMOVE = "ability.run", "ability.list", "ability.remove"
PEOPLE = ("you", "cli")  # who may take an ability away: the person, at the page or the command line. Never an agent
MAX_CODE = 3  # code steps in one batch: each is read by a person on a phone
CODE_MAX = 2000  # characters of one code step
DOES_MAX = 140  # characters of the sentence that says what the code does
MAX_TRACKS = 8
NAME_MAX = 40  # characters of a new track's name
OWN_KINDS = ("remove", "new_track", "code")
STEP_KINDS = ("set", "add", "device", "move", "use", *OWN_KINDS)
NO_UNDO = ("remove", "track", "code")  # the ops undo does not take back (and a `use` of an ability that changes Live)
ONLY_ON_MAIN = coderun.ONLY_ON_MAIN  # the devices that are only the desk's own on Main: code may not name them


# ---- reading the ask -----------------------------------------------------------------------------------------------


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
    tree = coderun.parsed(value)
    if isinstance(tree, str):
        return f"{words} {tree}" if tree.startswith("is not") else f"{words}: {tree}"
    # what makes it reusable: a name, its parameters, and this run's values for them (`args` in the code)
    kept_as = step.get("name")
    if kept_as is not None and (not isinstance(kept_as, str) or not abilities.NAME.match(kept_as)):
        return f'{words}: "name" is {abilities.NAME_RULE}'
    params = abilities.read_params(step.get("params"))
    if isinstance(params, str):
        return f"{words}: {params}"
    args = step.get("args")
    if why := abilities.args_problem(params, args):
        return f"{words}: {why}"
    values = abilities.typed(params, args or {})
    if why := coderun.screened_args(values):
        return f"{words}: {why}"
    unused = [name for name in params if name not in abilities.reads(tree)]
    if unused:
        return (
            f"{words}: {', '.join(unused)} is declared but not used: the code never reads "
            f'args["{unused[0]}"]. Read every parameter from `args`, or do not declare it'
        )
    return Step(n, "code", "", words, code=value, does=does, name=kept_as or "", params=params, args=values)


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


def name_code(steps: list[Step], have: list[str]) -> list[str]:
    """Give every code step the name it would be kept under as an ability: its own, or one made from `does` that
    no ability and no other step has (so a made-up name never takes an ability's place). Returns the problems."""
    problems = []
    taken = {*have, *(s.name for s in steps if s.op == "code" and s.name)}
    seen: set[str] = set()
    for s in steps:
        if s.op != "code":
            continue
        if not s.name:
            s.name = abilities.free_name(abilities.slug(s.does), taken)
            taken.add(s.name)
        elif s.name in seen:
            problems.append(f'step {s.n} ({s.words}): another code step of this batch is also named "{s.name}"')
        seen.add(s.name)
    return problems


def checked(desk: Desk, args: Any) -> tuple[str, list[Step], dict[str, Description], list[str]]:
    """The batch read and checked whole: (why, steps, the descriptions of the values to be set, every problem)."""
    why, steps, problems = read(args)
    found: dict[str, Description] = {}
    if steps:
        problems += name_code(steps, desk.abilities.names())
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
    if s.op == "use":
        return f"Run {abilities.call_words(s.name, s.args)}"
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
    """The steps as the chat's card shows them: {"n", "text"}, with "no_undo" for a step undo cannot take back. A
    code step also has "code", "name" (what "Always" would keep it as), "args" (this run's [parameter, value]
    pairs) and "replaces" when an ability has that name already. One short read gives the values as Live would
    show them; without it, the raw numbers."""
    links = abilities.graph(desk.abilities.all())
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
        if s.op in NO_UNDO or (s.op == "use" and not s.reads):
            row["no_undo"] = True
        if s.op == "code":
            row.update(code=s.code, name=s.name, args=[[k, v] for k, v in s.args.items()])
            if named := abilities.used(s.code):
                row["uses"] = named
            if s.name in links:  # "Always" would put it in that ability's place, for everything that uses it
                row.update(replaces=True, used_by=len(links[s.name]["used_by"]))
        out.append(row)
    return out


def may_keep(desk: Desk, steps: list[Step]) -> bool:
    """May "Always" be offered: the batch has code, and there is room for what it would add."""
    names = {s.name for s in steps if s.op == "code"}
    have = set(desk.abilities.names())
    return bool(names) and len(have | names) <= abilities.MAX


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


RUNNERS: dict[str, change.Runner] = {**change.RUNNERS, "remove": _remove, "track": _track}


# ---- the two commands ----------------------------------------------------------------------------------------------


def propose_check(desk: Desk, cmd: Command) -> Reply:
    """Check the batch whole and answer with its card. Nothing changes; a batch with a problem gets no card."""
    if desk.bus.guard is not None:
        desk.bus.guard.check()  # a read is not held to the set, but a card for the wrong set would be a lie
    why, steps, found, problems = checked(desk, cmd.args)
    if problems:
        return refused(problems, asked=False)
    reply = {"ok": True, "why": why, "steps": card(desk, steps, found), "always": may_keep(desk, steps)}
    if said := hints(desk, steps):
        reply["hints"] = said  # for the agent, after the tap: they are not on the card
    return 200, reply


def hints(desk: Desk, steps: list[Step]) -> list[str]:
    """What would make a code step a better ability, for the agent: an ability that already looks like it, and a
    track or device of the open set spelled out in code that has no text parameter. Nothing is refused for these."""
    coded = [s for s in steps if s.op == "code"]
    if not coded:
        return []
    have = desk.abilities.all()
    known = {a["name"] for a in have}
    out: list[str] = []
    names: dict[str, list[str]] | None = None
    for s in coded:
        other = abilities.near(s.name, s.does, have) if s.name not in known else None
        if other:
            out.append(
                f'step {s.n}: the ability "{other}" looks like this one. If it fits, call '
                f'{abilities.TOOL_PREFIX}{other}; if it almost fits, propose "{other}" again under the same name '
                "with a broader parameter, rather than keeping a second one"
            )
        if any(p["type"] == "string" for p in s.params.values()):
            continue
        spelled = coderun.literals(ast.parse(s.code))
        if spelled and names is None:
            try:
                names = chain.set_names(desk.conn)
            except (LiveError, OSError, ValueError):
                names = {}
        hit = next(((t, k) for t in spelled for k in ("track", "device") if t in (names or {}).get(k, ())), None)
        if hit:
            out.append(
                f'step {s.n}: the code spells out "{hit[0]}", a {hit[1]} of this set, and has no text parameter. '
                f'Make what could differ next time a parameter (args["{hit[1]}"]) and name the step for what it '
                "does in general, so that one ability serves every such case"
            )
    return out


def keep(desk: Desk, cmd: Command, steps: list[Step], reply: dict[str, Any]) -> None:
    """The person said "Always": keep each code step that ran without an error as an ability, and say in the reply
    which were kept ("abilities") and which were not, and why ("not_saved")."""
    ran = {r["step"]: r["ok"] for r in reply.get("ran", [])}
    session = (cmd.group or "").removeprefix("ask-") if (cmd.group or "").startswith("ask-") else ""
    saved, left = [], []
    for s in steps:
        if s.op != "code":
            continue
        if not ran.get(s.n):
            left.append({"name": s.name, "why": "Live reported an error" if s.n in ran else "it did not run"})
            continue
        try:
            _, replaced = desk.abilities.save(s.name, s.does, s.params, s.code, session)
        except abilities.Full as exc:
            left.append({"name": s.name, "why": str(exc)})
            continue
        saved.append({"name": s.name, "replaced": replaced})
    reply["abilities"], reply["not_saved"] = saved, left


def live_propose(desk: Desk, cmd: Command) -> Reply:
    """Run a batch the person said yes to: check it whole again, save a version, run the steps in order. With
    "always" (the gate sets it after that tap; an agent cannot), the code steps that ran are kept as abilities."""
    why, steps, found, problems = checked(desk, cmd.args)
    if problems:
        return refused(problems, asked=True)
    said = hints(desk, steps)
    code, reply = change.run(desk, cmd, why, steps, found, KIND, RUNNERS)
    reply.setdefault("no_undo", [])
    if cmd.args.get("always") is True:
        keep(desk, cmd, steps, reply)
    if said:
        reply["hints"] = said
    return code, reply


# ---- abilities: code steps kept for good, run again with new arguments (zpkt.app.abilities) ----------------------


def listing(desk: Desk) -> list[dict[str, Any]]:
    """Every ability as the list gives it: the file's fields, what it "uses" and is "used_by", what it uses that
    is "missing" (it is broken until that is proposed again), and whether it only "reads"."""
    found = desk.abilities.all()
    links = abilities.graph(found)
    library = {a["name"]: a for a in found}
    out = []
    for a in found:
        made = coderun.prepare(a["code"], {}, library, top=a["name"])
        out.append({**a, **links[a["name"]], "reads": not isinstance(made, str) and made.reads})
    return out


def ability_list(desk: Desk, cmd: Command) -> Reply:
    """Every ability, with its code: what an agent may run on its own now."""
    return 200, {"ok": True, "abilities": listing(desk), "max": abilities.MAX}


def ability_remove(desk: Desk, cmd: Command) -> Reply:
    """Take an ability away, at once: {"name"}. The person's only. The reply names the abilities that used it:
    they are broken until it is proposed again."""
    name = cmd.args.get("name")
    users = abilities.graph(desk.abilities.all()).get(str(name), {}).get("used_by", [])
    if not desk.abilities.remove(name):
        return 404, {"ok": False, "error": f"there is no ability {name!r}"}
    return 200, {"ok": True, "removed": name, "broken": users}


def ability_run(desk: Desk, cmd: Command) -> Reply:
    """Run an ability: {"name", "args"}. No card and no wait: the person's "Always" is the standing yes. The same
    checks as a `use` step of a batch (the ability is there, with everything it uses; the arguments fit; the
    rails), then one call to Live. Code that changes something is one History row with a version before it, and
    undo does not take it back; code that only reads leaves no row and no version."""
    name = cmd.args.get("name")
    args = cmd.args.get("args")
    if not isinstance(name, str) or (args is not None and not isinstance(args, dict)):
        return 400, {"ok": False, "error": 'the body needs "name", an ability, and "args", an object'}
    if desk.abilities.get(name) is None:
        return 404, {
            "ok": False,
            "error": f'there is no ability "{name}" any more: the person removed it, or it was never kept. Nothing '
            "ran. If it is still needed, propose its code again with propose_live.",
        }
    step = Step(1, "use", "", f'use "{name}"', name=name, args=dict(args or {}))
    if why := change.ready(step, desk.abilities.library()):
        return 400, {"ok": False, "name": name, "error": f"{name} was not run, and nothing changed: {why}"}
    words = abilities.call_words(name, step.args)[: change.WHY_MAX]
    code, reply = change.run(desk, cmd, words, [step], {}, RUN, RUNNERS)
    ran = reply.get("ran") or []
    if code == 200:
        told = {"ok": True, "name": name, "result": ran[0]["result"] if ran else None}
        return 200, told if step.reads else {**told, "no_undo": reply.get("no_undo", [])}
    failed = reply.get("failed") or {}
    return code, {"ok": False, "name": name, "error": str(failed.get("why") or reply.get("error") or "it failed")}


def register(bus: Bus, desk: Desk) -> None:
    """Put the commands on the bus. Running a proposal is for the API's callers (zpkt.app.jobs), as running code
    is: the web page may not. An agent's needs your word, which the Ask gate gives after the tap. Running an
    ability is the one of these an agent may ask for on its own (zpkt.app.effects, AGENT_MAY): your "Always" was
    the word. Taking one away is yours only."""

    def check(cmd: Command) -> Reply:
        return propose_check(desk, cmd)

    def run(cmd: Command) -> Reply:
        return live_propose(desk, cmd)

    effects.register(bus, CHECK, check, touches_live=True)
    effects.register(bus, KIND, run, touches_live=True, checks_first=True, callers=jobs.API_CALLERS)
    effects.register(bus, LIST, lambda cmd: ability_list(desk, cmd))
    effects.register(bus, REMOVE, lambda cmd: ability_remove(desk, cmd), callers=PEOPLE)
    effects.register(
        bus, RUN, lambda cmd: ability_run(desk, cmd), touches_live=True, checks_first=True, callers=jobs.API_CALLERS
    )
