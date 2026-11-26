"""A fake LLM provider for tests: it runs a script of steps and never talks to a model.

A step is an event to emit, or a `Call(tool, args)` which goes through the same gate an agent's MCP call does, so a
test sees the bus, the checks and the `agent` tag. `Wait` blocks until `cancel` is set (a long run to stop).
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from zpkt.app.ask.compaction import INSTRUCTIONS
from zpkt.app.ask.events import Event
from zpkt.app.ask.provider import Emit, Outcome, Turn
from zpkt.app.ask.tools import ToolGate


@dataclass(frozen=True)
class Call:
    tool: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Wait:
    pass


@dataclass(frozen=True)
class Permit:
    """Ask for a permission, then say what came of it."""

    title: str


@dataclass(frozen=True)
class Started:
    """The engine now has a conversation of its own (a real one says so once it answers), under this id."""

    engine_id: str = ""


Step = Event | Call | Wait | Permit | Started


class ScriptedProvider:
    """Plays `script` for every turn. `seen` keeps each Turn it was given and `replies` what its calls got back.
    A turn that asks for a compaction's summary plays `summary` instead and is kept in `summaries`; with
    `summary_outcome` that turn ends so (a summary that fails)."""

    def __init__(
        self,
        engine: str,
        script: Sequence[Step],
        gate: ToolGate | None = None,
        outcome: Outcome | None = None,
        summary: Sequence[Step] | None = None,
        summary_outcome: Outcome | None = None,
    ) -> None:
        self.engine, self.script, self.gate, self.outcome = engine, list(script), gate, outcome or Outcome(0)
        self.summary, self.summary_outcome = summary, summary_outcome
        self.summaries: list[Turn] = []
        self.seen: list[Turn] = []
        self.replies: list[tuple[int, dict[str, Any]]] = []
        self.answers: list[str | None] = []

    def available(self) -> dict[str, Any]:
        return {"id": self.engine, "name": self.engine}

    def run(self, turn: Turn, emit: Emit, cancel: threading.Event) -> Outcome:
        summing = self.summary is not None and turn.prompt.startswith(INSTRUCTIONS)
        (self.summaries if summing else self.seen).append(turn)
        n = 0
        for step in (self.summary or []) if summing else self.script:
            if cancel.is_set():
                return Outcome(None, "SIGTERM")
            if isinstance(step, Wait):
                cancel.wait(10)
                return Outcome(None, "SIGTERM")
            if isinstance(step, Started):
                turn.mark_started(step.engine_id)
            elif isinstance(step, Permit):
                self.answers.append(
                    turn.ask_permission(
                        {"title": step.title, "kind": "edit"},
                        [
                            {"id": "yes", "name": "Allow", "kind": "allow_once"},
                            {"id": "no", "name": "Reject", "kind": "reject_once"},
                        ],
                    )
                )
            elif isinstance(step, Call):
                assert self.gate is not None and turn.tools is not None
                n += 1
                tid = f"call-{n}"
                emit({"type": "tool_use", "tool_name": step.tool, "tool_id": tid, "parameters": step.args})
                env = turn.tools.env
                code, body = self.gate.call(env["ZPKT_APP_SESSION"], env["ZPKT_APP_TOKEN"], step.tool, step.args)
                self.replies.append((code, body))
                emit(
                    {
                        "type": "tool_result",
                        "tool_id": tid,
                        "status": "error" if code >= 400 else "success",
                        "output": str(body),
                    }
                )
            else:
                emit(dict(step))
        return (self.summary_outcome or Outcome(0)) if summing else self.outcome
