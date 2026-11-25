"""The page's event shape, and what is worked out from events. Pure: events in, events or text out.

An event is a JSON object with a `type`: prompt, message, tool_use, tool_result, result, error, log, run_end, init,
compact, notes, summary, surface, permission, permission_answer. The store (store.py) numbers them with `seq`.
Claude Code's stream-json is translated into this shape (`ClaudeStream`); Gemini's ACP updates are translated in
gemini.py. Both engines hand each other the conversation so far (`handoff_context`).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

Event = dict[str, Any]

ENGINES = ("claude", "gemini")
ENGINE_NAME = {"claude": "Claude Code", "gemini": "Gemini CLI"}

# Same pattern the page uses to tell that a shell command failed whatever status the CLI gave it.
FAILED_RUN = re.compile(
    r"^(ERROR|GUARD):|^Traceback \(most recent call last\)|Exit Code: [1-9]|WARNING: the render is silent", re.M
)

FAILS_IN_A_ROW, SAME_CALL, MAX_CALLS = 4, 4, 40
KEEP_OUTPUT = 50000


def flat(content: Any) -> str:
    """A tool result's content as text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(str(b.get("text", "")))
            elif isinstance(b, dict) and b.get("type") == "image":
                parts.append("[image]")
            else:
                parts.append(json.dumps(b))
        return "\n".join(parts)
    return "" if content is None else json.dumps(content)


class ClaudeStream:
    """Turns Claude Code's stream-json objects into page events. One per run: it keeps the run's state."""

    def __init__(self) -> None:
        self.current: str | None = None  # id of the API message being streamed
        self.streamed: set[str] = set()  # message ids whose text already arrived as deltas
        self.tools = 0

    def feed(self, j: dict[str, Any]) -> list[Event]:
        events = self._one(j)
        parent = j.get("parent_tool_use_id")  # events from inside a subagent name the call that started it
        return [{**e, "parent": parent} for e in events] if parent else events

    def _one(self, j: dict[str, Any]) -> list[Event]:
        kind = j.get("type")
        if kind == "system":
            if j.get("subtype") == "compact_boundary":
                return [{"type": "compact"}]
            if j.get("subtype") == "init":
                return [{"type": "init", "session_id": j.get("session_id"), "model": j.get("model")}]
            return []
        if kind == "stream_event":
            return self._partial(j.get("event") or {})
        if kind == "assistant":
            return self._assistant(j)
        if kind == "user":
            return self._results(j)
        if kind == "result":
            return [self._result(j)]
        return []

    def _partial(self, e: dict[str, Any]) -> list[Event]:
        if e.get("type") == "message_start":
            self.current = (e.get("message") or {}).get("id")
        delta = e.get("delta") or {}
        if e.get("type") == "content_block_delta" and delta.get("type") == "text_delta" and delta.get("text"):
            if self.current:
                self.streamed.add(self.current)
            return [{"type": "message", "role": "assistant", "content": delta["text"], "delta": True}]
        block = e.get("content_block") or {}
        if e.get("type") == "content_block_start" and block.get("type") == "text" and self.current in self.streamed:
            return [{"type": "message", "role": "assistant", "content": "\n\n", "delta": True}]
        return []

    def _assistant(self, j: dict[str, Any]) -> list[Event]:
        out: list[Event] = []
        message = j.get("message") or {}
        for b in message.get("content") or []:
            if b.get("type") == "text" and b.get("text") and message.get("id") not in self.streamed:
                out.append({"type": "message", "role": "assistant", "content": b["text"], "delta": True})
            if b.get("type") == "tool_use":
                if not j.get("parent_tool_use_id"):
                    self.tools += 1
                out.append(
                    {
                        "type": "tool_use",
                        "tool_name": b.get("name"),
                        "tool_id": b.get("id"),
                        "parameters": b.get("input") or {},
                    }
                )
        return out

    def _results(self, j: dict[str, Any]) -> list[Event]:
        content = (j.get("message") or {}).get("content")
        if not isinstance(content, list):
            return []
        return [
            {
                "type": "tool_result",
                "tool_id": b.get("tool_use_id"),
                "status": "error" if b.get("is_error") else "success",
                "output": flat(b.get("content"))[:KEEP_OUTPUT],
            }
            for b in content
            if b.get("type") == "tool_result"
        ]

    def _result(self, j: dict[str, Any]) -> Event:
        u = j.get("usage") or {}
        total = sum(
            u.get(k) or 0
            for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
        )
        stats: dict[str, Any] = {"duration_ms": j.get("duration_ms")}
        if total:
            stats["total_tokens"] = total
        if self.tools:
            stats["tool_calls"] = self.tools
        if j.get("modelUsage"):
            stats["models"] = j["modelUsage"]
        ev: Event = {"type": "result", "status": "error" if j.get("is_error") else "success", "stats": stats}
        cost = j.get("total_cost_usd")
        if isinstance(cost, int | float) and cost > 0:
            ev["cost_usd"] = cost
        return ev


def handoff_context(events: Iterable[Event], max_chars: int = 24000, since: bool = False) -> str:
    """The conversation so far as text, for an engine that joins a session the other engine started."""
    turns: list[dict[str, str]] = []
    cur: dict[str, str] | None = None
    for e in events:
        if e.get("type") == "prompt" and not e.get("auto"):
            cur = {"user": e.get("text", ""), "engine": e.get("engine") or "gemini", "answer": ""}
            turns.append(cur)
        elif e.get("parent"):
            continue  # a subagent's own work: its report reaches the main agent as a tool result
        elif e.get("type") == "message" and e.get("role") != "user" and cur is not None:
            cur["answer"] += e.get("content") or ""
        elif e.get("type") == "tool_use" and cur is not None:
            cur["answer"] += f"\n[used tool {e.get('tool_name')}]\n"
    if not turns:
        return ""
    text = "\n\n".join(
        f"### User\n{t['user']}\n\n### {ENGINE_NAME.get(t['engine'], t['engine'])}\n{t['answer'].strip() or '(no text)'}"
        for t in turns
    )
    if len(text) > max_chars:
        text = "…(earlier turns cut)…\n" + text[-max_chars:]
    if since:
        return (
            "While you were away, the person talked to another agent in this session. "
            f"Here is what was said, so you can carry on:\n\n{text}\n\n---\n\n"
        )
    return (
        "This conversation started with another agent in the same folder. "
        f"Here is what was said so far, so you can carry on:\n\n{text}\n\n---\n\n"
    )


def first_line(output: Any) -> str:
    text = output if isinstance(output, str) else json.dumps(output if output is not None else "")
    lines = text.split("\n")
    found = next((ln for ln in lines if re.match(r"^(ERROR|GUARD):|WARNING: the render is silent", ln)), None)
    line = found or next((ln for ln in lines if ln.strip()), "")
    return re.sub(r"^(ERROR|GUARD):\s*", "", line).strip()[:240]


class Budget:
    """A failure budget for one agent turn. A weak model that hits an error it does not understand tries again and
    again; this stops the turn as soon as it is plainly going nowhere: `fails` failed calls in a row, the same call
    `same` times, or more than `calls` calls. `watch(event)` returns None, or one sentence saying why to stop."""

    def __init__(self, fails: int = FAILS_IN_A_ROW, same: int = SAME_CALL, calls: int = MAX_CALLS) -> None:
        self.fails, self.same, self.calls = fails, same, calls
        self.in_row = 0
        self.total = 0
        self.last = ""
        self.done = False
        self.seen: dict[str, int] = {}

    def _stop(self, why: str) -> str:
        self.done = True
        return (
            f"{why} I stopped the agent so it does not keep trying; nothing else was changed. "
            + (f"The last error was: {self.last}. " if self.last else "")
            + "Say it another way, or check that Live is not stuck."
        )

    def watch(self, ev: Event) -> str | None:
        if self.done or ev.get("parent"):
            return None  # a subagent's calls are its own business
        if ev.get("type") == "tool_use":
            self.total += 1
            key = f"{ev.get('tool_name')} {json.dumps(ev.get('parameters') or {}, sort_keys=True)}"
            n = self.seen[key] = self.seen.get(key, 0) + 1
            if n >= self.same:
                return self._stop(f"The agent ran the same command {n} times.")
            if self.total > self.calls:
                return self._stop(f"The agent made more than {self.calls} tool calls in one turn.")
        if ev.get("type") == "tool_result":
            out = ev.get("output")
            text = out if isinstance(out, str) else json.dumps(out if out is not None else "")
            if ev.get("status") == "error" or FAILED_RUN.search(text):
                self.in_row += 1
                self.last = first_line(out)
                if self.in_row >= self.fails:
                    return self._stop(f"{self.in_row} commands failed in a row.")
            else:
                self.in_row = 0
        return None
