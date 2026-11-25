"""Pages in the app: check a spec, make a page (lint, save, put it on the desk and the MiniLab), draw one.

An agent's spec, or what Claude answers to "Make a surface", comes in as a Page spec v2 (zpkt.live.page). The linter is
the gate: a rejected spec answers with its reasons and nothing is saved. A good one is saved as a Page under
<sets_dir>/pages/<set>/<id>.json and as one made surface per MiniLab page, which is how the pager in Live and the old
desk take it. The shell draws the Page from `layout` (zpkt.live.page_layout). All of it runs as commands on the bus.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from zpkt.app import surfaces
from zpkt.app.bus import BadRequest, Command, Reply
from zpkt.live import describe, page, page_layout
from zpkt.live.describe import Description
from zpkt.live.inlive import keys

if TYPE_CHECKING:
    from zpkt.app.desk import Desk

NO_LAYOUT = "no page with that id in this set"


def pages_dir(desk: Desk) -> Path:
    return desk.settings.pages_dir or page.folder(desk.settings.set_name)


def reasons(problems: list[page.Problem]) -> str:
    """The errors of a lint, as one plain text for a person or an agent to act on."""
    return " ".join(f"{p['where']}: {p['text']}." for p in problems if p["level"] == "error")


def checked(desk: Desk, spec: Any, who: str = "you") -> tuple[page.Page, dict[str, Description], list[page.Problem]]:
    """Parse a spec and lint it against what Live holds. ValueError is a spec that is not a Page at all."""
    if not isinstance(spec, dict):
        raise ValueError("the spec must be a JSON object")
    parsed = page.parse({**spec, "made_by": who})
    found, missing = describe.look(desk.conn, parsed.targets())
    return parsed, found, page.lint(parsed, found, missing)


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


def apply(desk: Desk, parsed: page.Page, found: dict[str, Description], prompt: str = "") -> list[int]:
    """Put a saved Page on the desk: one made surface per MiniLab page, the pager reloaded once, the first armed.
    Returns the desk pages' numbers."""
    taken = _taken_names(desk)
    made: list[tuple[Path, dict[str, Any]]] = []
    for surface in page_layout.to_surfaces(parsed, found):
        surface["name"] = _unique(surface["name"], taken)
        taken.append(surface["name"])
        made.append((surfaces.save(surface, desk.settings.set_name, prompt, desk.settings.surfaces_dir), surface))
    now = time.time_ns()
    for i, (path, _) in enumerate(made):  # the hardware pages stay in order whatever the clock's grain
        os.utime(path, ns=(now + i * 1_000_000, now + i * 1_000_000))
    return desk.adopt_surfaces(made)


def _unique(name: str, taken: list[str]) -> str:
    lower = [t.lower() for t in taken]
    out, n = name, 2
    while out.lower() in lower:
        out, n = f"{name[: 24 - len(str(n)) - 1]} {n}", n + 1
    return out


def listing(desk: Desk) -> list[dict[str, Any]]:
    """The set's saved pages: id, title, who made it, when, and how many controls. A file that is not a page is
    passed over."""
    out = []
    for path in sorted(pages_dir(desk).glob("*.json")):
        try:
            p = page.load(path)
        except ValueError:
            continue
        out.append(
            {"id": p.id or path.stem, "title": p.title, "made_by": p.made_by, "at": p.at, "controls": len(p.controls())}
        )
    return out


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
    found, missing = describe.look(desk.conn, parsed.targets())
    return 200, {"ok": True, "layout": page_layout.layout(parsed, found, missing).model_dump()}


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
