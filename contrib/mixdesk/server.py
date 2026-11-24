"""The HW002 mix desk: one screen showing every control of desk.json's pages, which MiniLab 3 control each sits on,
and which page the controller has armed.

    uv run python contrib/mixdesk/server.py      # http://127.0.0.1:8985, needs HW002_121_pp_finish in Live

The server loads pager.py into Live's Python through hands' Remote Script (AbletonLiveMCP) and starts it; from then
on the MiniLab drives Live directly, inside Live, with no round trip through here. The pager sends every change as a
UDP datagram to 127.0.0.1:8986; the server keeps the latest state and streams it to the page (server-sent events).
The page arms pages and flips toggles with one short hands call each. Every 5 s the server asks Live whether the
pager still holds the controller (a set load rebuilds Live's MiniLab script) and restarts it if not.

`Desk` owns the one mutable state, behind one lock; deskstate.py holds the pure rules that change it and protocol.py
the messages. Nothing here makes or plays sound: the page shows and arms controls; the mix itself is Live's.
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import queue
import socket
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlparse

import deskstate as D
import history
import meter
import monitor
import protocol as P
import surfaces

from zpkt.live import config
from zpkt.live import state as S
from zpkt.live.transport import LiveClient, LiveError

HERE = Path(__file__).resolve().parent
SOURCES = json.loads((HERE / "sources.json").read_text())
MOD = "zpkt_mixdesk_pager"  # the pager's name in Live's sys.modules
START_CHECKPOINT_H = 12  # a server start makes a "start-..." checkpoint unless the desk made one this recently
SUPERVISE_S = 5.0
NO_MINILAB = "no MiniLab 3 in Live"


@dataclass(frozen=True)
class Settings:
    """Where the desk reads and writes, and its ports. `from_env` is the running desk's; tests make their own."""

    set_name: str
    viz_dir: Path  # analysis.json and the WAVs analyze.py wrote
    http_port: int
    udp_port: int  # the pager's datagrams
    meter_port: int  # the Max for Live meter's OSC
    live_port: int | None  # the Remote Script's port; None is the rig's
    history_dir: Path
    checkpoints_dir: Path  # hands states, <sets_dir>/state/<set>
    surfaces_dir: Path  # made surfaces, <sets_dir>/surfaces/<set>
    align_beat: float = monitor.ALIGN_BEAT  # where the references start (the drop)

    @classmethod
    def from_env(cls) -> Settings:
        http_port = int(os.environ.get("MIXDESK_PORT", "8985"))
        set_name = SOURCES["set"]
        return cls(
            set_name=set_name,
            viz_dir=Path(SOURCES["dir"]).expanduser(),
            http_port=http_port,
            udp_port=http_port + 1,
            meter_port=meter.METER_PORT,
            live_port=None,
            history_dir=history.HISTORY_DIR,
            checkpoints_dir=S.folder(set_name),
            surfaces_dir=config.rig().sets_dir / "surfaces" / set_name,
        )


class BadRequest(ValueError):
    """A request body the route cannot use: the page gets 400 and this message."""


def pager_start_code(cfg: dict[str, Any], udp_port: int) -> str:
    """The code that (re)loads pager.py into Live and starts it, handing the old desk's monitor and page over."""
    return (
        "import importlib.util, sys, json\n"
        f"spec = importlib.util.spec_from_file_location({MOD!r}, {str(HERE / 'pager.py')!r})\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(m)\n"
        f"old = sys.modules.get({MOD!r})\n"
        "if old is not None and getattr(old, 'DESK', None) is not None:\n"
        "    d = old.DESK\n"
        "    m.CARRY = {'main_saved': getattr(d, 'main_saved', None), 'slot': getattr(d, 'monitor_slot', 'W'), "
        "'ref': getattr(d, 'monitor_ref', 'C1'), 'page': d.page, 'v': getattr(old, 'SLOTS_V', 1)}\n"
        "    d.stop()\n"
        f"sys.modules[{MOD!r}] = m\n"
        f"result = m.start(song, json.loads({json.dumps(cfg)!r}), {udp_port})\n"
    )


def pager_call_code(expr: str) -> str:
    """An expression on the running pager's desk; None when no pager runs."""
    return (
        f"import sys\nm = sys.modules.get({MOD!r})\nresult = {expr} if m is not None and m.DESK is not None else None"
    )


def meter_message(levels: list[float], hz: list[float]) -> dict[str, Any] | None:
    """The meter's RMS levels as the page's {"t": "meter"} message in dB; None if the band count is wrong."""
    if len(levels) != len(hz):
        return None
    db = [round(20 * math.log10(v), 2) if v > 1e-7 else -140.0 for v in levels]
    return {"t": "meter", "hz": hz, "db": db}


class Desk:
    """The running desk: the state Live reported, the page's event queues, the history. One owner, one lock."""

    def __init__(self, settings: Settings, hist: history.History | None = None) -> None:
        self.settings = settings
        self.lock = threading.Lock()
        self.state: D.DeskState = D.initial()
        self.clients: list[queue.Queue[dict[str, Any]]] = []
        self.labels: dict[str, str] = {}  # shared with the history, which names its moves by them
        self.history = hist or history.History(
            settings.set_name, self.labels, settings.history_dir, checkpoints=settings.checkpoints_dir
        )
        self.history.labels = self.labels
        self.making = threading.Lock()  # one "Make a surface" job at a time
        self._analysis: tuple[float | None, dict[str, Any]] = (None, {"sources": {}})

    # ---- reading the state -----------------------------------------------------------------------------------------
    def snapshot(self) -> D.DeskState:
        """A deep copy of the state: the UDP thread keeps changing it after a copy is queued or sent."""
        with self.lock:
            copy: D.DeskState = json.loads(json.dumps(self.state))
        return copy

    def page_state(self) -> dict[str, Any]:
        """The state as the page gets it: a copy, with the loudness match's gains for every reference."""
        return {**self.snapshot(), "gains": D.matched_gains(self.analysis()["sources"])}

    def monitor_choice(self) -> D.MonitorChoice:
        return self.snapshot()["monitor"]

    # ---- Live ------------------------------------------------------------------------------------------------------
    def live(self, keep: bool = False) -> LiveClient:
        return LiveClient(timeout=10.0, retries=1, keep=keep, port=self.settings.live_port)

    def call(self, expr: str) -> Any:
        return self.live().run(pager_call_code(expr))

    def cfg(self) -> dict[str, Any]:
        """desk.json's pages, then the surfaces made for this set (surfaces.py), oldest first."""
        d = json.loads((HERE / "desk.json").read_text())
        d["pages"] = d["pages"] + surfaces.pages(self.settings.set_name, self.settings.surfaces_dir)
        return d

    def page_names(self) -> list[str]:
        return [pg["name"] for pg in self.cfg()["pages"]]

    def start_pager(self) -> dict[str, Any]:
        return self.live().run(pager_start_code(self.cfg(), self.settings.udp_port))

    def restart_pager(self) -> None:
        self.set_state(self.start_pager(), "attached")

    # ---- changing the state ----------------------------------------------------------------------------------------
    def push(self, msg: dict[str, Any]) -> None:
        for q in list(self.clients):
            with contextlib.suppress(queue.Full):
                q.put_nowait(msg)

    def push_full(self) -> None:
        self.push({"t": "full", "state": self.page_state()})

    def set_state(self, snap: dict[str, Any] | None, status: str) -> None:
        """A pager snapshot (or None) and Live's status: learn its keys, fold it in, send the page all of it."""
        if snap and snap.get("values"):
            self.learn(snap["values"])
        with self.lock:
            self.state = D.with_snapshot(self.state, snap, status)
        self.push_full()

    def learn(self, values: dict[str, Any]) -> None:
        """The snapshot's keys and labels, and its values as the history's starting point (not moves)."""
        for key, label in D.labels(self.cfg()["pages"], values).items():
            self.labels.setdefault(key, label)
        self.history.baseline(values)

    def receive(self, data: bytes) -> None:
        """One datagram from the pager: into the state, out to the page, and into the history if it moved a value."""
        try:
            msg = P.parse_datagram(data)
        except P.BadMessage as exc:
            print(f"mixdesk: dropped a datagram from the pager: {exc}", flush=True)
            return
        with self.lock:
            self.state = D.reduce(self.state, msg, time.time())
        self.push(dict(msg))
        if msg["t"] == "v" and self.history.seen(msg["key"], msg["s"], msg["r"], who=P.who_moved(msg)):
            self.push(self.history.view())

    def set_match(self, match: bool) -> None:
        with self.lock:
            self.state = {**self.state, "match": match}

    # ---- the threads ---------------------------------------------------------------------------------------------
    def serve_udp(self, sock: socket.socket) -> None:
        while True:
            data, _ = sock.recvfrom(65536)
            self.receive(data)

    def serve_meter(self, sock: socket.socket) -> None:
        """The live meter on Main (meter.py): 31 third-octave RMS levels, 10 a second, to the page as dB."""
        hz = [round(f, 2) for f in meter.centers()]
        while True:
            data, _ = sock.recvfrom(4096)
            levels = meter.parse(data)
            msg = meter_message(levels, hz) if levels else None
            if msg:
                self.push(msg)

    def supervise(self) -> None:
        """Keep the pager in Live and holding the MiniLab."""
        ensured = started = False
        while True:
            try:
                ensured = ensured or self._ensure_monitor_tracks()
                if not started and self.history.cur:  # the pager reports keys (a pager from before history has none)
                    self.start_checkpoint()
                    started = True
                self.check_pager()
            except (LiveError, OSError) as exc:
                self.set_state(None, f"Live does not answer ({str(exc)[:80]})")
            time.sleep(SUPERVISE_S)

    def _ensure_monitor_tracks(self) -> bool:
        if self.snapshot()["live"] == "starting":
            return False
        names = self.live().run("result = [t.name for t in song.tracks]")
        if not all(n in names for n in monitor.wanted()):
            monitor.ensure(self.live(), log=lambda *a: print(*a, flush=True))
        return True

    def check_pager(self) -> None:
        """One supervisor step: start the pager if it is gone, reattach it if it lost the MiniLab."""
        status = self.snapshot()["live"]
        ok = self.call("m.DESK.attached()")
        if ok is None:
            snap = self.start_pager()
            self.set_state(snap, "attached" if snap.get("attached") else NO_MINILAB)
        elif ok is False:
            attached = self.call("m.DESK.attach()")
            if attached or status != NO_MINILAB:
                self.set_state(self.call("m.DESK.snapshot()"), "attached" if attached else NO_MINILAB)
        elif status != "attached":
            self.set_state(self.call("m.DESK.snapshot()"), "attached")

    # ---- monitor ---------------------------------------------------------------------------------------------------
    def analysis(self) -> dict[str, Any]:
        """analyze.py's analysis.json (read again when it changes), or no sources before it has run."""
        f = self.settings.viz_dir / "analysis.json"
        try:
            mtime = f.stat().st_mtime
        except FileNotFoundError:
            return {"sources": {}}
        with self.lock:
            if self._analysis[0] != mtime:
                self._analysis = (mtime, json.loads(f.read_text()))
            return self._analysis[1]

    def gain_db(self, slot: str, ref: str) -> float:
        return D.matched_gain_db(self.analysis()["sources"], slot, ref, self.snapshot()["match"])

    def apply_monitor(self, slot: str, ref: str) -> None:
        st = self.snapshot()
        if slot == "C":
            if st["loop"] == "build":
                self.call("m.DESK.transport('loop', None, 'drop')")
            if st["pos"] < self.settings.align_beat:  # the reference only exists from the drop
                self.call(f"m.DESK.transport('seek', {self.settings.align_beat})")
        self.call(f"m.DESK.monitor({slot!r}, {ref!r}, {self.gain_db(slot, ref)!r})")

    # ---- surfaces --------------------------------------------------------------------------------------------------
    def adopt_surface(self, path: Path, surface: dict[str, Any]) -> int:
        """A surface just saved: reload the pager with it, arm its page, tell the page. Returns the page's index.
        What the pager could not use of its macros is added to the surface's notes."""
        self.restart_pager()
        idx = next(i for i, pg in enumerate(self.cfg()["pages"]) if pg.get("surface") == path.name)
        self.call(f"m.DESK.arm({idx})")
        for x in self.call(f"m.DESK.macro_skipped({idx})") or []:
            surface["notes"].append(f"{x} could not be used in Live; that part of the macro does nothing.")
        self.push({"t": "desk", "open": idx})
        return idx

    def inventory(self) -> dict[str, Any]:
        return surfaces.parse_inventory(self.call("m.DESK.inventory()") or "")

    def make_surface(self, text: str, ask: Callable[[str], str] | None = None) -> None:
        """The Make a surface job (its own thread): what the set holds -> Claude -> checked -> saved -> on the
        MiniLab. `ask` stands in for Claude in tests."""

        def say(status: str, msg: str) -> None:
            self.push({"t": "surface", "status": status, "msg": msg})

        if not self.making.acquire(blocking=False):
            return say("error", "A surface is already being made.")
        try:
            say("working", "Reading the set…")
            inv = self.inventory()
            if not inv:
                return say("error", "Live did not answer with the set's controls.")
            say("working", f"Asking Claude ({len(inv)} parameters in the set)…")
            path, surface = surfaces.make(
                text,
                inv,
                self.settings.set_name,
                self.page_names(),
                ask=ask or surfaces.ask_claude,
                directory=self.settings.surfaces_dir,
            )
            say("working", "Putting it on the MiniLab…")
            self.adopt_surface(path, surface)
            notes = " ".join(surface["notes"])
            done = f"Made “{surface['name']}” ({len(surface['controls'])} controls), saved as {path.name}."
            say("done", done + (f" {notes}" if notes else ""))
        except surfaces.SurfaceError as exc:
            say("error", str(exc))
        except (LiveError, OSError) as exc:
            say("error", f"Live does not answer ({str(exc)[:120]})")
        finally:
            self.making.release()

    # ---- history ---------------------------------------------------------------------------------------------------
    def write(self, pairs: list[list[Any]]) -> list[str]:
        """[[key, raw], ...] into Live through the pager (one call); returns the keys it could not find."""
        return self.call(f"m.DESK.set_raw({pairs!r})") if pairs else []

    def make_checkpoint(self, name: str, who: P.Who = P.DEFAULT_WHO) -> dict[str, Any]:
        """Checkpoint `name`: the whole mix as Live has it now. `who` made it: "sys" when the desk did on its own."""
        history.check_name(name)
        client = self.live(keep=True)  # one connection for the whole read
        try:
            full = S.take(client)
        finally:
            client.close()
        saved = self.call("m.DESK.main_saved") if self.monitor_choice()["slot"] != "W" else None
        return self.history.checkpoint(name, full, saved, who)

    def start_checkpoint(self) -> None:
        now = time.time()
        recent = [
            e for e in self.history.entries if e["k"] == "checkpoint" and now - e["at"] < START_CHECKPOINT_H * 3600
        ]
        if not recent:
            self.make_checkpoint(time.strftime("start-%Y%m%d-%H%M"), who="sys")
            self.push(self.history.view())


# ---- POST routes: each takes the desk and the parsed body, and returns (status, JSON) --------------------------------

Reply = tuple[int, dict[str, Any]]
OK: Reply = (200, {"ok": True})


def _int(body: dict[str, Any], name: str) -> int:
    try:
        return int(body[name])
    except KeyError:
        raise BadRequest(f"the body needs {name!r}") from None
    except (TypeError, ValueError):
        raise BadRequest(f"{name!r} must be a whole number") from None


def _float(body: dict[str, Any], name: str) -> float:
    try:
        value = float(body[name])
    except KeyError:
        raise BadRequest(f"the body needs {name!r}") from None
    except (TypeError, ValueError):
        raise BadRequest(f"{name!r} must be a number") from None
    if not math.isfinite(value):
        raise BadRequest(f"{name!r} must be a finite number")
    return value


def _str(body: dict[str, Any], name: str, default: str | None = None) -> str:
    if name not in body or body[name] is None:
        if default is None:
            raise BadRequest(f"the body needs {name!r}")
        return default
    return str(body[name])


def post_page(desk: Desk, body: dict[str, Any]) -> Reply:
    desk.call(f"m.DESK.arm({_int(body, 'page')})")
    return OK


def post_toggle(desk: Desk, body: dict[str, Any]) -> Reply:
    slot = _str(body, "slot")
    if not (slot[:1] == "b" and slot[1:].isdigit()):
        return 400, {"error": "bad slot"}
    desk.call(f"m.DESK.toggle({slot!r}, {_int(body, 'page')})")
    return OK


def post_transport(desk: Desk, body: dict[str, Any]) -> Reply:
    action = _str(body, "action")
    if action == "seek":
        beat = D.seek_beat(_float(body, "beat"), desk.monitor_choice()["slot"], desk.settings.align_beat)
        desk.call(f"m.DESK.transport('seek', {beat!r})")
    elif action == "loop":
        kind = _str(body, "loop")
        if kind not in D.LOOPS:
            return 400, {"error": "bad loop"}
        desk.call(f"m.DESK.transport('loop', None, {kind!r})")
    elif action in ("play", "pause"):
        desk.call(f"m.DESK.transport({action!r})")
    else:
        return 400, {"error": "bad action"}
    return OK


def post_monitor(desk: Desk, body: dict[str, Any]) -> Reply:
    now = desk.monitor_choice()
    slot, ref = _str(body, "slot", now["slot"]), _str(body, "ref", now["ref"])
    if slot not in D.SLOTS or ref not in desk.analysis()["sources"]:
        return 400, {"error": "bad slot or ref"}
    if "match" in body:
        desk.set_match(bool(body["match"]))
    desk.apply_monitor(slot, ref)
    desk.push_full()
    return OK


def post_restart(desk: Desk, body: dict[str, Any]) -> Reply:
    desk.restart_pager()
    return OK


def post_surface_make(desk: Desk, body: dict[str, Any]) -> Reply:
    text = _str(body, "text", "").strip()
    if not text:
        return 400, {"error": "say what the surface is for"}
    threading.Thread(target=desk.make_surface, args=(text[:2000],), daemon=True).start()
    return OK


def post_surface_save(desk: Desk, body: dict[str, Any]) -> Reply:
    """A ready-made surface: the same checks as a made one, no model."""
    if not isinstance(body.get("surface"), dict):
        raise BadRequest("the body needs 'surface', a surface object")
    try:
        surface = surfaces.validate(body["surface"], desk.inventory(), desk.page_names())
        path = surfaces.save(surface, desk.settings.set_name, _str(body, "prompt", ""), desk.settings.surfaces_dir)
    except surfaces.SurfaceError as exc:
        return 400, {"error": str(exc)}
    idx = desk.adopt_surface(path, surface)
    return 200, {"ok": True, "file": path.name, "page": idx, "notes": surface["notes"]}


def post_surface_remove(desk: Desk, body: dict[str, Any]) -> Reply:
    # stay on the page that was armed (by name: the indexes after the removed one shift)
    was, old = desk.page_names(), desk.snapshot()["page"]
    armed = was[old] if 0 <= old < len(was) else None
    try:
        surfaces.remove(desk.settings.set_name, _str(body, "file", ""), desk.settings.surfaces_dir)
    except surfaces.SurfaceError as exc:
        return 400, {"error": str(exc)}
    desk.restart_pager()
    names = desk.page_names()
    idx = names.index(armed) if armed in names else max(0, min(old, len(names)) - 1)
    desk.call(f"m.DESK.arm({idx})")
    desk.push({"t": "desk", "open": idx})
    return OK


def _step(desk: Desk, undo: bool) -> Reply:
    pairs, e = desk.history.undo() if undo else desk.history.redo()
    missing = desk.write(pairs)
    desk.push(desk.history.view())
    return 200, {"ok": True, "entry": e and e["id"], "missing": missing}


def post_undo(desk: Desk, body: dict[str, Any]) -> Reply:
    return _step(desk, undo=True)


def post_redo(desk: Desk, body: dict[str, Any]) -> Reply:
    return _step(desk, undo=False)


def post_checkpoint(desk: Desk, body: dict[str, Any]) -> Reply:
    name = str(body.get("name") or time.strftime("cp-%H%M%S")).strip()
    try:
        e = desk.make_checkpoint(name)
    except ValueError as exc:
        return 400, {"error": str(exc)}
    desk.push(desk.history.view())
    return 200, {"ok": True, "name": e["name"]}


def post_revert(desk: Desk, body: dict[str, Any]) -> Reply:
    to = _str(body, "to")
    keys = body.get("keys")
    if keys is not None and not (isinstance(keys, list) and all(isinstance(k, str) for k in keys)):
        raise BadRequest("'keys' must be a list of state keys")
    try:
        desk.history.load(to)  # the name is checked before anything changes
    except ValueError as exc:
        raise BadRequest(str(exc)) from None
    except FileNotFoundError:
        raise BadRequest(f"there is no checkpoint named {to!r}") from None
    if body.get("all"):
        # the whole mix: the desk's controls as one undoable step, then everything else (not undoable, so a
        # checkpoint of the mix as it was comes first), heard on W so the monitor tracks stay put
        desk.make_checkpoint(time.strftime("before-revert-%H%M%S"), who="sys")
        now = desk.monitor_choice()
        if now["slot"] != "W":
            desk.apply_monitor("W", now["ref"])
        pairs, _ = desk.history.revert(to)
        desk.write(pairs)
        rows = S.put(desk.live(), S.load(desk.history.folder() / f"{to}.json"))
        desk.push(desk.history.view())
        return 200, {"ok": True, "left": [list(r) for r in rows if not r[0].startswith("mon ")][:20]}
    pairs, _ = desk.history.revert(to, keys)
    missing = desk.write(pairs)
    desk.push(desk.history.view())
    return 200, {"ok": True, "moved": len(pairs), "missing": missing}


POST_ROUTES: dict[str, Callable[[Desk, dict[str, Any]], Reply]] = {
    "/api/page": post_page,
    "/api/toggle": post_toggle,
    "/api/transport": post_transport,
    "/api/monitor": post_monitor,
    "/api/restart": post_restart,
    "/api/surface/make": post_surface_make,
    "/api/surface/save": post_surface_save,
    "/api/surface/remove": post_surface_remove,
    "/api/undo": post_undo,
    "/api/redo": post_redo,
    "/api/checkpoint": post_checkpoint,
    "/api/revert": post_revert,
}


def parse_body(raw: bytes) -> dict[str, Any]:
    """A POST body: a JSON object, or nothing (an empty object)."""
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        raise BadRequest("the body is not JSON") from None
    if not isinstance(body, dict):
        raise BadRequest("the body must be a JSON object")
    return body


class Handler(BaseHTTPRequestHandler):
    server: DeskHTTPServer

    def log_message(self, format: str, *args: Any) -> None:
        pass

    @property
    def desk(self) -> Desk:
        return self.server.desk

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: Any, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _media(self, name: str) -> None:
        """Serve one analysed WAV (with Range, so the browser can seek). Only files analyze.py wrote."""
        f = self.desk.settings.viz_dir / name
        if "/" in name or not name.endswith(".wav") or not f.is_file():
            return self._send(404, b"not found", "text/plain")
        size = f.stat().st_size
        a, b, code = 0, size - 1, 200
        rng = self.headers.get("Range", "")
        if rng.startswith("bytes="):
            lo, _, hi = rng[6:].partition("-")
            try:
                a = int(lo) if lo else 0
                b = min(int(hi), size - 1) if hi else size - 1
            except ValueError:
                return self._send(416, b"bad range", "text/plain")
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

    # ---- GET -----------------------------------------------------------------------------------------------------
    def get_index(self, query: dict[str, str]) -> None:
        self._send(200, (HERE / "static" / "index.html").read_bytes(), "text/html; charset=utf-8")

    def get_analysis(self, query: dict[str, str]) -> None:
        f = self.desk.settings.viz_dir / "analysis.json"
        if f.exists():
            self._send(200, f.read_bytes(), "application/json")
        else:
            self._json({"error": "run analyze.py first"}, 404)

    def get_desk(self, query: dict[str, str]) -> None:
        self._json(self.desk.cfg())

    def get_history(self, query: dict[str, str]) -> None:
        self._json(self.desk.history.view())

    def get_checkpoint(self, query: dict[str, str]) -> None:
        try:
            vals = self.desk.history.load(query.get("name", ""))
        except (ValueError, FileNotFoundError) as exc:
            return self._json({"error": str(exc)}, 404)
        self._json({k: vals[k] for k in self.desk.history.cur if k in vals})

    def get_compare(self, query: dict[str, str]) -> None:
        try:
            self._json(self.desk.history.compare(query.get("a", ""), query.get("b", "now")))
        except (ValueError, FileNotFoundError) as exc:
            self._json({"error": str(exc)}, 404)

    def get_state(self, query: dict[str, str]) -> None:
        self._json(self.desk.page_state())

    def get_events(self, query: dict[str, str]) -> None:
        q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=2000)
        self.desk.clients.append(q)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            first = json.dumps({"t": "full", "state": self.desk.page_state()})
            self.wfile.write(f"data: {first}\n\n".encode())
            self.wfile.flush()
            while True:
                try:
                    msg = q.get(timeout=15)
                    self.wfile.write(f"data: {json.dumps(msg)}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except OSError:  # the page went away (BrokenPipeError, ConnectionResetError)
            pass
        finally:
            self.desk.clients.remove(q)

    GET_ROUTES: ClassVar[dict[str, Callable[[Handler, dict[str, str]], None]]] = {
        "/": get_index,
        "/index.html": get_index,
        "/api/analysis": get_analysis,
        "/api/desk": get_desk,
        "/api/history": get_history,
        "/api/checkpoint": get_checkpoint,
        "/api/compare": get_compare,
        "/api/state": get_state,
        "/events": get_events,
    }

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path.startswith("/media/"):
            return self._media(url.path[len("/media/") :])
        route = self.GET_ROUTES.get(url.path)
        if route is None:
            return self._send(404, b"not found", "text/plain")
        route(self, {k: v[0] for k, v in parse_qs(url.query).items()})

    # ---- POST ----------------------------------------------------------------------------------------------------
    def do_POST(self) -> None:
        route = POST_ROUTES.get(self.path)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = parse_body(self.rfile.read(n))
            if route is None:
                return self._json({"error": "not found"}, 404)
            code, reply = route(self.desk, body)
        except BadRequest as exc:
            code, reply = 400, {"error": str(exc)}
        except (LiveError, OSError) as exc:
            code, reply = 503, {"error": str(exc)}
        self._json(reply, code)


class DeskHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], desk: Desk) -> None:
        super().__init__(address, Handler)
        self.desk = desk


def udp_socket(port: int) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", port))
    return s


def start(desk: Desk, supervise: bool = True) -> DeskHTTPServer:
    """The desk's threads (pager datagrams, meter, supervisor) and its HTTP server, not yet serving."""
    threading.Thread(target=desk.serve_udp, args=(udp_socket(desk.settings.udp_port),), daemon=True).start()
    threading.Thread(target=desk.serve_meter, args=(udp_socket(desk.settings.meter_port),), daemon=True).start()
    if supervise:
        threading.Thread(target=desk.supervise, daemon=True).start()
    return DeskHTTPServer(("127.0.0.1", desk.settings.http_port), desk)


def main() -> None:
    srv = start(Desk(Settings.from_env()))
    print(f"mix desk on http://127.0.0.1:{srv.server_address[1]}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
