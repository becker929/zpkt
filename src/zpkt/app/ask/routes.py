"""The Ask routes on the web server: the page at /app/ask/ and its API at /app/ask/api/.

The names are Zpkt web's, under a prefix, so its page code works here with the prefix changed: sessions (with a
server-sent stream that replays then follows), messages, stop, rename, delete and undo of a delete, workspaces,
engines, files an agent points at, attachments, card state and the preset library. Two routes are new: `permission`
(answer an agent's question) and `tool` (an agent's tool call, from its MCP server). `AskRoutes` is a mount
(zpkt.app.mounts): the web server hands it every request under the prefix. It writes its answers on the connection
itself, since some are streams.
"""

from __future__ import annotations

import contextlib
import json
import queue
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from zpkt.app.ask.media import byte_range, resolve_media, save_attachment
from zpkt.app.ask.service import Ask
from zpkt.app.ask.store import NoSuchSession, Refused
from zpkt.app.ask.tools import TOOLS
from zpkt.app.mounts import MountReply, Request

if TYPE_CHECKING:
    from zpkt.app.web import Handler

PREFIX = "/app/ask"
STATIC = Path(__file__).resolve().parents[1] / "static" / "ask"
MAX_BODY = 12 * 1024 * 1024
MAX_SURFACE = 256 * 1024
SID = r"([0-9a-f-]{36})"
ASSET = re.compile(r"^/app/ask/zpkt/([a-z][\w-]{0,40}\.(?:js|css))$")
TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}


def text(v: Any, limit: int = 100000) -> str:
    return v[:limit] if isinstance(v, str) else ""


class AskRoutes:
    """The mount at /app/ask."""

    def __init__(self, ask: Ask, home: Path | None = None) -> None:
        self.ask = ask
        self.home = (home or Path.home()).resolve()

    def handle(self, request: Request) -> MountReply | None:
        """Answer on the connection (None says so to the web server). A HEAD has no route here."""
        if request.method == "HEAD":
            return MountReply(404, b"", "text/plain")
        with contextlib.suppress(OSError):  # the page went away mid-answer
            self.serve(request.connection, request.method, request.path, request.query)
        return None

    # ---- entry ------------------------------------------------------------------------------------------------
    def serve(self, h: Handler, method: str, path: str, query: dict[str, str]) -> None:
        self.ask.app_url = f"http://127.0.0.1:{h.server.server_address[1]}"
        try:
            if method == "GET" and path in (PREFIX, PREFIX + "/"):
                return h._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            if method == "GET" and (m := ASSET.match(path)):
                return self._asset(h, m.group(1))
            if not path.startswith(PREFIX + "/api/"):
                return h._json({"error": "Not found"}, 404)
            site = h.headers.get("Sec-Fetch-Site")
            if site and site not in ("same-origin", "none"):  # a request another site makes on the viewer's behalf
                return h._json({"error": "Cross-site request refused"}, 403)
            api = path[len(PREFIX) + len("/api") :]
            self._api(h, method, api, query)
        except Refused as exc:
            h._json({"error": str(exc)}, exc.code)
        except NoSuchSession:
            h._json({"error": "No such session"}, 404)

    def _asset(self, h: Handler, name: str) -> None:
        f = STATIC / "zpkt" / name
        if not f.is_file():
            return h._json({"error": "Not found"}, 404)
        h._send(200, f.read_bytes(), TYPES[f.suffix])

    def _body(self, h: Handler) -> dict[str, Any]:
        n = int(h.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise Refused("Request too large", 413)
        raw = h.rfile.read(n) if n else b""
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            raise Refused("Bad JSON") from None
        if not isinstance(body, dict):
            raise Refused("Expected a JSON object")
        return body

    # ---- the API ----------------------------------------------------------------------------------------------
    def _api(self, h: Handler, method: str, api: str, query: dict[str, str]) -> None:
        ask, send = self.ask, h._json
        if method == "GET" and api == "/health":
            return send({"ok": True, "commit": "app", "engines": [e["id"] for e in ask.engines()]})
        if method == "GET" and api == "/engines":
            return send({"engines": ask.engines()})
        if method == "GET" and api == "/workspaces":
            return send({"workspaces": ask.workspaces.all()})
        if method == "POST" and api == "/workspaces":
            body = self._body(h)
            return send({"workspace": ask.workspaces.add(text(body.get("name"), 60), text(body.get("path"), 1000))})
        if method == "DELETE" and (m := re.fullmatch(r"/workspaces/([\w-]+)", api)):
            ask.workspaces.remove(m.group(1))
            return send({"ok": True})
        if method == "GET" and api == "/feedback":
            return send({"feedback": []})  # Zpkt web's "improve this app" is not part of the app
        if method == "GET" and api == "/sessions":
            return send({"sessions": ask.sessions(), "claudeSignedOut": False})
        if method == "POST" and api == "/sessions":
            body = self._body(h)
            turn = self._turn_args(body)
            s = ask.create(text(body.get("workspace"), 80), text(body.get("prompt")), **turn)
            return send({"session": s})
        if m := re.fullmatch(rf"/sessions/{SID}(/[a-z]+)?", api):
            return self._session(h, method, m.group(1), m.group(2) or "", query)
        if method == "POST" and api == "/attachments":
            body = self._body(h)
            file, size = save_attachment(ask.attach_dir, body.get("dataUrl"), text(body.get("name"), 80))
            return send({"attachment": {"file": file, "size": size}})
        if method == "GET" and (m := re.fullmatch(r"/attachments/([\w.\-]{1,120})", api)):
            f = ask.attach_dir / m.group(1)
            if not f.is_file():
                raise Refused("No such attachment", 404)
            return self._file(
                h,
                f,
                {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}.get(
                    f.suffix, "application/octet-stream"
                ),
            )
        if method == "GET" and api == "/surfaces":
            sess = query.get("session", "")
            return send({"states": ask.library.states(sess + "/" if re.fullmatch(r"[0-9a-f-]{36}", sess) else "")})
        if method == "PUT" and (m := re.fullmatch(r"/surfaces/([\w:.\-%]{1,200})", api)):
            from urllib.parse import unquote

            return send({"state": ask.library.set_state(unquote(m.group(1)), self._body(h))})
        if method == "GET" and api == "/library":
            return send({"library": ask.library.library()})
        if method == "POST" and api == "/library":
            b = self._body(h)
            p = ask.library.star(
                b.get("spec"),
                b.get("values"),
                text(b.get("name"), 80),
                text(b.get("session"), 40),
                text(b.get("source"), 120),
            )
            return send({"preset": p})
        if m := re.fullmatch(r"/library/([\w-]{1,20})", api):
            if method == "PATCH":
                b = self._body(h)
                return send({"preset": ask.library.update(m.group(1), b.get("name"), b.get("values"))})
            if method == "DELETE":
                ask.library.remove(m.group(1))
                return send({"ok": True})
        if method == "GET" and api == "/tools":
            return send(
                {
                    "tools": [
                        {"name": t.name, "kind": t.kind, "description": t.description, "input": t.schema} for t in TOOLS
                    ]
                }
            )
        if method == "POST" and api == "/tool":
            b = self._body(h)
            args = b.get("args")
            code, reply = ask.gate.call(
                text(b.get("session"), 80),
                text(b.get("token"), 200),
                text(b.get("tool"), 80),
                args if isinstance(args, dict) else {},
            )
            return send(reply, code)
        send({"error": "Not found"}, 404)

    def _turn_args(self, body: dict[str, Any]) -> dict[str, Any]:
        """What a turn needs from a request body: mode, engine, model, and what goes to the agent besides the words."""
        extra, attachments = self._extras(body)
        engine = text(body.get("engine"), 20) or "claude"
        return {
            "mode": text(body.get("mode"), 20) or "plan",
            "engine": engine,
            "model": text(body.get("model"), 80),
            "extra": extra,
            "attachments": attachments,
        }

    def _extras(self, body: dict[str, Any]) -> tuple[str, list[str]]:
        files = [
            f
            for f in (body.get("attachments") or [])
            if isinstance(f, str) and re.fullmatch(r"[\w.\-]{1,120}", f) and (self.ask.attach_dir / f).exists()
        ][:8]
        parts = []
        if files:
            names = "\n".join(f"- {self.ask.attach_dir / f}" for f in files)
            parts.append(f"Attached image{'s' if len(files) > 1 else ''} (open with your file-reading tool):\n{names}")
        sf = body.get("surface")
        if isinstance(sf, dict) and sf.get("id"):
            j = json.dumps(
                {"id": text(str(sf["id"]), 120), "title": text(sf.get("title"), 120), "values": sf.get("values") or {}}
            )
            if len(j) < 32000:
                parts.append("Surface state (the armed controller, as the user left it):\n```json\n" + j + "\n```")
        return "\n\n".join(parts), files

    def _session(self, h: Handler, method: str, sid: str, sub: str, query: dict[str, str]) -> None:
        ask, send = self.ask, h._json
        if method == "POST" and sub == "/restore":
            return send({"session": ask.store.restore(sid)})
        s = ask.store.get(sid)
        if method == "GET" and sub == "/stream":
            return self._stream(h, sid, query)
        if method == "POST" and sub == "/messages":
            b = self._body(h)
            ask.send(s, text(b.get("prompt")), **self._turn_args(b))
            return send({"ok": True})
        if method == "POST" and sub == "/stop":
            return send({"stopped": ask.stop(sid)})
        if method == "POST" and sub == "/permission":
            b = self._body(h)
            try:
                done = ask.permissions.answer(
                    sid, text(b.get("id"), 40), b.get("option") if isinstance(b.get("option"), str) else None
                )
            except ValueError as exc:
                raise Refused(str(exc)) from None
            return send({"ok": done}, 200 if done else 409)
        if method == "DELETE" and not sub:
            ask.remove(sid)
            return send({"ok": True})
        if method == "PATCH" and not sub:
            return send({"session": ask.store.rename(sid, text(self._body(h).get("title"), 200))})
        if method == "POST" and sub == "/summary":
            b = self._body(h)
            if b.get("level") not in ("step", "agent", "turn") or not isinstance(b.get("turn"), int):
                raise Refused("Which line?")
            ask.store.emit(
                sid,
                {
                    "type": "summary",
                    "level": b["level"],
                    "turn": b["turn"],
                    "ref": text(str(b.get("ref", "turn")), 120),
                    "wrong": True,
                },
            )
            return send({"ok": True})
        if method == "POST" and sub == "/surface":
            b = self._body(h)
            spec = b.get("spec")
            if not isinstance(spec, dict) or not isinstance(spec.get("controls"), list):
                raise Refused("Spec required")
            if len(json.dumps([spec, b.get("values", 0)])) > MAX_SURFACE:
                raise Refused("Control panel too large", 413)
            e = ask.store.emit(
                sid,
                {
                    "type": "surface",
                    "spec": spec,
                    "values": b.get("values") if isinstance(b.get("values"), dict) else None,
                    "from": text(b.get("from"), 120) or None,
                    "name": text(b.get("name"), 80) or None,
                },
            )
            ask.store.touch(s)
            return send({"seq": e["seq"]})
        if method == "GET" and sub == "/file":
            f = resolve_media(query.get("path"), Path(s["cwd"]), self.home)
            return self._file(h, f.path, f.type)
        send({"error": "Not found"}, 404)

    # ---- streams and files ------------------------------------------------------------------------------------
    def _stream(self, h: Handler, sid: str, query: dict[str, str]) -> None:
        """Replay from `last-event-id` or ?from=, then follow. A `state` event says whether a run is going."""
        last = h.headers.get("Last-Event-ID", "")
        start = (
            int(last) + 1
            if last.lstrip("-").isdigit()
            else max(0, int(query["from"]) if query.get("from", "").isdigit() else 0)
        )
        q: queue.Queue[dict[str, Any] | None] = queue.Queue()
        h.send_response(200)
        for k, v in (("Content-Type", "text/event-stream"), ("Cache-Control", "no-store"), ("X-Accel-Buffering", "no")):
            h.send_header(k, v)
        h.end_headers()
        off = self.ask.store.follow(sid, start, q.put)
        try:
            q.put({"__state": {"running": self.ask.is_live(sid)}})  # right after the replay
            h.wfile.flush()
            while True:
                try:
                    e = q.get(timeout=15)
                except queue.Empty:
                    h.wfile.write(b": hb\n\n")
                    h.wfile.flush()
                    continue
                if e is None:
                    break
                if "__state" in e:
                    h.wfile.write(f"event: state\ndata: {json.dumps(e['__state'])}\n\n".encode())
                else:
                    h.wfile.write(f"id: {e['seq']}\ndata: {json.dumps(e)}\n\n".encode())
                h.wfile.flush()
        except OSError:
            pass
        finally:
            off()

    def _file(self, h: Handler, f: Path, ctype: str) -> None:
        size = f.stat().st_size
        part = byte_range(h.headers.get("Range", ""), size)
        a, b = part if part else (0, size - 1)
        with f.open("rb") as fh:
            fh.seek(a)
            body = fh.read(b - a + 1)
        h.send_response(206 if part else 200)
        for k, v in (
            ("Content-Type", ctype),
            ("Accept-Ranges", "bytes"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "private, max-age=60"),
            ("X-Content-Type-Options", "nosniff"),
        ):
            h.send_header(k, v)
        if part:
            h.send_header("Content-Range", f"bytes {a}-{b}/{size}")
        h.end_headers()
        h.wfile.write(body)
