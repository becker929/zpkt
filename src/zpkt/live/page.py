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

lib/contracts/page.schema.json is generated from these models (hands/tools/gen_schemas.py). Unknown keys are kept, so
the file can grow. Pages live in <sets_dir>/pages/<set>/<id>.json.
"""

from __future__ import annotations

import json
import re
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


class Page(_Open):
    schema_: int = Field(default=SCHEMA, alias="schema", description="The file's version: 2.")
    id: str | None = Field(default=None, description="Its file name without .json; set when saved.")
    title: str
    groups: list[Group]
    made_by: Who = "you"
    at: str | None = Field(default=None, description="When it was made, YYYY-MM-DD HH:MM:SS.")
    prompt: str | None = Field(default=None, description="What was asked for.")

    def controls(self) -> list[Control]:
        return [c for g in self.groups for c in g.controls]

    def targets(self) -> list[str]:
        """Every state key the page moves, once each, in page order."""
        return list(dict.fromkeys(t for c in self.controls() for t in c.targets()))


class Problem(TypedDict):
    level: Literal["error", "note"]  # an error keeps the page from being shown; a note is told to the user
    where: str  # a control's ref, a group's name, or "page"
    text: str


class Slot(TypedDict):
    slot: str  # k1-k8 (knobs), f1-f4 (faders), b1-b8 (bank B pads)
    ref: str
    group: str


class HardwarePage(TypedDict):
    groups: list[str]
    slots: list[Slot]


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
    if not controls:
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
    assign(page, described, notes=out)  # adds its own: a fader given up for a knob, a group that does not fit
    return sorted(out, key=lambda p: p["level"] != "error")


# ---- the MiniLab ---------------------------------------------------------------------------------------------------


def _fits(levels: int, others: int, keys: int) -> bool:
    return keys <= PADS and others + max(0, levels - FADERS) <= KNOBS


def assign(page: Page, described: dict[str, Description], notes: list[Problem] | None = None) -> list[HardwarePage]:
    """The page on the MiniLab 3: which knob, fader and pad moves what. Groups stay whole and in order; a hardware
    page takes as many as fit (8 knobs, 4 faders, 8 pads) and the next groups go to the next hardware page. Faders
    take the levels, heaviest first; a fifth level becomes a knob, and that is noted. Knobs take the rest in page
    order. Pads take the switches."""
    kinds = {c.ref: widget(c, described.get(c.ref)) for c in page.controls()}

    def count(groups: list[Group]) -> tuple[int, int, int]:
        ws = [kinds[c.ref] for g in groups for c in g.controls]
        levels, keys = ws.count("fader"), ws.count("key")
        return levels, len(ws) - levels - keys, keys

    batches: list[list[Group]] = []
    for g in page.groups:
        if batches and _fits(*count([*batches[-1], g])):
            batches[-1].append(g)
        else:
            batches.append([g])
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
        slots += [{"slot": f"b{i + 1}", "ref": c.ref, "group": g} for i, (g, c) in enumerate(keys[:PADS])]
        if notes is not None:
            for _, c in levels:
                if c.ref not in fader_refs:
                    notes.append(
                        {"level": "note", "where": c.ref, "text": "the MiniLab has 4 faders; this level is on a knob"}
                    )
            for name, c in knobs[KNOBS:] + keys[PADS:]:
                notes.append({"level": "error", "where": c.ref, "text": f"group {name!r} does not fit the MiniLab"})
        out.append({"groups": [g.name for g in batch], "slots": slots})
    return out


# ---- files ---------------------------------------------------------------------------------------------------------


def folder(set_name: str) -> Path:
    return config.rig().sets_dir / "pages" / set_name


def slug(title: str) -> str:
    """A file name from a title: lower case, words joined by "-"."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "page"


def to_json(page: Page) -> dict[str, Any]:
    return page.model_dump(mode="json", by_alias=True, exclude_none=True)


def save(page: Page, set_name: str) -> Path:
    """Write the page under its id (from its title if it has none, numbered if that name is taken by another)."""
    d = folder(set_name)
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
