# ZpktMiniLabTempo: tempo on an Arturia MiniLab 3, on top of Live's factory MiniLab_3 script.
#
#   fader 4 (CC 30, ch 1, normally send B)  -> tempo, TEMPO_MIN..TEMPO_MAX, whole BPM
#   pad 7 of bank A (note 42, ch 10)        -> tempo x 0.5
#   pad 8 of bank A (note 43, ch 10)        -> tempo x 2
#
# How: every factory MiniLab_3 control is a StackingResource. A client grabbing it above the
# script's own layers (priority 0) makes the script let go, and a value listener does the work.
# This surface has no MIDI ports of its own; it finds the MiniLab_3 instance and re-grabs whenever
# that instance is rebuilt (set load, re-selection). Select it in a free Control Surface row,
# Input/Output None. Install: hands/remote_scripts/install.sh, then restart Live once.
from __future__ import annotations

import Live
from _Framework.ControlSurface import ControlSurface

FADER = "send_b_fader"
PAD_BANK = "pad_bank_a_raw"
HALF_PAD, DOUBLE_PAD = 6, 7
TEMPO_MIN, TEMPO_MAX = 60.0, 200.0
PRIORITY = 10
POLL_TICKS = 10  # ~1 s between checks that our grabs are still in place


def create_instance(c_instance):
    return ZpktMiniLabTempo(c_instance)


class _Grabber(object):
    def __init__(self, control, on_value):
        self.control = control
        self.on_value = on_value
        self.grabbed = False

    def set_control_element(self, control, grabbed):
        if grabbed and not self.grabbed:
            control.add_value_listener(self.on_value)
        elif not grabbed and self.grabbed and control.value_has_listener(self.on_value):
            control.remove_value_listener(self.on_value)
        self.grabbed = grabbed

    def grab(self):
        self.control.resource.grab(self, PRIORITY)

    def release(self):
        try:
            self.control.resource.release(self)
        except Exception:
            pass


class ZpktMiniLabTempo(ControlSurface):
    def __init__(self, c_instance):
        ControlSurface.__init__(self, c_instance)
        self._target = None
        self._grabbers = []
        self.log_message("ZpktMiniLabTempo: loaded")
        self.schedule_message(POLL_TICKS, self._tick)

    def disconnect(self):
        self._release()
        ControlSurface.disconnect(self)

    def _release(self):
        for g in self._grabbers:
            g.release()
        self._grabbers = []
        self._target = None

    def _minilab(self):
        for cs in Live.Application.get_application().control_surfaces:
            if cs is not None and cs.__class__.__name__ == "MiniLab_3":
                return cs
        return None

    def _tick(self):
        try:
            cs = self._minilab()
            if cs is not self._target or not all(g.grabbed for g in self._grabbers):
                self._release()
                if cs is not None:
                    self._attach(cs)
        except Exception as exc:  # never let a tick kill the poll loop
            self.log_message("ZpktMiniLabTempo: %s" % exc)
        self.schedule_message(POLL_TICKS, self._tick)

    def _attach(self, cs):
        e = cs.elements
        pads = getattr(e, PAD_BANK)
        self._grabbers = [_Grabber(getattr(e, FADER), self._on_fader),
                          _Grabber(pads[HALF_PAD], self._on_half),
                          _Grabber(pads[DOUBLE_PAD], self._on_double)]
        for g in self._grabbers:
            g.grab()
        self._target = cs
        cs.request_rebuild_midi_map()
        self.log_message("ZpktMiniLabTempo: attached to MiniLab_3")

    def _set_tempo(self, bpm):
        bpm = max(20.0, min(999.0, bpm))

        def apply():
            self.song().tempo = bpm
        try:
            apply()
        except RuntimeError:  # changes can't be triggered by notifications: defer a tick
            self.schedule_message(1, apply)

    def _on_fader(self, value):
        self._set_tempo(round(TEMPO_MIN + (TEMPO_MAX - TEMPO_MIN) * value / 127.0))

    def _on_half(self, value):
        if value:
            self._set_tempo(self.song().tempo / 2.0)

    def _on_double(self, value):
        if value:
            self._set_tempo(self.song().tempo * 2.0)
