"""The MIDI adapter: the MiniLab 3, through raw MIDI, as one of the app's hands (who = minilab).

It is off unless asked for (`zpkt app --adapters web,midi`). The pager in Live and ZpktMiniLabTempo stay the default
until Anthony's gate; to try this one, set Live's MiniLab 3 control surface to None (so Live lets go of the ports) and
stop the old pager's hold. Two programs on one controller would both act.

The shell only moves data. A move arrives from the port, `zpkt.app.minilab.mapper.step` decides what it means, and the
result is either a Command for the bus (stamped `minilab`, so history and undo cover it) or two lines for the display.
A knob's stream is coalesced: the latest place per control is kept, and each tick one batch goes out (`page.set`).
What comes back (LEDs, knob rings, the page's name) is sent as SysEx, once, when it changes.

One worker thread owns the map's state, so the state needs no lock: the port's callback and the desk's events only put
items in a queue. This module imports nothing from zpkt.live; Live is reached through the bus alone.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from zpkt.app.adapters import AdapterSpec, AppContext
from zpkt.app.bus import Command
from zpkt.app.minilab import feedback, mapper, sysex
from zpkt.app.minilab.core import pagercore
from zpkt.app.minilab.latency import LatencyProbe
from zpkt.app.minilab.mapper import MapState, Show, Submit, View
from zpkt.app.minilab.ports import MidiPort, open_port
from zpkt.app.minilab.profile import Event, Profile, load_profile
from zpkt.app.minilab.view import pages_from_cfg, view_from

WHO = "minilab"
TICK_S = 0.02  # a stream is sent at most this often
VIEW_MESSAGES = ("full", "page", "v", "pos", "mon", "loop", "hear", "desk")  # desk messages that change the View
TEMPO_MODES = ("auto", "on", "off")


class MidiAdapter:
    """Raw MIDI in, commands out, SysEx back. See the module docstring."""

    name = "midi"

    def __init__(
        self,
        context: AppContext,
        port: MidiPort | None = None,
        profile: Profile | None = None,
        tempo: str = "auto",
        tick_s: float = TICK_S,
        clock: Callable[[], float] = time.monotonic,
        probe: LatencyProbe | None = None,
    ) -> None:
        if tempo not in TEMPO_MODES:
            raise ValueError(f"tempo is one of {', '.join(TEMPO_MODES)}, not {tempo!r}")
        self.context, self.port, self.tempo, self.tick_s, self.clock, self.probe = (
            context,
            port,
            tempo,
            tick_s,
            clock,
            probe,
        )
        self.profile = profile or load_profile()
        self.refused: deque[tuple[str, int, str]] = deque(maxlen=50)  # (kind, status, why): the last the bus refused
        self._inbox: queue.Queue[tuple[str, Any, float]] = queue.Queue()
        self._desk_q: queue.Queue[dict[str, Any]] | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._map = MapState()
        self._view = View()
        self._pending: list[Submit] = []
        self._moved_at: dict[str, float] = {}  # the oldest unsent move of a stream
        self._sent: dict[str, list[int]] = {}  # the last message sent to each target
        self._last_page: int | None = None
        self._cfg_pages: tuple[Any, ...] = ()

    # ---- lifecycle -------------------------------------------------------------------------------------------------
    def start(self) -> None:
        if self.port is None:
            self.port = open_port(self.profile)
        self._desk_q = self.context.desk.subscribe()
        self._refresh(reload_pages=True)
        self._running = True
        self._thread = threading.Thread(target=self._run, name="midi-adapter", daemon=True)
        self._thread.start()
        self.port.start(lambda event: self._inbox.put(("midi", event, self.clock())))
        self._inbox.put(("refresh", None, self.clock()))

    def stop(self) -> None:
        self._running = False
        self._inbox.put(("stop", None, self.clock()))
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        if self.port is not None:
            self.port.close()
        if self._desk_q is not None:
            self.context.desk.unsubscribe(self._desk_q)
            self._desk_q = None
        if self.probe is not None:
            self.probe.close()

    # ---- the worker ------------------------------------------------------------------------------------------------
    def _run(self) -> None:
        while self._running:
            try:
                items = [self._inbox.get(timeout=self.tick_s)]
            except queue.Empty:
                items = []
            while True:
                try:
                    items.append(self._inbox.get_nowait())
                except queue.Empty:
                    break
            for kind, payload, at in items:
                if kind == "stop":
                    return
                try:
                    self._handle(kind, payload, at)
                except Exception as exc:  # one bad message never ends the adapter
                    print(f"midi: {kind} failed ({type(exc).__name__}: {exc}); dropped", flush=True)
            self._drain_desk()
            self._flush()

    def _handle(self, kind: str, payload: Any, at: float) -> None:
        if kind == "midi":
            self._on_event(payload, at)
        elif kind == "refresh":
            self._refresh(reload_pages=True)

    def _drain_desk(self) -> None:
        """The desk's messages: the View changes, and Live's echo of a knob is its latency's end."""
        if self._desk_q is None:
            return
        changed = False
        while True:
            try:
                msg = self._desk_q.get_nowait()
            except queue.Empty:
                break
            if msg.get("t") not in VIEW_MESSAGES:
                continue
            changed = True
            if msg.get("t") == "v" and self.probe is not None:
                self.probe.echo(str(msg.get("slot")), self.clock())
        if changed:
            self._refresh(reload_pages=False)

    # ---- the View and what is sent back ------------------------------------------------------------------------------
    def _refresh(self, reload_pages: bool) -> None:
        desk = self.context.desk
        if reload_pages or not self._cfg_pages:
            self._cfg_pages = pages_from_cfg(desk.cfg()["pages"])
        message = desk.monitor.message()
        self._view = view_from(desk.snapshot(), self._cfg_pages, desk.labels, str(message.get("hearing", "now")))
        changed = self._view.page != self._last_page
        self._last_page = self._view.page
        self._send(feedback.feedback(self.profile, self._view, page_changed=changed))

    def _send(self, messages: dict[str, list[int]]) -> None:
        """SysEx for each target whose message changed."""
        if self.port is None:
            return
        for target, data in messages.items():
            if self._sent.get(target) != data:
                self._sent[target] = data
                self.port.send_sysex(data)

    def _show(self, action: Show) -> None:
        self._send({"display": sysex.display(self.profile, action.line_1, action.line_2)})

    # ---- a move ------------------------------------------------------------------------------------------------------
    def _on_event(self, event: Event, at: float) -> None:
        hit = self.profile.match(event)
        if hit is None:
            return
        tempo_on = pagercore().tempo_layer_on(self.tempo, self._view.driving)
        self._map, actions = mapper.step(self._map, hit, self._view, tempo_on)
        for action in actions:
            if isinstance(action, Show):
                self._show(action)
            elif action.coalesce is not None:
                self._pending = mapper.merge(self._pending, action)
                self._moved_at.setdefault(action.coalesce, at)
            else:
                self._flush()  # what was asked first goes first
                self._submit(action, at, at)

    def _flush(self) -> None:
        """One batch per stream: the latest places the knobs were turned to."""
        pending, self._pending = self._pending, []
        moved, self._moved_at = self._moved_at, {}
        for action in pending:
            assert action.coalesce is not None
            self._submit(action, moved.get(action.coalesce, self.clock()), self.clock())

    def _submit(self, action: Submit, moved_at: float, sent_at: float) -> None:
        reply = self.context.bus.submit(Command(action.kind, WHO, dict(action.args)))  # type: ignore[arg-type]
        replied_at = self.clock()
        status, body = reply
        if status != 200:
            why = str(body.get("error", ""))
            self.refused.append((action.kind, status, why))
            self._show(Show("Refused", why[:18]))
        if self.probe is not None and action.kind == "page.set":
            slots = [str(c["slot"]) for c in action.args["controls"]]
            self.probe.batch(slots, moved_at, sent_at, replied_at, status)


def settings_from_env() -> dict[str, Any]:
    """The adapter's choices from the environment: ZPKT_MIDI_TEMPO (auto, on, off)."""
    return {"tempo": os.environ.get("ZPKT_MIDI_TEMPO", "auto")}


def make(context: AppContext) -> MidiAdapter:
    return MidiAdapter(context, **settings_from_env())


ADAPTER = AdapterSpec("midi", make)
