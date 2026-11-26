"""The commands an agent may use: draft a page (linted and saved; the reply has the link you open it by), read the
state, read the last measurement, propose an Option (filed in the app's one store of Options, zpkt.app.renders).

They are ordinary commands on the bus, so a person or the API may use them too. An agent gets exactly these four,
by `zpkt.app.ask.tools`, and the bus tags its calls `agent`. None of them moves Live. `page.draft` reads Live to
check the page against the open set; that goes through the app's connection and its lock like any other command.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from zpkt.app import effects
from zpkt.app import pages as app_pages
from zpkt.app.bus import BadRequest, Bus, Command, Reply
from zpkt.app.commands import options_pick
from zpkt.live import describe as describe_live
from zpkt.live import page as pages  # the page spec; `zpkt.app.pages` is the fuller `page.make`

if TYPE_CHECKING:
    from zpkt.app.desk import Desk

MAX_MEASUREMENT_BYTES = 16000  # about 4,000 tokens in one reply; a longer one is sent as a summary


def page_make(desk: Desk, cmd: Command) -> Reply:
    """Parse the spec, check it against the open set, and save it only when it has no error."""
    spec = cmd.args.get("spec", cmd.args.get("page"))  # `page` is the older key
    if not isinstance(spec, dict):
        raise BadRequest("the body needs 'spec', a page spec (title and groups of controls)")
    try:
        page = pages.parse({**spec, "made_by": cmd.who})
    except ValueError as exc:
        raise BadRequest(f"the page is not valid: {exc}") from None
    found, missing = describe_live.look(desk.conn, page.targets())
    problems = pages.lint(page, found, missing)
    if any(p["level"] == "error" for p in problems):
        return 422, {"error": "the page has errors and was not saved: fix them and try again", "problems": problems}
    page.at = time.strftime("%Y-%m-%d %H:%M:%S")
    path = pages.save(page, desk.settings.set_name, app_pages.pages_dir(desk))  # where GET /api/pages lists it
    link = app_pages.link(page.id)
    return 200, {
        "ok": True,
        "id": page.id,
        "title": page.title,
        "link": link,  # opening it is the person's act (page.open): it puts the page on the Desk and the MiniLab
        "markdown": f"[{page.title}]({link})",
        "file": path.name,
        "problems": problems,
        "labels": pages.labels(page, found),
    }


def state_read(desk: Desk, cmd: Command) -> Reply:
    """What the desk shows now: the set, its pages, what is heard, and whether Live's pager is attached."""
    state = desk.snapshot()
    return 200, {
        "set": desk.settings.set_name,
        "pages": desk.page_names(),
        "page": state["page"],
        "attached": state["attached"],
        "playing": state["playing"],
        "monitor": state["monitor"],
        "values": state["values"],
        "match": state["match"],
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


def option_propose(desk: Desk, cmd: Command) -> Reply:
    """File a proposal in the app's one store of Options. Nothing moves until you pick it."""
    try:
        option = desk.options.propose(cmd.args.get("option"), cmd.who, cmd.group)
    except ValueError as exc:
        raise BadRequest(str(exc)) from None
    return 200, {"ok": True, "option": option}


def register(bus: Bus, desk: Desk) -> None:
    """Put the agent commands on the bus. `option.pick` is the older name of `options.pick`, for you only: only a
    pick by you lets an agent's move pass."""
    bus.option_picked = desk.options.is_picked
    effects.register(bus, "option.pick", lambda cmd: options_pick(desk, cmd), touches_live=True, callers=("you",))
    table: dict[str, tuple[Any, bool]] = {  # kind -> (handler, touches Live)
        "page.draft": (page_make, True),
        "desk.state": (state_read, False),
        "state.read": (state_read, False),  # the older name of desk.state
        "measurement.read": (measurement_read, False),
        "options.propose": (option_propose, False),
        "option.propose": (option_propose, False),  # the older name of options.propose
    }
    for kind, (handler, touches) in table.items():

        def run(cmd: Command, handler: Any = handler) -> Reply:
            reply: Reply = handler(desk, cmd)
            return reply

        effects.register(bus, kind, run, touches_live=touches)
