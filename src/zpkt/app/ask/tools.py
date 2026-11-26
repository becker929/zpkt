"""The tools an agent has: three app commands, and the key that lets a session call them.

An agent reaches the app through a small MCP server (mcp.py) that calls `POST /app/ask/api/tool`. Each call carries
the session's id and its token. The gate checks the token, keeps only the three tools below, and submits the command
to the bus as `agent`, grouped by the session, so one undo takes the whole ask back. An agent cannot name any other
command: `mix.set`, `transport` and the rest are not here and are refused. Nothing in this package imports zpkt.live.
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
