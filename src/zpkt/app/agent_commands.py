"""The commands an agent may use: draft a page (linted and saved; the reply has the link you open it by), read the
state, read the last measurement.

They are ordinary commands on the bus, so a person or the API may use them too. An agent gets these three,
`live.change` (zpkt.app.change) and `live.propose` (zpkt.app.propose, after the person's tap), by
`zpkt.app.ask.tools`, and the bus tags its calls `agent`. None of these three moves Live. `page.draft` reads Live to
check the page against the open set; that goes through the app's connection and its lock like any other command.

When the person wants to try an alternative, the agent drafts a page with compare states (zpkt.live.page) and gives
its link. To change it ("a bit brighter") it drafts again with the same `id`: the page is written over in place.
The person's press on a pad is what moves the mix.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from zpkt.app import effects
from zpkt.app import pages as app_pages
from zpkt.app.bus import BadRequest, Bus, Command, Reply
from zpkt.live import describe as describe_live
from zpkt.live import page as pages  # the page spec; `zpkt.app.pages` is the fuller `page.make`

if TYPE_CHECKING:
    from zpkt.app.desk import Desk

MAX_MEASUREMENT_BYTES = 16000  # about 4,000 tokens in one reply; a longer one is sent as a summary


def page_make(desk: Desk, cmd: Command) -> Reply:
    """Parse the spec, check it against the open set, and save it only when it has no error. A spec with the `id` of
    a saved page writes over that page (an agent: only one an agent made). Where that page is on the desk it is
    redrawn in place; a new page is only saved, and opening it is the person's act."""
    spec = cmd.args.get("spec", cmd.args.get("page"))  # `page` is the older key
    if not isinstance(spec, dict):
        raise BadRequest("the body needs 'spec', a page spec (title and groups of controls)")
    before = None
    if spec.get("id") is not None:
        before = app_pages.saved_page(desk, str(spec["id"]))
        if before is None:
            raise BadRequest(f"no saved page has the id {spec['id']!r}: leave 'id' out to make a new page")
        if cmd.who == "agent" and before.made_by != "agent":
            raise BadRequest(f"the page {spec['id']!r} was not made by an agent: leave 'id' out to make a new page")
    try:
        page = pages.parse({**spec, "made_by": cmd.who})
    except ValueError as exc:
        raise BadRequest(f"the page is not valid: {exc}") from None
    found, missing = describe_live.look(desk.conn, page.targets())
    app_pages.whole(desk, page, found)
    problems = pages.lint(page, found, missing)
    if any(p["level"] == "error" for p in problems):
        return 422, {"error": "the page has errors and was not saved: fix them and try again", "problems": problems}
    page.at = time.strftime("%Y-%m-%d %H:%M:%S")
    redrawn = bool(before) and bool(app_pages.on_desk(desk, page.id))
    if redrawn and desk.bus.guard is not None:
        desk.bus.guard.check()  # a page for another set must not land on this one
    path = pages.save(page, desk.settings.set_name, app_pages.pages_dir(desk))  # where GET /api/pages lists it
    if redrawn:  # the same page, where it already is: the desk stays on the page it was on
        app_pages.apply(desk, page, found, page.prompt or "", arm=False)
    link = app_pages.link(page.id)
    reply: dict[str, Any] = {
        "ok": True,
        "id": page.id,
        "title": page.title,
        "link": link,  # opening it is the person's act (page.open): it puts the page on the Desk and the MiniLab
        "markdown": f"[{page.title}]({link})",
        "file": path.name,
        "updated": before is not None,
        "problems": problems,
        "labels": pages.labels(page, found),
    }
    if page.compare is not None:
        reply["compare"] = {"states": [s.name for s in page.compare.states], "baseline": page.compare.baseline}
    return 200, reply


def state_read(desk: Desk, cmd: Command) -> Reply:
    """What the desk shows now: the set, its pages, what is heard, and whether Live's pager is attached."""
    state = desk.snapshot()
    return 200, {
        "set": desk.settings.set_name,
        "pages": desk.page_names(),
        "units": app_pages.units_listing(desk),
        "page": state["page"],
        "attached": state["attached"],
        "playing": state["playing"],
        "monitor": state["monitor"],
        "values": state["values"],
        "match": state["match"],
        "compare": app_pages.compare_view(desk),
    }


def measurement_read(desk: Desk, cmd: Command) -> Reply:
    """The last measurement of the renders (analysis.json), as the desk has it."""
    analysis = desk.analysis()
    return 200, measurement_view(analysis)


def measurement_view(analysis: dict[str, Any]) -> dict[str, Any]:
    """The analysis whole when it is short; otherwise a summary: the sources and what each section holds."""
    import json

    if len(json.dumps(analysis)) <= MAX_MEASUREMENT_BYTES:
        return {"analysis": analysis}
    return {
        "sources": sorted(analysis.get("sources", {})),
        "sections": {k: sorted(v) if isinstance(v, dict) else type(v).__name__ for k, v in sorted(analysis.items())},
        "cut": True,
        "note": "too long to send whole; this lists the sources and what each section holds",
    }


def register(bus: Bus, desk: Desk) -> None:
    """Put the agent commands on the bus."""
    table: dict[str, tuple[Any, bool]] = {  # kind -> (handler, touches Live)
        "page.draft": (page_make, True),
        "desk.state": (state_read, False),
        "state.read": (state_read, False),  # the older name of desk.state
        "measurement.read": (measurement_read, False),
    }
    for kind, (handler, touches) in table.items():

        def run(cmd: Command, handler: Any = handler) -> Reply:
            reply: Reply = handler(desk, cmd)
            return reply

        effects.register(bus, kind, run, touches_live=touches)
