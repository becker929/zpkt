"""The commands an agent may use: draft a page (linted and saved, not put on the desk), read the state, read the last measurement, propose an Option.

They are ordinary commands on the bus, so a person or the API may use them too. An agent gets exactly these four,
by `zpkt.app.ask.tools`, and the bus tags its calls `agent`. None of them moves Live. `page.draft` reads Live to
check the page against the open set; that goes through the app's connection and its lock like any other command.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from zpkt.app.bus import BadRequest, Bus, Command, Effect, Reply, Spec
from zpkt.app.proposals import OptionStore
from zpkt.live import describe as describe_live
from zpkt.live import page as pages  # the page spec; `zpkt.app.pages` is the fuller `page.make`

if TYPE_CHECKING:
    from zpkt.app.desk import Desk

MAX_MEASUREMENT_BYTES = 60000


def page_make(desk: Desk, cmd: Command) -> Reply:
    """Parse the spec, check it against the open set, and save it only when it has no error."""
    spec = cmd.args.get("page")
    if not isinstance(spec, dict):
        raise BadRequest("the body needs 'page', a page spec (title and groups of controls)")
    try:
        page = pages.parse({**spec, "made_by": cmd.who})
    except ValueError as exc:
        raise BadRequest(f"the page is not valid: {exc}") from None
    found, missing = describe_live.look(desk.conn, page.targets())
    problems = pages.lint(page, found, missing)
    if any(p["level"] == "error" for p in problems):
        return 422, {"error": "the page has errors and was not saved: fix them and try again", "problems": problems}
    path = pages.save(page, desk.settings.set_name)
    return 200, {
        "ok": True,
        "id": page.id,
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
    import json

    text = json.dumps(analysis)
    if len(text) > MAX_MEASUREMENT_BYTES:
        return 200, {"sources": sorted(analysis.get("sources", {})), "cut": True, "note": "too long to send whole"}
    return 200, {"analysis": analysis}


def option_propose(options: OptionStore) -> Any:
    def handler(desk: Desk, cmd: Command) -> Reply:
        try:
            option = options.propose(cmd.args.get("option"), cmd.who, cmd.group)
        except ValueError as exc:
            raise BadRequest(str(exc)) from None
        return 200, {"ok": True, "option": option}

    return handler


def register(bus: Bus, desk: Desk, options: OptionStore) -> None:
    """Put the agent commands on the bus."""
    table: dict[str, tuple[Any, Effect, bool]] = {
        "page.draft": (page_make, "make", True),
        "state.read": (state_read, "read", False),
        "measurement.read": (measurement_read, "read", False),
        "option.propose": (option_propose(options), "make", False),
    }
    for kind, (handler, effect, touches) in table.items():

        def run(cmd: Command, handler: Any = handler) -> Reply:
            reply: Reply = handler(desk, cmd)
            return reply

        bus.register(kind, Spec(run, effect, touches))
