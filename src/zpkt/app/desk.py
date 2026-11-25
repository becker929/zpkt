"""The desk: what the app knows about Live's mix and the MiniLab, and the things it does with it.

`Desk` is the app's service for the mix desk. It owns the one mutable state (behind one lock), the page's event
queues, the history, the monitor and the bus. It reaches Live only through the app's connections, handed to every
zpkt.live call. deskstate.py holds the pure rules that change the state and protocol.py the messages.

Nothing here makes or plays sound: the page shows and arms controls; the mix itself is Live's.
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zpkt.app import deskstate as D
from zpkt.app import history, jobs, pages, surfaces
from zpkt.app import protocol as P
from zpkt.app.bus import Bus, Command, SetGuard
from zpkt.app.connections import BUSY_WAIT_S, LiveConnections, bind_udp, open_connections
from zpkt.app.monitor import Monitor
from zpkt.app.mounts import Mounts
from zpkt.app.renders import Options
from zpkt.audio.levels import rms_to_db
from zpkt.live import changes, config, desk_pager, meter, monitor_tracks, openset
from zpkt.live import state as S
from zpkt.live.describe import Description
from zpkt.live.transport import LiveError

START_CHECKPOINT_H = 12  # a start makes a "start-..." checkpoint unless the desk made one this recently
SUPERVISE_S = 5.0
STALE_RETRY_S = 30.0  # after a pager reload that did not help, wait this long before trying again
NO_MINILAB = "no MiniLab 3 in Live"
BEATS_PER_S = 160.0 / 60.0  # the HW002 set's tempo; the references line up on the drop in beats


HOSTS_ENV = "ZPKT_APP_HOSTS"


def hosts_from_env() -> tuple[str, ...]:
    """ZPKT_APP_HOSTS: more Host names the web server answers for, comma separated (a proxy's name that is not a
    tailnet's; see zpkt.app.web.host_allowed)."""
    return tuple(name.strip() for name in os.environ.get(HOSTS_ENV, "").split(",") if name.strip())


def mixdesk_dir() -> Path:
    """The folder with the desk's own files (desk.json, sources.json, pager.py and the old page). ZPKT_MIXDESK_DIR
    names another one; the default is contrib/mixdesk of this checkout."""
    env = os.environ.get("ZPKT_MIXDESK_DIR")
    return Path(env).expanduser() if env else Path(__file__).resolve().parents[3] / "contrib" / "mixdesk"


def read_sources() -> dict[str, Any]:
    """sources.json: the set the desk is for and the A, B and reference renders it plays."""
    sources: dict[str, Any] = json.loads((mixdesk_dir() / "sources.json").read_text())
    return sources


def default_align_beat() -> float:
    """Where the references start (the drop), in beats."""
    return float(read_sources()["ref_align_s"]) * BEATS_PER_S


def reference_ids() -> tuple[str, ...]:
    return tuple(str(r["id"]) for r in read_sources()["refs"])


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
    pages_dir: Path | None = None  # Pages (zpkt.live.page), <sets_dir>/pages/<set>; None is that default
    align_beat: float = field(default_factory=default_align_beat)  # where the references start (the drop)
    desk_file: Path = field(default_factory=lambda: mixdesk_dir() / "desk.json")  # the set's own pages
    pager_file: Path = field(default_factory=lambda: mixdesk_dir() / "pager.py")
    changes_file: Path | None = None  # the set's change stream (zpkt.live.changes); None writes none
    references: tuple[str, ...] = field(default_factory=reference_ids)
    options_dir: Path | None = None  # the queue's jobs, renders and measures (zpkt.app.renders); None: <data>/options
    arranger_dir: Path | None = None  # the HW002 arranger's data, read for Options; None: ARRANGER_DATA
    panels_dir: Path | None = None  # where `hands panel` keeps its panel files; None: the rig's renders folder
    hosts: tuple[str, ...] = ()  # more Host names the web server answers for (ZPKT_APP_HOSTS); see web.host_allowed

    @classmethod
    def from_env(cls) -> Settings:
        http_port = int(os.environ.get("MIXDESK_PORT", "8985"))
        sources = read_sources()
        set_name = sources["set"]
        return cls(
            set_name=set_name,
            viz_dir=Path(sources["dir"]).expanduser(),
            http_port=http_port,
            udp_port=http_port + 1,
            meter_port=meter.METER_PORT,
            live_port=None,
            history_dir=history.HISTORY_DIR,
            checkpoints_dir=S.folder(set_name),
            surfaces_dir=config.rig().sets_dir / "surfaces" / set_name,
            pages_dir=config.rig().sets_dir / "pages" / set_name,
            changes_file=changes.path_for(set_name),
            hosts=hosts_from_env(),
        )


def meter_message(levels: list[float], hz: list[float]) -> dict[str, Any] | None:
    """The meter's RMS levels as the page's {"t": "meter"} message in dB; None if the band count is wrong."""
    if len(levels) != len(hz):
        return None
    return {"t": "meter", "hz": hz, "db": rms_to_db(levels)}


class Desk:
    """The running desk: the state Live reported, the page's event queues, the history. One owner, one lock."""

    def __init__(
        self, settings: Settings, hist: history.History | None = None, connections: LiveConnections | None = None
    ) -> None:
        self.settings = settings
        self.conn = connections or open_connections(settings.live_port, settings.meter_port)
        self.lock = threading.Lock()
        self.state: D.DeskState = D.initial()
        self.clients: list[queue.Queue[dict[str, Any]]] = []  # the old page's event queues
        self.app_clients: list[queue.Queue[dict[str, Any]]] = []  # the /app/ shell's: they also get "hear" messages
        self._clients_lock = threading.Lock()
        self.labels: dict[str, str] = {}  # shared with the history, which names its moves by them
        self.descriptions: dict[str, Description] = {}  # what Live said of a control's range, by state key
        stream = changes.Stream(settings.changes_file) if settings.changes_file else None
        self.history = hist or history.History(
            settings.set_name, self.labels, settings.history_dir, checkpoints=settings.checkpoints_dir, changes=stream
        )
        self.making = threading.Lock()  # one "Make a surface" job at a time
        self._ensured = self._started = False  # the supervisor's: monitor tracks made, start checkpoint taken
        self._stale_reload_at = 0.0  # when the supervisor last reloaded a pager Live raised from
        self._analysis: tuple[float | None, dict[str, Any]] = (None, {"sources": {}})
        self.monitor = Monitor(self)
        self.options = Options(self)
        self.mounts = Mounts()  # the one seam for an adapter's pages: route sets under a path prefix (Ask, the Song)
        self.bus = self._make_bus()

    def _make_bus(self) -> Bus:
        from zpkt.app.commands import register_all

        def open_set() -> str:
            with self.conn.exclusive(wait_s=BUSY_WAIT_S):  # a render holds Live: say busy, do not hang the caller
                return openset.open_set_name(self.conn)

        guard = SetGuard(self.settings.set_name, open_set)
        bus = Bus(guard=guard, lock=lambda: self.conn.exclusive(wait_s=5.0), version_before=self.version_before)
        register_all(bus, self)
        jobs.register(bus, self.conn)
        return bus

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
    def call(self, expr: str) -> Any:
        """An expression on the pager's desk in Live (None when no pager runs)."""
        return desk_pager.call(self.conn, expr)

    def cfg(self) -> dict[str, Any]:
        """desk.json's pages, then the surfaces made for this set (surfaces.py), oldest first."""
        d = json.loads(self.settings.desk_file.read_text())
        d["pages"] = d["pages"] + surfaces.pages(self.settings.set_name, self.settings.surfaces_dir)
        return d

    def page_names(self) -> list[str]:
        return [pg["name"] for pg in self.cfg()["pages"]]

    def start_pager(self) -> dict[str, Any]:
        snap: dict[str, Any] = desk_pager.start(self.conn, self.settings.pager_file, self.cfg(), self.settings.udp_port)
        return snap

    def restart_pager(self) -> None:
        snap = self.start_pager()
        self.monitor.adopt(snap)
        self.set_state(snap, "attached")

    # ---- changing the state ----------------------------------------------------------------------------------------
    def push(self, msg: dict[str, Any]) -> None:
        """A message to every page connected, old page and shell."""
        with self._clients_lock:
            targets = [*self.clients, *self.app_clients]
        for q in targets:
            with contextlib.suppress(queue.Full):
                q.put_nowait(msg)

    def push_app(self, msg: dict[str, Any]) -> None:
        """A message only the /app/ shell understands."""
        with self._clients_lock:
            targets = list(self.app_clients)
        for q in targets:
            with contextlib.suppress(queue.Full):
                q.put_nowait(msg)

    def subscribe(self, app: bool = False) -> queue.Queue[dict[str, Any]]:
        q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=2000)
        with self._clients_lock:
            (self.app_clients if app else self.clients).append(q)
        return q

    def unsubscribe(self, q: queue.Queue[dict[str, Any]]) -> None:
        with self._clients_lock:
            for group in (self.clients, self.app_clients):
                if q in group:
                    group.remove(q)

    def push_full(self) -> None:
        self.push({"t": "full", "state": self.page_state()})
        self.push_app(self.monitor.message())

    def set_state(self, snap: dict[str, Any] | None, status: str) -> None:
        """A pager snapshot (or None) and Live's status: learn its keys, fold it in, send the page all of it."""
        if snap and snap.get("values"):
            self.learn(snap["values"])
        with self.lock:
            self.state = D.with_snapshot(self.state, snap, status)
        self.push_full()

    def learn(self, values: dict[str, Any]) -> None:
        """The snapshot's keys and labels, and its values as the history's starting point (not moves)."""
        self.history.add_labels(D.labels(self.cfg()["pages"], values))
        self.history.baseline(values)

    def ingest(self, msg: P.PagerMessage) -> None:
        """One message from the pager (or the app itself): into the state, out to the page, and into the history if
        it moved a value."""
        if msg["t"] == "v":
            self.monitor.before_move(msg)
        with self.lock:
            self.state = D.reduce(self.state, msg, time.time())
        self.push(dict(msg))
        if msg["t"] == "v" and self.history.seen(msg["key"], msg["s"], msg["r"], who=P.who_moved(msg)):
            self.push(self.history.view())
            self.push_app(self.monitor.message())

    def receive(self, data: bytes) -> None:
        """One datagram from the pager. A datagram that is not one of the pager's messages is dropped and said so."""
        try:
            msg = P.parse_datagram(data)
        except P.BadMessage as exc:
            print(f"app: dropped a datagram from the pager: {exc}", flush=True)
            return
        self.ingest(msg)

    def set_match(self, match: bool) -> None:
        with self.lock:
            self.state = {**self.state, "match": match}

    # ---- the threads -----------------------------------------------------------------------------------------------
    def serve_udp(self, sock: socket.socket) -> None:
        """The pager's datagrams. One bad message, or one that fails inside (a full disk), never ends the thread."""
        while True:
            try:
                data, _ = sock.recvfrom(65536)
            except OSError:
                if sock.fileno() == -1:  # closed: the app is stopping
                    return
                print("app: reading the pager's socket failed; trying again", flush=True)
                time.sleep(0.1)
                continue
            try:
                self.receive(data)
            except Exception as exc:
                print(f"app: a datagram from the pager failed ({type(exc).__name__}: {exc}); dropped", flush=True)

    def serve_meter(self) -> None:
        """The live meter on Main (zpkt.live.meter), read from the app's socket: bands as dB to the page."""
        hz = [round(f, 2) for f in meter.centers()]
        while True:
            try:
                levels = self.conn.read_meter()
            except OSError:
                if getattr(self.conn.meter, "fileno", lambda: 0)() == -1:
                    return
                time.sleep(0.1)
                continue
            msg = meter_message(levels, hz) if levels else None
            if msg:
                self.push(msg)
                self.monitor.heard(msg)

    def supervise(self) -> None:
        """Keep the pager in Live and holding the MiniLab; write the settled changes to the stream."""
        while True:
            self.supervise_once()
            with contextlib.suppress(OSError):
                self.history.flush_changes()
            time.sleep(SUPERVISE_S)

    def supervise_once(self, now: Callable[[], float] = time.time) -> None:
        """One supervisor step. When Live answers but raises from the pager, the pager is stale: it outlives the set,
        and after another set is opened under it its parameters belong to a set that is gone ("Python argument types
        in None.None(DeviceParameter) did not match C++ signature", 25 Nov 2026). Then it is loaded again, at most
        once every STALE_RETRY_S. When Live cannot be reached at all, the state says so and nothing is reloaded."""
        try:
            self._ensured = self._ensured or self._ensure_monitor_tracks()
            if not self._started and self.history.cur:  # the pager reports keys (one from before history has none)
                self.start_checkpoint()
                self._started = True
            self.check_pager()
        except LiveError as exc:
            if exc.result is None or now() - self._stale_reload_at < STALE_RETRY_S:
                self.set_state(None, f"Live does not answer ({str(exc)[:80]})")
                return
            self._stale_reload_at = now()
            self._ensured = False  # another set came in under the pager: its monitor tracks are checked again
            print(f"app: Live raised from the pager ({str(exc)[:80]}); loading the pager again", flush=True)
            try:
                self.restart_pager()
            except (LiveError, OSError) as again:
                self.set_state(None, f"Live does not answer ({str(again)[:80]})")
        except OSError as exc:
            self.set_state(None, f"Live does not answer ({str(exc)[:80]})")
        except Exception as exc:
            print(f"app: supervising failed ({type(exc).__name__}: {exc})", flush=True)

    def _ensure_monitor_tracks(self) -> bool:
        if self.snapshot()["live"] == "starting":
            return False
        want = self.monitor.wanted_tracks()
        if monitor_tracks.missing(self.conn, want):
            monitor_tracks.ensure(self.conn, want, log=lambda *a: print(*a, flush=True))
        return True

    def check_pager(self) -> None:
        """One supervisor step: start the pager if it is gone, reattach it if it lost the MiniLab."""
        status = self.snapshot()["live"]
        ok = self.call("m.DESK.attached()")
        if ok is None:
            snap = self.start_pager()
            self.monitor.adopt(snap)
            self.set_state(snap, "attached" if snap.get("attached") else NO_MINILAB)
        elif ok is False:
            attached = self.call("m.DESK.attach()")
            if attached or status != NO_MINILAB:
                self.set_state(self.call("m.DESK.snapshot()"), "attached" if attached else NO_MINILAB)
        elif status != "attached":
            self.set_state(self.call("m.DESK.snapshot()"), "attached")

    # ---- the analysis ----------------------------------------------------------------------------------------------
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
            analysis: dict[str, Any] = self._analysis[1]
            return analysis

    # ---- surfaces --------------------------------------------------------------------------------------------------
    def adopt_surface(self, path: Path, surface: dict[str, Any]) -> int:
        """A surface just saved: reload the pager with it, arm its page, tell the page. Returns the page's index.
        What the pager could not use of its macros is added to the surface's notes."""
        return self.adopt_surfaces([(path, surface)])[0]

    def adopt_surfaces(self, made: list[tuple[Path, dict[str, Any]]]) -> list[int]:
        """Several surfaces just saved (a Page with more than one MiniLab page): one pager reload, the first armed.
        Returns their pages' indexes."""
        self.restart_pager()
        pages = self.cfg()["pages"]
        found = [next(i for i, pg in enumerate(pages) if pg.get("surface") == path.name) for path, _ in made]
        self.call(f"m.DESK.arm({found[0]})")
        for idx, (_, surface) in zip(found, made, strict=True):
            for x in self.call(f"m.DESK.macro_skipped({idx})") or []:
                surface["notes"].append(f"{x} could not be used in Live; that part of the macro does nothing.")
        self.push({"t": "desk", "open": found[0]})
        return found

    def inventory(self) -> surfaces.Inventory:
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
            answer = surfaces.extract_json((ask or surfaces.ask_claude)(pages.prompt_for(text, inv, self.page_names())))
            if "groups" in answer:  # a Page: the same door as `zpkt page make`
                code, reply = self.bus.submit(Command("page.make", "you", {"spec": answer, "prompt": text}))
                if code != 200:
                    return say("error", str(reply.get("error", "The page was not made.")))
                notes = " ".join(reply["notes"])
                done = f"Made “{reply['title']}” ({len(reply['pages'])} MiniLab page(s)), saved as {reply['file']}."
                return say("done", done + (f" {notes}" if notes else ""))
            surface = surfaces.validate(answer, inv, self.page_names())  # the old slot form is still taken
            path = surfaces.save(surface, self.settings.set_name, text, self.settings.surfaces_dir)
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
        missing: list[str] = self.call(f"m.DESK.set_raw({[p[:2] for p in pairs]!r})") if pairs else []
        return missing

    def make_checkpoint(self, name: str, who: P.Who | str = P.DEFAULT_WHO) -> dict[str, Any]:
        """Checkpoint `name`: the whole mix as Live has it now. `who` made it: "sys" when the desk did on its own."""
        history.check_name(name)
        with self.conn.exclusive():  # one hold of Live for the whole read
            full = S.take(self.conn)
        saved = self.monitor.main_saved if self.monitor_choice()["slot"] != "W" else None
        return self.history.checkpoint(name, full, saved, who)  # type: ignore[arg-type]

    def version_before(self, group: str) -> None:
        """The automatic version saved before an agent's first change of a group: one name per group."""
        slug = "".join(c if c.isalnum() else "-" for c in group)[:40].strip("-") or "group"
        self.make_checkpoint(f"before-{slug}-{time.strftime('%H%M%S')}", who="sys")
        self.push(self.history.view())

    def start_checkpoint(self) -> None:
        now = time.time()
        recent = [
            e for e in self.history.entries if e["k"] == "checkpoint" and now - e["at"] < START_CHECKPOINT_H * 3600
        ]
        if not recent:
            self.make_checkpoint(time.strftime("start-%Y%m%d-%H%M"), who="sys")
            self.push(self.history.view())


def start_threads(desk: Desk, supervise: bool = True) -> None:
    """The desk's threads: the pager's datagrams, the meter and (unless told not to) the supervisor."""
    sock = bind_udp(desk.settings.udp_port)
    threading.Thread(target=desk.serve_udp, args=(sock,), daemon=True, name="pager-udp").start()
    if desk.conn.meter is not None:
        threading.Thread(target=desk.serve_meter, daemon=True, name="meter").start()
    if supervise:
        threading.Thread(target=desk.supervise, daemon=True, name="supervisor").start()
