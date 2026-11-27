"""Steps on the MiniLab: the app's side of the pager's steps layer.

While the step sequencer has a pattern in hand (the focus, zpkt.app.steps_commands.focus) and nothing is in its
way, the MiniLab's pads are that pattern's steps: bank A is steps 1-8 and bank B steps 9-16 of the bar in view, lit
when on; knobs 1-3 are the velocity, length and swing of a new step; the data knob walks the kit's sounds; a key
played chooses its sound. The decisions are contrib/mixdesk/pagercore.py's (the same file the pager runs in Live).
`Hand` carries both directions:

    to the pager      `show()`: one short call, `m.DESK.steps_layer(...)`, with what the controller shows
                      (pagercore.steps_layer: on or off, the 16 lights, the three knob values), and only when
                      that has changed. The focus's `rev` says cheaply that nothing has.
    from the pager    its datagrams become commands on the bus, as the minilab:
                      {"t": "step", "pad"}                  steps.toggle (the focus, and the step under that pad)
                      {"t": "step_knob", "what", "value"}   steps.focus {velocity | length | swing}
                      {"t": "step_sound", "turn"}           steps.focus {pitch}: the next or previous sound
                      {"t": "step_sound", "pitch"}          steps.focus {pitch}, when it is one of the kit's sounds

Both run on a thread of the hand's own, in the order they came: never on the pager's datagram thread (which must not
wait for Live), and never inside the command that changed the pattern (a call to Live waits for Live's next tick,
and the page that sent the command should not wait for the controller's lights). What arrives while a command is in
Live is taken together: a run of knob turns and data-knob turns becomes one command with the latest of each, and
the pager is told once, the latest. That is the throttle. A light that changed is told at once. A knob's value that
changed on the screen is not urgent (it only moves where knobs 1-3 stand): it is told when the changes have stopped
for a moment, so a knob dragged on the page does not share Live with a call per value. The screen needs nothing
more: every one of these ends in the {"t": "steps"} message every page gets.

With the MIDI adapter (zpkt.app.adapters.midi) the map sends the same commands itself (zpkt.app.minilab.mapper).
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from zpkt.app.bus import Command
from zpkt.app.connections import BUSY_WAIT_S
from zpkt.app.protocol import STEP_KNOBS, Who

if TYPE_CHECKING:
    from zpkt.app.desk import Desk

KINDS = ("step", "step_knob", "step_sound")  # the pager's messages that are the hand's
SHOW = {"t": "_show"}  # the hand's own: tell the pager what the focus is now
WHO: Who = "minilab"
IDLE_S = 5.0  # the hand's thread ends after this long with nothing to do; the next message starts one
KNOBS_QUIET_S = 0.3  # a knob value changed from the screen reaches the pager once the changes have stopped this long
PRESS_KEYS = ("track", "bar", "bars", "steps_per_bar", "pitch", "velocity", "length", "swing")  # of the focus

log = logging.getLogger(__name__)


def core() -> Any:
    """pagercore.py, the rules shared with the pager (loaded on first use: its loader imports the desk)."""
    from zpkt.app.minilab.core import pagercore

    return pagercore()


class Hand:
    """The MiniLab's hand on the step sequencer, for one desk."""

    def __init__(self, desk: Desk) -> None:
        self.desk = desk
        self.calls = 0  # how many times the pager was told (tests count them)
        self._told: dict[str, Any] | None = None  # what the pager last got; None: no layer
        self._told_rev: int | None = None  # the focus's rev that was (None: no focus)
        self._known = False  # whether the pager shows `_told`: not after a call that failed, nor before the first
        self._reloaded = False  # a pager from before the steps layer was loaded again (once while the app runs)
        self._turned: dict[str, Any] = {}  # the knob values the pager itself reported since it was last told
        self._inbox: queue.Queue[dict[str, Any]] = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._waiting = 0  # messages given to the hand and not yet done
        self._later: float | None = None  # when (time.monotonic) knob values that wait are told to the pager
        self._sounds: tuple[str, tuple[int, ...]] | None = None  # (track, its kit's pitches) as last read

    # ---- to the pager ------------------------------------------------------------------------------------------
    def show(self) -> None:
        """The focus changed (or may have): have the hand's thread tell the pager, if what it shows has changed."""
        self.heard(SHOW)

    def heal(self) -> None:
        """The supervisor's step: a pager that was not told (a call that failed, an app that just started) is."""
        if not self._known:
            self.show()

    def restarted(self) -> None:
        """The pager was loaded afresh: it shows no layer. With a focus in place it is told now, in this thread
        (the pager's own restart is a call to Live already)."""
        with self._lock:
            self._told, self._told_rev, self._known = None, None, True
        if self.desk.steps_now() is not None:
            self.tell(force=True)

    def tell(self, force: bool = False) -> bool:
        """Tell the pager what the controller shows of the focus, unless it shows that already; `force` says it
        again whatever it shows. Never raises: a Live that is busy or gone is tried again by the supervisor.
        Returns whether the pager was called."""
        try:
            with self.desk.conn.exclusive(wait_s=BUSY_WAIT_S):  # one at a time, each with the focus as it is then
                focus = self.desk.steps_now()
                rev = None if focus is None else focus.get("rev")
                with self._lock:
                    known, told, told_rev = self._known, self._told, self._told_rev
                if not force and known and rev == told_rev:
                    return False
                state = core().steps_layer(focus)
                if not force and known and (state == told or self._own_knobs(state, told)):
                    with self._lock:
                        self._told, self._told_rev = state, rev
                    return False
                answer = self.desk.call(f"m.DESK.steps_layer({state!r}, {bool(force)!r})")
                self.calls += 1
                with self._lock:  # None: no pager runs; one that starts is told then (`restarted`)
                    self._told, self._told_rev, self._known = state, rev, answer is not None
                    self._turned = {}
        except Exception as exc:  # the lights never fail anything else
            with self._lock:
                self._known = False
                old_pager = "no attribute 'steps_layer'" in str(exc) and not self._reloaded
                self._reloaded = self._reloaded or old_pager
            log.warning(f"app: the MiniLab was not told the steps ({type(exc).__name__}: {str(exc)[:120]})")
            if old_pager:
                self._reload()
            return False
        return True

    def _own_knobs(self, state: dict[str, Any] | None, told: dict[str, Any] | None) -> bool:
        """Is the pager's own knob all that changed? Then it stands there already: a turn of knob 1 needs no call
        back to say the velocity it has just reported."""
        if state is None or told is None:
            return False
        changed = [k for k in state if state[k] != told.get(k)]
        return all(k in STEP_KNOBS and k in self._turned and self._turned[k] == state[k] for k in changed)

    def _reload(self) -> None:
        """The pager in Live is from before it had a steps layer (the app was updated under it, and a pager that
        holds the MiniLab is not loaded again by itself): load it again, once. It keeps its page and what is heard,
        and is told the focus as it starts (`restarted`)."""
        log.warning("app: the pager in Live has no steps layer; loading the pager again")
        try:
            self.desk.restart_pager()
        except Exception as exc:
            log.warning(f"app: the pager was not loaded again ({type(exc).__name__}: {str(exc)[:120]})")

    # ---- from the pager ----------------------------------------------------------------------------------------
    def heard(self, message: Mapping[str, Any]) -> None:
        """One of the pager's steps messages (or SHOW): queued for the hand's thread, started when there is none."""
        with self._lock:
            self._inbox.put(dict(message))
            self._waiting += 1
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, daemon=True, name="minilab-steps")
                self._thread.start()

    def idle(self) -> bool:
        """Has the hand done everything it was given? (Tests wait for this.)"""
        with self._lock:
            return self._waiting == 0 and self._later is None

    def _run(self) -> None:
        while True:
            later = self._later
            try:
                first = self._inbox.get(timeout=IDLE_S if later is None else max(0.0, later - time.monotonic()))
            except queue.Empty:
                if later is not None:  # the knob values that waited: the changes have stopped
                    self.tell()
                    with self._lock:
                        self._later = None
                    continue
                with self._lock:
                    if self._inbox.empty():
                        self._thread = None
                        return
                continue
            batch = [first]
            while True:
                try:
                    batch.append(self._inbox.get_nowait())
                except queue.Empty:
                    break
            try:
                self.work(batch)
            except Exception as exc:  # one bad message never ends the hand
                log.warning(f"app: a steps message from the MiniLab failed ({type(exc).__name__}: {exc}); dropped")
            finally:
                with self._lock:
                    self._waiting -= len(batch)

    def work(self, batch: list[dict[str, Any]]) -> None:
        """Everything that came since the last command, in order. Knob turns and data-knob turns in a row are one
        steps.focus with the latest value of each knob and the sum of the turns; the pager is told last, once."""
        values: dict[str, Any] = {}
        turn = 0
        show = False
        for message in batch:
            kind = message.get("t")
            if kind == SHOW["t"]:
                show = True
            elif kind == "step_knob" and message.get("what") in STEP_KNOBS:
                values[str(message["what"])] = message.get("value")
                with self._lock:
                    self._turned[str(message["what"])] = message.get("value")
            elif kind == "step_sound" and "turn" in message:
                turn += int(message["turn"])
            else:
                self._set(values, turn)
                values, turn = {}, 0
                if kind == "step":
                    self._press(message.get("pad"))
                elif kind == "step_sound" and "pitch" in message:
                    self._choose(message["pitch"])
        self._set(values, turn)
        if show:
            self._shown()

    def _shown(self) -> None:
        """The focus changed: tell the pager now, unless knob values are all that it would hear. Those wait until
        the changes have stopped (each new one waits again)."""
        state = core().steps_layer(self.desk.steps_now())
        with self._lock:
            known, told = self._known, self._told
            waits = (
                known
                and state is not None
                and told is not None
                and state != told
                and all(state[k] == told.get(k) for k in state if k not in STEP_KNOBS)
                and not self._own_knobs(state, told)
            )
            self._later = time.monotonic() + KNOBS_QUIET_S if waits else None
        if not waits:
            self.tell()

    def _focus(self) -> dict[str, Any] | None:
        """The focus, when the layer is on for it (there is one and no clip is in its way)."""
        focus = self.desk.steps_now()
        return focus if core().steps_layer(focus) is not None else None

    def _submit(self, kind: str, args: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        code, body = self.desk.bus.submit(Command(kind, WHO, args))
        if code != 200:
            log.info(f"app: the MiniLab's {kind} was refused ({code}: {str(body.get('error', ''))[:120]})")
        return code, body

    def _press(self, pad: Any) -> None:
        """A pad: flip its step. A press that flips nothing (no focus, a pad past the pattern, Live refused) has
        the pager say its lights again: the pad's light flipped under the finger."""
        focus = self._focus()
        step = core().pad_step(focus, pad) if focus is not None and type(pad) is int else None
        if focus is not None and step is not None:
            code, _ = self._submit("steps.toggle", {**{k: focus[k] for k in PRESS_KEYS}, "step": step})
            if code == 200:
                return
        self.tell(force=True)

    def _set(self, values: dict[str, Any], turn: int) -> None:
        """The knobs' values and the data knob's turns as one steps.focus."""
        if not values and not turn:
            return
        focus = self._focus()
        if focus is None:
            return
        args = dict(values)
        if turn:
            kit = self._kit(focus["track"])
            pitch = None if kit is None else core().step_sound(kit, focus["pitch"], turn)
            if pitch is not None and pitch != focus["pitch"]:
                args["pitch"] = pitch
        if args:
            self._submit("steps.focus", args)

    def _choose(self, pitch: Any) -> None:
        """A pad of the Drum Rack was selected in Live (a key was played): the sound, if it is one of the kit's."""
        focus = self._focus()
        if focus is None or type(pitch) is not int or pitch == focus["pitch"]:
            return
        kit = self._kit(focus["track"], want=pitch)
        if kit is not None and core().is_sound(kit, pitch):
            self._submit("steps.focus", {"pitch": pitch})

    def _kit(self, track: str, want: int | None = None) -> tuple[int, ...] | None:
        """The pitches of the track's kit, lowest first (steps.sounds): read once per track, and again when `want`
        is not among them (a pad may have been filled since). Empty for a track with no Drum Rack; None when Live
        did not say."""
        kept = self._sounds
        if kept is None or kept[0] != track or (want is not None and kept[1] and want not in kept[1]):
            code, body = self._submit("steps.sounds", {"track": track})
            if code != 200:
                return None
            kept = (track, tuple(int(s["pitch"]) for s in body["sounds"]))
            self._sounds = kept
        return kept[1]
