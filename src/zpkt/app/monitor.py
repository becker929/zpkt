"""zpkt.app.monitor: what is heard, and how to compare it. Now, the Pin, the Reference, the level match, the transport.

Now is the mix as Live has it. The Pin is a checkpoint you set aside (a checkpoint, or the mix as the desk first saw it
until you pin one). Hearing the Pin writes the pinned values into Live; Now comes back when you ask, or when you touch
a control (the move then counts from where Now was). The Reference is one of the monitor tracks: audio clips that
Live plays, soloed, with Main's desk devices bypassed (zpkt.live.monitor_tracks). The level match brings A, B and the
reference to one loudness (deskstate.matched_gain_db).

The monitor reaches Live only through zpkt.live functions that take the app's connection. Band levels come from the
meter (zpkt.live.meter), and dB from zpkt.audio.levels; both arrive here already read. It streams its state to the
clients as {"t": "hear", ...}.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import soundfile as sf

from zpkt.app import deskstate as D
from zpkt.app import history
from zpkt.app import protocol as P
from zpkt.live import monitor_tracks

if TYPE_CHECKING:
    from zpkt.app.desk import Desk

HEARINGS: tuple[str, ...] = ("now", "pin", "ref")
PIN_NAME = "pin"  # the checkpoint a pin is saved as
# The legacy slots that are a render, not the live mix: A the original render, B the recipe's render.
RENDER_HEARINGS: dict[str, str] = {"A": "original", "B": "recipe"}


def hearing_of(slot: str, pin_heard: bool) -> str:
    """What the Hear bar says is heard: the Pin when it is, else the reference (slot C), a legacy render (A, B) or Now (W)."""
    if pin_heard:
        return "pin"
    if slot == "C":
        return "ref"
    return RENDER_HEARINGS.get(slot, "now")


class Monitor:
    """The desk's monitor. Its small state has its own lock, never held while Live is called."""

    def __init__(self, desk: Desk) -> None:
        self.desk = desk
        self._lock = threading.Lock()
        self.main_saved: dict[str, float] | None = None  # Main's desk devices' On values while a monitor track plays
        self._pin: dict[str, list[Any]] | None = None  # the pinned values; None: the mix as first seen
        self._loop_before: str | None = None  # the loop that was on when the reference was chosen
        self._pin_name: str | None = (
            None  # the checkpoint chosen as the Pin (B) in History; None: the mix pinned as it was
        )
        self._now: dict[str, list[Any]] | None = None  # Now's values while the Pin is heard
        self.last_meter: dict[str, Any] | None = None

    # ---- the monitor tracks ----------------------------------------------------------------------------------------
    def wanted_tracks(self) -> dict[str, tuple[Path, float]]:
        """{monitor track: (its WAV, the beat it starts at)}: A and B at the start, the references at the drop."""
        s = self.desk.settings
        want = {"mon A": (s.viz_dir / "A.wav", 0.0), "mon B": (s.viz_dir / "B.wav", 0.0)}
        for ref in s.references:
            want[f"mon {ref}"] = (s.viz_dir / f"{ref}.wav", s.align_beat)
        return want

    def adopt(self, snapshot: dict[str, Any] | None) -> None:
        """What a pager (re)start reports of the monitor: Main's saved devices, so a bypass is not forgotten."""
        if snapshot and "main_saved" in snapshot:
            with self._lock:
                self.main_saved = snapshot["main_saved"]

    def reference_beats(self, ref: str, st: Mapping[str, Any]) -> float:
        """How long reference `ref`'s clip is in the set, in beats: its file's seconds at the set's tempo (its warping
        is off). 0.0 when the file cannot be read."""
        try:
            seconds = sf.info(str(self.desk.settings.viz_dir / f"{ref}.wav")).duration
        except Exception:  # no file, or not audio: the caller keeps the song's own loop
            return 0.0
        from zpkt.app.desk import beats_per_s  # here, not at the top: desk imports this module

        tempo = float(st.get("tempo") or 0.0) or 60.0 * beats_per_s()
        return round(float(seconds) * tempo / 60.0, 4)

    # ---- the level match -------------------------------------------------------------------------------------------
    def gain_db(self, slot: str, ref: str) -> float:
        d = self.desk
        return D.matched_gain_db(d.analysis()["sources"], slot, ref, d.snapshot()["match"])

    def choose(self, slot: str, ref: str) -> None:
        """Hear slot A, B, W (the working mix) or C (reference `ref`), at the matched level."""
        d = self.desk
        st = d.snapshot()
        was_c = st["monitor"]["slot"] == "C"
        if slot == "C":
            # The reference loops on its own timing (Anthony, 26 November 2026: it went silent where its file ended,
            # before the song's loop did): Live loops over the reference's own clip, from the drop for as long as the
            # file lasts. The loop that was on comes back when the reference is left.
            a, n = d.settings.align_beat, self.reference_beats(ref, st)
            if not was_c:
                with self._lock:
                    self._loop_before = st["loop"]
            if n > 0:
                d.call(
                    f"[setattr(m.DESK.song, 'loop', True), setattr(m.DESK.song, 'loop_start', {a!r}), "
                    f"setattr(m.DESK.song, 'loop_length', {n!r})]"
                )
            elif st["loop"] == "build":
                d.call("m.DESK.transport('loop', None, 'drop')")
            if st["pos"] < a or (n > 0 and st["pos"] >= a + n):  # the reference only exists inside its clip
                d.call(f"m.DESK.transport('seek', {a})")
        elif was_c:
            with self._lock:
                before, self._loop_before = self._loop_before, None
            if before in D.LOOPS:
                d.call(f"m.DESK.transport('loop', None, {before!r})")
        with self._lock:
            saved = self.main_saved
        out = monitor_tracks.switch(d.conn, slot, ref, self.gain_db(slot, ref), saved)
        with self._lock:
            self.main_saved = out["main_saved"]
        if "error" in out:  # said as the pager says it: the choice stays as it was
            d.ingest({"t": "mon", "slot": st["monitor"]["slot"], "ref": st["monitor"]["ref"], "err": out["error"]})
            return
        d.ingest({"t": "mon", "slot": slot, "ref": ref})

    def select(self, slot: str, ref: str) -> None:
        """The old desk's A / B / W / C switch (a pinned checkpoint stops being heard first)."""
        self._leave_pin()
        self.choose(slot, ref)
        self.desk.push_app(self.message())

    # ---- the transport ---------------------------------------------------------------------------------------------
    def transport(self, action: str, beat: float | None = None, loop: str | None = None) -> None:
        """Play, pause, seek (the reference only from the drop) or set the loop, through the pager."""
        d = self.desk
        if action == "seek":
            where = D.seek_beat(float(beat or 0.0), d.monitor_choice()["slot"], d.settings.align_beat)
            d.call(f"m.DESK.transport('seek', {where!r})")
        elif action == "loop":
            d.call(f"m.DESK.transport('loop', None, {loop!r})")
        else:
            d.call(f"m.DESK.transport({action!r})")

    # ---- Now, Pin ----------------------------------------------------------------------------------------------------
    def pin_values(self) -> dict[str, list[Any]]:
        with self._lock:
            pin = self._pin
        return dict(pin) if pin is not None else {k: list(v) for k, v in self.desk.history.first.items()}

    def now_values(self) -> dict[str, list[Any]]:
        """The mix as Now has it: the desk's values, or the saved ones while the Pin is heard."""
        with self._lock:
            now = self._now
        return dict(now) if now is not None else {k: list(v) for k, v in self.desk.history.cur.items()}

    def changed(self) -> list[str]:
        """The keys whose Now differs from the Pin."""
        pin, now = self.pin_values(), self.now_values()
        return sorted(k for k, v in now.items() if k in pin and not history.same(v[1], pin[k][1]))

    def make_pin(self, who: P.Who | str = "you") -> None:
        """Set the mix as it is now aside as the Pin, saved as the checkpoint "pin". Heard from Now only."""
        self._leave_pin()
        with self._lock:
            self._pin = {k: list(v) for k, v in self.desk.history.cur.items()}
            self._pin_name = None
        self.desk.make_checkpoint(PIN_NAME, who)
        self.desk.push_app(self.message())

    def pin_checkpoint(self, name: str) -> None:
        """Choose the checkpoint `name` as the Pin (B): its values for the desk's controls. Nothing is written to Live
        until the Pin is heard. Raises ValueError when there is no such checkpoint."""
        if not self.desk.history.has_checkpoint(name):
            raise ValueError(f"no checkpoint {name!r}")
        saved = self.desk.history.load(name)
        self._leave_pin()
        with self._lock:
            self._pin = {k: list(saved[k]) for k in self.desk.history.cur if k in saved}
            self._pin_name = name
        self.desk.push_app(self.message())

    def hear(self, what: str) -> None:
        """Hear Now, the Pin or the Reference (the last one is the monitor's slot C)."""
        if what not in HEARINGS:
            raise ValueError(f"hear one of {', '.join(HEARINGS)}, not {what!r}")
        if what == "pin":
            self._hear_pin()
        elif what == "ref":
            self._leave_pin()
            self.choose("C", self.desk.monitor_choice()["ref"])
        else:
            self._leave_pin()
            if self.desk.monitor_choice()["slot"] != "W":
                self.choose("W", self.desk.monitor_choice()["ref"])
        self.desk.push_app(self.message())

    def leave_pin(self) -> None:
        """Hear Now again if the Pin was heard (a control is about to move); the monitor's slot is left as it is."""
        self._leave_pin()
        self.desk.push_app(self.message())

    def _write(self, values: dict[str, list[Any]], keys: list[str]) -> None:
        """Put `keys` of `values` into Live; the echo is not a new move."""
        pairs = [[k, values[k][1]] for k in keys if k in values]
        self.desk.history.expect_writes(pairs)
        for k in keys:
            if k in values:
                self.desk.history.rebase(k, values[k])  # what Live will report back; counts are right at once
        self.desk.write(pairs)

    def _hear_pin(self) -> None:
        with self._lock:
            if self._now is not None:
                return
        if self.desk.monitor_choice()["slot"] != "W":
            self.choose("W", self.desk.monitor_choice()["ref"])
        now, pin = self.now_values(), self.pin_values()
        with self._lock:
            self._now = now
        self._write(pin, self.changed())

    def _leave_pin(self, keep: str | None = None) -> None:
        """Put Now back (all of it but `keep`, which the user is moving) when the Pin was heard."""
        with self._lock:
            if self._now is None:
                return
            now, self._now = self._now, None
        pin = self.pin_values()
        self._write(now, [k for k, v in now.items() if k != keep and k in pin and not history.same(v[1], pin[k][1])])

    def before_move(self, msg: Any) -> None:
        """A control moved while the Pin is heard, by someone's hand: Now comes back first, and the move counts
        from where Now was. The desk's own writes (the echo of hearing the Pin) are not touches."""
        key = msg.get("key")
        with self._lock:
            pinned = self._now is not None
        if not pinned or not key or P.who_moved(msg) == "sys" or self.desk.history.awaiting(key):
            return
        known = self.desk.history.value(key)
        if known is not None and history.same(known[1], msg.get("r")):
            return  # the value the desk already has: a report, not a touch
        with self._lock:
            before = (self._now or {}).get(key)
        if before is not None:
            self.desk.history.rebase(key, before)
        self._leave_pin(keep=key)
        self.desk.push_app({**self.message(), "why": "touched"})

    # ---- the meter, and what the clients get -----------------------------------------------------------------------
    def heard(self, meter_message: dict[str, Any]) -> None:
        """The latest band levels in dB (the page draws them)."""
        self.last_meter = meter_message

    def message(self) -> dict[str, Any]:
        """The monitor's state as the shell is sent it."""
        with self._lock:
            pin_heard = self._now is not None
            pinned = self._pin is not None
            pin_name = self._pin_name
        choice = self.desk.monitor_choice()
        return {
            "t": "hear",
            "hearing": hearing_of(choice["slot"], pin_heard),
            "monitor": choice,
            "match": self.desk.snapshot()["match"],
            # counted from the last checkpoint saved or gone back to (history.base), never from the Pin
            "changed": len(changed := self.desk.history.changed(self.now_values())),
            "keys": changed,
            "base": self.desk.history.base_name,
            "pin": pin_name or (PIN_NAME if pinned else "start"),
        }
