"""A Page as the shell draws it: one panel per MiniLab page, each a map of the MiniLab 3 with every slot on it.

`layout` is the one place the layout rules live (DESIGN 3a). It is pure: a Page and Live's descriptions of its
targets go in, a plain model comes out, and the browser only draws it. The rules:

- A panel is one MiniLab page (zpkt.live.page.assign) and always has the same 20 slots in the hardware's order:
  knobs k1-k8, faders f1-f4, pads b1-b8. The screen draws each where it sits on the controller.
- A slot with a control names it by `ref`, with its group and the group's tint. A slot with none is still there, with
  only its hardware name ("Knob 6"), and is drawn greyed.
- A target the open set lacks keeps its slot and is drawn greyed, with the reason.
- The groups keep their facts (widget, role, weight, size, pair) for whoever reads the model. The shell's place for
  a control is its slot, so it does not use size or pair.

`to_surfaces` turns a Page into the mix desk's made surfaces (one per MiniLab page), which is how the pager in Live
takes a Page.

lib/contracts/page-layout.schema.json is generated from `Layout` (hands/tools/gen_schemas.py).
"""

from __future__ import annotations

from itertools import pairwise
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from zpkt.live import page as P
from zpkt.live.describe import Description
from zpkt.live.inlive import keys, shown

SlotKind = Literal["knob", "fader", "pad"]
# Every slot of the MiniLab 3 in the order it is drawn, with its kind and what the hardware calls it.
HARDWARE_SLOTS: list[tuple[str, SlotKind, str]] = [
    *[(f"k{i}", "knob", f"Knob {i}") for i in range(1, P.KNOBS + 1)],
    *[(f"f{i}", "fader", f"Fader {i}") for i in range(1, P.FADERS + 1)],
    *[(f"b{i}", "pad", f"Pad {i}") for i in range(1, P.PADS + 1)],
]
Size = Literal["big", "normal", "small"]
SIZE_OF_WEIGHT: dict[int, Size] = {3: "big", 2: "normal", 1: "small"}


class LayoutControl(BaseModel):
    """One control as it is drawn."""

    model_config = ConfigDict(extra="forbid")

    ref: str = Field(description="The control's target, or macro:LABEL.")
    target: str | None = Field(description="Its state key; None for a macro.")
    label: str = Field(description="At most 10 characters unless the spec set a longer one.")
    widget: P.Widget
    role: P.Role
    weight: int
    size: Size
    pair: str | None = Field(description="Controls with the same pair name are drawn as one unit (an EQ band).")
    missing: str | None = Field(description="Why the control is greyed: the open set lacks its target.")
    items: list[str] = Field(description="The shown texts of a row of keys or a list, lowest first.")
    range: tuple[float, float] | None = Field(
        description="The stretch worth playing, as positions 0 to 1 along the control."
    )
    slot: str | None = Field(description="The MiniLab slot that moves it: k1-k8, f1-f4 or b1-b8.")
    hardware: int | None = Field(description="Which MiniLab page that slot is on, from 0.")
    macro: list[str] = Field(description="For a macro, the state keys it moves.")
    notes: list[str] = Field(description="What is told to the user about this control.")


class LayoutGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    tint: int = Field(description="0 or 1: neighbouring cards alternate a faint tint.")
    controls: list[LayoutControl]


class PanelSlot(BaseModel):
    """One place on the MiniLab, mapped or not."""

    model_config = ConfigDict(extra="forbid")

    slot: str = Field(description="k1-k8, f1-f4 or b1-b8.")
    kind: SlotKind
    name: str = Field(description='What the hardware calls it: "Knob 6", "Fader 2", "Pad 3".')
    ref: str | None = Field(description="The control it moves (a ref in `groups`); None when nothing is mapped.")
    group: str | None = Field(description="That control's group.")
    tint: int | None = Field(description="That group's tint, 0 or 1.")


class Panel(BaseModel):
    """One MiniLab page as a map of the controller: all 20 slots, in the hardware's order."""

    model_config = ConfigDict(extra="forbid")

    groups: list[str] = Field(description="The groups on this MiniLab page, in order.")
    slots: list[PanelSlot] = Field(description="Always 20: the 8 knobs, the 4 faders, the 8 pads.")


class Layout(BaseModel):
    """What GET of a page returns and the shell draws."""

    model_config = ConfigDict(extra="forbid")

    id: str | None
    title: str
    made_by: str
    groups: list[LayoutGroup]
    panels: list[Panel] = Field(description="One per MiniLab page: what the shell draws.")
    minilab: list[P.HardwarePage]
    problems: list[P.Problem]


def _norm(d: Description, text: str | float) -> float | None:
    """Where a shown text (or number) sits along the control, 0 to 1, read between the shown stops."""
    stops = [(shown.shown_number(s.shown), s.raw) for s in d["stops"]]
    points = sorted((n, float(r)) for n, r in stops if n is not None and isinstance(r, int | float))
    want = shown.shown_number(text)
    span = d["max"] - d["min"]
    if want is None or len(points) < 2 or span == 0:
        return None
    for (n0, r0), (n1, r1) in pairwise(points):
        if n0 <= want <= n1 and n1 > n0:
            raw = r0 + (want - n0) / (n1 - n0) * (r1 - r0)
            return round((raw - d["min"]) / span, 4)
    return None


def stripe(c: P.Control, d: Description | None) -> tuple[float, float] | None:
    """The control's range as two positions along it, low first; None when there is none or it cannot be placed."""
    if c.range is None or d is None or d["kind"] != "continuous":
        return None
    ends = [_norm(d, x) for x in c.range]
    if ends[0] is None or ends[1] is None:
        return None
    lo, hi = sorted((ends[0], ends[1]))
    return (lo, hi)


def _device_of(key: str) -> str:
    return key.rsplit("/", 1)[0]


def pairs(group: P.Group, described: dict[str, Description]) -> dict[str, str]:
    """{ref: pair name} for the EQ bands of a group: one continuous tone and one continuous level on one device."""
    by_device: dict[str, dict[str, list[str]]] = {}
    for c in group.controls:
        d = described.get(c.ref)
        if c.target is None or d is None or d["kind"] != "continuous":
            continue
        role = P.role_of(c, d)
        if role in ("tone", "level"):
            by_device.setdefault(_device_of(c.target), {"tone": [], "level": []})[role].append(c.ref)
    out: dict[str, str] = {}
    for device, roles in by_device.items():
        if len(roles["tone"]) == 1 and len(roles["level"]) == 1 and device.count("/") >= 1:
            for ref in (*roles["tone"], *roles["level"]):
                out[ref] = f"{group.name}:{device}"
    return out


def _ordered(group: P.Group, paired: dict[str, str]) -> list[P.Control]:
    """Heaviest first (page order among equals); the members of a pair stay together, at the heavier one's place."""
    ranked = sorted(group.controls, key=lambda c: -c.weight)
    out: list[P.Control] = []
    for c in ranked:
        if c in out:
            continue
        out.append(c)
        if c.ref in paired:
            out += [m for m in ranked if m is not c and m not in out and paired.get(m.ref) == paired[c.ref]]
    return out


def panels(hardware: list[P.HardwarePage], tints: dict[str, int]) -> list[Panel]:
    """Each MiniLab page as its full map: the assigned slots in their places, and every other slot named and empty."""
    out: list[Panel] = []
    for hw in hardware:
        taken = {s["slot"]: s for s in hw["slots"]}
        slots = []
        for slot, kind, name in HARDWARE_SLOTS:
            got = taken.get(slot)
            slots.append(
                PanelSlot(
                    slot=slot,
                    kind=kind,
                    name=name,
                    ref=got["ref"] if got else None,
                    group=got["group"] if got else None,
                    tint=tints.get(got["group"]) if got else None,
                )
            )
        out.append(Panel(groups=list(hw["groups"]), slots=slots))
    return out


def _missing_reason(c: P.Control, missing: dict[str, str]) -> str | None:
    for t in c.targets():
        if t in missing:
            return missing[t]
    return None


def layout(
    page: P.Page, described: dict[str, Description], missing: dict[str, str] | None = None, lint: bool = True
) -> Layout:
    """The page as the shell draws it. A control whose target is in `missing` is greyed, never dropped."""
    missing = missing or {}
    problems = P.lint(page, described, missing) if lint else []
    names = P.labels(page, described)
    hardware = P.assign(page, described)
    where = {s["ref"]: (s["slot"], i) for i, hw in enumerate(hardware) for s in hw["slots"]}
    notes: dict[str, list[str]] = {}
    for p in problems:
        notes.setdefault(p["where"], []).append(p["text"])
    groups: list[LayoutGroup] = []
    for gi, g in enumerate(page.groups):
        paired = pairs(g, described)
        controls = []
        for c in _ordered(g, paired):
            d = described.get(c.ref)
            gone = _missing_reason(c, missing)
            slot, hw = where.get(c.ref, (None, None))
            controls.append(
                LayoutControl(
                    ref=c.ref,
                    target=c.target,
                    label=names[c.ref],
                    widget="knob" if gone else P.widget(c, d),
                    role=P.role_of(c, d),
                    weight=c.weight,
                    size=SIZE_OF_WEIGHT[c.weight],
                    pair=paired.get(c.ref),
                    missing=gone,
                    items=list(d["items"]) if d and d["kind"] != "continuous" and not gone else [],
                    range=stripe(c, d),
                    slot=slot,
                    hardware=hw,
                    macro=[m.target for m in c.macro] if c.macro else [],
                    notes=notes.get(c.ref, []),
                )
            )
        groups.append(LayoutGroup(name=g.name, tint=gi % 2, controls=controls))
    return Layout(
        id=page.id,
        title=page.title,
        made_by=page.made_by,
        groups=groups,
        panels=panels(hardware, {g.name: g.tint for g in groups}),
        minilab=hardware,
        problems=problems,
    )


# ---- the mix desk's made surfaces ----------------------------------------------------------------------------------


def key_parts(key: str) -> dict[str, str]:
    """A state key as a desk control's track, device and param: "Kick bus/desk EQ/1 Gain A" has all three,
    "Kick bus/volume" and "Kick bus/send Space" (param "send:Space") have no device."""
    track, _, rest = key.partition("/")
    device, sep, param = rest.partition("/")
    if not sep or rest in keys.MIXER or rest.startswith(keys.SEND_IN_KEY):
        ret = keys.send_return(rest)
        return {"track": track, "param": keys.send_param(ret) if ret is not None else rest}
    return {"track": track, "device": device, "param": param}


def _end(x: str | float) -> str:
    return x if isinstance(x, str) else f"{x:g}"


def _surface_control(c: P.Control, label: str) -> dict[str, Any]:
    if c.macro is None:
        assert c.target is not None
        return {**key_parts(c.target), "label": label}
    parts = [{**key_parts(m.target), "from": _end(m.low), "to": _end(m.high)} for m in c.macro]
    return {"label": label, "macro": parts}


def to_surfaces(page: P.Page, described: dict[str, Description]) -> list[dict[str, Any]]:
    """The page as made surfaces (surfaces.SurfaceFile without the file's own keys), one per MiniLab page. Each
    names its page (`page_id`) and its place (`hardware`), so the shell draws the Page and the old desk still shows
    plain slots."""
    by_ref = {c.ref: c for c in page.controls()}
    names = P.labels(page, described)
    hardware = P.assign(page, described)
    out: list[dict[str, Any]] = []
    for i, hw in enumerate(hardware):
        title = page.title if len(hardware) == 1 else f"{page.title} {i + 1}"
        out.append(
            {
                "name": title[:24].rstrip(),
                "what": f"{page.title}: {', '.join(hw['groups'])}",
                "controls": {s["slot"]: _surface_control(by_ref[s["ref"]], names[s["ref"]]) for s in hw["slots"]},
                "notes": [],
                "page_id": page.id,
                "hardware": i,
            }
        )
    return out
