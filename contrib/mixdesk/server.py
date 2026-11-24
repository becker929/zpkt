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

from hands.live import state as S
from hands.live.transport import LiveClient, LiveError

import history
import monitor

HERE = Path(__file__).resolve().parent
VIZ = Path(json.loads((HERE / "sources.json").read_text())["dir"]).expanduser()
HTTP_PORT = int(os.environ.get("MIXDESK_PORT", "8985"))
UDP_PORT = HTTP_PORT + 1
MOD = "zpkt_mixdesk_pager"

LOCK = threading.Lock()
STATE: dict = {"page": 0, "attached": False, "values": {}, "hw": {}, "picked": {}, "live": "starting", "touch": None,
               "monitor": {"slot": "W", "ref": "C1"}, "match": True, "pos": 0.0, "playing": False, "loop": "off"}
CLIENTS: list[queue.Queue] = []
SET = json.loads((HERE / "sources.json").read_text())["set"]
LABELS: dict[str, str] = {}
HIST = history.History(SET, LABELS)
START_CHECKPOINT_H = 12     # a server start makes a "start-..." checkpoint unless the desk made one this recently


def _label(spec: dict) -> str:
    p, t = spec["param"], spec["track"]
    if spec.get("label"):
        return f"{t}: {spec['label']}"
    if p in ("volume", "pan", "mute", "solo"):
        return f"{t} {p}"
    if p.startswith("send:"):
        return f"{t} send {p[5:]}"
    return f"{t}: {spec.get('device', '')} {p}"


def learn(values: dict) -> None:
    """The snapshot's keys and labels, and its values as the history's starting point (not moves)."""
    pages = cfg()["pages"]
    for pk, v in values.items():
        page, slot = pk.split(":")
        spec = pages[int(page)]["controls"].get(slot)
        if v.get("key") and spec:
            LABELS.setdefault(v["key"], _label(spec))
    HIST.baseline(values)


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
        "    d = old.DESK\n"
        "    m.CARRY = {'main_saved': getattr(d, 'main_saved', None), 'slot': getattr(d, 'monitor_slot', 'W'), 'ref': getattr(d, 'monitor_ref', 'C1'), 'page': d.page, 'v': getattr(old, 'SLOTS_V', 1)}\n"
        "    d.stop()\n"
        f"sys.modules[{MOD!r}] = m\n"
        f"result = m.start(song, json.loads({json.dumps(cfg())!r}), {UDP_PORT})\n")
    return live().run(code)


def call(expr: str):
    return live().run(f"import sys\nm = sys.modules.get({MOD!r})\nresult = {expr} if m is not None and m.DESK is not None else None")


def set_state(snap: dict | None, status: str) -> None:
    with LOCK:
        if snap:
            if snap.get("values"):
                learn(snap["values"])
            STATE.update({k: snap[k] for k in ("page", "attached", "values", "hw", "picked", "monitor", "pos", "playing") if k in snap})
            if "loop" in snap:
                lp = snap["loop"]
                STATE["loop"] = lp if isinstance(lp, str) else ("off" if not lp else (STATE["loop"] if STATE["loop"] != "off" else "on"))
        STATE["live"] = status
    push({"t": "full", "state": STATE})


def push(msg: dict) -> None:
    for q in list(CLIENTS):
        try:
            q.put_nowait(msg)
        except queue.Full:
            pass


def analysis() -> dict:
    f = monitor.VIZ / "analysis.json"
    return json.loads(f.read_text()) if f.exists() else {"sources": {}}


def gain_db(slot: str, ref: str) -> float:
    """Loudness match: bring A, B and the reference to the level of the quietest drop of the three. W (the
    working mix, live) is never changed."""
    if not STATE["match"] or slot == "W":
        return 0.0
    src = analysis()["sources"]
    ids = ["A", "B", ref]
    if not all(i in src for i in ids):
        return 0.0
    lufs = {i: src[i]["sections"]["drop"]["lufs"] for i in ids}
    return min(lufs.values()) - lufs[ref if slot == "C" else slot]


def apply_monitor(slot: str, ref: str) -> None:
    if slot == "C":
        if STATE["loop"] == "build":
            call("m.DESK.transport('loop', None, 'drop')")
        if STATE["pos"] < monitor.ALIGN_BEAT:   # the reference only exists from the drop
            call(f"m.DESK.transport('seek', {monitor.ALIGN_BEAT})")
    call(f"m.DESK.monitor({slot!r}, {ref!r}, {gain_db(slot, ref)!r})")


def supervisor() -> None:
    """Keep the pager in Live and holding the MiniLab."""
    ensured = started = False
    while True:
        try:
            if not ensured and STATE["live"] != "starting":
                names = live().run("result = [t.name for t in song.tracks]")
                if not all(n in names for n in monitor.wanted()):
                    monitor.ensure(live(), log=lambda *a: print(*a, flush=True))
                ensured = True
            if not started and HIST.cur:      # the pager reports keys (a pager from before history has none)
                start_checkpoint()
                started = True
            ok = call("m.DESK.attached()")
            if ok is None:
                snap = start_pager()
                set_state(snap, "attached" if snap.get("attached") else "no MiniLab 3 in Live")
            elif ok is False:
                attached = call("m.DESK.attach()")
                if attached or STATE["live"] != "no MiniLab 3 in Live":
                    set_state(call("m.DESK.snapshot()"), "attached" if attached else "no MiniLab 3 in Live")
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
                v.update({k: msg[k] for k in ("n", "s", "r", "key") if k in msg})
            elif msg["t"] == "pos":
                STATE["pos"], STATE["playing"] = msg["b"], msg["p"]
            elif msg["t"] == "mon":
                STATE["monitor"] = {"slot": msg["slot"], "ref": msg["ref"]}
            elif msg["t"] == "loop":
                STATE["loop"] = msg["loop"]
            elif msg["t"] == "page":
                STATE["page"], STATE["picked"] = msg["page"], {}
            elif msg["t"] == "hw":
                if msg.get("hw") is not None and msg["slot"].startswith("f"):
                    STATE["hw"][msg["slot"]] = msg["hw"]
                    STATE["picked"][msg["slot"]] = msg["picked"]
                STATE["touch"] = {"page": msg["page"], "slot": msg["slot"], "at": time.time()}
        push(msg)
        if msg["t"] == "v" and HIST.seen(msg.get("key"), msg.get("s", ""), msg.get("r"), bool(msg.get("sys"))):
            push(HIST.view())


def write(pairs: list[list]) -> list:
    """[[key, raw], ...] into Live through the pager (one call); returns the keys it could not find."""
    return call(f"m.DESK.set_raw({pairs!r})") if pairs else []


def make_checkpoint(name: str) -> dict:
    client = LiveClient(timeout=10.0, retries=1, keep=True)    # one connection for the whole read
    try:
        full = S.take(client)
    finally:
        client.close()
    saved = call("m.DESK.main_saved") if STATE["monitor"]["slot"] != "W" else None
    return HIST.checkpoint(name, full, saved)


def start_checkpoint() -> None:
    recent = [e for e in HIST.entries if e["k"] == "checkpoint" and time.time() - e["at"] < START_CHECKPOINT_H * 3600]
    if not recent:
        make_checkpoint(time.strftime("start-%Y%m%d-%H%M"))
        push(HIST.view())


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

    def _media(self, name: str) -> None:
        """Serve one analysed WAV (with Range, so the browser can seek). Only files analyze.py wrote."""
        f = VIZ / name
        if "/" in name or not name.endswith(".wav") or not f.is_file():
            return self._send(404, b"not found", "text/plain")
        size = f.stat().st_size
        a, b, code = 0, size - 1, 200
        rng = self.headers.get("Range", "")
        if rng.startswith("bytes="):
            lo, _, hi = rng[6:].partition("-")
            a = int(lo) if lo else 0
            b = min(int(hi), size - 1) if hi else size - 1
            code = 206
        with f.open("rb") as fh:
            fh.seek(a)
            body = fh.read(b - a + 1)
        self.send_response(code)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(len(body)))
        if code == 206:
            self.send_header("Content-Range", f"bytes {a}-{b}/{size}")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._send(200, (HERE / "static" / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/analysis":
            f = VIZ / "analysis.json"
            if f.exists():
                self._send(200, f.read_bytes(), "application/json")
            else:
                self._json({"error": "run analyze.py first"}, 404)
        elif path.startswith("/media/"):
            self._media(path[len("/media/"):])
        elif path == "/api/desk":
            self._json(cfg())
        elif path == "/api/history":
            self._json(HIST.view())
        elif path in ("/api/checkpoint", "/api/compare"):
            from urllib.parse import parse_qs, urlparse
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            try:
                if path == "/api/checkpoint":
                    vals = HIST.load(q.get("name", ""))
                    self._json({k: vals[k] for k in HIST.cur if k in vals})
                else:
                    self._json(HIST.compare(q.get("a", ""), q.get("b", "now")))
            except (ValueError, FileNotFoundError) as exc:
                self._json({"error": str(exc)}, 404)
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
            elif self.path == "/api/transport":
                act = str(body["action"])
                if act == "seek":
                    t = float(body["beat"])
                    if STATE["monitor"]["slot"] == "C":
                        t = max(t, monitor.ALIGN_BEAT)
                    call(f"m.DESK.transport('seek', {t!r})")
                elif act == "loop":
                    kind = str(body["loop"])
                    if kind not in ("off", "build", "drop"):
                        return self._json({"error": "bad loop"}, 400)
                    call(f"m.DESK.transport('loop', None, {kind!r})")
                elif act in ("play", "pause"):
                    call(f"m.DESK.transport({act!r})")
                else:
                    return self._json({"error": "bad action"}, 400)
            elif self.path == "/api/monitor":
                slot, ref = str(body.get("slot", STATE["monitor"]["slot"])), str(body.get("ref", STATE["monitor"]["ref"]))
                if slot not in ("A", "B", "W", "C") or ref not in analysis()["sources"]:
                    return self._json({"error": "bad slot or ref"}, 400)
                with LOCK:
                    if "match" in body:
                        STATE["match"] = bool(body["match"])
                apply_monitor(slot, ref)
                with LOCK:
                    snap_state = dict(STATE)
                push({"t": "full", "state": snap_state})
            elif self.path == "/api/restart":
                set_state(start_pager(), "attached")
            elif self.path in ("/api/undo", "/api/redo"):
                pairs, e = HIST.undo() if self.path == "/api/undo" else HIST.redo()
                missing = write(pairs)
                push(HIST.view())
                return self._json({"ok": True, "entry": e and e["id"], "missing": missing})
            elif self.path == "/api/checkpoint":
                name = str(body.get("name") or time.strftime("cp-%H%M%S")).strip()
                try:
                    e = make_checkpoint(name)
                except ValueError as exc:
                    return self._json({"error": str(exc)}, 400)
                push(HIST.view())
                return self._json({"ok": True, "name": e["name"]})
            elif self.path == "/api/revert":
                to = str(body["to"])
                keys = body.get("keys")
                if body.get("all"):
                    # the whole mix: the desk's controls as one undoable step, then everything else (not undoable,
                    # so a checkpoint of the mix as it was comes first), heard on W so the monitor tracks stay put
                    make_checkpoint(time.strftime("before-revert-%H%M%S"))
                    if STATE["monitor"]["slot"] != "W":
                        apply_monitor("W", STATE["monitor"]["ref"])
                    pairs, e = HIST.revert(to)
                    write(pairs)
                    rows = S.put(live(), S.load(HIST.folder() / f"{to}.json"))
                    push(HIST.view())
                    return self._json({"ok": True, "left": [list(r) for r in rows if not r[0].startswith("mon ")][:20]})
                pairs, e = HIST.revert(to, keys)
                missing = write(pairs)
                push(HIST.view())
                return self._json({"ok": True, "moved": len(pairs), "missing": missing})
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
