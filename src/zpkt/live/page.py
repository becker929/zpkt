"""A Page: at most 24 controls bound to values of the mix, in groups. One spec draws the same page on a phone, on a
desktop and on the MiniLab. An agent writes it ("I want to change the kick's sub and knock"); it holds no pixels.

    {"schema": 2, "title": "Kick: sub and knock", "made_by": "agent",
     "groups": [{"name": "Sub", "controls": [
         {"target": "Kick bus/desk EQ/1 Gain A", "role": "level", "weight": 3},
         {"target": "Kick bus/desk EQ/1 Frequency A", "role": "tone", "range": ["34 Hz", "42 Hz"]}]}]}

`target` is a state key (zpkt.live.inlive.keys). Name, range, unit and shown text come from Live
(zpkt.live.describe), never from the spec. The spec may say what a control is for (`role`), how much it matters
(`weight`, 1 to 3), a short `label`, and the stretch worth playing (`range`, as two shown texts or numbers). It may
not say widget, size, colour, position or MIDI slot: `widget` and `assign` decide those by rule, so every page looks
and maps the same way. `lint` is the gate: a page with an "error" is not shown, and the agent is told why.

A page may also carry compare states: 2 to 8 named settings of the same controls, one pad each, to switch between
while Live plays.

    "compare": {"name": "Kick", "states": [
        {"name": "as it is"},
        {"name": "hotter", "writes": [{"target": "Kick bus/volume", "to": 0.8}]}]}

A write's `to` is the raw value (what desk.state gives as `r`). A state that leaves a target out, or gives no writes
at all, takes the value that target had when the page was made (`fill` keeps them in `baseline`), so there is always
a way back; `fill` also keeps each target's range (`ranges`). Which pad is lit is never stored: a state is on exactly
when every one of its targets holds its value (`lit`).

lib/contracts/page.schema.json is generated from these models (hands/tools/gen_schemas.py). Unknown keys are kept, so
the file can grow. Pages live in <sets_dir>/pages/<set>/<id>.json.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from zpkt.live import config
from zpkt.live.changes import Who
from zpkt.live.describe import Description
from zpkt.live.inlive import shown

SCHEMA = 2  # version 1 is the mix desk's made surface (contrib/mixdesk/surfaces.py)
MAX_CONTROLS = 24
MAX_IN_GROUP = 6
MAX_LABEL = 10  # characters that fit under a knob on a phone
SEGMENTS = 5  # a choice of up to this many is a row of keys; more is a list
KNOBS, FADERS, PADS = 8, 4, 8  # the MiniLab 3
MIN_STATES, MAX_STATES = 2, PADS  # compare states: one pad each
MAX_COMPARE_TARGETS = 24  # the values one compare may write
COMPARE_STEP = 0.001  # a continuous value holds a state's value within this much of its range; a switch exactly

Role = Literal["level", "tone", "amount", "time", "switch", "choice"]
Widget = Literal["key", "segmented", "list", "fader", "knob", "macro"]


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")


class MacroPart(_Open):
    target: str = Field(description="A state key.")
    low: str | float = Field(description="Where this value sits when the macro is at its bottom (shown text or raw).")
    high: str | float = Field(description="Where it sits when the macro is at its top.")


class Control(_Open):
    target: str | None = Field(default=None, description="A state key. Left out only for a macro.")
    macro: list[MacroPart] | None = Field(default=None, description="Several values moved together by one knob.")
    role: Role | None = Field(default=None, description="What it is for. Inferred from Live when left out.")
    weight: int = Field(default=2, ge=1, le=3, description="How much it matters: 3 is drawn big and placed first.")
    label: str | None = Field(default=None, description="At most 10 characters. Live's name, shortened, if left out.")
    range: tuple[str | float, str | float] | None = Field(
        default=None, description='The stretch worth playing, as two shown texts ("34 Hz") or numbers.'
    )
    steps: int | None = Field(default=None, ge=2, le=9, description="With a range: make this many versions to hear.")

    @model_validator(mode="after")
    def _one_kind(self) -> Control:
        if (self.target is None) == (self.macro is None):
            raise ValueError("a control has a target or a macro, not both and not neither")
        if self.macro is not None and not self.label:
            raise ValueError("a macro needs a label: Live has no name for it")
        if self.macro is not None and len(self.macro) < 2:
            raise ValueError("a macro moves two or more values")
        return self

    @property
    def ref(self) -> str:
        """How lint and assign name this control: its target, or "macro:LABEL"."""
        return self.target if self.target is not None else f"macro:{self.label}"

    def targets(self) -> list[str]:
        return [self.target] if self.target is not None else [p.target for p in self.macro or []]


class Group(_Open):
    name: str
    controls: list[Control]


class Write(_Open):
    target: str = Field(description="A state key.")
    to: float | bool = Field(description="The raw value, as desk.state gives it (`r`).")


class CompareState(_Open):
    name: str = Field(description="At most 10 characters: it is written on a pad.")
    writes: list[Write] = Field(
        default_factory=list, description="Left out or short: the missing targets take the page's baseline."
    )


class Compare(_Open):
    """Named settings of the same controls, one pad each. Pressing a pad writes its state as one move."""

    name: str | None = Field(
        default=None, description="What is compared, in a word or two; the page's title if left out."
    )
    states: list[CompareState]
    baseline: dict[str, float | bool] = Field(
        default_factory=dict, description="Each target's raw value when the page was made. The app fills it in."
    )
    ranges: dict[str, tuple[float, float, bool]] = Field(
        default_factory=dict,
        description="Each target's lowest and highest raw value and whether it is a switch or a list. The app fills it in.",
    )

    def targets(self) -> list[str]:
        """Every state key a state writes, once each, in the order first named."""
        return list(dict.fromkeys(w.target for s in self.states for w in s.writes))


class Page(_Open):
    schema_: int = Field(default=SCHEMA, alias="schema", description="The file's version: 2.")
    id: str | None = Field(default=None, description="Its file name without .json; set when saved.")
    title: str
    groups: list[Group]
    made_by: Who = "you"
    at: str | None = Field(default=None, description="When it was made, YYYY-MM-DD HH:MM:SS.")
    prompt: str | None = Field(default=None, description="What was asked for.")
    compare: Compare | None = Field(default=None, description="States to switch between, one pad each.")

    def controls(self) -> list[Control]:
        return [c for g in self.groups for c in g.controls]

    def targets(self) -> list[str]:
        """Every state key the page moves, once each: its controls' in page order, then its compare states'."""
        mine = [t for c in self.controls() for t in c.targets()]
        return list(dict.fromkeys(mine + (self.compare.targets() if self.compare else [])))


class Problem(TypedDict):
    level: Literal["error", "note"]  # an error keeps the page from being shown; a note is told to the user
    where: str  # a control's ref, a group's name, or "page"
    text: str


class Slot(TypedDict):
    slot: str  # k1-k8 (knobs), f1-f4 (faders), b1-b8 (bank B pads)
    ref: str
    group: str


class StatePad(TypedDict):
    slot: str  # b1-b8
    state: int  # the compare state's place in the page's list, from 0
    name: str


class HardwarePage(TypedDict):
    groups: list[str]
    slots: list[Slot]
    compare: list[StatePad]  # the pads that switch compare states: the same on every MiniLab page of the Page


def parse(data: Any) -> Page:
    """A page from its JSON; ValueError naming the first thing wrong."""
    try:
        return Page.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = "/".join(str(p) for p in first["loc"]) or "the page"
        raise ValueError(f"not a page: {where}: {first['msg']}") from None


# ---- what Live's description decides ------------------------------------------------------------------------------

_LEVEL = re.compile(r"gain|volume|level|send|output|input|threshold|makeup", re.I)
_TONE = re.compile(r"freq|resonance|\bq\b|cutoff|tone|filter", re.I)
_TIME = re.compile(r"attack|release|decay|delay|time|\bhold\b", re.I)


def infer_role(d: Description) -> Role:
    """What a value is for, from what Live says about it: its kind, then its name, then its unit."""
    if d["kind"] == "switch":
        return "switch"
    if d["kind"] == "choice":
        return "choice"
    name, unit = d["name"], d["unit"].lower()
    for role, by_name, units in (
        ("tone", _TONE, ("hz", "khz")),
        ("level", _LEVEL, ("db",)),
        ("time", _TIME, ("ms", "s")),
    ):
        if by_name.search(name) or unit in units:
            return role  # type: ignore[return-value]  # one of Role's names
    return "amount"


def role_of(c: Control, d: Description | None) -> Role:
    """The control's role: the spec's when set and possible, else inferred. A switch or list is what Live says."""
    if c.macro is not None or d is None:
        return c.role or "amount"
    if d["kind"] != "continuous":
        return infer_role(d)
    return c.role if c.role in ("level", "tone", "amount", "time") else infer_role(d)


def widget(c: Control, d: Description | None) -> Widget:
    """The widget rule: a switch is a key, a short choice a row of keys, a long one a list, a level a fader,
    anything else a knob."""
    if c.macro is not None:
        return "macro"
    if d is None:
        return "knob"
    if d["kind"] == "switch":
        return "key"
    if d["kind"] == "choice":
        return "segmented" if (d["steps"] or 0) <= SEGMENTS else "list"
    return "fader" if role_of(c, d) == "level" else "knob"


_VOWELS = re.compile(r"(?<=\w)[aeiou](?=\w)", re.I)


def short_label(text: str, limit: int = MAX_LABEL) -> str:
    """A name that fits under a knob: as it is if it fits, else vowels inside words dropped from the last word
    back, else cut."""
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    words = text.split(" ")
    for i in range(len(words) - 1, -1, -1):
        words[i] = _VOWELS.sub("", words[i])
        if len(" ".join(words)) <= limit:
            return " ".join(words)
    return " ".join(words)[:limit].rstrip()


def labels(page: Page, described: dict[str, Description]) -> dict[str, str]:
    """Each control's label by ref: the spec's, else Live's name shortened. Names alike within the page get the
    track's first word in front ("Kick Gain", "Hats Gain")."""
    full: dict[str, str] = {}
    for c in page.controls():
        if c.label:
            full[c.ref] = c.label
        else:
            d = described.get(c.ref)
            full[c.ref] = d["name"] if d else c.ref.rsplit("/", 1)[-1]
    counts: dict[str, int] = {}
    for c in page.controls():
        if not c.label:
            counts[full[c.ref]] = counts.get(full[c.ref], 0) + 1
    out: dict[str, str] = {}
    for c in page.controls():
        text = full[c.ref]
        if not c.label and counts[text] > 1:
            text = f"{c.ref.split('/', 1)[0].split(' ')[0]} {text}"
        out[c.ref] = text if c.label else short_label(text)
    return out


def _in_range(c: Control, d: Description) -> str | None:
    """Why the control's `range` cannot be used, or None."""
    if c.range is None:
        return None
    if d["kind"] != "continuous":
        return "a range needs a continuous value; this is a switch or a list"
    ends = [shown.shown_number(x) for x in c.range]
    lo, hi = (shown.shown_number(s.shown) for s in (d["stops"][0], d["stops"][-1]))
    if None in ends or lo is None or hi is None:
        return f"cannot read the range {list(c.range)} against what Live shows ({d['now'].shown})"
    a, b = sorted(e for e in ends if e is not None)
    if a == b:
        return "the range's two ends are the same"
    if a < min(lo, hi) or b > max(lo, hi):
        return f"the range {list(c.range)} is outside {d['stops'][0].shown} to {d['stops'][-1].shown}"
    return None


def lint(page: Page, described: dict[str, Description], missing: dict[str, str] | None = None) -> list[Problem]:
    """What is wrong with a page, given Live's description of its targets (zpkt.live.describe.look gives both
    arguments). Errors first. An empty list, or notes only, means it may be shown."""
    out: list[Problem] = []

    def say(level: Literal["error", "note"], where: str, text: str) -> None:
        out.append({"level": level, "where": where, "text": text})

    controls = page.controls()
    if not controls and page.compare is None:
        say("error", "page", "the page has no controls")
    if len(controls) > MAX_CONTROLS:
        say("error", "page", f"{len(controls)} controls; a page holds at most {MAX_CONTROLS}: split it in two")
    if len(page.title) > 40:
        say("error", "page", "the title is over 40 characters")
    seen_groups: set[str] = set()
    for g in page.groups:
        if not g.controls:
            say("error", g.name, "the group is empty")
        if len(g.controls) > MAX_IN_GROUP:
            say("error", g.name, f"{len(g.controls)} controls; a group holds at most {MAX_IN_GROUP}")
        if g.name in seen_groups:
            say("error", g.name, "two groups have this name")
        seen_groups.add(g.name)
    seen: set[str] = set()
    for c in controls:
        if c.ref in seen:
            say("error", c.ref, "the page has this control twice")
        seen.add(c.ref)
        for t in c.targets():
            if missing and t in missing:
                say("error", c.ref, f"not in the open set: {missing[t]}")
            elif t not in described:
                say("error", c.ref, f"no description of {t}: it was not looked up in Live")
        if c.label and len(c.label) > MAX_LABEL:
            say("error", c.ref, f"the label {c.label!r} is over {MAX_LABEL} characters")
        if c.steps is not None and c.range is None:
            say("error", c.ref, "steps needs a range to step through")
        d = described.get(c.ref)
        if d is None:
            continue
        why = _in_range(c, d)
        if why:
            say("error", c.ref, why)
        if c.role and c.role != role_of(c, d):
            say("note", c.ref, f"Live says this is a {role_of(c, d)}, not a {c.role}; shown as a {widget(c, d)}")
        if d["plain"]:
            say("note", c.ref, "Live shows no number for it; the control shows the raw value")
        if not d["enabled"]:
            say("note", c.ref, "Live has it disabled now; it will not move until its device allows it")
    named = labels(page, described)
    for g in page.groups:
        in_group: dict[str, str] = {}
        for c in g.controls:
            text = named[c.ref].lower()
            if text in in_group:
                say("error", c.ref, f"its label {named[c.ref]!r} is the same as {in_group[text]}'s in {g.name!r}")
            in_group[text] = c.ref
    out += _lint_compare(page, described, missing or {})
    assign(page, described, notes=out)  # adds its own: a fader given up for a knob, a group that does not fit
    return sorted(out, key=lambda p: p["level"] != "error")


# ---- compare states ------------------------------------------------------------------------------------------------


def tolerance(d: Description) -> float:
    """How far a value may sit from a state's and still hold it: half a step of a switch or list, else COMPARE_STEP
    of the range."""
    return 0.5 if d["kind"] != "continuous" else (d["max"] - d["min"]) * COMPARE_STEP


def holds(value: Any, want: Any, lo: float, hi: float, quantized: bool) -> bool:
    """Does a control at `value` hold a state's `want`? contrib/mixdesk/pagercore.py has the same rule for the pager
    in Live (tests/live/test_page.py holds the two together)."""
    if value is None or want is None:
        return False
    gap = abs(float(value) - float(want))
    return gap < 0.5 if quantized else gap <= (hi - lo) * COMPARE_STEP


def fill(page: Page, described: dict[str, Description]) -> Page:
    """The page with its compare states made whole: the baseline holds every target's value (the one already kept,
    else what Live has now), and every state writes every target, the missing ones from the baseline. So a state
    with no writes is the mix as it was when the page was made. A target Live does not describe is left as it is
    (lint says so). The page itself is changed and returned."""
    cmp = page.compare
    if cmp is None:
        return page
    targets = cmp.targets()
    kept = {t: v for t, v in cmp.baseline.items() if t in targets}
    for t in targets:
        if t not in kept and t in described and described[t]["now"].raw is not None:
            raw = described[t]["now"].raw
            kept[t] = raw if isinstance(raw, bool) else float(raw)
    cmp.baseline = {t: kept[t] for t in targets if t in kept}
    cmp.ranges = {
        t: (float(d["min"]), float(d["max"]), d["kind"] != "continuous")
        for t in targets
        if (d := described.get(t)) is not None
    }
    for state in cmp.states:
        given = {w.target for w in state.writes}
        filled = [Write(target=t, to=kept[t]) for t in targets if t not in given and t in kept]
        state.writes = sorted([*state.writes, *filled], key=lambda w: targets.index(w.target))  # one order for all
    return page


def lit(compare: Compare, values: Mapping[str, Any]) -> int | None:
    """Which state is on: the first whose every target holds its value, given each target's raw value now (by state
    key). None when no state is: somebody moved one of the controls. Derived, never stored. The ranges are the ones
    `fill` kept."""
    for i, state in enumerate(compare.states):
        if state.writes and all(
            (r := compare.ranges.get(w.target)) is not None and holds(values.get(w.target), w.to, *r)
            for w in state.writes
        ):
            return i
    return None


def _lint_compare(page: Page, described: dict[str, Description], missing: dict[str, str]) -> list[Problem]:
    """What is wrong with the page's compare states. It reads them as `fill` leaves them: a state may leave a target
    out only when the baseline has it."""
    cmp = page.compare
    if cmp is None:
        return []
    out: list[Problem] = []

    def say(where: str, text: str) -> None:
        out.append({"level": "error", "where": where, "text": text})

    n = len(cmp.states)
    if not MIN_STATES <= n <= MAX_STATES:
        say("compare", f"{n} states; a compare has {MIN_STATES} to {MAX_STATES}, one pad each")
    if cmp.name is not None and len(cmp.name) > 24:
        say("compare", "the compare's name is over 24 characters")
    targets = cmp.targets()
    if not targets:
        say("compare", "no state writes anything: give at least one state its writes ({target, to})")
    if len(targets) > MAX_COMPARE_TARGETS:
        say("compare", f"the states write {len(targets)} values; a compare writes at most {MAX_COMPARE_TARGETS}")
    for t in targets:
        if t in missing:
            say(f"compare:{t}", f"not in the open set: {missing[t]}")
        elif t not in described:
            say(f"compare:{t}", f"no description of {t}: it was not looked up in Live")
    names: set[str] = set()
    whole: dict[tuple[Any, ...], str] = {}
    for state in cmp.states:
        where = f"compare:{state.name}"
        if not state.name.strip():
            say("compare", "a state has no name")
        if len(state.name) > MAX_LABEL:
            say(where, f"the name {state.name!r} is over {MAX_LABEL} characters: it is written on a pad")
        if state.name.lower() in names:
            say(where, "two states have this name")
        names.add(state.name.lower())
        seen: set[str] = set()
        for w in state.writes:
            if w.target in seen:
                say(where, f"it writes {w.target} twice")
            seen.add(w.target)
            d = described.get(w.target)
            if d is None:
                continue
            value = float(w.to)
            if not math.isfinite(value) or not d["min"] <= value <= d["max"]:
                say(where, f"{w.target}: {w.to!r} is outside its raw range {d['min']:g} to {d['max']:g}")
            elif d["kind"] != "continuous" and value != round(value):
                say(where, f"{w.target} is a switch or a list: its raw value is a whole number, not {w.to!r}")
        for t in targets:
            if t not in seen and t in described and t not in cmp.baseline:
                say(where, f"it does not write {t}, and no value of it was kept when the page was made")
        if all(t in seen or t in cmp.baseline for t in targets) and all(t in described for t in targets):
            given = {w.target: float(w.to) for w in state.writes}
            values = {t: given.get(t, float(cmp.baseline.get(t, 0.0))) for t in targets}
            key = tuple(round(values[t] / (tolerance(described[t]) or 1.0)) for t in targets)
            if key in whole:
                say(where, f"it is the same as {whole[key]!r}: two states must differ in at least one value")
            whole.setdefault(key, state.name)
    return out


# ---- the MiniLab ---------------------------------------------------------------------------------------------------


def _fits(levels: int, others: int, keys: int, pads: int = PADS) -> bool:
    return keys <= pads and others + max(0, levels - FADERS) <= KNOBS


def assign(page: Page, described: dict[str, Description], notes: list[Problem] | None = None) -> list[HardwarePage]:
    """The page on the MiniLab 3: which knob, fader and pad moves what. Groups stay whole and in order; a hardware
    page takes as many as fit (8 knobs, 4 faders, 8 pads) and the next groups go to the next hardware page. Faders
    take the levels, heaviest first; a fifth level becomes a knob, and that is noted. Knobs take the rest in page
    order. Pads take the switches from the left. The compare states take the last pads, one each, the same pads on
    every MiniLab page of the Page; the switches of a MiniLab page get the pads before them."""
    states = page.compare.states[:PADS] if page.compare else []
    free = PADS - len(states)  # pads left for switches
    kinds = {c.ref: widget(c, described.get(c.ref)) for c in page.controls()}

    def count(groups: list[Group]) -> tuple[int, int, int]:
        ws = [kinds[c.ref] for g in groups for c in g.controls]
        levels, keys = ws.count("fader"), ws.count("key")
        return levels, len(ws) - levels - keys, keys

    batches: list[list[Group]] = []
    for g in page.groups:
        if batches and _fits(*count([*batches[-1], g]), pads=free):
            batches[-1].append(g)
        else:
            batches.append([g])
    if states and not batches:
        batches.append([])  # states and no controls: one MiniLab page with only the pads
    out: list[HardwarePage] = []
    for batch in batches:
        flat = [(g.name, c) for g in batch for c in g.controls]
        levels = [(g, c) for g, c in flat if kinds[c.ref] == "fader"]
        on_faders = sorted(levels, key=lambda gc: -gc[1].weight)[:FADERS]
        fader_refs = {c.ref for _, c in on_faders}
        kept = [x for x in levels if x[1].ref in fader_refs]
        slots: list[Slot] = [{"slot": f"f{i + 1}", "ref": c.ref, "group": g} for i, (g, c) in enumerate(kept)]
        knobs = [(g, c) for g, c in flat if kinds[c.ref] != "key" and c.ref not in fader_refs]
        slots += [{"slot": f"k{i + 1}", "ref": c.ref, "group": g} for i, (g, c) in enumerate(knobs[:KNOBS])]
        keys = [(g, c) for g, c in flat if kinds[c.ref] == "key"]
        slots += [{"slot": f"b{i + 1}", "ref": c.ref, "group": g} for i, (g, c) in enumerate(keys[:free])]
        pads: list[StatePad] = [{"slot": f"b{free + i + 1}", "state": i, "name": s.name} for i, s in enumerate(states)]
        if notes is not None:
            for _, c in levels:
                if c.ref not in fader_refs:
                    notes.append(
                        {"level": "note", "where": c.ref, "text": "the MiniLab has 4 faders; this level is on a knob"}
                    )
            for name, c in knobs[KNOBS:] + keys[free:]:
                notes.append({"level": "error", "where": c.ref, "text": f"group {name!r} does not fit the MiniLab"})
        out.append({"groups": [g.name for g in batch], "slots": slots, "compare": pads})
    return out


# ---- files ---------------------------------------------------------------------------------------------------------


def folder(set_name: str) -> Path:
    return config.rig().sets_dir / "pages" / set_name


def slug(title: str) -> str:
    """A file name from a title: lower case, words joined by "-"."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "page"


def to_json(page: Page) -> dict[str, Any]:
    return page.model_dump(mode="json", by_alias=True, exclude_none=True)


def save(page: Page, set_name: str, directory: Path | None = None) -> Path:
    """Write the page under its id (from its title if it has none, numbered if that name is taken by another).
    `directory` defaults to folder(set_name)."""
    d = directory or folder(set_name)
    d.mkdir(parents=True, exist_ok=True)
    if not page.id:
        base, n = slug(page.title), 1
        page.id = base
        while (d / f"{page.id}.json").exists():
            n += 1
            page.id = f"{base}-{n}"
    path = d / f"{page.id}.json"
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(to_json(page), indent=1))
    tmp.replace(path)
    return path


def load(path: Path) -> Page:
    try:
        return parse(json.loads(path.read_text()))
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from None


def saved(set_name: str) -> list[Path]:
    """The set's page files, by name."""
    return sorted(folder(set_name).glob("*.json"))
