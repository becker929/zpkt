"""The tools an agent has: five app commands, and the key that lets a session call them.

An agent reaches the app through a small MCP server (mcp.py) that calls `POST /app/ask/api/tool`. Each call carries
the session's id and its token. The gate checks the token, keeps only the five tools below, and submits the command
to the bus as `agent`, grouped by the session. Three of them change nothing in Live: make a page, read the state,
read the measurement. The other two are the two tiers of changing Live (Anthony, 26 November 2026):

- `change_live`, act then undo: a batch of steps (set values; add, bypass, enable or reorder devices) in one call,
  which the app checks whole, runs one short step at a time and keeps as one History row that one undo takes back
  (zpkt.app.change; why an agent may: zpkt.app.effects).
- `propose_live`, ask first: a batch that may also remove a device, make a track or run code (zpkt.app.propose).
  The gate has the app check it whole (`live.propose.check`, a read). A batch that passes is shown as a card in the
  chat through the permission desk (permissions.py), and the call blocks, for at most PROPOSE_WAIT_S, until the
  person taps. Only after "Do it" does the gate send `live.propose` with the person's word (`approval`), still as
  `agent`. After "Don't", with no answer, or when the turn is stopped, nothing is sent and the reply says so. What
  came of it goes into the transcript as a `proposal` event, so the card shows it. Nothing of Live is held while
  the card waits: the bus is free for every other command.

Abilities are more tools, one each (Anthony, 26 November 2026: "an 'Always' button which adds the code to an auto
allowed set, as new abilities with documentation and everything, run the same as other tools"). A proposal with a
code step offers a third answer, "Always": the batch runs as after "Do it" (the gate adds `always` to the command;
an agent's own `always` never gets through), and each code step that ran is kept as an ability
(zpkt.app.abilities). From then on the tool list has `ability_<name>` for it, with a description made from what was
kept and an input schema made from its parameters (`ability_tool`). A call of one goes to `ability.run` as `agent`
with no card and no wait, in every mode: the tap on "Always" was the standing yes. The person takes it back by
removing the ability (`ability.remove`, which an agent cannot ask for). `abilities_markdown` is the same list as a
page to read: what the agent may do on its own now.

An agent cannot name any other command: `mix.set`, `transport`, `live.run` and the rest are not here and are
refused. Nothing in this package imports zpkt.live.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from zpkt.app.abilities import TOOL_PREFIX as ABILITY_PREFIX  # an ability's tool is named ability_<name>
from zpkt.app.bus import APPROVED_BY_USER, Bus, Command, Reply

PROPOSE_WAIT_S = 240.0  # how long a proposal waits for the tap (Gemini CLI gives an MCP call 10 minutes in all)
YES: dict[str, Any] = {"id": "yes", "name": "Do it", "kind": "allow_once"}
ALWAYS: dict[str, Any] = {"id": "always", "name": "Always", "kind": "allow_always"}
NO: dict[str, Any] = {"id": "no", "name": "Don't", "kind": "reject_once"}
PROPOSE_OPTIONS = [YES, NO]  # a proposal with code that can be kept also offers ALWAYS, between the two
ABILITY_TOOL = re.compile(re.escape(ABILITY_PREFIX) + r"[a-z][a-z0-9_]{0,39}")


@dataclass(frozen=True)
class Tool:
    name: str  # what the agent calls it
    kind: str  # the bus command it is
    description: str
    schema: dict[str, Any]  # JSON Schema of its arguments
    check: str = ""  # for a tool that waits for the person's tap: the read that checks the ask and writes its card
    wait_s: float = 0.0  # ... and how long the person has. mcp.py's HTTP timeout is longer by this much


@dataclass(frozen=True)
class Answer:
    """What came of a card the person was shown."""

    card: str  # the card's id in the transcript (the `permission` event's)
    choice: str | None  # the option tapped; None when nobody tapped
    stopped: bool = False  # the turn was stopped while the card waited


# (session, card, options, seconds to wait) -> the answer; None when no turn of that session is running.
Asker = Callable[[str, dict[str, Any], list[dict[str, Any]], float], Answer | None]
Teller = Callable[[str, dict[str, Any]], object]  # (session, event): into the transcript


TOOLS: tuple[Tool, ...] = (
    Tool(
        "make_page",
        "page.draft",
        "Make a page of controls for the open set, or change one you made. It is checked against Live's own names "
        "and ranges and saved only when it has no error. `spec` has a title and groups of controls; each control has "
        "a `target` (a state key such as 'Kick bus/volume') and may say its `role`, `weight` (1 to 3), `label` and "
        "`range`. It cannot say widget, colour, size or MIDI slot. To let the person try an alternative, add "
        "`compare`: {name, states: [{name}, {name, writes: [{target, to}]}]} with 2 to 8 states, one pad each; `to` "
        "is the raw number read_state gives (r); a state with no writes is the mix as it is now. To change a page "
        "you made, send the whole spec again with its `id` (from the earlier reply): the page is replaced where it "
        "is. Nothing in Live moves: the person's press on a pad switches the mix. The reply has `markdown`, a link "
        "to the page (/app/#page=<id>): put it in your answer so the person can open the page on the Desk and the "
        "MiniLab.",
        {
            "type": "object",
            "properties": {"spec": {"type": "object", "description": "The page spec."}},
            "required": ["spec"],
        },
    ),
    Tool(
        "read_state",
        "desk.state",
        "What the desk shows now: the set, its pages, what is heard, and the values of the controls.",
        {"type": "object", "properties": {}},
    ),
    Tool(
        "read_measurement",
        "measurement.read",
        "The last measurement of the renders: loudness, spectrum and the references, as the desk has them.",
        {"type": "object", "properties": {}},
    ),
    Tool(
        "change_live",
        "live.change",
        "Change Live yourself: set values, and add, bypass, enable or reorder devices on existing tracks. Send ALL "
        "the steps of one request in ONE call. `why` is a few words for the History row. Each step is one of: "
        '{"set": "<state key>", "to": <raw number>} (keys and raw numbers as read_state gives them, e.g. '
        '"Kick bus/volume", "Kick bus/desk EQ/1 Gain A", "Kick bus/mute"); {"add": "<audio effect, as the '
        'browser in Live names it>", "track": "<track>", "at": <index, optional: last>}; {"device": "<device>", "track": '
        '"<track>", "on": true|false}; {"move": "<device>", "track": "<track>", "to": <index>}. A value on a '
        'device added earlier in the same call is "<track>/<device>/<parameter>". The whole batch is checked '
        "before anything moves: if anything is wrong nothing changes, and `problems` lists every fault to fix. "
        "Then the steps run in order; the reply has `done`, `now` (each key written: [shown, raw]), `added`, and "
        '`undo`, the History row that one undo takes back. A step {"use": "<ability>", "args": {...}} runs an '
        "ability in its place among the steps: code the person allowed for good with Always (read_state lists "
        "the abilities and their parameters); the reply's `ran` has its result, and undo does not take it back "
        "(`no_undo`). It cannot remove a device, make a track, change routing or clips, or run code that is not "
        "an ability: for those, use propose_live, which asks the person first. Monitor tracks "
        "(mon ...) and Main's desk devices are never changed; at most 40 steps and 8 added devices per call.",
        {
            "type": "object",
            "properties": {
                "why": {"type": "string", "description": "A few words for the History row."},
                "steps": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 40,
                    "items": {
                        "type": "object",
                        "properties": {
                            "set": {"type": "string"},
                            "to": {"type": "number"},
                            "add": {"type": "string"},
                            "device": {"type": "string"},
                            "move": {"type": "string"},
                            "track": {"type": "string"},
                            "at": {"type": "integer", "minimum": 0},
                            "on": {"type": "boolean"},
                            "use": {"type": "string", "description": "An ability's name, to run it as a step."},
                            "args": {"type": "object", "description": "The ability's arguments."},
                        },
                    },
                },
            },
            "required": ["why", "steps"],
        },
    ),
    Tool(
        "propose_live",
        "live.propose",
        "Propose a change to Live that needs the person's yes: remove a device, make a track, or run code in Live "
        "(routing, clips, anything change_live cannot do). The person sees `why` and every step as a card in the "
        "chat and taps Do it or Don't. This call waits for that tap, up to 4 minutes, and then the app runs the "
        "steps. Send ALL the steps of one request in ONE call. `why` is a few words: the card's title and the "
        "History row. Each step is any change_live step, or one of: "
        '{"remove": "<device>", "track": "<track>"}; '
        '{"new_track": "audio"|"midi"|"return", "name": "<name>"} (made last; later steps may name it); '
        '{"code": "<Python for Live>", "does": "<one plain sentence saying what it does>"} (the person reads '
        "`does` and the code itself: at most 3 code steps of 2000 characters each; `song`, `tracks`, `returns`, "
        "`master`, `browser` and `find_track(name)` are defined and `result = ...` comes back; keep it short and "
        "never read a value back in the code that wrote it). Write a code step that may be needed again as a "
        'function of its parameters, so that it can be kept: add "name" (verb_noun for what it does in general, '
        'route_track_to_return, never for this one case, route_hats_to_drive), "params" ({"<name>": {"type": '
        '"number"|"integer"|"string"|"boolean", "description": "<what it is, with its unit>", "default": '
        '<optional>, "enum": [<optional>]}}) and "args" (this run\'s values; a parameter without a default is '
        "required). Everything that could differ next time (track, device, amount, bar, name) is a parameter, "
        'read from the dict `args` (args["track"]); nothing that is a parameter is spelled out in the code, and '
        "every declared parameter must be read. Put what changed in `result` as a small dict, so that another "
        'ability can build on it. Code may call use("<ability>", {...}), the name written out, to run an '
        "ability that exists and get its result: build new abilities from the ones there are. Before you "
        "propose code, look at the abilities there are (read_state lists them): if one fits, call it; if one "
        "almost fits, propose THAT ability again under the same name with a broader parameter, rather than a "
        "second one. The card of a proposal with code also offers Always: the steps run as after Do it, and "
        "each code step that ran is kept as an ability, a tool of its own named ability_<name>, listed in the "
        "reply's `abilities` (`tool` is the name to call). From then on call that tool, or run it as a step "
        '{"use": "<name>", "args": {...}} here or in change_live: it runs with no card. Do not propose the same '
        "code again. The reply may carry `hints`: how to make a step more general next time. "
        "The whole batch is checked before the person is "
        "asked: if anything is wrong nobody is asked, nothing changes, and `problems` lists every fault to fix. "
        "Steps are checked against the set as it is, so no step may rely on what a code step makes. After Do it "
        "the steps run in order and the reply has `done`, `now`, `added`, `removed`, `made`, `ran` (each code "
        "step's result), `undo` and `no_undo`; a step that fails stops the batch (`failed`, `not_done`). `undo` is "
        "what one undo in History takes back: values, added and moved devices. `no_undo` lists what it does NOT "
        "take back: a removed device, a new track and code stay, so say that when you report. After Don't the "
        'reply is {"ok": false, "declined": true}; with no tap in time, {"ok": false, "unanswered": true}. In '
        "both nothing changed: say so in one sentence and do not propose it again unless the person asks. Monitor "
        "tracks (mon ...) and Main's desk devices are never changed, no device is added, moved or removed on "
        'Main, and no new track is named "mon ...". For values, and for adding, bypassing or reordering devices, '
        "use change_live instead: those need no yes.",
        {
            "type": "object",
            "properties": {
                "why": {"type": "string", "description": "A few words: the card's title and the History row."},
                "steps": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 40,
                    "items": {
                        "type": "object",
                        "properties": {
                            "set": {"type": "string"},
                            "to": {"type": "number"},
                            "add": {"type": "string"},
                            "device": {"type": "string"},
                            "move": {"type": "string"},
                            "remove": {"type": "string"},
                            "track": {"type": "string"},
                            "at": {"type": "integer", "minimum": 0},
                            "on": {"type": "boolean"},
                            "new_track": {"type": "string", "enum": ["audio", "midi", "return"]},
                            "name": {"type": "string"},
                            "code": {"type": "string", "maxLength": 2000},
                            "does": {"type": "string", "maxLength": 140},
                            "params": {
                                "type": "object",
                                "description": "A code step's parameters, to keep it as an ability.",
                                "additionalProperties": {
                                    "type": "object",
                                    "properties": {
                                        "type": {"type": "string", "enum": ["number", "integer", "string", "boolean"]},
                                        "description": {"type": "string"},
                                        "default": {},
                                        "enum": {"type": "array"},
                                    },
                                    "required": ["type", "description"],
                                },
                            },
                            "args": {"type": "object", "description": "This run's values for the parameters."},
                            "use": {"type": "string", "description": "An ability's name, to run it as a step."},
                        },
                    },
                },
            },
            "required": ["why", "steps"],
        },
        check="live.propose.check",
        wait_s=PROPOSE_WAIT_S,
    ),
)
BY_NAME = {t.name: t for t in TOOLS}


# ---- abilities as tools ------------------------------------------------------------------------------------------


def param_line(name: str, p: dict[str, Any]) -> str:
    """ "track (string): the track to send from" / "amount (number, default 0.5): ...": one parameter in a line."""
    extra = "".join(
        f", {word} {json.dumps(p[key])}" for key, word in (("enum", "one of"), ("default", "default")) if key in p
    )
    return f"{name} ({p['type']}{extra}): {p['description']}"


def ability_description(a: dict[str, Any]) -> str:
    """What an agent reads about an ability: what it does first, then one line per parameter, then how it runs."""
    params = a.get("params") or {}
    lines = [str(a["does"]), *(f"- {param_line(n, p)}" for n, p in params.items())]
    if a.get("missing"):
        lines.append(f"BROKEN: it uses {', '.join(a['missing'])}, which is gone. Propose that again before calling.")
    elif a.get("uses"):
        lines.append(f"Uses {', '.join(a['uses'])}.")
    lines.append(
        "An ability (the person's Always): runs at once, no card. "
        + ("Only reads: no History row." if a.get("reads") else "One History row a run; undo does not take it back.")
        + ' Reply {"ok", "result"}; after an error part of it may have run.'
    )
    return "\n".join(lines)


def ability_schema(a: dict[str, Any]) -> dict[str, Any]:
    """The JSON Schema of an ability's arguments: a parameter without a default is required, nothing else is taken."""
    params = a.get("params") or {}
    keys = ("type", "description", "enum", "default")
    return {
        "type": "object",
        "properties": {n: {k: p[k] for k in keys if k in p} for n, p in params.items()},
        "required": [n for n, p in params.items() if "default" not in p],
        "additionalProperties": False,
    }


def ability_tool(a: dict[str, Any]) -> Tool:
    return Tool(ABILITY_PREFIX + a["name"], "ability.run", ability_description(a), ability_schema(a))


def abilities_markdown(found: list[dict[str, Any]], most: int) -> str:
    """The abilities as a page to read: what an agent may run on its own now."""
    out = [
        "# Abilities",
        "",
        "Code for Live that an agent may run without asking. Each was shown on a card in Ask and answered with "
        f'"Always". {len(found)} of at most {most}. Remove one in Ask (the clock button) to take that yes back.',
    ]
    for a in found:
        params = a.get("params") or {}
        out += ["", f"## {ABILITY_PREFIX}{a['name']}", "", a["does"], ""]
        out += [f"- `{n}` {param_line(n, p)[len(n) + 1 :]}" for n, p in params.items()] or ["- No parameters."]
        for key, word in (("uses", "Uses"), ("used_by", "Used by"), ("missing", "BROKEN, it uses what is gone:")):
            if a.get(key):
                out.append(f"- {word} {', '.join(a[key])}.")
        runs = int(a.get("runs") or 0)
        out.append(
            f"- Kept {a.get('made') or 'at an unknown time'}. "
            + (f"Run {runs} time{'' if runs == 1 else 's'}, last {a.get('last_run')}." if runs else "Not run since.")
        )
        out.append(
            "- Only reads: no History row." if a.get("reads") else "- Changes Live: one History row a run, no undo."
        )
        fence = "`" * max(3, 1 + max((len(m) for m in re.findall(r"`+", a["code"])), default=0))
        out += ["", f"{fence}python", a["code"].rstrip("\n"), fence]
    return "\n".join(out) + "\n"


def outcome(code: int, reply: dict[str, Any]) -> dict[str, Any]:
    """What came of a batch the person said yes to, as the card shows it: done, failed at a step (the steps before
    it are done), or refused (nothing changed). After "Always", also which code steps were kept as abilities
    ("saved": their names) and which were not ("unsaved": name and why)."""
    kept: dict[str, Any] = {}
    if "abilities" in reply:
        kept["saved"] = [str(a["name"]) for a in reply["abilities"]]
        if reply.get("not_saved"):
            kept["unsaved"] = [{"name": str(a["name"]), "why": str(a["why"])[:120]} for a in reply["not_saved"]]
    if code == 200:
        return {"state": "done", "done": int(reply.get("done") or 0), **kept}
    failed = reply.get("failed")
    if isinstance(failed, dict):
        return {
            "state": "failed",
            "done": int(reply.get("done") or 0),
            "step": failed.get("step"),
            "note": str(failed.get("why") or "")[:200],
            **kept,
        }
    problems = reply.get("problems") or []
    return {"state": "refused", "done": 0, "note": str(problems[0] if problems else reply.get("error") or "")[:200]}


class ToolGate:
    """Checks a session's token and runs its tool calls on the bus as the agent. `ask` and `tell` are the service's
    (service.py): how a card is shown and waited on, and how the transcript is told what came of it."""

    def __init__(self, bus: Bus, key: bytes | None = None) -> None:
        self.bus = bus
        self.key = key or secrets.token_bytes(32)
        self.ask: Asker | None = None
        self.tell: Teller = lambda session, event: None

    def token(self, session_id: str) -> str:
        """The session's token: it proves a call came from an agent this app started for that session."""
        return hmac.new(self.key, session_id.encode(), hashlib.sha256).hexdigest()

    def abilities(self) -> tuple[list[dict[str, Any]], int]:
        """(the abilities as the app lists them, how many it keeps at most). None when the app has no such command."""
        code, reply = self.bus.submit(Command("ability.list", "agent"))
        return (list(reply.get("abilities") or []), int(reply.get("max") or 0)) if code == 200 else ([], 0)

    def tools(self) -> list[Tool]:
        """The tools an agent has now: the five built in, then one for each ability."""
        return [*TOOLS, *(ability_tool(a) for a in self.abilities()[0])]

    def call(self, session_id: str, token: str, tool: str, args: dict[str, Any]) -> Reply:
        if not hmac.compare_digest(self.token(session_id), str(token)):
            return 403, {"error": "that token is not for this session"}
        group = f"ask-{session_id}"
        if ABILITY_TOOL.fullmatch(str(tool)):  # no card, no wait: the person's "Always" is the standing yes
            name = tool[len(ABILITY_PREFIX) :]
            return self.bus.submit(Command("ability.run", "agent", {"name": name, "args": args}, group=group))
        spec = BY_NAME.get(tool)
        if spec is None:
            return 404, {"error": f"no tool {tool!r}; the tools are {', '.join(t.name for t in self.tools())}"}
        if spec.check:
            return self._proposed(session_id, spec, args)
        return self.bus.submit(Command(spec.kind, "agent", args, group=group))

    def _proposed(self, session_id: str, spec: Tool, args: dict[str, Any]) -> Reply:
        """A tool that waits for the person: check, show the card, wait for the tap, then run with their word."""
        group = f"ask-{session_id}"
        if self.ask is None:
            return 503, {"ok": False, "error": "this app has no chat to ask the person in: nothing changed"}
        # only what the person is shown is sent on: an agent's own "always" (or anything else) never reaches the run
        args = {k: args[k] for k in ("why", "steps") if k in args}
        code, card = self.bus.submit(Command(spec.check, "agent", args, group=group))
        if code != 200:
            return code, card
        shown = {"kind": spec.name, "title": card["why"], "steps": card["steps"]}
        options = [YES, ALWAYS, NO] if card.get("always") else PROPOSE_OPTIONS
        answer = self.ask(session_id, shown, options, spec.wait_s)
        if answer is None:
            return 409, {
                "ok": False,
                "error": "no turn of this conversation is running, so there is nobody to ask: nothing changed",
            }
        if answer.choice not in ("yes", "always"):
            state = "declined" if answer.choice == "no" else "stopped" if answer.stopped else "unanswered"
            self.tell(session_id, {"type": "proposal", "id": answer.card, "state": state, "done": 0})
            if state == "declined":
                return 200, {
                    "ok": False,
                    "declined": True,
                    "message": "The person tapped Don't: nothing changed in Live. Say so in one sentence, and do "
                    "not propose it again unless they ask.",
                }
            said = (
                "The turn was stopped while the card waited"
                if state == "stopped"
                else f"Nobody tapped within {round(spec.wait_s / 60)} minutes, so the card closed"
            )
            return 200, {
                "ok": False,
                "unanswered": True,
                **({"stopped": True} if state == "stopped" else {}),
                "message": f"{said}: nothing changed in Live. Say so in one sentence; propose it again only if the "
                "person asks.",
            }
        always = answer.choice == "always" and bool(card.get("always"))
        sent = {**args, "always": True} if always else args
        code, reply = self.bus.submit(Command(spec.kind, "agent", sent, approval=APPROVED_BY_USER, group=group))
        self.tell(session_id, {"type": "proposal", "id": answer.card, **outcome(code, reply)})
        reply = {**reply, "approved": True}
        if "abilities" in reply:  # kept after "Always": each is a tool of its own from now on
            reply["always"] = True
            reply["abilities"] = [{**a, "tool": ABILITY_PREFIX + str(a["name"])} for a in reply["abilities"]]
        return code, reply
