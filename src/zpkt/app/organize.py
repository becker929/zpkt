"""The order of the desk's pages, which of them are archived, and what they are called: one small file per set.

A page here is a unit: what the person sees as one page. It is a saved Page (`page:<id>`, one or more MiniLab pages),
one of the desk's own pages from desk.json (`desk:<name>`), or an older made surface with no Page (`surface:<file>`).
All three are treated alike for order and archive.

The file is `_organize.json` next to the set's saved Pages: {"order": [unit ids], "archived": [unit ids], "names":
{unit id: name}}. `arrange` turns the desk's raw page list (desk.json's pages, then the made surfaces, oldest first)
into the list the desk, the pager in Live and the page all use: archived units left out, the rest in the stored
order (a unit the order does not name keeps its place after the named ones), renamed.

Pads. While no order is stored, each page keeps the pad desk.json gives it (two pages on one pad are a layer). Once
the person has ordered the pages, the pads follow the order: the first eight units are on pads 1 to 8, the rest on
none (the big encoder and the screen still reach them). A unit of several MiniLab pages has its first on the pad.

Pure rules and one file; nothing here reaches Live.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, TypedDict

FILE = "_organize.json"
PADS = 8
NAME_MAX = 40


class Organized(TypedDict):
    order: list[str]
    archived: list[str]
    names: dict[str, str]


class Unit(TypedDict):
    """One page as the organizer shows it."""

    id: str
    name: str
    kind: str  # "page" (a saved Page), "desk" (built in), "surface" (an older made surface)
    archived: bool
    pages: list[dict[str, Any]]  # its desk pages as they are raw: one per MiniLab page


def empty() -> Organized:
    return {"order": [], "archived": [], "names": {}}


def read(directory: Path) -> Organized:
    """The set's stored order, archive and names; nothing stored (or a broken file) is the empty one."""
    try:
        raw = json.loads((directory / FILE).read_text())
    except (OSError, ValueError):
        return empty()
    if not isinstance(raw, dict):
        return empty()
    stored = raw.get("names")
    names: dict[Any, Any] = stored if isinstance(stored, dict) else {}
    return {
        "order": [str(x) for x in raw.get("order", []) if isinstance(x, str)],
        "archived": [str(x) for x in raw.get("archived", []) if isinstance(x, str)],
        "names": {str(k): str(v) for k, v in names.items()},
    }


def write(directory: Path, org: Organized) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / f".{FILE}.tmp"
    tmp.write_text(json.dumps(org, indent=1))
    os.replace(tmp, directory / FILE)


def unit_id(page: dict[str, Any]) -> str:
    """The unit a raw desk page belongs to."""
    if page.get("page_id"):
        return f"page:{page['page_id']}"
    if page.get("surface"):
        return f"surface:{page['surface']}"
    return f"desk:{page['name']}"


def _own_name(unit_pages: list[dict[str, Any]]) -> str:
    """A unit's name from its pages: the page's own, or for a Page of several MiniLab pages ("Kick 1", "Kick 2")
    what they share."""
    first = str(unit_pages[0]["name"])
    return re.sub(r"\s+1$", "", first) if len(unit_pages) > 1 else first


def units(raw: list[dict[str, Any]], org: Organized) -> list[Unit]:
    """Every unit: the ones on the desk in their order, then the archived ones (in the order they were archived)."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for page in raw:
        grouped.setdefault(unit_id(page), []).append(page)
    place = {uid: i for i, uid in enumerate(org["order"])}
    found = list(grouped)
    ordered = sorted(found, key=lambda uid: (uid not in place, place.get(uid, 0), found.index(uid)))
    archived = [uid for uid in org["archived"] if uid in grouped]
    out: list[Unit] = []
    for uid in [u for u in ordered if u not in archived] + archived:
        out.append(
            {
                "id": uid,
                "name": org["names"].get(uid) or _own_name(grouped[uid]),
                "kind": uid.split(":", 1)[0],
                "archived": uid in archived,
                "pages": grouped[uid],
            }
        )
    return out


def arrange(raw: list[dict[str, Any]], org: Organized) -> list[dict[str, Any]]:
    """The desk's pages as everything uses them: see the module's words on order, archive, names and pads."""
    out: list[dict[str, Any]] = []
    active = [u for u in units(raw, org) if not u["archived"]]
    for at, unit in enumerate(active):
        many = len(unit["pages"]) > 1
        for k, page in enumerate(unit["pages"]):
            page = dict(page)
            if unit["id"] in org["names"]:
                page["name"] = f"{unit['name']} {k + 1}" if many else unit["name"]
            if org["order"]:  # the person ordered the pages: the pads follow the order
                page["pad"] = at + 1 if at < PADS and k == 0 else 0
            out.append(page)
    return out


def clean_name(name: Any) -> str:
    """A name as it may be stored; ValueError says what a name may be."""
    text = " ".join(str(name or "").split())
    if not text or len(text) > NAME_MAX:
        raise ValueError(f"a page's name is 1 to {NAME_MAX} characters")
    return text


def slots_of(unit: Unit) -> list[list[str]]:
    """The mapped slots of each of the unit's MiniLab pages (k1..k8, f1..f4, b1..b8): what a thumbnail lights."""
    out = []
    for page in unit["pages"]:
        mapped = [s for s in page.get("controls", {}) if re.fullmatch(r"[kf]\d|b\d", s)]
        pads = [s for s in ((page.get("compare") or {}).get("pads") or {}) if s not in mapped]
        out.append(sorted(mapped + pads))
    return out
