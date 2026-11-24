"""Gemini CLI sessions as the phone sees them (/studio/gemini/): one ACP process (acp.py), the sessions the page knows,
their events, and the permissions waiting for an answer on the phone.

    <gemini_dir>/sessions/<id>.json   a session the page knows: title, model, mode, dates
    <gemini_dir>/events/<id>.jsonl    what the page shows, one event per line, numbered (n)
    <gemini_dir>/files/<id>/<name>    images he attached
    <gemini_dir>/usage.jsonl          one line per turn: tokens and estimated dollars (cost.py)

Gemini CLI keeps its own record of each session (~/.gemini), which is how a session survives a restart: the harness
loads it into a new process (session/load) the next time he writes in it. In a session's default mode every edit
and command waits for a yes from the phone (a notification goes out), "autoEdit" lets edits through, "yolo" lets
everything through, and "plan" is read-only.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import re
import secrets
import shutil
import threading
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config import agent_path
from .acp import Acp, AcpError
from .cost import turn_cost
from .terminal import gemini_command

log = logging.getLogger(__name__)

MODES = ("default", "autoEdit", "yolo", "plan")
KEEP_TEXT = 6000  # characters of a tool's output kept for the page
MODE_UPDATE = re.compile(r"\[MODE_UPDATE\] (\w+)")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# --- sessions as the page sees them ---------------------------------------------------------------------------------


class Session:
    """One session's page events, in memory and on disk, and who is waiting for the next one."""

    def __init__(self, path: Path):
        self.path = path
        self.events: list[dict] = []
        if path.is_file():
            for line in path.read_text().splitlines():
                with contextlib.suppress(ValueError):
                    self.events.append(json.loads(line))
        self.changed = asyncio.Condition()
        self.running = False
        self.tools: dict[str, int] = {}  # toolCallId -> its event's n, to update in place

    def add(self, ev: dict) -> dict:
        ev = {"n": len(self.events), "at": now(), **ev}
        self.events.append(ev)
        with self.path.open("a") as f:
            f.write(json.dumps(ev) + "\n")
        asyncio.get_running_loop().create_task(self._wake())
        return ev

    def amend(self, i: int, **changes) -> dict:
        """Changes an earlier event (a tool call's status, a permission's answer) by adding a new event that names
        it (`of`); the page replaces the old one."""
        merged = {**{k: v for k, v in self.events[i].items() if k not in ("n", "at", "of")}, **changes}
        return self.add({**merged, "of": self.events[i].get("of", i)})

    async def _wake(self) -> None:
        async with self.changed:
            self.changed.notify_all()


def _text_of(content) -> str:
    if isinstance(content, dict):
        return content.get("text", "") if content.get("type") == "text" else ""
    return ""


def _tool_view(tc: dict) -> dict:
    """What the page shows of a tool call: its title, kind, status, files, and a bounded view of its content."""
    out: dict = {k: tc[k] for k in ("title", "kind", "status") if k in tc}
    if tc.get("locations"):
        out["paths"] = [loc.get("path", "") for loc in tc["locations"]][:20]
    shown = []
    for c in tc.get("content") or []:
        if c.get("type") == "diff":
            shown.append(
                {
                    "diff": c.get("path", ""),
                    "old": (c.get("oldText") or "")[:KEEP_TEXT],
                    "new": (c.get("newText") or "")[:KEEP_TEXT],
                }
            )
        elif c.get("type") == "content":
            t = _text_of(c.get("content"))
            if t:
                shown.append({"text": t[:KEEP_TEXT]})
    if shown:
        out["content"] = shown
    return out


class Gemini:
    """The harness's side of Gemini CLI: one ACP process (started on first use, restarted when it dies), the
    sessions the page knows, their events, and the permissions waiting for the phone."""

    def __init__(
        self,
        root: Path,
        cwd: Path,
        key: Callable[[], str | None],
        cmd: list[str] | None = None,
        notify: Callable[[str, str, str], None] | None = None,
    ):
        self.root, self.cwd, self.key, self.cmd = Path(root), Path(cwd), key, cmd or gemini_command()
        self.notify = notify
        for d in ("sessions", "events", "files"):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        self.usage_path = self.root / "usage.jsonl"
        self.acp: Acp | None = None
        self._starting = asyncio.Lock()
        self.live: set[str] = set()  # sessions open in the current process
        self.loading: set[str] = set()  # sessions being loaded (their replayed updates are skipped)
        self.sessions: dict[str, Session] = {}
        self.waiting: dict[str, tuple[str, asyncio.Future, dict]] = {}  # permission id -> (session, answer, options)
        self.offers: dict = {}  # the models and modes the last new session offered
        self._lock = threading.Lock()

    # records
    @staticmethod
    def valid(sid: str) -> bool:
        return bool(re.fullmatch(r"[0-9A-Za-z-]{8,64}", sid or ""))

    def _rec_path(self, sid: str) -> Path:
        if not self.valid(sid):
            raise KeyError(sid)
        return self.root / "sessions" / f"{sid}.json"

    def record(self, sid: str) -> dict:
        p = self._rec_path(sid)
        if not p.is_file():
            raise KeyError(sid)
        return json.loads(p.read_text())

    def save(self, rec: dict) -> None:
        rec["updated"] = now()
        p = self._rec_path(rec["id"])
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec))
        tmp.replace(p)

    def view(self, rec: dict) -> dict:
        s = self.sessions.get(rec["id"])
        return {
            **rec,
            "dollars": round(self.spent().get(rec["id"], 0.0), 4),
            "running": bool(s and s.running),
            "asking": any(w[0] == rec["id"] for w in self.waiting.values()),
        }

    def list(self) -> list[dict]:
        out = []
        for p in (self.root / "sessions").glob("*.json"):
            with contextlib.suppress(ValueError):
                out.append(self.view(json.loads(p.read_text())))
        return sorted(out, key=lambda r: r["updated"], reverse=True)

    def session(self, sid: str) -> Session:
        if sid not in self.sessions:
            if not self._rec_path(sid).is_file():
                raise KeyError(sid)
            self.sessions[sid] = Session(self.root / "events" / f"{sid}.jsonl")
        return self.sessions[sid]

    def delete(self, sid: str) -> None:
        if (s := self.sessions.get(sid)) and s.running:
            raise ValueError("Stop the session before deleting it.")
        self._rec_path(sid).unlink(missing_ok=True)
        (self.root / "events" / f"{sid}.jsonl").unlink(missing_ok=True)
        d = self.root / "files" / sid
        if d.is_dir():
            shutil.rmtree(d)
        self.sessions.pop(sid, None)

    def usage_rows(self) -> list[dict]:
        if not self.usage_path.is_file():
            return []
        rows = []
        for line in self.usage_path.read_text().splitlines():
            with contextlib.suppress(ValueError):
                rows.append(json.loads(line))
        return rows

    def spent(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for r in self.usage_rows():
            out[r["session"]] = out.get(r["session"], 0.0) + r.get("dollars", 0.0)
        return out

    def attach(self, sid: str, mime: str, data_b64: str) -> str:
        ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}.get(mime)
        if not ext:
            raise ValueError("Attachments are images (JPEG, PNG, WebP or GIF).")
        raw = base64.b64decode(data_b64, validate=True)
        d = self.root / "files" / sid
        d.mkdir(parents=True, exist_ok=True)
        name = f"{secrets.token_hex(6)}.{ext}"
        (d / name).write_bytes(raw)
        return name

    def file(self, sid: str, name: str) -> Path | None:
        if not self.valid(sid) or not re.fullmatch(r"[0-9a-f]{12}\.[a-z]{3,4}", name):
            return None
        p = self.root / "files" / sid / name
        return p if p.is_file() else None

    # the process
    async def _acp(self) -> Acp:
        async with self._starting:
            if self.acp and self.acp.alive:
                return self.acp
            key = self.key()
            if not key:
                raise AcpError("No Gemini key (Keychain zpkt-gemini-api-key).")
            self.live.clear()
            self.acp = Acp(
                self.cmd,
                self.cwd,
                {**os.environ, "PATH": agent_path(), "GEMINI_API_KEY": key},
                self._on_notify,
                self._on_request,
            )
            await self.acp.start()
            return self.acp

    async def close(self) -> None:
        for _sid, fut, _ in self.waiting.values():
            if not fut.done():
                fut.set_result(None)
        if self.acp:
            await self.acp.close()

    async def new(self, model: str | None = None, mode: str = "default", title: str = "New session") -> dict:
        acp = await self._acp()
        res = await acp.request("session/new", {"cwd": str(self.cwd), "mcpServers": []}, 120)
        sid = res["sessionId"]
        self.live.add(sid)
        self.offers = {
            "models": [m["modelId"] for m in (res.get("models") or {}).get("availableModels", [])],
            "modes": [m["id"] for m in (res.get("modes") or {}).get("availableModes", [])],
        }
        rec = {
            "id": sid,
            "title": title,
            "created": now(),
            "updated": now(),
            "cwd": str(self.cwd),
            "model": (res.get("models") or {}).get("currentModelId", ""),
            "mode": "default",
        }
        self.save(rec)
        if model and model != rec["model"]:
            rec = await self.set_model(sid, model)
        if mode != "default":
            rec = await self.set_mode(sid, mode)
        return rec

    async def _ensure(self, sid: str) -> Acp:
        acp = await self._acp()
        if sid not in self.live:
            rec = self.record(sid)
            self.loading.add(sid)
            try:
                await acp.request(
                    "session/load", {"sessionId": sid, "cwd": rec.get("cwd", str(self.cwd)), "mcpServers": []}, 120
                )
            finally:
                self.loading.discard(sid)
            self.live.add(sid)
            if rec.get("model"):
                with contextlib.suppress(AcpError):
                    await acp.request("session/set_model", {"sessionId": sid, "modelId": rec["model"]}, 30)
            if rec.get("mode", "default") != "default":
                with contextlib.suppress(AcpError):
                    await acp.request("session/set_mode", {"sessionId": sid, "modeId": rec["mode"]}, 30)
        return acp

    async def set_mode(self, sid: str, mode: str) -> dict:
        if mode not in MODES:
            raise ValueError(f"mode is one of {', '.join(MODES)}")
        acp = await self._ensure(sid)
        await acp.request("session/set_mode", {"sessionId": sid, "modeId": mode}, 30)
        rec = self.record(sid)
        rec["mode"] = mode
        self.save(rec)
        self.session(sid).add({"type": "note", "text": f"Mode: {mode}", "mode": mode})
        return rec

    async def set_model(self, sid: str, model: str) -> dict:
        if not re.fullmatch(r"[\w.\-]{3,80}", model):
            raise ValueError("bad model name")
        acp = await self._ensure(sid)
        await acp.request("session/set_model", {"sessionId": sid, "modelId": model}, 30)
        rec = self.record(sid)
        rec["model"] = model
        self.save(rec)
        return rec

    # a turn
    def prompt(self, sid: str, text: str, images: list[dict]) -> None:
        """Starts a turn; it runs on whether or not the page stays (events() follows it)."""
        s = self.session(sid)
        if s.running:
            raise ValueError("This session is already working.")
        rec = self.record(sid)
        if rec["title"] == "New session" and text.strip():
            t = " ".join(text.split())
            rec["title"] = t[:60] + ("…" if len(t) > 60 else "")
            self.save(rec)
        names = [self.attach(sid, im["mime"], im["data"]) for im in images[:8]]
        s.running = True
        s.add({"type": "user", "text": text, "files": names})
        blocks: list[dict] = [{"type": "image", "mimeType": im["mime"], "data": im["data"]} for im in images[:8]]
        blocks.append({"type": "text", "text": text or " "})
        asyncio.get_running_loop().create_task(self._turn(sid, blocks))

    async def _turn(self, sid: str, blocks: list[dict]) -> None:
        s = self.session(sid)
        try:
            acp = await self._ensure(sid)
            res = await acp.request("session/prompt", {"sessionId": sid, "prompt": blocks}) or {}
            rec = self.record(sid)
            usage = res.get("usage") or {}
            per_model = ((res.get("_meta") or {}).get("quota") or {}).get("model_usage") or []
            model = per_model[0].get("model", "") if len(per_model) == 1 else rec.get("model", "")
            row = {
                "at": now(),
                "session": sid,
                "model": model,
                **{k: usage.get(k, 0) for k in ("inputTokens", "cachedReadTokens", "outputTokens", "thoughtTokens")},
                "dollars": round(turn_cost(model, usage), 6),
            }
            with self._lock, self.usage_path.open("a") as f:
                f.write(json.dumps(row) + "\n")
            self.save(rec)
            s.add({"type": "done", "stop": res.get("stopReason", ""), "model": model, "dollars": row["dollars"]})
        except Exception as e:  # noqa: BLE001 - shown in the session
            log.warning("gemini session %s: %s", sid, e)
            s.add({"type": "error", "text": str(e)[:800]})
        finally:
            for _pid, (psid, fut, _) in list(self.waiting.items()):
                if psid == sid and not fut.done():
                    fut.set_result(None)
            s.running = False
            s.add({"type": "idle"})

    async def cancel(self, sid: str) -> None:
        for _pid, (psid, fut, _) in list(self.waiting.items()):
            if psid == sid and not fut.done():
                fut.set_result(None)
        if self.acp and self.acp.alive and sid in self.live:
            await self.acp.notify("session/cancel", {"sessionId": sid})

    def answer(self, pid: str, option: str | None) -> bool:
        w = self.waiting.get(pid)
        if not w or w[1].done():
            return False
        if option is not None and option not in w[2]:
            raise ValueError("not one of the offered options")
        w[1].set_result(option)
        return True

    async def events(self, sid: str, after: int = -1) -> AsyncIterator[dict]:
        """Every event after `after`, then new ones while the session is working; ends when it is idle."""
        s = self.session(sid)
        i = after + 1
        while True:
            while i < len(s.events):
                yield s.events[i]
                i += 1
            if not s.running:
                return
            async with s.changed:
                await s.changed.wait_for(lambda i=i: i < len(s.events) or not s.running)

    # from the process
    def _on_notify(self, method: str, params: dict) -> None:
        if method != "session/update":
            return
        sid = params.get("sessionId", "")
        if sid in self.loading:
            return
        try:
            s = self.session(sid)
        except KeyError:
            return
        u = params.get("update") or {}
        kind = u.get("sessionUpdate")
        if kind == "agent_message_chunk" and (m := MODE_UPDATE.fullmatch(_text_of(u.get("content")).strip())):
            self._mode_changed(sid, m.group(1))  # Gemini CLI says a mode change as text ("allow always")
        elif kind == "current_mode_update":
            self._mode_changed(sid, u.get("currentModeId", ""))
        elif kind in ("agent_message_chunk", "agent_thought_chunk"):
            t = _text_of(u.get("content"))
            if t:
                s.add({"type": "text" if kind == "agent_message_chunk" else "thought", "text": t})
        elif kind == "tool_call":
            ev = s.add({"type": "tool", "id": u.get("toolCallId", ""), **_tool_view(u)})
            s.tools[u.get("toolCallId", "")] = ev["n"]
        elif kind == "tool_call_update":
            i = s.tools.get(u.get("toolCallId", ""))
            if i is not None:
                s.tools[u.get("toolCallId", "")] = s.amend(i, **_tool_view(u))["n"]
        elif kind == "plan":
            s.add(
                {
                    "type": "plan",
                    "entries": [
                        {"content": e.get("content", ""), "status": e.get("status", "")} for e in u.get("entries") or []
                    ],
                }
            )

    def _mode_changed(self, sid: str, mode: str) -> None:
        if mode not in MODES:
            return
        rec = self.record(sid)
        if rec.get("mode") != mode:
            rec["mode"] = mode
            self.save(rec)
            self.session(sid).add({"type": "note", "text": f"Mode: {mode}", "mode": mode})

    async def _on_request(self, method: str, params: dict) -> Any:
        if method != "session/request_permission":
            raise AcpError(f"{method} is not offered")
        sid = params.get("sessionId", "")
        s = self.session(sid)
        tc = params.get("toolCall") or {}
        options = {o["optionId"]: o for o in params.get("options") or []}
        pid = secrets.token_hex(6)
        fut = asyncio.get_running_loop().create_future()
        self.waiting[pid] = (sid, fut, options)
        ev = s.add(
            {
                "type": "permission",
                "id": pid,
                "tool": _tool_view(tc),
                "options": [
                    {"id": o["optionId"], "name": o.get("name", ""), "kind": o.get("kind", "")}
                    for o in options.values()
                ],
            }
        )
        if self.notify:
            title = (tc.get("title") or "a tool")[:120]
            asyncio.get_running_loop().run_in_executor(None, self.notify, "Gemini asks", title, sid)
        try:
            choice = await fut
        finally:
            self.waiting.pop(pid, None)
        s.amend(ev["n"], answered=choice or "cancelled")
        if choice is None:
            return {"outcome": {"outcome": "cancelled"}}
        return {"outcome": {"outcome": "selected", "optionId": choice}}


def phone_notify(app_url: Callable[[], str]) -> Callable[[str, str, str], None]:
    """ntfy, with a tap that opens the session on the page."""

    def send(title: str, body: str, sid: str) -> None:
        from ..notify import notify

        notify(title, body, click=f"{app_url()}/studio/gemini/?s={sid}")

    return send
