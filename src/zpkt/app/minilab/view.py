"""What the desk shows, as the map's View: from the desk's state (a pure function; the adapter reads the desk)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from zpkt.app.minilab.core import pagercore
from zpkt.app.minilab.mapper import ControlView, PageView, StepsView, View


def pages_from_cfg(pages: Sequence[Mapping[str, Any]]) -> tuple[PageView, ...]:
    """desk.json's pages (and made surfaces) as the map sees them: a name, the pad that arms it, and the pads that
    hold its compare states."""
    return tuple(
        PageView(
            str(p["name"]),
            int(p["pad"]) if "pad" in p else None,
            {str(slot): int(i) for slot, i in ((p.get("compare") or {}).get("pads") or {}).items()},
        )
        for p in pages
    )


def lit_pad(compare: Mapping[str, Any] | None, values: Mapping[str, Mapping[str, Any]]) -> str | None:
    """The pad slot of the compare state that is on now, from a desk page's "compare" (its states' writes and the
    targets' ranges) and the desk's values: the pager's own rule (pagercore.lit_state), so the light and Live agree.
    None when no state holds."""
    if not compare:
        return None
    by_key = {str(v["key"]): v.get("r") for v in values.values() if v.get("key") and not v.get("err")}
    ranges = compare.get("ranges") or {}

    def read(key: str) -> tuple[Any, float, float, bool] | None:
        if key not in by_key or key not in ranges:
            return None
        lo, hi, quantized = ranges[key]
        return by_key[key], float(lo), float(hi), bool(quantized)

    on = pagercore().lit_state(compare.get("states") or [], read)
    return next((str(slot) for slot, i in (compare.get("pads") or {}).items() if i == on), None)


def controls_of(
    values: Mapping[str, Mapping[str, Any]], page: int, labels: Mapping[str, str]
) -> dict[str, ControlView]:
    """The armed page's working controls by slot. A control with no state key, or one the pager could not find (it
    reports an error), is left out: there is nothing to move."""
    out: dict[str, ControlView] = {}
    prefix = f"{page}:"
    for name, v in values.items():
        if not name.startswith(prefix) or not v.get("key") or v.get("err") or v.get("n") is None:
            continue
        slot = name[len(prefix) :]
        out[slot] = ControlView(
            key=str(v["key"]),
            n=float(v["n"]),
            text=str(v.get("s", "")),
            label=labels.get(str(v["key"]), ""),
            quantized=bool(v.get("q", False)),
        )
    return out


def steps_view(focus: Mapping[str, Any] | None, sounds: Sequence[Mapping[str, Any]] | None = None) -> StepsView | None:
    """The steps layer for the app's focus (Desk.steps_now) and the kit's sounds (steps.sounds; None: not read):
    None when the layer is off (no focus, or clips in its way), by the pager's own rule."""
    if focus is None or pagercore().steps_layer(focus) is None:
        return None
    kit = None if sounds is None else tuple(sorted((int(s["pitch"]), str(s["name"])) for s in sounds))
    return StepsView(focus, kit)


def view_from(
    state: Mapping[str, Any],
    pages: tuple[PageView, ...],
    labels: Mapping[str, str],
    hearing: str = "now",
    compare: Mapping[str, Any] | None = None,
    steps: StepsView | None = None,
) -> View:
    """The View of a desk state (deskstate.DeskState) with the page list, the history's labels and what is heard.
    `compare` is the armed page's own "compare" (desk.cfg): which of its pads is lit is worked out here. `steps` is
    the steps layer (steps_view), when the sequencer has a pattern in hand."""
    page = int(state["page"])
    return View(
        page=page,
        pages=pages,
        controls=controls_of(state["values"], page, labels),
        playing=bool(state["playing"]),
        pos=float(state["pos"]),
        loop=str(state["loop"]),
        match=bool(state["match"]),
        hearing=hearing,
        driving=bool(state["values"]),
        lit=lit_pad(compare, state["values"]),
        steps=steps,
    )
