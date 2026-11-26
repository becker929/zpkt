"""The desk: what the app knows about Live's mix and the MiniLab, and the things it does with it.

`Desk` is the app's service for the mix desk. It owns the one mutable state (behind one lock), the page's event
queues, the history, the monitor and the bus. It reaches Live only through the app's connections, handed to every
zpkt.live call. deskstate.py holds the pure rules that change the state and protocol.py the messages.

Nothing here makes or plays sound: the page shows and arms controls; the mix itself is Live's.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import queue
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zpkt.app import change, deskstate, history, jobs, organize, pages, protocol, surfaces
from zpkt.app.bus import Bus, Command, SetGuard
from zpkt.app.connections import BUSY_WAIT_S, LiveConnections, bind_udp, open_connections
from zpkt.app.monitor import Monitor
from zpkt.app.mounts import Mounts
from zpkt.audio.levels import rms_to_db
from zpkt.live import changes, config, desk_pager, meter, monitor_tracks, openset
from zpkt.live import state as live_state
from zpkt.live import writes as live_writes
from zpkt.live.describe import Description
from zpkt.live.transport import LiveError

START_CHECKPOINT_H = 12  # a start makes a "start-..." checkpoint unless the desk made one this recently
SUPERVISE_S = 5.0
STALE_RETRY_S = 30.0  # after a pager reload that did not help, wait this long before trying again
NO_MINILAB = "no MiniLab 3 in Live"
METER_KEY = "Main/zpkt desk meter"  # the history's key for the spectrum's device being on Main (no parameter of Live's)
DEFAULT_BPM = 120.0  # a set whose sources.json names no "bpm" (or ZPKT_DESK_BPM) is taken to play at this tempo


HOSTS_ENV = "ZPKT_APP_HOSTS"


log = logging.getLogger(__name__)


def hosts_from_env() -> tuple[str, ...]:
    """ZPKT_APP_HOSTS: more Host names the web server answers for, comma separated (a proxy's name that is not a
    tailnet's; see zpkt.app.web.host_allowed)."""
    return tuple(name.strip() for name in os.environ.get(HOSTS_ENV, "").split(",") if name.strip())


def mixdesk_dir() -> Path:
    """The folder with the desk's own files (desk.json, sources.json, pager.py and the old page). ZPKT_MIXDESK_DIR or
    the rig's `mixdesk_dir` names it; without either, contrib/mixdesk of a source checkout."""
    env = os.environ.get("ZPKT_MIXDESK_DIR")
    if env:
        return Path(env).expanduser()
    return config.rig().mixdesk_dir or Path(__file__).resolve().parents[3] / "contrib" / "mixdesk"


def read_sources() -> dict[str, Any]:
    """sources.json: the set the desk is for and the A, B and reference renders it plays."""
    sources: dict[str, Any] = json.loads((mixdesk_dir() / "sources.json").read_text())
    return sources


def default_ask_dir() -> Path:
    """Ask's data folder: ZPKT_ASK_DIR, else the rig's `ask_dir`."""
    env = os.environ.get("ZPKT_ASK_DIR")
    return Path(env).expanduser() if env else config.rig().ask_dir


def beats_per_s(sources: dict[str, Any] | None = None) -> float:
    """The set's tempo in beats per second: sources.json "bpm", else ZPKT_DESK_BPM, else DEFAULT_BPM."""
    bpm = (read_sources() if sources is None else sources).get("bpm") or os.environ.get("ZPKT_DESK_BPM") or DEFAULT_BPM
    return float(bpm) / 60.0


def default_align_beat() -> float:
    """Where the references start (the drop), in beats."""
    sources = read_sources()
    return float(sources["ref_align_s"]) * beats_per_s(sources)


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
    ask_dir: Path = field(default_factory=default_ask_dir)  # Ask's sessions and files (ZPKT_ASK_DIR)
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
            checkpoints_dir=live_state.folder(set_name),
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
        self.state: deskstate.DeskState = deskstate.initial()
        self.clients: list[queue.Queue[dict[str, Any]]] = []  # the old page's event queues
        self.app_clients: list[queue.Queue[dict[str, Any]]] = []  # the /app/ shell's: they also get "hear" messages
        self._clients_lock = threading.Lock()
        self.labels: dict[str, str] = {}  # shared with the history, which names its moves by them
        self.descriptions: dict[str, Description] = {}  # what Live said of a control's range, by state key
        stream = changes.Stream(settings.changes_file) if settings.changes_file else None
        self.history = hist or history.History(
            settings.set_name, self.labels, settings.history_dir, checkpoints=settings.checkpoints_dir, changes=stream
        )
        self.history.place = self.place_of
        self.history.quiet.add(METER_KEY)
        self.making = threading.Lock()  # one "Make a surface" job at a time
        self.metering = threading.Lock()  # one "turn the spectrum on" job at a time
        self._arrangement: dict[str, Any] | None = None  # the song in Live as last read; None: read it again
        self._meter_tool: Any = None
        self._ensured = self._started = False  # the supervisor's: monitor tracks made, start checkpoint taken
        self._stale_reload_at = 0.0  # when the supervisor last reloaded a pager Live raised from
        self._analysis: tuple[float | None, dict[str, Any]] = (None, {"sources": {}})
        self.monitor = Monitor(self)
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
        change.register(bus, self)
        jobs.register(bus, self.conn, self.descriptions.clear)
        return bus

    # ---- reading the state -----------------------------------------------------------------------------------------
    def snapshot(self) -> deskstate.DeskState:
        """A deep copy of the state: the UDP thread keeps changing it after a copy is queued or sent."""
        with self.lock:
            copy: deskstate.DeskState = json.loads(json.dumps(self.state))
        return copy

    def page_state(self) -> dict[str, Any]:
        """The state as the page gets it: a copy, with the loudness match's gains for every reference."""
        state = self.snapshot()
        song = {"name": state.get("set") or self.settings.set_name, **deskstate.song_facts(state)}
        gains = deskstate.matched_gains(self.analysis()["sources"])
        # "open_set" is what Live has in front ("" for a set with no file); "desk_set" the set this desk is for
        return {
            **state,
            "gains": gains,
            "song": song,
            "open_set": state.get("set") or "",
            "desk_set": self.settings.set_name,
        }

    def monitor_choice(self) -> deskstate.MonitorChoice:
        return self.snapshot()["monitor"]

    # ---- Live ------------------------------------------------------------------------------------------------------
    def call(self, expr: str) -> Any:
        """An expression on the pager's desk in Live (None when no pager runs)."""
        return desk_pager.call(self.conn, expr)

    def raw_pages(self) -> list[dict[str, Any]]:
        """desk.json's pages, then the surfaces made for this set (surfaces.py), oldest first: every page there is,
        archived or not, before the person's order."""
        d = json.loads(self.settings.desk_file.read_text())
        made: list[dict[str, Any]] = surfaces.pages(self.settings.set_name, self.settings.surfaces_dir)
        return [*d["pages"], *made]

    def pages_dir(self) -> Path:
        """Where the set's saved Pages are, and beside them the pages' order and archive (organize.py)."""
        from zpkt.live import page as live_page

        return self.settings.pages_dir or live_page.folder(self.settings.set_name)

    def cfg(self) -> dict[str, Any]:
        """The desk's pages as the page, the pager in Live and the MiniLab use them: the raw pages in the person's
        order, without the archived ones (organize.arrange)."""
        d = json.loads(self.settings.desk_file.read_text())
        d["pages"] = organize.arrange(self.raw_pages(), organize.read(self.pages_dir()))
        return d

    def page_names(self) -> list[str]:
        return [pg["name"] for pg in self.cfg()["pages"]]

    def start_pager(self) -> dict[str, Any]:
        snap: dict[str, Any] = desk_pager.start(self.conn, self.settings.pager_file, self.cfg(), self.settings.udp_port)
        return snap

    def arrangement(self, fresh: bool = False) -> dict[str, Any]:
        """The song as it lies in Live's Arrangement: tracks, their clips as regions, the locators
        (deskstate.arrangement_view). One short read through the pager, kept until Live says it changed, the pager
        loads again, or `fresh` asks."""
        with self.lock:
            kept = None if fresh else self._arrangement
        if kept is not None:
            return kept
        text = self.call("m.DESK.arrangement()")
        state = self.snapshot()
        per_bar = deskstate.song_facts(state)["beats_per_bar"]
        view = deskstate.arrangement_view(json.loads(text) if text else {}, state.get("set") or "", per_bar)
        with self.lock:
            self._arrangement = view
        return view

    def restart_pager(self) -> None:
        self.descriptions.clear()  # the pager loads again: the set may hold other devices now
        with self.lock:
            self._arrangement = None
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
        if snap:
            self.learn_extras(snap)
        with self.lock:
            self.state = deskstate.with_snapshot(self.state, snap, status)
        self.push_full()

    def learn(self, values: dict[str, Any]) -> None:
        """The snapshot's keys and labels, and its values as the history's starting point (not moves)."""
        self.history.add_labels(deskstate.labels(self.cfg()["pages"], values))
        self.history.baseline(values)

    def learn_extras(self, snap: dict[str, Any]) -> None:
        """What a snapshot says beside the pages' controls, as the history's starting point too: every track's solo
        and mute, and whether the spectrum's device is on Main."""
        flags = snap.get("flags")
        if isinstance(flags, dict):
            self.history.baseline_flags(flags.get("tracks", []), flags.get("solo", []), flags.get("mute", []))
        if isinstance(snap.get("meter"), bool):
            on = snap["meter"]
            self.history.add_labels({METER_KEY: "Spectrum"})
            self.history.baseline({"meter": {"key": METER_KEY, "s": "on" if on else "off", "r": on}})

    def place_of(self, key: str, raw: Any) -> float | None:
        """A raw value as a place from 0 to 1 on its control; None when the desk has not read the control's range."""
        if isinstance(raw, bool):
            return 1.0 if raw else 0.0
        with self.lock:
            d = self.descriptions.get(key)
        if d is None or raw is None or d["max"] == d["min"]:
            return None
        return max(0.0, min(1.0, (float(raw) - d["min"]) / (d["max"] - d["min"])))

    def ingest(self, msg: protocol.PagerMessage) -> None:
        """One message from the pager (or the app itself): into the state, out to the page, and into the history if
        it moved a value."""
        if msg["t"] == "v":
            self.monitor.before_move(msg)
        if msg["t"] == "pad":  # a pad of the MiniLab that holds a compare state: the app writes it, as the minilab
            press = Command("page.compare", "minilab", {"page": msg["page"], "slot": msg["slot"]})
            threading.Thread(target=self.bus.submit, args=(press,), daemon=True, name="minilab-pad").start()
        with self.lock:
            before = self.state
            self.state = deskstate.reduce(self.state, msg, time.time())
            after = self.state
        self.push(dict(msg))
        if msg["t"] == "arr":  # a clip or a locator changed in Live: what was read is stale
            with self.lock:
                self._arrangement = None
        if msg["t"] == "flags":  # a track soloed or muted (in Live, or by the app): each flag is a control that moved
            who: protocol.Who = "sys" if msg.get("sys") else protocol.DEFAULT_WHO
            flagged = [
                self.history.seen(key, "on" if on else "off", on, who=who)
                for key, on in deskstate.flag_changes(before, after)
            ]
            if any(flagged) or self.history.take_named():
                self.push(self.history.view())
            self.push_app(self.monitor.message())
        if msg["t"] == "v":
            moved = self.history.seen(msg["key"], msg["s"], msg["r"], who=protocol.who_moved(msg))
            if moved or self.history.take_named():  # named: the echo of a write gave its row the shown text
                self.push(self.history.view())
            if moved:
                self.push_app(self.monitor.message())

    def receive(self, data: bytes) -> None:
        """One datagram from the pager. A datagram that is not one of the pager's messages is dropped and said so."""
        try:
            msg = protocol.parse_datagram(data)
        except protocol.BadMessage as exc:
            log.warning(f"app: dropped a datagram from the pager: {exc}")
            return
        self.ingest(msg)

    def set_tempo(self, bpm: float) -> None:
        """The tempo the app just set in Live: the page's identity line follows without asking Live again."""
        with self.lock:
            self.state = {**self.state, "tempo": float(bpm)}
        self.push_full()

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
                log.warning("app: reading the pager's socket failed; trying again")
                time.sleep(0.1)
                continue
            try:
                self.receive(data)
            except Exception as exc:
                log.warning(f"app: a datagram from the pager failed ({type(exc).__name__}: {exc}); dropped")

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
            log.warning(f"app: Live raised from the pager ({str(exc)[:80]}); loading the pager again")
            try:
                self.restart_pager()
            except (LiveError, OSError) as again:
                self.set_state(None, f"Live does not answer ({str(again)[:80]})")
        except OSError as exc:
            self.set_state(None, f"Live does not answer ({str(exc)[:80]})")
        except Exception as exc:
            log.warning(f"app: supervising failed ({type(exc).__name__}: {exc})")

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

    def adopt_surfaces(self, made: list[tuple[Path, dict[str, Any]]], arm: bool = True) -> list[int]:
        """Several surfaces just saved (a Page with more than one MiniLab page): one pager reload, the first armed.
        With `arm` false the desk stays on the page it was on (a page written over in place, by an agent: what the
        MiniLab's controls work does not change under the hand unless it is that page). Returns their pages'
        indexes."""
        before = None if arm else self.armed_page_name()
        self.restart_pager()
        pages = self.cfg()["pages"]
        found = [next(i for i, pg in enumerate(pages) if pg.get("surface") == path.name) for path, _ in made]
        shown = found[0]
        if not arm:
            stay = next((i for i, pg in enumerate(pages) if (pg.get("surface") or pg["name"]) == before), None)
            shown = min(self.snapshot()["page"], len(pages) - 1) if stay is None else stay
        self.call(f"m.DESK.arm({shown})")
        for idx, (_, surface) in zip(found, made, strict=True):
            for x in self.call(f"m.DESK.macro_skipped({idx})") or []:
                surface["notes"].append(f"{x} could not be used in Live; that part of the macro does nothing.")
        self.push({"t": "desk", "open": shown})
        return found

    def current_unit_id(self) -> str | None:
        """The unit id of the page currently armed on the desk (before a write to _organize.json)."""
        pages = self.cfg()["pages"]
        idx = self.snapshot()["page"]
        return organize.unit_id(pages[idx]) if 0 <= idx < len(pages) else None

    def apply_organize(self, before_unit: str | None = None) -> int:
        """Reload the pager after _organize.json changed, staying on `before_unit` if it is still on the desk."""
        self.restart_pager()
        pages = self.cfg()["pages"]
        shown = next((i for i, pg in enumerate(pages) if before_unit and organize.unit_id(pg) == before_unit), None)
        if shown is None:
            shown = max(0, min(self.snapshot()["page"], len(pages) - 1))
        self.call(f"m.DESK.arm({shown})")
        self.push({"t": "desk", "open": shown})
        return shown

    def armed_page_name(self) -> str | None:
        """What names the armed page across a reload: its surface file, or its name for one of desk.json's. The
        surfaces on disk may have changed already, so the pager's own list is asked."""
        with contextlib.suppress(LiveError, OSError, TypeError, ValueError):
            named = self.call(
                "(m.DESK.cfg['pages'][m.DESK.page].get('surface') or m.DESK.cfg['pages'][m.DESK.page]['name'])"
            )
            return str(named) if named else None
        return None

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
        """[[key, raw], ...] into Live through the pager (one call); returns the keys it could not find. The
        spectrum's device is the one "control" that is no parameter: its value is whether it is on Main."""
        for _key, raw, *_ in (p for p in pairs if p[0] == METER_KEY):
            self.meter_set(bool(raw))
        rest = [p[:2] for p in pairs if p[0] != METER_KEY]
        missing: list[str] = self.call(f"m.DESK.set_raw({rest!r})") if rest else []
        return missing

    def write_anywhere(self, pairs: list[list[Any]]) -> list[str]:
        """`write`, and a key the pager does not know (it knows the controls on the desk's pages) is then written
        by its name in the set (zpkt.live.writes.set_keys): a batch and its undo reach values no page holds.
        Returns the keys the set does not have."""
        missing = self.write(pairs)
        if missing:
            missing = live_writes.set_keys(self.conn, [p[:2] for p in pairs if p[0] in missing])
        return missing

    # ---- the spectrum's device on Main -----------------------------------------------------------------------------
    def meter_tool(self) -> Any:
        """The desk's own meter tool (`meter.py` in the mixdesk folder: present, install, remove), loaded by path."""
        if self._meter_tool is None:
            import importlib.util

            path = mixdesk_dir() / "meter.py"
            spec = importlib.util.spec_from_file_location("zpkt_mixdesk_meter", path)
            if spec is None or spec.loader is None or not path.exists():
                raise OSError(f"there is no meter tool at {path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self._meter_tool = module
        return self._meter_tool

    def meter_set(self, on: bool) -> None:
        """Put the spectrum's device on Main, or take it off (undo and redo of turning it on)."""
        tool = self.meter_tool()
        if on:
            tool.install(self.conn, log=lambda *a: None)
        else:
            tool.remove(self.conn)
        self._meter_is(on)

    def _meter_is(self, on: bool) -> None:
        with self.lock:
            self.state = {**self.state, "meter": on}
        self.push_full()

    def meter_job(self, who: protocol.Who | str, group: str | None = None) -> None:
        """Turn the spectrum on (its own thread: Live's browser takes seconds to list a new device): the device goes
        last on Main, as one history entry, so undo takes it off again. The page is told how it goes."""

        def say(status: str, msg: str = "") -> None:
            self.push_app({"t": "meterjob", "status": status, "msg": msg})

        if not self.metering.acquire(blocking=False):
            return
        try:
            say("working")
            self.meter_tool().install(self.conn, log=lambda *a: None)
            self.history.record([[METER_KEY, True, "on"]], who, group)
            self._meter_is(True)
            self.push(self.history.view())
            say("done")
        except Exception as exc:  # the tool's own stop, Live, a missing template: all are "it did not turn on"
            log.warning(f"app: turning the spectrum on failed ({type(exc).__name__}: {str(exc)[:120]})")
            say("error", str(exc)[:200])
        finally:
            self.metering.release()

    def make_checkpoint(self, name: str, who: protocol.Who | str = protocol.DEFAULT_WHO) -> dict[str, Any]:
        """Checkpoint `name`: the whole mix as Live has it now. `who` made it: "sys" when the desk did on its own."""
        history.check_name(name)
        with self.conn.exclusive():  # one hold of Live for the whole read
            full = live_state.take(self.conn)
        saved = self.monitor.main_saved if self.monitor_choice()["slot"] != "W" else None
        entry = self.history.checkpoint(name, full, saved, who)  # type: ignore[arg-type]
        self.push_app(self.monitor.message())  # "changed" counts from this checkpoint now
        return entry

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
