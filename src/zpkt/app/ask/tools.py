"""The tools an agent has: four app commands, and the key that lets a session call them.

An agent reaches the app through a small MCP server (mcp.py) that calls `POST /app/ask/api/tool`. Each call carries
the session's id and its token. The gate checks the token, keeps only the four tools below, and submits the command
to the bus as `agent`, grouped by the session. Three of them change nothing in Live: make a page, read the state,
read the measurement. The fourth, `change_live`, is the one way an agent changes Live: a batch of steps (set values;
add, bypass, enable or reorder devices) in one call, which the app checks whole, runs one short step at a time and
keeps as one History row that one undo takes back (zpkt.app.change; why an agent may: zpkt.app.effects). An agent
cannot name any other command: `mix.set`, `transport`, `live.run` and the rest are not here and are refused.
Nothing in this package imports zpkt.live.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Any

from zpkt.app.bus import Bus, Command, Reply


@dataclass(frozen=True)
class Tool:
    name: str  # what the agent calls it
    kind: str  # the bus command it is
    description: str
    schema: dict[str, Any]  # JSON Schema of its arguments


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
        "routing or clips, or run code; monitor tracks (mon ...) and Main's desk devices are never changed; at "
        "most 40 steps and 8 added devices per call.",
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
)
BY_NAME = {t.name: t for t in TOOLS}


class ToolGate:
    """Checks a session's token and runs its tool calls on the bus as the agent."""

    def __init__(self, bus: Bus, key: bytes | None = None) -> None:
        self.bus = bus
        self.key = key or secrets.token_bytes(32)

    def token(self, session_id: str) -> str:
        """The session's token: it proves a call came from an agent this app started for that session."""
        return hmac.new(self.key, session_id.encode(), hashlib.sha256).hexdigest()

    def call(self, session_id: str, token: str, tool: str, args: dict[str, Any]) -> Reply:
        if not hmac.compare_digest(self.token(session_id), str(token)):
            return 403, {"error": "that token is not for this session"}
        spec = BY_NAME.get(tool)
        if spec is None:
            return 404, {"error": f"no tool {tool!r}; the tools are {', '.join(BY_NAME)}"}
        return self.bus.submit(Command(spec.kind, "agent", args, group=f"ask-{session_id}"))
