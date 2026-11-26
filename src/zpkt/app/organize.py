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


def resolve_id(raw: list[dict[str, Any]], org: Organized, ident: str) -> str:
    """Resolve a unit id (or a bare saved page_id when `page:<id>` exists); ValueError if unknown."""
    all_units = units(raw, org)
    known = {u["id"] for u in all_units}
    if ident in known:
        return ident
    if f"page:{ident}" in known:
        return f"page:{ident}"
    raise ValueError(f"no page with id {ident!r}")


def rename(raw: list[dict[str, Any]], org: Organized, ident: str, name: Any) -> Organized:
    """Return a copy of `org` with unit `ident` renamed to `name`."""
    uid = resolve_id(raw, org, ident)
    cleaned = clean_name(name)
    names = dict(org["names"])
    names[uid] = cleaned
    return {"order": list(org["order"]), "archived": list(org["archived"]), "names": names}


def archive(raw: list[dict[str, Any]], org: Organized, ident: str, archived: bool = True) -> Organized:
    """Return a copy of `org` with unit `ident` archived or restored. At least one active page must stay."""
    uid = resolve_id(raw, org, ident)
    all_units = units(raw, org)
    active_ids = [u["id"] for u in all_units if not u["archived"]]
    arch = list(org["archived"])
    order = list(org["order"])
    if archived:
        if uid in active_ids and len(active_ids) <= 1:
            raise ValueError("at least one page must stay on the desk")
        if uid not in arch:
            arch.append(uid)
    else:
        arch = [x for x in arch if x != uid]
        if order and uid not in order:
            order.append(uid)
    return {"order": order, "archived": arch, "names": dict(org["names"])}


def reorder(raw: list[dict[str, Any]], org: Organized, order: list[str]) -> Organized:
    """Return a copy of `org` with the given unit order. Unknown or duplicate ids raise ValueError."""
    if not isinstance(order, list) or not all(isinstance(x, str) for x in order):
        raise ValueError("'order' must be a list of page ids")
    all_units = units(raw, org)
    resolved: list[str] = []
    seen: set[str] = set()
    for ident in order:
        uid = resolve_id(raw, org, ident)
        if uid in seen:
            raise ValueError(f"duplicate page id {uid!r} in order")
        seen.add(uid)
        resolved.append(uid)
    for u in all_units:
        if not u["archived"] and u["id"] not in seen:
            resolved.append(u["id"])
    return {"order": resolved, "archived": list(org["archived"]), "names": dict(org["names"])}


def move(
    raw: list[dict[str, Any]], org: Organized, ident: str, to: int | None = None, by: int | None = None
) -> Organized:
    """Move an active unit to index `to` or by offset `by` (-1 earlier, +1 later)."""
    uid = resolve_id(raw, org, ident)
    active = [u["id"] for u in units(raw, org) if not u["archived"]]
    if uid not in active:
        raise ValueError("archived pages cannot be reordered; restore the page first")
    cur = active.index(uid)
    if to is not None:
        dest = max(0, min(len(active) - 1, to))
    elif by is not None:
        dest = max(0, min(len(active) - 1, cur + by))
    else:
        raise ValueError("move needs 'by' or 'to'")
    active.pop(cur)
    active.insert(dest, uid)
    return reorder(raw, org, active)


def listing(raw: list[dict[str, Any]], org: Organized) -> list[dict[str, Any]]:
    """Every unit (active in order, then archived) as JSON for the Desk UI and agents."""
    all_units = units(raw, org)
    out: list[dict[str, Any]] = []
    active_idx = 0
    for u in all_units:
        if u["archived"]:
            pad = 0
        elif org["order"]:
            pad = active_idx + 1 if active_idx < PADS else 0
            active_idx += 1
        else:
            pad = int(u["pages"][0].get("pad") or 0)
            active_idx += 1
        out.append(
            {
                "id": u["id"],
                "name": u["name"],
                "kind": u["kind"],
                "archived": u["archived"],
                "pages": len(u["pages"]),
                "page_id": u["pages"][0].get("page_id") if u["kind"] == "page" else None,
                "pad": pad,
                "slots": slots_of(u),
            }
        )
    return out

