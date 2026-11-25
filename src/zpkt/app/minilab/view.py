"""What the desk shows, as the map's View: from the desk's state (a pure function; the adapter reads the desk)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from zpkt.app.minilab.mapper import ControlView, PageView, View


def pages_from_cfg(pages: Sequence[Mapping[str, Any]]) -> tuple[PageView, ...]:
    """desk.json's pages (and made surfaces) as the map sees them: a name and the pad that arms it."""
    return tuple(PageView(str(p["name"]), int(p["pad"]) if "pad" in p else None) for p in pages)


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


def view_from(
    state: Mapping[str, Any], pages: tuple[PageView, ...], labels: Mapping[str, str], hearing: str = "now"
) -> View:
    """The View of a desk state (deskstate.DeskState) with the page list, the history's labels and what is heard."""
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
    )
