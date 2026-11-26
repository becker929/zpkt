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

An agent cannot name any other command: `mix.set`, `transport`, `live.run` and the rest are not here and are
refused. Nothing in this package imports zpkt.live.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from zpkt.app.bus import APPROVED_BY_USER, Bus, Command, Reply

PROPOSE_WAIT_S = 240.0  # how long a proposal waits for the tap (Gemini CLI gives an MCP call 10 minutes in all)
PROPOSE_OPTIONS: list[dict[str, Any]] = [
    {"id": "yes", "name": "Do it", "kind": "allow_once"},
    {"id": "no", "name": "Don't", "kind": "reject_once"},
]


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
        "`undo`, the History row that one undo takes back. It cannot remove a device, make a track, change "
        "routing or clips, or run code: for those, use propose_live, which asks the person first. Monitor tracks "
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
        "never read a value back in the code that wrote it). The whole batch is checked before the person is "
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


def outcome(code: int, reply: dict[str, Any]) -> dict[str, Any]:
    """What came of a batch the person said yes to, as the card shows it: done, failed at a step (the steps before
    it are done), or refused (nothing changed)."""
    if code == 200:
        return {"state": "done", "done": int(reply.get("done") or 0)}
    failed = reply.get("failed")
    if isinstance(failed, dict):
        return {
            "state": "failed",
            "done": int(reply.get("done") or 0),
            "step": failed.get("step"),
            "note": str(failed.get("why") or "")[:200],
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

    def call(self, session_id: str, token: str, tool: str, args: dict[str, Any]) -> Reply:
        if not hmac.compare_digest(self.token(session_id), str(token)):
            return 403, {"error": "that token is not for this session"}
        spec = BY_NAME.get(tool)
        if spec is None:
            return 404, {"error": f"no tool {tool!r}; the tools are {', '.join(BY_NAME)}"}
        if spec.check:
            return self._proposed(session_id, spec, args)
        return self.bus.submit(Command(spec.kind, "agent", args, group=f"ask-{session_id}"))

    def _proposed(self, session_id: str, spec: Tool, args: dict[str, Any]) -> Reply:
        """A tool that waits for the person: check, show the card, wait for the tap, then run with their word."""
        group = f"ask-{session_id}"
        if self.ask is None:
            return 503, {"ok": False, "error": "this app has no chat to ask the person in: nothing changed"}
        code, card = self.bus.submit(Command(spec.check, "agent", args, group=group))
        if code != 200:
            return code, card
        shown = {"kind": spec.name, "title": card["why"], "steps": card["steps"]}
        answer = self.ask(session_id, shown, PROPOSE_OPTIONS, spec.wait_s)
        if answer is None:
            return 409, {
                "ok": False,
                "error": "no turn of this conversation is running, so there is nobody to ask: nothing changed",
            }
        if answer.choice != "yes":
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
        code, reply = self.bus.submit(Command(spec.kind, "agent", args, approval=APPROVED_BY_USER, group=group))
        self.tell(session_id, {"type": "proposal", "id": answer.card, **outcome(code, reply)})
        return code, {**reply, "approved": True}
