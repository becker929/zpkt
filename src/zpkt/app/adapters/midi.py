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

import logging
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
from zpkt.app.minilab.view import pages_from_cfg, steps_view, view_from

WHO = "minilab"
TICK_S = 0.02  # a stream is sent at most this often
# desk messages that change the View ("steps": what the step sequencer has in hand; the pads are its steps then)
VIEW_MESSAGES = ("full", "page", "v", "pos", "mon", "loop", "hear", "desk", "steps")
TEMPO_MODES = ("auto", "on", "off")


log = logging.getLogger(__name__)


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
        self._last_shown: tuple[Any, ...] | None = None  # the page, and the steps layer's sound, last shown
        self._kit: tuple[str, list[dict[str, Any]] | None] | None = None  # (track, its kit's sounds as last read)
        self._cfg_pages: tuple[Any, ...] = ()
        self._compares: list[Any] = []  # each desk page's "compare" block, or None

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
            if items:
                self._drain_desk()  # a move is decided on what the desk shows now, not a tick ago
            for kind, payload, at in items:
                if kind == "stop":
                    return
                try:
                    self._handle(kind, payload, at)
                except Exception as exc:  # one bad message never ends the adapter
                    log.warning(f"midi: {kind} failed ({type(exc).__name__}: {exc}); dropped")
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
        changed = pages = False
        while True:
            try:
                msg = self._desk_q.get_nowait()
            except queue.Empty:
                break
            if msg.get("t") not in VIEW_MESSAGES:
                continue
            changed = True
            pages = pages or msg.get("t") == "desk"  # a page was made, changed or removed: read the list again
            if msg.get("t") == "v" and self.probe is not None:
                self.probe.echo(str(msg.get("slot")), self.clock())
        if changed:
            self._refresh(reload_pages=pages)

    # ---- the View and what is sent back ------------------------------------------------------------------------------
    def _refresh(self, reload_pages: bool) -> None:
        desk = self.context.desk
        if reload_pages or not self._cfg_pages:
            cfg = desk.cfg()["pages"]
            self._cfg_pages = pages_from_cfg(cfg)
            self._compares = [pg.get("compare") for pg in cfg]
        message = desk.monitor.message()
        state = desk.snapshot()
        compare = self._compares[state["page"]] if 0 <= state["page"] < len(self._compares) else None
        focus = desk.steps_now()
        steps = steps_view(focus, self._sounds(focus))
        hearing = str(message.get("hearing", "now"))
        self._view = view_from(state, self._cfg_pages, desk.labels, hearing, compare, steps)
        # the rings and the display are said again when a page is armed, and when the steps layer comes or goes
        # or has another sound in hand
        sound = None if steps is None else tuple(steps.focus[k] for k in ("track", "bar", "pitch"))
        shown = (self._view.page, sound)
        changed = shown != self._last_shown
        self._last_shown = shown
        self._send(feedback.feedback(self.profile, self._view, page_changed=changed))

    def _sounds(self, focus: dict[str, Any] | None) -> list[dict[str, Any]] | None:
        """The sounds of the focused track's kit (steps.sounds, as the minilab): asked once per track, while the
        sequencer has a pattern in hand. None when Live did not say: the keys and the data knob then choose
        nothing."""
        if focus is None:
            return None
        if self._kit is None or self._kit[0] != focus["track"]:
            ask = Command("steps.sounds", WHO, {"track": focus["track"]})  # type: ignore[arg-type]
            status, body = self.context.bus.submit(ask)
            self._kit = (focus["track"], list(body["sounds"]) if status == 200 else None)
        return self._kit[1]

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
        if hit is None and self._view.steps is not None:
            hit = self.profile.key(event)  # in the steps layer a key in any octave may be one of the kit's sounds
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
