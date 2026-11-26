"""Pages in the app: check a spec, make a page (lint, save, put it on the desk and the MiniLab), draw one.

An agent's spec, or what Claude answers to "Make a surface", comes in as a Page spec v2 (zpkt.live.page). The linter is
the gate: a rejected spec answers with its reasons and nothing is saved. A good one is saved as a Page under
<sets_dir>/pages/<set>/<id>.json and as one made surface per MiniLab page, which is how the pager in Live and the old
desk take it. The shell draws the Page from `layout` (zpkt.live.page_layout). All of it runs as commands on the bus.

A spec that names the id of a saved page replaces that page: the file is written over, and where the page is on the
desk its surfaces are written over in place, so the page keeps its place and the desk stays on the page it was on.
A page's compare states are made whole here (`whole`): the values its controls had when it was first made are kept
across every later version of it, so there is always a way back.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from zpkt.app import organize, surfaces
from zpkt.app.bus import BadRequest, Command, Reply
from zpkt.live import describe, page, page_layout
from zpkt.live.describe import Description
from zpkt.live.inlive import keys

if TYPE_CHECKING:
    from zpkt.app.desk import Desk

NO_LAYOUT = "no page with that id in this set"


def pages_dir(desk: Desk) -> Path:
    return desk.settings.pages_dir or page.folder(desk.settings.set_name)


def link(page_id: str | None) -> str:
    """Where a saved page opens: the Desk reads the hash and sends `page.open`."""
    return f"/app/#page={page_id}"


def reasons(problems: list[page.Problem]) -> str:
    """The errors of a lint, as one plain text for a person or an agent to act on."""
    return " ".join(f"{p['where']}: {p['text']}." for p in problems if p["level"] == "error")


def saved_page(desk: Desk, page_id: str | None) -> page.Page | None:
    """The saved page with that id, or None (no id, no such file, or a file that is not a page)."""
    if not page_id or "/" in page_id or page_id.startswith("."):
        return None
    path = pages_dir(desk) / f"{page_id}.json"
    if not path.is_file():
        return None
    try:
        parsed = page.load(path)
    except ValueError:
        return None
    parsed.id = page_id
    return parsed


def whole(desk: Desk, parsed: page.Page, found: dict[str, Description]) -> page.Page:
    """The page with its compare states made whole (zpkt.live.page.fill). The baseline is the app's to keep, never
    the spec's: the values kept when the page with this id was first made, and for a target new to it, what Live
    has now."""
    if parsed.compare is not None:
        before = saved_page(desk, parsed.id)
        parsed.compare.baseline = dict(before.compare.baseline) if before and before.compare else {}
        page.fill(parsed, found)
    return parsed


def checked(desk: Desk, spec: Any, who: str = "you") -> tuple[page.Page, dict[str, Description], list[page.Problem]]:
    """Parse a spec, make its compare states whole, and lint it against what Live holds. ValueError is a spec that
    is not a Page at all."""
    if not isinstance(spec, dict):
        raise ValueError("the spec must be a JSON object")
    parsed = page.parse({**spec, "made_by": who})
    found, missing = describe.look(desk.conn, parsed.targets())
    whole(desk, parsed, found)
    return parsed, found, page.lint(parsed, found, missing)


def on_desk(desk: Desk, page_id: str | None) -> list[int]:
    """The desk pages (their numbers) that draw the saved page with this id: one per MiniLab page."""
    return [i for i, pg in enumerate(desk.cfg()["pages"]) if page_id and pg.get("page_id") == page_id]


def _rejected(problems: list[page.Problem]) -> Reply:
    return 422, {"ok": False, "error": f"The page was not made. {reasons(problems)}", "problems": problems}


def lint(desk: Desk, cmd: Command) -> Reply:
    """Check a spec without saving it: the problems, the widgets and the MiniLab map."""
    try:
        parsed, found, problems = checked(desk, cmd.args.get("spec"), cmd.who)
    except ValueError as exc:
        return _rejected([{"level": "error", "where": "page", "text": str(exc)}])
    out = page_layout.layout(parsed, found, lint=False)
    ok = not any(p["level"] == "error" for p in problems)
    return 200, {
        "ok": ok,
        "problems": problems,
        "layout": out.model_dump(),
        **({} if ok else {"error": reasons(problems)}),
    }


def _taken_names(desk: Desk) -> list[str]:
    return desk.page_names()


def make(desk: Desk, cmd: Command) -> Reply:
    """A spec in; linted, saved, and (unless `apply` is false) put on the desk and the MiniLab."""
    if desk.bus.guard is not None:
        desk.bus.guard.check()  # a page for another set must not land on this one
    try:
        parsed, found, problems = checked(desk, cmd.args.get("spec"), cmd.who)
    except ValueError as exc:
        return _rejected([{"level": "error", "where": "page", "text": str(exc)}])
    if any(p["level"] == "error" for p in problems):
        return _rejected(problems)
    parsed.at = time.strftime("%Y-%m-%d %H:%M:%S")
    parsed.prompt = str(cmd.args["prompt"]) if cmd.args.get("prompt") else parsed.prompt
    saved = page.save(parsed, desk.settings.set_name, pages_dir(desk))
    reply: dict[str, Any] = {
        "ok": True,
        "id": parsed.id,
        "file": saved.name,
        "title": parsed.title,
        "made_by": parsed.made_by,
        "notes": [p["text"] for p in problems],
        "problems": problems,
        "minilab": page.assign(parsed, found),
    }
    if cmd.args.get("apply", True):
        reply["pages"] = apply(desk, parsed, found, cmd.args.get("prompt") or "")
    return 200, reply


def apply(
    desk: Desk, parsed: page.Page, found: dict[str, Description], prompt: str = "", arm: bool = True
) -> list[int]:
    """Put a saved Page on the desk: one made surface per MiniLab page, the pager reloaded once, the first armed
    (`arm` false: the desk stays on the page it was on). A page that is on the desk already is written over where it
    is: its surfaces keep their files and their place. Returns the desk pages' numbers."""
    folder = desk.settings.surfaces_dir
    old = [pg for pg in surfaces.pages(desk.settings.set_name, folder) if parsed.id and pg.get("page_id") == parsed.id]
    mine = {pg["name"] for pg in old}
    taken = [name for name in _taken_names(desk) if name not in mine]
    made: list[tuple[Path, dict[str, Any]]] = []
    stamps: list[int] = []
    last = max(((folder / pg["surface"]).stat().st_mtime_ns for pg in old), default=time.time_ns())
    for i, surface in enumerate(page_layout.to_surfaces(parsed, found)):
        surface["name"] = _unique(surface["name"], taken)
        taken.append(surface["name"])
        if i < len(old):  # the same file, at the same place among the desk's pages
            path = folder / old[i]["surface"]
            stamps.append(path.stat().st_mtime_ns)
            surfaces.write(
                path,
                {**surface, "prompt": prompt, "made": time.strftime("%Y-%m-%d %H:%M"), "set": desk.settings.set_name},
            )
        else:  # a MiniLab page more than before: right after the page's last one
            path = surfaces.save(surface, desk.settings.set_name, prompt, folder)
            stamps.append(last + (i - len(old) + 1) * 1_000 if old else last + i * 1_000_000)
        made.append((path, surface))
    for path, stamp in zip((p for p, _ in made), stamps, strict=True):  # the order holds whatever the clock's grain
        os.utime(path, ns=(stamp, stamp))
    for pg in old[len(made) :]:  # a MiniLab page fewer than before
        surfaces.remove(desk.settings.set_name, pg["surface"], folder)
    return desk.adopt_surfaces(made, arm=arm)


def open_saved(desk: Desk, cmd: Command) -> Reply:
    """Open a saved page by id (the link an agent gives, /app/#page=<id>): arm it when it is on the desk already,
    else put it on the desk and the MiniLab first. It is your act: an agent drafts pages and cannot open one."""
    page_id = str(cmd.args.get("id", ""))
    path = pages_dir(desk) / f"{page_id}.json"
    if not page_id or "/" in page_id or not path.is_file():
        raise BadRequest(NO_LAYOUT)
    try:
        parsed = page.load(path)
    except ValueError as exc:
        raise BadRequest(str(exc)) from None
    parsed.id = page_id
    there = on_desk(desk, page_id)
    if there:
        desk.call(f"m.DESK.arm({there[0]})")
        desk.push({"t": "desk", "open": there[0]})
        return 200, {"ok": True, "id": page_id, "title": parsed.title, "pages": there, "added": False}
    found, missing = describe.look(desk.conn, parsed.targets())
    page.fill(parsed, found)
    problems = page.lint(parsed, found, missing)
    if any(p["level"] == "error" for p in problems):
        return 422, {
            "ok": False,
            "error": f"The page cannot be opened on this set. {reasons(problems)}",
            "problems": problems,
        }
    made = apply(desk, parsed, found, parsed.prompt or "")
    return 200, {"ok": True, "id": page_id, "title": parsed.title, "pages": made, "added": True}


def _unique(name: str, taken: list[str]) -> str:
    lower = [t.lower() for t in taken]
    out, n = name, 2
    while out.lower() in lower:
        out, n = f"{name[: 24 - len(str(n)) - 1]} {n}", n + 1
    return out


def listing(desk: Desk) -> list[dict[str, Any]]:
    """The set's saved pages: id, title, who made it, when, and how many controls. A file that is not a page is
    passed over."""
    names = organize.read(desk.pages_dir())["names"]
    out = []
    for path in sorted(pages_dir(desk).glob("*.json")):
        try:
            p = page.load(path)
        except ValueError:
            continue
        pid = p.id or path.stem
        out.append(
            {
                "id": pid,
                "title": names.get(f"page:{pid}") or p.title,
                "made_by": p.made_by,
                "at": p.at,
                "controls": len(p.controls()),
            }
        )
    return out


def units_listing(desk: Desk) -> list[dict[str, Any]]:
    """Every page unit on the desk (active in order, then archived), with its id, name, kind, pad and slots."""
    return organize.listing(desk.raw_pages(), organize.read(desk.pages_dir()))


def list_units(desk: Desk, cmd: Command) -> Reply:
    """Read the desk's page units (active and archived), for the UI and agents."""
    return 200, {"ok": True, "units": units_listing(desk)}


def organize_units(desk: Desk, cmd: Command) -> Reply:
    """Rename, reorder, archive or restore pages on the desk (`_organize.json`), then reload the pager while
    staying on the same page where possible. No mix value in Live moves."""
    if desk.bus.guard is not None:
        desk.bus.guard.check()
    action = str(cmd.args.get("action") or "")
    raw = desk.raw_pages()
    org = organize.read(desk.pages_dir())
    before_unit = desk.current_unit_id()
    try:
        if action == "rename":
            updated = organize.rename(raw, org, str(cmd.args.get("id") or ""), cmd.args.get("name"))
        elif action == "archive":
            updated = organize.archive(raw, org, str(cmd.args.get("id") or ""), True)
        elif action == "restore":
            updated = organize.archive(raw, org, str(cmd.args.get("id") or ""), False)
        elif action == "reorder":
            updated = organize.reorder(raw, org, cmd.args.get("order"))  # type: ignore[arg-type]
        elif action == "move":
            by_raw, to_raw = cmd.args.get("by"), cmd.args.get("to")
            by = None if by_raw is None else int(by_raw)
            to = None if to_raw is None else int(to_raw)
            if isinstance(by_raw, bool) or isinstance(to_raw, bool):
                raise ValueError("'by' and 'to' must be whole numbers")
            updated = organize.move(raw, org, str(cmd.args.get("id") or ""), to=to, by=by)
        else:
            raise BadRequest("action must be one of rename, archive, restore, reorder, move")
    except (ValueError, TypeError) as exc:
        raise BadRequest(str(exc)) from None
    organize.write(desk.pages_dir(), updated)
    shown = desk.apply_organize(before_unit)
    return 200, {"ok": True, "units": organize.listing(raw, updated), "open": shown}


def layout_of(desk: Desk, cmd: Command) -> Reply:
    """A saved page as the shell draws it. A target the set lacks is greyed in it, not an error."""
    page_id = str(cmd.args.get("id", ""))
    path = pages_dir(desk) / f"{page_id}.json"
    if not page_id or "/" in page_id or not path.is_file():
        raise BadRequest(NO_LAYOUT)
    try:
        parsed = page.load(path)
    except ValueError as exc:
        raise BadRequest(str(exc)) from None
    parsed.id = page_id
    stored_name = organize.read(desk.pages_dir())["names"].get(f"page:{page_id}")
    if stored_name:
        parsed.title = stored_name
    found, missing = describe.look(desk.conn, parsed.targets())
    return 200, {"ok": True, "layout": page_layout.layout(parsed, found, missing).model_dump()}


# ---- compare states --------------------------------------------------------------------------------------------------


def state_asked(desk: Desk, cmd: Command) -> tuple[page.Page, int]:
    """The saved page and the compare state a press means: {"id", "state"} from the screen (the state's place or its
    name), or {"page", "slot"} from the MiniLab (the desk page's number and the pad). BadRequest when there is none."""
    args = cmd.args
    index: Any = args.get("state")
    page_id = str(args.get("id") or "")
    if not page_id and "page" in args:
        cfg = desk.cfg()["pages"]
        at = args["page"]
        if isinstance(at, bool) or not isinstance(at, int) or not 0 <= at < len(cfg):
            raise BadRequest("'page' is the number of a page on the desk")
        page_id = str(cfg[at].get("page_id") or "")
        index = ((cfg[at].get("compare") or {}).get("pads") or {}).get(str(args.get("slot", "")))
        if index is None:
            raise BadRequest(f"pad {args.get('slot')!r} of that page holds no compare state")
    parsed = saved_page(desk, page_id)
    if parsed is None or parsed.compare is None:
        raise BadRequest("that page has no compare states" if parsed else NO_LAYOUT)
    states = parsed.compare.states
    if isinstance(index, str):
        index = next((i for i, s in enumerate(states) if s.name == index), None)
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(states):
        raise BadRequest(f"'state' is one of {', '.join(s.name for s in states)} (or its place from 0)")
    return parsed, index


def compare_view(desk: Desk) -> list[dict[str, Any]]:
    """The compare states of the pages on the desk, and which is on now (None: no state holds). For whoever reads
    the desk: an agent's read of the state, the MiniLab adapter's lights."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pg in desk.cfg()["pages"]:
        page_id = pg.get("page_id")
        if not page_id or page_id in seen or not pg.get("compare"):
            continue
        seen.add(page_id)
        parsed = saved_page(desk, page_id)
        if parsed is None or parsed.compare is None:
            continue
        on = page.lit(parsed.compare, compare_values(desk, parsed.compare))
        out.append(
            {
                "page": page_id,
                "name": parsed.compare.name or parsed.title,
                "states": [s.name for s in parsed.compare.states],
                "on": None if on is None else parsed.compare.states[on].name,
            }
        )
    return out


def compare_values(desk: Desk, compare: page.Compare) -> dict[str, Any]:
    """Each compare target's raw value as the desk last saw it (None for one the pager has not reported)."""
    out: dict[str, Any] = {}
    for t in compare.targets():
        value = desk.history.value(t)
        out[t] = None if value is None else value[1]
    return out


# ---- what Claude is asked --------------------------------------------------------------------------------------------


def state_key(track: str, device: str, param: str) -> str:
    """The key of an inventory line (the pager lists track, device, param)."""
    ret = keys.send_return(param)
    if ret is not None:
        return keys.send_key(track, ret)
    return keys.device_key(track, device, param) if device else keys.mixer_key(track, param)


def inventory_text(inv: dict[Any, Any]) -> str:
    """The set's values for the prompt: one state key a line, with what it shows now and its range."""
    lines = []
    for (track, device, param), v in inv.items():
        kind = " [switch/list]" if v["q"] else ""
        lines.append(f"- {state_key(track, device, param)}: now {v['now']} ({v['min']} .. {v['max']}){kind}")
    return "\n".join(lines)


def prompt_for(request: str, inv: dict[Any, Any], existing: list[str]) -> str:
    return f"""You are making one page of controls for an Ableton Live set. A person will move them on a phone, a desktop and an Arturia MiniLab 3.

The musician asked:
<request>
{request}
</request>

Write a Page spec. It has no pixels: you say what belongs together and what matters, and a fixed renderer draws it.
- "title": at most 40 characters. Titles already taken: {existing!r}
- "groups": a list of {{"name": ..., "controls": [...]}}. A group holds at most 6 controls and the page at most 24. Group things that are changed together.
- A control: {{"target": "<state key from the list below>", "role": "level"|"tone"|"amount"|"time"|"switch"|"choice", "weight": 1-3, "label": "<at most 10 characters, optional>", "range": ["<low shown>", "<high shown>"] (optional)}}.
- Or a macro: {{"label": "<short>", "macro": [{{"target": "<key>", "low": "<shown value>", "high": "<shown value>"}}, ...]}}.
- weight 3 is big and first; 1 is small. Never write widget, size, colour, position or MIDI slot.
- Use ONLY keys from the list, spelled exactly. Two controls in one group must not have the same label.

Reply with ONE JSON object: {{"title": ..., "groups": [...]}} and nothing else.

# The set
{inventory_text(inv)}
"""
