"""The mix desk's pager, running inside Live (loaded by server.py through hands' Remote Script, never imported here).

It rides on Live's factory MiniLab_3 control surface the way zpkt.live's remote_scripts/ZpktMiniLabTempo does: every
MiniLab control is a StackingResource, and grabbing it above the factory script's own layers makes the script let
go of it while we hold it. Bank-A pads (and the big encoder) arm one of desk.json's pages; the 4 faders, 8 knobs and
8 bank-B pads then drive what that page lists (pagercore.HARDWARE is that map, as a table). Knobs are realigned to
the parameter when a page is armed; faders pick up (they act once they pass the value Live has), so arming a page
never makes a value jump.

A page may carry compare states ("compare": named settings of the same controls, one pad each). While it is armed,
those pads do not arm pages: a press is reported to the app ({"t": "pad"}), which writes the state as one move, and
the pad of the state that is on is lit. Which one is on is read from the values, never kept.

A page may name its pad ("pad": 2); pages that share a pad are layers: pressing the pad of the page that is armed
arms the next page on that pad. The big encoder steps through every page in order.

Every change (a value moved in Live by anything, a control touched, a page armed) goes out as one small JSON UDP
datagram to the server (protocol.py has their shapes), which shows it on the surface.

This file is the Live shell: listeners, grabs and LOM writes. Its decisions are in pagercore.py, and tracks, keys and
shown values are hands' inlive helpers; all three are loaded by path, since Live's Python cannot import hands.
Live's Python is 3.11; keep this file free of newer syntax.
"""

import contextlib
import importlib.util
import json
import os
import socket
import time

import Live

_HERE = os.path.dirname(os.path.abspath(__file__))
_INLIVE = os.path.join(_HERE, os.pardir, os.pardir, "src", "zpkt", "live", "inlive")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core = _load("zpkt_mixdesk_pagercore", os.path.join(_HERE, "pagercore.py"))
tracks = _load("zpkt_inlive_tracks", os.path.join(_INLIVE, "tracks.py"))
shown = _load("zpkt_inlive_shown", os.path.join(_INLIVE, "shown.py"))
keys = _load("zpkt_inlive_keys", os.path.join(_INLIVE, "keys.py"))

PRIORITY = 20  # above ZpktMiniLabTempo (10): while the desk holds fader 4, the tempo script does not
MAIN_DEVICES = ("desk headroom", "desk Glue", "desk Utility")  # bypassed while an audio-clip monitor track plays
METER_DEVICE = "zpkt desk meter"  # the spectrum's device on Main (meter.py): the snapshot says whether it is there
END_BEAT = core.END_BEAT
SLOTS_V = core.SLOTS_V  # the server hands this over on a reload (server.pager_start_code)
DESK = None


def _minilab():
    for cs in Live.Application.get_application().control_surfaces:
        if cs is not None and cs.__class__.__name__ == "MiniLab_3":
            return cs
    return None


class _Grab:
    """One MiniLab control held by the desk; on_value(value) gets its MIDI values while held."""

    def __init__(self, control, on_value):
        self.control, self.on_value, self.grabbed = control, on_value, False

    def set_control_element(self, control, grabbed):
        if grabbed and not self.grabbed:
            control.add_value_listener(self.on_value)
        elif not grabbed and self.grabbed and control.value_has_listener(self.on_value):
            control.remove_value_listener(self.on_value)
        self.grabbed = grabbed

    def grab(self):
        self.control.resource.grab(self, PRIORITY)

    def release(self):
        with contextlib.suppress(Exception):
            self.control.resource.release(self)


class _Target:
    """A control's target in the set: a parameter, or a track's mute or solo."""

    def __init__(self, song, spec):
        self.spec, self.param, self.track, self.flag, self.error = spec, None, None, None, None
        self.key = None
        try:
            self.track = tracks.find_track(song, spec["track"])
            tn = _key_name(self.track, song)
            p = spec["param"]
            ret = keys.send_return(p) if p.startswith(keys.SEND_IN_PARAM) else None
            if "device" in spec:
                dev = next(d for d in self.track.devices if d.name == spec["device"])
                self.param = next(x for x in dev.parameters if x.name == p)
                self.key = keys.device_key(tn, spec["device"], p)
            elif p == "volume":
                self.param = self.track.mixer_device.volume
                self.key = keys.mixer_key(tn, p)
            elif p == "pan":
                self.param = self.track.mixer_device.panning
                self.key = keys.mixer_key(tn, p)
            elif ret is not None:
                rets = list(song.return_tracks)
                i = next(k for k, r in enumerate(rets) if r.name == ret or tracks.short_name(r.name, True) == ret)
                self.param = self.track.mixer_device.sends[i]
                self.key = keys.send_key(tn, tracks.short_name(rets[i].name, True))
            elif p in ("mute", "solo"):
                self.flag = p
                self.key = keys.mixer_key(tn, p)
            else:
                raise ValueError(f"unknown param {p!r}")
        except (StopIteration, LookupError):
            self.error = "not in the set"
        except Exception as exc:
            self.error = str(exc)

    def norm(self):
        if self.flag:
            return 1.0 if getattr(self.track, self.flag) else 0.0
        p = self.param
        return 0.0 if p is None else core.norm(p.value, p.min, p.max)

    def text(self):
        if self.flag:
            return "on" if getattr(self.track, self.flag) else "off"
        return str(self.param) if self.param is not None else ""

    def raw(self):
        """The exact value (what undo and checkpoints keep): the parameter's value, or the flag as a bool."""
        if self.flag:
            return bool(getattr(self.track, self.flag))
        return self.param.value if self.param is not None else None

    def set_raw(self, v):
        if self.flag:
            if bool(getattr(self.track, self.flag)) != bool(v):
                setattr(self.track, self.flag, bool(v))
            return
        p = self.param
        if p is not None and p.is_enabled:
            v = max(p.min, min(p.max, float(v)))
            if p.value != v:
                p.value = v

    def quantized(self):
        return bool(self.flag) or bool(self.param is not None and self.param.is_quantized)

    def set_norm(self, n):
        if self.flag:
            setattr(self.track, self.flag, max(0.0, min(1.0, n)) >= 0.5)
            return
        p = self.param
        if p.is_enabled:
            p.value = core.value_at(n, p.min, p.max, p.is_quantized)

    def toggle(self):
        if self.flag:
            setattr(self.track, self.flag, not getattr(self.track, self.flag))
        elif self.param is not None and self.param.is_enabled:
            p = self.param
            p.value = core.toggled(p.value, p.min, p.max, p.is_quantized)

    def listen(self, fn):
        if self.flag == "mute":
            self.track.add_mute_listener(fn)
        elif self.flag == "solo":
            self.track.add_solo_listener(fn)
        elif self.param is not None:
            self.param.add_value_listener(fn)

    def unlisten(self, fn):
        try:
            if self.flag == "mute":
                self.track.remove_mute_listener(fn)
            elif self.flag == "solo":
                self.track.remove_solo_listener(fn)
            elif self.param is not None:
                self.param.remove_value_listener(fn)
        except Exception:
            pass


class _Macro:
    """One control that moves several parameters together: each from its "from" to its "to" as the control goes
    from 0 to 1 ({"label": ..., "macro": [{"track", "device", "param", "from": "200 Hz", "to": "2 kHz"}, ...]}).
    Its value is its position; the first parameter is the one it is read from and listened to."""

    def __init__(self, song, spec):
        self.spec, self.error, self.flag, self.param = spec, None, None, None
        self.key = None  # not a value of the mix: the history keeps the parameters it moves
        self.subs, self.skipped, self.own_until, self._wrapped = [], [], 0.0, {}
        for m in spec.get("macro", []):
            t = _Target(song, m)
            a = b = None
            if not t.error and t.param is not None:
                a, b = shown.raw_for(t.param, m.get("from", "min")), shown.raw_for(t.param, m.get("to", "max"))
            if a is None or b is None:
                self.skipped.append(f"{m.get('track')}/{m.get('device', '')}/{m.get('param')}")
            else:
                self.subs.append((t, a, b))
        if not self.subs:
            self.error = "not in the set"
        self.pos = self._derive()

    def _derive(self):
        if not self.subs:
            return 0.0
        t, a, b = self.subs[0]
        return core.macro_position(t.param.value, a, b)

    def norm(self):
        return self.pos

    def raw(self):
        return self.pos

    def text(self):
        return f"{round(100 * self.pos)} %"  # its own position; its parameters show on their own controls

    def quantized(self):
        return False

    def set_norm(self, n):
        n = max(0.0, min(1.0, float(n)))
        self.pos = n
        self.own_until = time.time() + 0.4
        for t, a, b in self.subs:
            p = t.param
            if p.is_enabled:
                v = core.macro_value(n, a, b, p.min, p.max, p.is_quantized)
                if p.value != v:
                    p.value = v

    set_raw = set_norm

    def toggle(self):
        self.set_norm(0.0 if self.pos >= 0.5 else 1.0)

    def listen(self, fn):
        if not self.subs:
            return

        def changed():
            if time.time() > self.own_until:  # the parameter was moved from elsewhere: follow it
                self.pos = self._derive()
            fn()

        self._wrapped[fn] = changed
        self.subs[0][0].param.add_value_listener(changed)

    def unlisten(self, fn):
        with contextlib.suppress(Exception):
            self.subs[0][0].param.remove_value_listener(self._wrapped.pop(fn))


def _hardware(cs, rows):
    """(control, role, target) for each row of a hardware table (pagercore.HARDWARE) the controller has."""
    out = []
    for element, index, role, target in rows:
        control = getattr(cs.elements, element)
        if index is not None:
            controls = list(control)
            if index >= len(controls):
                continue
            control = controls[index]
        out.append((control, role, target))
    return out


def _key_name(track, song):
    """A track's name in a state key: "Main", a return without Live's letter, any other track as it is."""
    if track == song.master_track:
        return "Main"
    return tracks.short_name(track.name, track in list(song.return_tracks))


class Desk:
    def __init__(self, song, cfg, port):
        self.song, self.cfg, self.port = song, cfg, port
        self.page = 0
        self.cs = None
        self.grabs = []
        self.hw = {}  # fader slot -> last physical position (0..1)
        self.picked = {}  # fader slot -> True once the fader has passed the value
        self.targets = {}  # (page, slot) -> _Target
        self.listeners = []
        self.main_saved = None  # Main's desk devices' On values while a monitor track plays (None = not bypassed)
        self.monitor_slot, self.monitor_ref = "W", "C1"
        self.sys_until, self.by_key = 0.0, {}
        self.lit = {}  # pad slot -> lit, as last sent to the controller
        self._last_pos = 0.0
        self._song_listeners = []
        self._flag_listeners = []  # (remove function, callback) for every track's solo and mute
        self._extra_song_listeners = []  # (remove function, callback): the loop brace, the list of tracks
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        self.resolve()
        self._listen_song()
        self._listen_flags()

    # ---- transport and monitor (the page is a control surface only: all audio is Live's) ---------------------------
    def _listen_song(self):
        for add, fn in (
            (self.song.add_current_song_time_listener, self._on_pos),
            (self.song.add_is_playing_listener, self._on_pos_force),
        ):
            add(fn)
            self._song_listeners.append(fn)
        s = self.song
        for name, fn in (
            ("tracks", self._on_tracks),
            ("return_tracks", self._on_tracks),
            ("loop", self._on_loop),
            ("loop_start", self._on_loop),
            ("loop_length", self._on_loop),
        ):
            with contextlib.suppress(Exception):  # a Live (or a fake) without that listener: the snapshot still says
                getattr(s, f"add_{name}_listener")(fn)
                self._extra_song_listeners.append((getattr(s, f"remove_{name}_listener"), fn))

    # ---- solo and mute of every track, and the loop brace: reported from in here, so the app never asks -----------
    def _flag_tracks(self):
        s = self.song
        return [t for t in list(s.tracks) + list(s.return_tracks) if not t.name.startswith("mon ")]

    def flags(self, names=False):
        """Which tracks are soloed and which are muted, by their names in state keys (the monitor's own tracks are
        left out: the desk mutes and solos those itself). With `names`, every track's name too."""
        out = {"solo": [], "mute": []}
        every = []
        for t in self._flag_tracks():
            name = _key_name(t, self.song)
            every.append(name)
            for flag in ("solo", "mute"):
                with contextlib.suppress(Exception):
                    if getattr(t, flag):
                        out[flag].append(name)
        if names:
            out["tracks"] = every
        return out

    def _on_flags(self):
        msg = {"t": "flags", "sys": time.time() < self.sys_until}
        msg.update(self.flags())
        self.emit(msg)

    def _unlisten_flags(self):
        for rm, fn in self._flag_listeners:
            with contextlib.suppress(Exception):
                rm(fn)
        self._flag_listeners = []

    def _listen_flags(self):
        self._unlisten_flags()
        for t in self._flag_tracks():
            for flag in ("solo", "mute"):
                with contextlib.suppress(Exception):
                    getattr(t, f"add_{flag}_listener")(self._on_flags)
                    self._flag_listeners.append((getattr(t, f"remove_{flag}_listener"), self._on_flags))

    def _on_tracks(self):
        self._listen_flags()
        self._on_flags()

    def _on_loop(self):
        self.emit(self._loop_message(self._loop_mode()))

    def _loop_message(self, mode):
        msg = {"t": "loop", "loop": mode}
        with contextlib.suppress(Exception):
            msg["start"], msg["length"] = float(self.song.loop_start), float(self.song.loop_length)
        return msg

    def set_flag(self, key, value):
        """A track's solo or mute by its state key ("Kick bus/solo"), for a track no page holds. True if found."""
        name, _sep, flag = key.rpartition("/")
        if flag not in ("solo", "mute"):
            return False
        for t in self._flag_tracks():
            if _key_name(t, self.song) == name:
                if bool(getattr(t, flag)) != bool(value):
                    setattr(t, flag, bool(value))
                return True
        return False

    def _on_pos(self):
        now = time.time()
        if now - self._last_pos < 0.07:
            return
        self._last_pos = now
        self._emit_pos()

    def _on_pos_force(self):
        self._emit_pos()

    def _emit_pos(self):
        s = self.song
        b, playing = s.current_song_time, s.is_playing
        self.emit({"t": "pos", "b": b, "p": bool(playing), "bpm": float(s.tempo)})
        if core.ran_past_end(playing, s.loop, b):
            try:
                s.stop_playing()
            except Exception:
                if self.cs is not None:
                    self.cs.schedule_message(1, lambda: s.stop_playing())

    def transport(self, action, beat=None, loop=None):
        s = self.song
        if action == "play":
            if s.back_to_arranger:
                s.back_to_arranger = False
            # start_playing begins at the start marker; continue_playing from a position set through the LOM jumped
            # to a stale spot in testing, so play from where the playhead is by moving the marker there first
            pos = core.play_from(s.current_song_time)
            s.start_time = pos
            s.start_playing()
        elif action == "pause":
            s.stop_playing()
        elif action == "seek":
            pos = core.seek_position(beat)
            s.current_song_time = pos
            if not s.is_playing:
                s.start_time = pos
        elif action == "loop":
            if loop == "off":
                s.loop = False
            else:
                a, n = core.LOOPS["build" if loop == "build" else "drop"]
                s.loop_start = a
                s.loop_length = n
                s.loop = True
        self.emit(
            self._loop_message(loop)
            if action == "loop"
            else {"t": "pos", "b": s.current_song_time, "p": bool(s.is_playing)}
        )

    def monitor(self, slot, ref, gain_db):
        """Choose what is heard. W = the working mix itself (all monitor tracks muted, Main's desk devices as they
        were). A / B / C = the audio clip on 'mon A' (original render) / 'mon B' (the recipe's render) / 'mon <ref>',
        soloed, at gain_db, with Main's desk devices bypassed so the clip (rendered after them) is heard exactly as
        rendered."""
        s = self.song
        self.sys_until = time.time() + 0.8
        mons = dict((t.name, t) for t in s.tracks if t.name.startswith("mon "))
        target = mons.get("mon " + (ref if slot == "C" else slot)) if slot != "W" else None
        if slot != "W" and target is None:
            self.emit({"t": "mon", "slot": self.monitor_slot, "ref": self.monitor_ref, "err": "monitor tracks missing"})
            return
        if slot != "W":  # exclusive: nothing else soloed
            for t in list(s.tracks) + list(s.return_tracks):
                if t.solo and t is not target:
                    t.solo = False
        for t in mons.values():
            if t is not target:
                if t.solo:
                    t.solo = False
                if not t.mute:
                    t.mute = True
        if target is not None:
            if target.mute:
                target.mute = False
            volume = target.mixer_device.volume
            value = shown.raw_for(volume, f"{gain_db:.2f} dB")
            if value is not None:
                volume.value = value
            if not target.solo:
                target.solo = True
        devs = [d for d in s.master_track.devices if d.name in MAIN_DEVICES]
        if slot != "W":
            if self.main_saved is None:
                self.main_saved = dict((d.name, d.parameters[0].value) for d in devs)
            for d in devs:
                if d.parameters[0].value != 0.0:
                    d.parameters[0].value = 0.0
        else:
            saved = self.main_saved or {}
            for d in devs:
                d.parameters[0].value = saved.get(d.name, 1.0)
            self.main_saved = None
        self.monitor_slot, self.monitor_ref = slot, ref
        self.emit({"t": "mon", "slot": slot, "ref": ref})

    # ---- the set ------------------------------------------------------------------------------------------------
    def resolve(self):
        self.unlisten()
        self.targets, self.by_key = {}, {}
        for i, page in enumerate(self.cfg["pages"]):
            for slot, spec in page["controls"].items():
                t = _Macro(self.song, spec) if "macro" in spec else _Target(self.song, spec)
                self.targets[(i, slot)] = t
                if t.key and not t.error:
                    self.by_key.setdefault(t.key, t)
                if isinstance(t, _Macro):  # the parameters a macro moves report (and can be set) like any control
                    for j, (sub, _a, _b) in enumerate(t.subs):
                        sslot = f"{slot}/{j}"
                        self.targets[(i, sslot)] = sub
                        self.by_key.setdefault(sub.key, sub)
                        fn = self._watcher(i, sslot)
                        sub.listen(fn)
                        self.listeners.append((sub, fn))
                if not t.error:
                    fn = self._watcher(i, slot)
                    t.listen(fn)
                    self.listeners.append((t, fn))
            # what the page's compare states write and no control of the page shows: watched and settable all the same
            shown_here = set(t.key for (pg, _s), t in self.targets.items() if pg == i and t.key)
            for j, (key, spec) in enumerate(sorted(((page.get("compare") or {}).get("targets") or {}).items())):
                if key in shown_here:
                    continue
                t = _Target(self.song, spec)
                slot = f"cmp/{j}"
                self.targets[(i, slot)] = t
                if t.key and not t.error:
                    self.by_key.setdefault(t.key, t)
                    fn = self._watcher(i, slot)
                    t.listen(fn)
                    self.listeners.append((t, fn))

    def unlisten(self):
        for t, fn in self.listeners:
            t.unlisten(fn)
        self.listeners = []

    def _watcher(self, page, slot):
        def changed():
            self.send_value(page, slot)
            if page == self.page:
                self.light_pads()

        return changed

    # ---- compare states --------------------------------------------------------------------------------------------
    def compare_lit(self, page=None):
        """The place of the compare state that is on, on `page` (the armed one): every one of its values holds."""
        page = self.page if page is None else page
        cmp = self.cfg["pages"][page].get("compare") if 0 <= page < len(self.cfg["pages"]) else None
        if not cmp:
            return None

        def read(key):
            t = self.by_key.get(key)
            if t is None or t.error:
                return None
            if t.flag:
                return (t.raw(), 0.0, 1.0, True)
            return (t.param.value, t.param.min, t.param.max, t.param.is_quantized)

        return core.lit_state(cmp.get("states") or [], read)

    def light_pads(self, force=False):
        """Light the pad of the state that is on, on both banks; the other state pads go dark. Sent only on a
        change. Unverified on the hardware: the pad's own send_value is used, nothing else is known to work here."""
        if self.cs is None:
            return
        pads = ((self.cfg["pages"][self.page].get("compare") or {}).get("pads") or {}) if self.cfg["pages"] else {}
        if not pads and not self.lit:
            return  # no state pads here and none lit before: nothing to say (this runs on every value change)
        on = self.compare_lit() if pads else None
        want = dict((slot, state == on) for slot, state in pads.items())
        for slot in list(self.lit):
            want.setdefault(slot, False)  # a pad lit on the page before: dark again
        for control, _role, pad in _hardware(self.cs, core.hardware_rows("page_pad")):
            slot = f"b{pad}"
            if slot in want and (force or self.lit.get(slot) != want[slot]):
                with contextlib.suppress(Exception):
                    control.send_value(127 if want[slot] else 0, force=True)
        self.lit = dict((slot, lit) for slot, lit in want.items() if slot in pads)

    # ---- the controller -----------------------------------------------------------------------------------------
    def attach(self):
        self.release()
        cs = _minilab()
        if cs is None:
            return False
        handlers = {
            "knob": self._knob,
            "fader": self._fader,
            "page_pad": self._page_pad,
            "toggle_pad": self._toggle_pad,
            "page_encoder": lambda _target: self._page_encoder,
        }
        g = [_Grab(control, handlers[role](target)) for control, role, target in _hardware(cs, core.HARDWARE)]
        for x in g:
            x.grab()
        self.grabs, self.cs = g, cs
        cs.request_rebuild_midi_map()
        self.arm(self.page)
        return True

    def release(self):
        for x in self.grabs:
            x.release()
        self.grabs = []
        if self.cs is not None:
            with contextlib.suppress(Exception):
                self.cs.request_rebuild_midi_map()
        self.cs = None

    def attached(self):
        return self.cs is not None and self.cs is _minilab() and bool(self.grabs) and all(x.grabbed for x in self.grabs)

    def _knob(self, slot):
        def on(value):
            t = self.targets.get((self.page, slot))
            if t is not None and not t.error:
                self._apply(t, value / 127.0)
                if isinstance(t, _Macro):
                    self.send_value(self.page, slot)
            self.emit({"t": "hw", "page": self.page, "slot": slot, "hw": value / 127.0, "picked": True})

        return on

    def _fader(self, slot):
        def on(value):
            n = value / 127.0
            last = self.hw.get(slot)
            self.hw[slot] = n
            t = self.targets.get((self.page, slot))
            if t is None or t.error:
                self.emit({"t": "hw", "page": self.page, "slot": slot, "hw": n, "picked": False})
                return
            if not self.picked.get(slot) and core.picks_up(n, last, t.norm()):
                self.picked[slot] = True
            if self.picked.get(slot):
                self._apply(t, n)
                if isinstance(t, _Macro):
                    self.send_value(self.page, slot)
            self.emit({"t": "hw", "page": self.page, "slot": slot, "hw": n, "picked": bool(self.picked.get(slot))})

        return on

    def _page_pad(self, pad):
        """Pad A`pad` arms the first page on that pad; pressed again, the next page on the same pad (a layer). On a
        page with compare states, a pad that holds one tells the app instead: the app writes the state."""

        def on(value):
            if value and core.compare_state(self.cfg, self.page, pad) is not None:
                self.emit({"t": "pad", "page": self.page, "slot": f"b{pad}"})
                return
            page = core.page_for_pad(self.cfg, pad, self.page) if value else None
            if page is not None:
                self.arm(page)

        return on

    def _toggle_pad(self, slot):
        def on(value):
            if value:
                self.toggle(slot)

        return on

    def _page_encoder(self, value):
        page = core.page_for_encoder(value, self.page, len(self.cfg["pages"]))
        if page is not None:
            self.arm(page)

    def _apply(self, t, n):
        try:
            t.set_norm(n)
        except RuntimeError:  # a change asked for while Live notifies: try again on the next tick
            with contextlib.suppress(Exception):
                self.cs.schedule_message(1, lambda: t.set_norm(n))

    # ---- what the server asks ------------------------------------------------------------------------------------
    def arm(self, page):
        if not 0 <= page < len(self.cfg["pages"]):
            return
        self.page = page
        self.picked = {}
        if self.cs is not None:
            for enc, _role, slot in _hardware(self.cs, core.hardware_rows("knob")):
                t = self.targets.get((page, slot))
                v = round(127 * t.norm()) if t is not None and not t.error else 0
                try:
                    enc.realign_value(v)
                except Exception:
                    with contextlib.suppress(Exception):
                        enc.send_value(v, force=True)
        self.emit({"t": "page", "page": page, "picked": {}})
        self.light_pads(force=True)

    def toggle(self, slot, page=None):
        page = self.page if page is None else page
        t = self.targets.get((page, slot))
        if t is not None and not t.error:
            with contextlib.suppress(RuntimeError):
                t.toggle()
            if isinstance(t, _Macro):
                self.send_value(page, slot)
        self.emit({"t": "hw", "page": page, "slot": slot, "hw": None, "picked": True})

    def send_value(self, page, slot):
        # "sys": the desk itself moved it (a monitor switch bypassing Main's devices), so it is not a mix change
        self.emit(core.value_message(page, slot, self.targets[(page, slot)], time.time() < self.sys_until))

    def inventory(self):
        """Everything a surface can hold, one line each: track, device ("" for the mixer), parameter, what it shows
        now, at its lowest and at its highest, and Q for a switch or list. Tab-separated (one flat string: the
        bridge garbles deep lists)."""
        s, out = self.song, []
        rets = list(s.return_tracks)
        for t in list(s.tracks) + rets + [s.master_track]:
            name = _key_name(t, s)
            if name.startswith("mon "):
                continue
            m = t.mixer_device
            mixer = [("volume", m.volume), ("pan", m.panning)] + [
                (keys.send_param(_key_name(r, s)), m.sends[k]) for k, r in enumerate(rets) if k < len(m.sends)
            ]
            for pn, p in mixer:
                out.append(
                    core.inventory_line(name, "", pn, str(p), p.str_for_value(p.min), p.str_for_value(p.max), False)
                )
            if t != s.master_track:
                for flag in ("mute", "solo"):
                    now = "on" if getattr(t, flag) else "off"
                    out.append(core.inventory_line(name, "", flag, now, "off", "on", True))
            for d in t.devices:
                bypassed = t == s.master_track and self.main_saved is not None and d.name in self.main_saved
                for k, p in enumerate(d.parameters):
                    try:
                        now = p.str_for_value(self.main_saved[d.name]) if bypassed and k == 0 else str(p)
                        out.append(
                            core.inventory_line(
                                name,
                                d.name,
                                p.name,
                                now,
                                p.str_for_value(p.min),
                                p.str_for_value(p.max),
                                p.is_quantized,
                            )
                        )
                    except Exception:
                        pass
        return "\n".join(out)

    def macro_skipped(self, page):
        """The macro parts of a page that could not be used (not in the set, or a "from"/"to" Live cannot show)."""
        out = []
        for (pg, slot), t in self.targets.items():
            if pg == page and isinstance(t, _Macro):
                out += [f"{slot}: {x}" for x in t.skipped]
        return out

    def set_raw(self, pairs):
        """[[key, raw], ...] -> the controls with those keys (undo, redo, revert). Returns the keys not found."""
        missing = []
        for key, v in pairs:
            t = self.by_key.get(key)
            if t is None:
                try:
                    found = self.set_flag(key, v)  # a track's solo or mute that no page holds
                except RuntimeError:
                    found = False
                if not found:
                    missing.append(key)
                continue
            try:
                t.set_raw(v)
            except RuntimeError:
                try:
                    self.cs.schedule_message(1, lambda t=t, v=v: t.set_raw(v))
                except Exception:
                    missing.append(key)
        return missing

    def emit(self, msg):
        with contextlib.suppress(Exception):
            self.sock.sendto(json.dumps(msg).encode("utf-8"), ("127.0.0.1", self.port))

    def _loop_mode(self):
        s = self.song
        return core.loop_mode(s.loop, s.loop_start, s.loop_length)

    def _set_name(self):
        """The open set's name: its file's name without the extension (what the app's wrong-set guard compares),
        else the name Live gives the set; "" for a set with neither."""
        with contextlib.suppress(Exception):
            path = str(getattr(self.song, "file_path", "") or "")
            if path:
                return os.path.splitext(os.path.basename(path))[0]
        with contextlib.suppress(Exception):
            return str(self.song.name or "")
        return ""

    def _loop_span(self):
        """The loop brace as [start, length] in beats; None when Live will not say."""
        with contextlib.suppress(Exception):
            return [float(self.song.loop_start), float(self.song.loop_length)]
        return None

    def _song_facts(self):
        """The song's tempo, time signature and length in beats, for the page's identity line. A fact Live will not
        give is left out."""
        out = {}
        for name, read in (
            ("tempo", lambda s: float(s.tempo)),
            ("sig", lambda s: [int(s.signature_numerator), int(s.signature_denominator)]),
            ("length", lambda s: float(s.last_event_time)),
        ):
            with contextlib.suppress(Exception):
                out[name] = read(self.song)
        return out

    def snapshot(self):
        vals = {f"{page}:{slot}": core.value_report(t) for (page, slot), t in self.targets.items()}
        return {
            "page": self.page,
            "attached": self.attached(),
            "values": vals,
            "hw": self.hw,
            "picked": self.picked,
            "monitor": {"slot": self.monitor_slot, "ref": self.monitor_ref},
            "pos": self.song.current_song_time,
            "playing": bool(self.song.is_playing),
            "loop": self._loop_mode(),
            "loop_span": self._loop_span(),
            "flags": self.flags(names=True),
            "meter": any(d.name == METER_DEVICE for d in self.song.master_track.devices),
            "set": self._set_name(),
            **self._song_facts(),
            "main_saved": self.main_saved,
        }

    def stop(self):
        for fn in self._song_listeners:
            for rm in (self.song.remove_current_song_time_listener, self.song.remove_is_playing_listener):
                with contextlib.suppress(Exception):
                    rm(fn)
        self._song_listeners = []
        for rm, fn in self._extra_song_listeners:
            with contextlib.suppress(Exception):
                rm(fn)
        self._extra_song_listeners = []
        self._unlisten_flags()
        self.unlisten()
        self.release()
        with contextlib.suppress(Exception):
            self.sock.close()


def start(song, cfg, port):
    """Start the desk: resolve the pages, grab the MiniLab. server.py loads this file afresh each time and hands the
    old desk's monitor and page over in CARRY (after stopping that desk)."""
    global DESK
    carry = globals().get("CARRY") or {}
    page = carry.get("page", 0)
    DESK = Desk(song, cfg, port)
    DESK.page = page if 0 <= page < len(cfg["pages"]) else 0  # the page it was on may be gone (a surface removed)
    DESK.main_saved = carry.get("main_saved")
    DESK.monitor_slot, DESK.monitor_ref = core.carried_slot(carry), carry.get("ref", "C1")
    DESK.attach()
    return DESK.snapshot()
