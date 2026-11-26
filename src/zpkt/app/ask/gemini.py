"""Gemini as an engine, over ACP: permission prompts the page answers, and the dollars each turn costs.

One `gemini --acp` process serves every session (started on first use, restarted when it dies). Gemini keeps its own
record of each session; the app keeps its ACP session id in the session's `engines.gemini.acp`, so a session resumes
(`session/load`) after a restart and from any device. The key comes only from the secret lookup the app is given.

Gemini asks before a tool it is not sure of, and `decide` answers: the app's own tools always run (they never move
Live), without a question to the person. Anything else is refused at once in `build` (the default mode: advise and
make pages), and waits for a yes from the page in the other modes.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from zpkt.app.ask.acp import Acp, AcpError
from zpkt.app.ask.cost import turn_cost
from zpkt.app.ask.engines import DEFAULT_MODE, TOOL_SERVER, ToolServer, agent_path
from zpkt.app.ask.events import Event
from zpkt.app.ask.provider import AskPermission, Emit, Outcome, Turn
from zpkt.app.ask.tools import TOOLS

# our mode -> Gemini's mode. `build` is Gemini's default too: it asks, and `decide` answers for the person.
GEMINI_MODE = {
    "auto": "yolo",
    "build": "default",
    "ask": "default",
    "auto_edit": "autoEdit",
    "yolo": "yolo",
    "plan": "plan",
}
APP_TOOLS = re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(t.name) for t in TOOLS) + r")(?![A-Za-z_])")
APP_SERVER = re.compile(rf"(?<![A-Za-z]){TOOL_SERVER}(?![A-Za-z])", re.I)
OWN_KINDS = ("edit", "delete", "move", "execute")  # Gemini's own file and shell tools: never taken for the app's
MODE_UPDATE = re.compile(r"\[MODE_UPDATE\] (\w+)")
KEEP_TEXT = 6000
DEFAULT_MODEL = "gemini-4-neon"  # one model for a session: a switch mid-session loses the prompt cache

Secret = Callable[[str], str | None]


def text_of(content: Any) -> str:
    return str(content.get("text", "")) if isinstance(content, dict) and content.get("type") == "text" else ""


def tool_view(tc: Mapping[str, Any]) -> dict[str, Any]:
    """What the page shows of a tool call: title, kind, status, files, and a bounded view of its content."""
    out: dict[str, Any] = {k: tc[k] for k in ("title", "kind", "status") if k in tc}
    if tc.get("locations"):
        out["paths"] = [loc.get("path", "") for loc in tc["locations"]][:20]
    shown: list[dict[str, Any]] = []
    for c in tc.get("content") or []:
        if c.get("type") == "diff":
            shown.append(
                {
                    "diff": c.get("path", ""),
                    "old": (c.get("oldText") or "")[:KEEP_TEXT],
                    "new": (c.get("newText") or "")[:KEEP_TEXT],
                }
            )
        elif c.get("type") == "content" and (t := text_of(c.get("content"))):
            shown.append({"text": t[:KEEP_TEXT]})
    if shown:
        out["content"] = shown
    return out


def tool_output(view: Mapping[str, Any]) -> str:
    parts = []
    for c in view.get("content") or []:
        parts.append(f"edited {c['diff']}" if "diff" in c else c.get("text", ""))
    return "\n".join(p for p in parts if p)


def is_app_tool(tool_call: Mapping[str, Any]) -> bool:
    """A call of one of the app's tools (zpkt.app.ask.tools): its id or title names the tool and the app's server."""
    named = f"{tool_call.get('toolCallId', '')} {tool_call.get('title', '')}"
    return bool(tool_call.get("kind") not in OWN_KINDS and APP_TOOLS.search(named) and APP_SERVER.search(named))


def option_of(options: list[dict[str, Any]], kind: str) -> str | None:
    """The offered option that allows (or rejects) this once, else any that allows (or rejects)."""
    once = next((o["id"] for o in options if o.get("kind") == f"{kind}_once"), None)
    return once or next((o["id"] for o in options if str(o.get("kind", "")).startswith(kind)), None)


def decide(mode: str, tool_call: Mapping[str, Any], options: list[dict[str, Any]], ask: AskPermission) -> str | None:
    """The answer to a permission question: an option's id, or None to cancel."""
    if is_app_tool(tool_call) and (yes := option_of(options, "allow")):
        return yes
    if mode in ("build", "plan"):
        return option_of(options, "reject")
    if mode == "auto":  # full power: a question Gemini still asks is answered yes
        return option_of(options, "allow")
    return ask(tool_view(tool_call), options)


class Running:
    """The turn being run in one ACP session: where its updates and permission questions go."""

    def __init__(self, emit: Emit, ask: AskPermission, mode: str = DEFAULT_MODE) -> None:
        self.emit, self.ask, self.mode = emit, ask, mode
        self.tools: dict[str, str] = {}  # toolCallId -> its name, so an update finishes the right row
        self.mode_seen: str | None = None


def update_events(update: Mapping[str, Any], running: Running) -> list[Event]:
    """One ACP session/update as page events (thoughts and plans are not shown)."""
    kind = update.get("sessionUpdate")
    if kind == "agent_message_chunk":
        text = text_of(update.get("content"))
        if m := MODE_UPDATE.fullmatch(text.strip()):  # Gemini CLI says a mode change as text ("allow always")
            running.mode_seen = m.group(1)
            return []
        return [{"type": "message", "role": "assistant", "content": text, "delta": True}] if text else []
    if kind == "current_mode_update":
        running.mode_seen = str(update.get("currentModeId", ""))
        return []
    if kind == "tool_call":
        tid = str(update.get("toolCallId", ""))
        view = tool_view(update)
        name = str(update.get("title") or update.get("kind") or "tool")
        running.tools[tid] = name
        return [
            {
                "type": "tool_use",
                "tool_name": name,
                "tool_id": tid,
                "parameters": {k: v for k, v in view.items() if k in ("kind", "paths")},
            }
        ]
    if kind == "tool_call_update":
        tid = str(update.get("toolCallId", ""))
        status = update.get("status")
        if tid not in running.tools or status not in ("completed", "failed"):
            return []
        return [
            {
                "type": "tool_result",
                "tool_id": tid,
                "status": "success" if status == "completed" else "error",
                "output": tool_output(tool_view(update)),
            }
        ]
    return []


class GeminiProvider:
    engine = "gemini"

    def __init__(
        self,
        secret: Secret,
        command: list[str] | None = None,
        environ: Mapping[str, str] | None = None,
        home: Path | None = None,
        usage_file: Path | None = None,
        policy: Path | None = None,
        key_name: str = "gemini",
    ) -> None:
        self.secret = secret
        self.environ = dict(os.environ if environ is None else environ)
        self.home = home or Path.home()
        self.cmd = command or [shutil.which("gemini") or "/opt/homebrew/bin/gemini"]
        if policy is not None:
            self.cmd = [*self.cmd, "--policy", str(policy)]
        self.usage_file = usage_file
        self.key_name = key_name
        self.acp: Acp | None = None
        self.start_lock = threading.Lock()
        self.loaded: set[str] = set()
        self.running: dict[str, Running] = {}  # ACP session id -> its turn
        self.usage_lock = threading.Lock()

    def available(self) -> dict[str, Any]:
        model = self.environ.get("GEMINI_AGENT_MODEL", DEFAULT_MODEL)
        return {"id": "gemini", "name": "Gemini CLI", "short": "Gemini", "model": model or "Gemini"}

    # ---- the process --------------------------------------------------------------------------------------------
    def _process(self, cwd: Path) -> Acp:
        with self.start_lock:
            if self.acp is not None and self.acp.alive:
                return self.acp
            key = self.secret(self.key_name)
            if not key:
                raise AcpError("No Gemini key: the app's secret lookup has none (Keychain zpkt-gemini-api-key).")
            self.loaded.clear()
            env = {
                **self.environ,
                "PATH": agent_path(self.home, self.environ.get("PATH", "")),
                "GEMINI_API_KEY": key,
                "ZPKT_AGENT": "1",
            }
            self.acp = Acp(self.cmd, cwd, env, self._notify, self._request)
            self.acp.start()
            return self.acp

    def close(self) -> None:
        if self.acp is not None:
            self.acp.close()

    def _servers(self, tools: ToolServer | None) -> list[dict[str, Any]]:
        if tools is None:
            return []
        env = [{"name": k, "value": v} for k, v in tools.env.items()]
        return [{"name": "zpkt", "command": tools.command, "args": list(tools.args), "env": env}]

    def _session(self, acp: Acp, turn: Turn) -> str:
        """The ACP session of this app session: made on first use, loaded when the process is new."""
        cwd = turn.session["cwd"]
        known = (turn.session.get("engines") or {}).get("gemini", {}).get("acp")
        servers = self._servers(turn.tools)
        if not known:
            res = acp.request("session/new", {"cwd": cwd, "mcpServers": servers}, 120)
            sid = str(res["sessionId"])
            self.loaded.add(sid)
            turn.mark_started(sid)
        else:
            sid = str(known)
            if sid not in self.loaded:
                acp.request("session/load", {"sessionId": sid, "cwd": cwd, "mcpServers": servers}, 120)
                self.loaded.add(sid)
        model = turn.model or self.environ.get("GEMINI_AGENT_MODEL", DEFAULT_MODEL)
        if model:
            with contextlib.suppress(AcpError):
                acp.request("session/set_model", {"sessionId": sid, "modelId": model}, 30)
        with contextlib.suppress(AcpError):
            acp.request("session/set_mode", {"sessionId": sid, "modeId": GEMINI_MODE.get(turn.mode, "default")}, 30)
        return sid

    # ---- a turn -------------------------------------------------------------------------------------------------
    def run(self, turn: Turn, emit: Emit, cancel: threading.Event) -> Outcome:
        try:
            acp = self._process(Path(turn.session["cwd"]))
            sid = self._session(acp, turn)
        except AcpError as exc:
            emit({"type": "error", "message": str(exc)})
            return Outcome(1, None, str(exc))
        self.running[sid] = Running(emit, turn.ask_permission, turn.mode)
        done = threading.Event()

        def watch() -> None:
            while not done.is_set():
                if cancel.wait(0.1):
                    with contextlib.suppress(AcpError):
                        acp.notify("session/cancel", {"sessionId": sid})
                    return

        threading.Thread(target=watch, daemon=True).start()
        try:
            res = (
                acp.request(
                    "session/prompt", {"sessionId": sid, "prompt": [{"type": "text", "text": turn.prompt or " "}]}
                )
                or {}
            )
        except AcpError as exc:
            emit({"type": "error", "message": str(exc)[:800]})
            return Outcome(1, None, str(exc))
        finally:
            done.set()
            self.running.pop(sid, None)
        emit(self._result(res, turn))
        stopped = res.get("stopReason") == "cancelled"
        return Outcome(None if stopped else 0, "SIGTERM" if stopped else None)

    def _result(self, res: Mapping[str, Any], turn: Turn) -> Event:
        usage = res.get("usage") or {}
        per_model = ((res.get("_meta") or {}).get("quota") or {}).get("model_usage") or []
        model = (
            per_model[0].get("model", "")
            if len(per_model) == 1
            else turn.model or self.environ.get("GEMINI_AGENT_MODEL", DEFAULT_MODEL)
        )
        dollars = round(turn_cost(model, usage), 6)
        total = sum(usage.get(k, 0) for k in ("inputTokens", "outputTokens", "thoughtTokens"))
        if self.usage_file is not None:
            row = {
                "session": turn.session["id"],
                "model": model,
                "dollars": dollars,
                **{k: usage.get(k, 0) for k in ("inputTokens", "cachedReadTokens", "outputTokens", "thoughtTokens")},
            }
            with self.usage_lock, self.usage_file.open("a") as f:
                f.write(json.dumps(row) + "\n")
        stats: dict[str, Any] = {"models": {model: {}}}
        if total:
            stats["total_tokens"] = total
        ev: Event = {
            "type": "result",
            "status": "success" if res.get("stopReason") != "refusal" else "error",
            "stats": stats,
        }
        if dollars > 0:
            ev["cost_usd"] = dollars
        return ev

    # ---- from the process ---------------------------------------------------------------------------------------
    def _notify(self, method: str, params: dict[str, Any]) -> None:
        if method != "session/update":
            return
        running = self.running.get(str(params.get("sessionId", "")))
        if running is None:  # a replay while loading, or a turn that is over
            return
        for ev in update_events(params.get("update") or {}, running):
            running.emit(ev)

    def _request(self, method: str, params: dict[str, Any]) -> Any:
        if method != "session/request_permission":
            raise AcpError(f"{method} is not offered")
        running = self.running.get(str(params.get("sessionId", "")))
        if running is None:
            return {"outcome": {"outcome": "cancelled"}}
        options = [
            {"id": o["optionId"], "name": o.get("name", ""), "kind": o.get("kind", "")}
            for o in params.get("options") or []
        ]
        choice = decide(running.mode, params.get("toolCall") or {}, options, running.ask)
        if choice is None:
            return {"outcome": {"outcome": "cancelled"}}
        return {"outcome": {"outcome": "selected", "optionId": choice}}
