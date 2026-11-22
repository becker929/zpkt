"""The HW002 mix desk: one screen showing every control of desk.json's pages, which MiniLab 3 control each sits on,
and which page the controller has armed.

    uv run --project hands python contrib/mixdesk/server.py      # http://127.0.0.1:8985, needs HW002_121_pp_finish in Live

The server loads pager.py into Live's Python through hands' Remote Script (AbletonLiveMCP) and starts it; from then
on the MiniLab drives Live directly, inside Live, with no round trip through here. The pager sends every change as a
UDP datagram to 127.0.0.1:8986; the server keeps the latest state and streams it to the page (server-sent events).
The page arms pages and flips toggles with one short hands call each. Every 5 s the server asks Live whether the
pager still holds the controller (a set load rebuilds Live's MiniLab script) and restarts it if not.

Nothing here makes or plays sound: the page shows and arms controls; the mix itself is Live's.
"""
from __future__ import annotations

import json
import os
import queue
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from hands.live.transport import LiveClient, LiveError

HERE = Path(__file__).resolve().parent
HTTP_PORT = int(os.environ.get("MIXDESK_PORT", "8985"))
UDP_PORT = HTTP_PORT + 1
MOD = "zpkt_mixdesk_pager"

LOCK = threading.Lock()
STATE: dict = {"page": 0, "attached": False, "values": {}, "hw": {}, "picked": {}, "live": "starting", "touch": None}
CLIENTS: list[queue.Queue] = []


def cfg() -> dict:
    return json.loads((HERE / "desk.json").read_text())


def live() -> LiveClient:
    return LiveClient(timeout=10.0, retries=1)


def start_pager() -> dict:
    code = (
        "import importlib.util, sys, json\n"
        f"spec = importlib.util.spec_from_file_location({MOD!r}, {str(HERE / 'pager.py')!r})\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(m)\n"
        f"old = sys.modules.get({MOD!r})\n"
        "if old is not None and getattr(old, 'DESK', None) is not None:\n"
        "    old.DESK.stop()\n"
        f"sys.modules[{MOD!r}] = m\n"
        f"result = m.start(song, json.loads({json.dumps(cfg())!r}), {UDP_PORT})\n")
    return live().run(code)


def call(expr: str):
    return live().run(f"import sys\nm = sys.modules.get({MOD!r})\nresult = {expr} if m is not None and m.DESK is not None else None")


def set_state(snap: dict | None, status: str) -> None:
    with LOCK:
        if snap:
            STATE.update({k: snap[k] for k in ("page", "attached", "values", "hw", "picked") if k in snap})
        STATE["live"] = status
    push({"t": "full", "state": STATE})


def push(msg: dict) -> None:
    for q in list(CLIENTS):
        try:
            q.put_nowait(msg)
        except queue.Full:
            pass


def supervisor() -> None:
    """Keep the pager in Live and holding the MiniLab."""
    while True:
        try:
            ok = call("m.DESK.attached()")
            if ok is None or ok is False:
                snap = start_pager()
                set_state(snap, "attached" if snap.get("attached") else "no MiniLab 3 in Live")
            elif STATE["live"] != "attached":
                set_state(call("m.DESK.snapshot()"), "attached")
        except (LiveError, OSError) as exc:
            set_state(None, f"Live does not answer ({str(exc)[:80]})")
        time.sleep(5)


def udp() -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", UDP_PORT))
    while True:
        data, _ = s.recvfrom(65536)
        try:
            msg = json.loads(data)
        except ValueError:
            continue
        with LOCK:
            if msg["t"] == "v":
                key = f"{msg['page']}:{msg['slot']}"
                v = STATE["values"].setdefault(key, {})
                v.update({"n": msg["n"], "s": msg["s"]})
            elif msg["t"] == "page":
                STATE["page"], STATE["picked"] = msg["page"], {}
            elif msg["t"] == "hw":
                if msg.get("hw") is not None and msg["slot"].startswith("f"):
                    STATE["hw"][msg["slot"]] = msg["hw"]
                    STATE["picked"][msg["slot"]] = msg["picked"]
                STATE["touch"] = {"page": msg["page"], "slot": msg["slot"], "at": time.time()}
        push(msg)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a) -> None:
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._send(200, (HERE / "static" / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/desk":
            self._json(cfg())
        elif path == "/api/state":
            with LOCK:
                self._json(STATE)
        elif path == "/events":
            q: queue.Queue = queue.Queue(maxsize=2000)
            CLIENTS.append(q)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                with LOCK:
                    first = json.dumps({"t": "full", "state": STATE})
                self.wfile.write(f"data: {first}\n\n".encode())
                self.wfile.flush()
                while True:
                    try:
                        msg = q.get(timeout=15)
                        self.wfile.write(f"data: {json.dumps(msg)}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                CLIENTS.remove(q)
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        try:
            if self.path == "/api/page":
                call(f"m.DESK.arm({int(body['page'])})")
            elif self.path == "/api/toggle":
                slot = str(body["slot"])
                if not (slot[:1] == "b" and slot[1:].isdigit()):
                    return self._json({"error": "bad slot"}, 400)
                call(f"m.DESK.toggle({slot!r}, {int(body['page'])})")
            elif self.path == "/api/restart":
                set_state(start_pager(), "attached")
            else:
                return self._json({"error": "not found"}, 404)
            self._json({"ok": True})
        except (LiveError, OSError) as exc:
            self._json({"error": str(exc)}, 503)


def main() -> None:
    threading.Thread(target=udp, daemon=True).start()
    threading.Thread(target=supervisor, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), Handler)
    srv.daemon_threads = True
    print(f"mix desk on http://127.0.0.1:{HTTP_PORT}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
