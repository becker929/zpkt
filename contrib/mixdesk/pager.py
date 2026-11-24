"""The mix desk's pager, running inside Live (loaded by server.py through hands' Remote Script, never imported here).

It rides on Live's factory MiniLab_3 control surface the way hands/remote_scripts/ZpktMiniLabTempo does: every
MiniLab control is a StackingResource, and grabbing it above the factory script's own layers makes the script let
go of it while we hold it. Bank-A pads (and the big encoder) arm one of desk.json's pages; the 4 faders, 8 knobs and
8 bank-B pads then drive what that page lists. Knobs are realigned to the parameter when a page is armed; faders
pick up (they act once they pass the value Live has), so arming a page never makes a value jump.

A page may name its pad ("pad": 2); pages that share a pad are layers: pressing the pad of the page that is armed
arms the next page on that pad. The big encoder steps through every page in order.

Every change (a value moved in Live by anything, a control touched, a page armed) goes out as one small JSON UDP
datagram to the server, which shows it on the surface. Live's Python is 3.11; keep this file free of newer syntax.
"""
import json
import re
import socket
import time

import Live

PRIORITY = 20          # above ZpktMiniLabTempo (10): while the desk holds fader 4, the tempo script does not
FADERS = ["volume_fader", "send_a_fader", "send_b_fader", "pan_fader"]   # CC 14, 15, 30, 31: left to right
PICKUP = 0.03

MAIN_DEVICES = ("desk headroom", "desk Glue", "desk Utility")   # bypassed while an audio-clip monitor track plays
END_BEAT = 160.0
SLOTS_V = 2          # slots A, B, W, C (v1 had B = the live mix); a reload maps a v1 "B" to "W"                                                 # the arrangement is 40 bars at 160 BPM
DESK = None


def _db_to_volume(param, db):
    """The mixer volume value whose label reads db (bisection on Live's own fader law)."""
    lo, hi = 0.0, 1.0
    for _ in range(24):
        mid = (lo + hi) / 2
        txt = param.str_for_value(mid).split()[0]
        val = float("-inf") if "inf" in txt else float(txt)
        if val < db:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _minilab():
    for cs in Live.Application.get_application().control_surfaces:
        if cs is not None and cs.__class__.__name__ == "MiniLab_3":
            return cs
    return None


class _Grab(object):
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
        try:
            self.control.resource.release(self)
        except Exception:
            pass


class _Target(object):
    """A control's target in the set: a parameter, or a track's mute or solo."""

    def __init__(self, song, spec):
        self.spec, self.param, self.track, self.flag, self.error = spec, None, None, None, None
        self.key = None
        try:
            self.track = _track(song, spec["track"])
            tn = "Main" if self.track == song.master_track else _short(self.track, song)
            p = spec["param"]
            if "device" in spec:
                dev = next(d for d in self.track.devices if d.name == spec["device"])
                self.param = next(x for x in dev.parameters if x.name == p)
                self.key = "%s/%s/%s" % (tn, spec["device"], p)
            elif p == "volume":
                self.param = self.track.mixer_device.volume
                self.key = tn + "/volume"
            elif p == "pan":
                self.param = self.track.mixer_device.panning
                self.key = tn + "/pan"
            elif p.startswith("send:"):
                rets = list(song.return_tracks)
                i = next(k for k, r in enumerate(rets) if _named(r, p[5:]))
                self.param = self.track.mixer_device.sends[i]
                self.key = "%s/send %s" % (tn, _short(rets[i], song))
            elif p in ("mute", "solo"):
                self.flag = p
                self.key = "%s/%s" % (tn, p)
            else:
                raise ValueError("unknown param %r" % p)
        except StopIteration:
            self.error = "not in the set"
        except Exception as exc:
            self.error = str(exc)

    def norm(self):
        if self.flag:
            return 1.0 if getattr(self.track, self.flag) else 0.0
        p = self.param
        if p is None or p.max == p.min:
            return 0.0
        return (p.value - p.min) / (p.max - p.min)

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
        n = max(0.0, min(1.0, n))
        if self.flag:
            setattr(self.track, self.flag, n >= 0.5)
            return
        p = self.param
        v = p.min + (p.max - p.min) * n
        if p.is_quantized:
            v = round(v)
        if p.is_enabled:
            p.value = v

    def toggle(self):
        if self.flag:
            setattr(self.track, self.flag, not getattr(self.track, self.flag))
        elif self.param is not None and self.param.is_enabled:
            p = self.param
            if p.is_quantized and p.max - p.min > 1:   # a list of more than two: step through it
                p.value = p.min if p.value >= p.max else p.value + 1
            else:
                p.value = p.min if p.value > p.min else p.max

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


_NUM = re.compile(r"\s*([+-]?(?:\d+\.?\d*|\.\d+|inf))\s*([a-zA-Z%]*)")
_SCALE = {"khz": 1e3, "ms": 1e-3}


def _num(text):
    """A shown value as a number in its base unit ("1.73 kHz" -> 1730, "2.5 ms" -> 0.0025, "-inf dB" -> very low)."""
    m = _NUM.match(str(text))
    if not m:
        return None
    if "inf" in m.group(1):
        return -1e9 if m.group(1).startswith("-") else 1e9
    return float(m.group(1)) * _SCALE.get(m.group(2).lower(), 1.0)


def _raw_for(p, want):
    """The parameter value that shows as `want` ("200 Hz", "-6 dB", "35 %", a list item's name, or "min", "max",
    "current"), found by bisecting what Live shows. None if it cannot be read."""
    w = str(want).strip()
    if w.lower() == "min":
        return p.min
    if w.lower() == "max":
        return p.max
    if w.lower() == "current":
        return p.value
    if p.is_quantized:
        for v in range(int(p.min), int(p.max) + 1):
            if p.str_for_value(v).strip().lower() == w.lower():
                return float(v)
    target = _num(w)
    a, b = _num(p.str_for_value(p.min)), _num(p.str_for_value(p.max))
    if target is None or a is None or b is None:
        return None
    lo, hi, rising = p.min, p.max, b >= a
    for _ in range(40):
        mid = (lo + hi) / 2.0
        v = _num(p.str_for_value(mid))
        if v is None:
            return None
        if (v < target) == rising:
            lo = mid
        else:
            hi = mid
    v = (lo + hi) / 2.0
    return float(round(v)) if p.is_quantized else v


class _Macro(object):
    """One control that moves several parameters together: each from its "from" to its "to" as the control goes
    from 0 to 1 ({"label": ..., "macro": [{"track", "device", "param", "from": "200 Hz", "to": "2 kHz"}, ...]}).
    Its value is its position; the first parameter is the one it is read from and listened to."""

    def __init__(self, song, spec, desk):
        self.spec, self.desk, self.error, self.flag, self.param = spec, desk, None, None, None
        self.key = None        # not a value of the mix: the history keeps the parameters it moves
        self.subs, self.skipped, self.own_until, self._wrapped = [], [], 0.0, {}
        for m in spec.get("macro", []):
            t = _Target(song, m)
            a = b = None
            if not t.error and t.param is not None:
                a, b = _raw_for(t.param, m.get("from", "min")), _raw_for(t.param, m.get("to", "max"))
            if a is None or b is None:
                self.skipped.append("%s/%s/%s" % (m.get("track"), m.get("device", ""), m.get("param")))
            else:
                self.subs.append((t, a, b))
        if not self.subs:
            self.error = "not in the set"
        self.pos = self._derive()

    def _derive(self):
        if not self.subs:
            return 0.0
        t, a, b = self.subs[0]
        return max(0.0, min(1.0, (t.param.value - a) / (b - a))) if b != a else 0.0

    def norm(self):
        return self.pos

    def raw(self):
        return self.pos

    def text(self):
        return "%d %%" % round(100 * self.pos)        # its own position; its parameters show on their own controls

    def quantized(self):
        return False

    def set_norm(self, n):
        n = max(0.0, min(1.0, float(n)))
        self.pos = n
        self.own_until = time.time() + 0.4
        for t, a, b in self.subs:
            p = t.param
            if p.is_enabled:
                v = a + (b - a) * n
                v = max(p.min, min(p.max, round(v) if p.is_quantized else v))
                if p.value != v:
                    p.value = v

    set_raw = set_norm

    def toggle(self):
        self.set_norm(0.0 if self.pos >= 0.5 else 1.0)

    def listen(self, fn):
        if not self.subs:
            return
        def changed():
            if time.time() > self.own_until:      # the parameter was moved from elsewhere: follow it
                self.pos = self._derive()
            fn()
        self._wrapped[fn] = changed
        self.subs[0][0].param.add_value_listener(changed)

    def unlisten(self, fn):
        try:
            self.subs[0][0].param.remove_value_listener(self._wrapped.pop(fn))
        except Exception:
            pass


def pad_of(cfg, i):
    """The bank-A pad (1-8) that arms page i: its "pad", or its place among the first eight pages."""
    page = cfg["pages"][i]
    if "pad" in page:
        return int(page["pad"])
    return i + 1 if i < 8 else None


def _named(track, name):
    # a return shows as "A-Space": the letter is part of its name
    return track.name == name or track.name[1:] == "-" + name


def _short(track, song):
    """A return's name without Live's letter ("A-Space" -> "Space"), as hands.live.state keys it."""
    n = track.name
    return n[2:] if track in list(song.return_tracks) and n[1:2] == "-" else n


def _track(song, name):
    if name.lower() in ("main", "master"):
        return song.master_track
    return next(t for t in list(song.tracks) + list(song.return_tracks) if _named(t, name))


class Desk(object):
    def __init__(self, song, cfg, port):
        self.song, self.cfg, self.port = song, cfg, port
        self.page = 0
        self.cs = None
        self.grabs = []
        self.hw = {}          # fader slot -> last physical position (0..1)
        self.picked = {}      # fader slot -> True once the fader has passed the value
        self.targets = {}     # (page, slot) -> _Target
        self.listeners = []
        self.main_saved = None      # Main's desk devices' On values while a monitor track plays (None = not bypassed)
        self.monitor_slot, self.monitor_ref = "W", "C1"
        self.sys_until, self.by_key = 0.0, {}
        self._last_pos = 0.0
        self._song_listeners = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        self.resolve()
        self._listen_song()

    # ---- transport and monitor (the page is a control surface only: all audio is Live's) ---------------------------
    def _listen_song(self):
        for add, fn in ((self.song.add_current_song_time_listener, self._on_pos),
                        (self.song.add_is_playing_listener, self._on_pos_force)):
            add(fn)
            self._song_listeners.append(fn)

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
        self.emit({"t": "pos", "b": b, "p": bool(playing)})
        if playing and not s.loop and b >= END_BEAT:
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
            pos = 0.0 if s.current_song_time >= END_BEAT else s.current_song_time
            s.start_time = pos
            s.start_playing()
        elif action == "pause":
            s.stop_playing()
        elif action == "seek":
            pos = max(0.0, min(END_BEAT - 0.01, float(beat)))
            s.current_song_time = pos
            if not s.is_playing:
                s.start_time = pos
        elif action == "loop":
            if loop == "off":
                s.loop = False
            else:
                a, n = (0.0, 64.0) if loop == "build" else (64.0, END_BEAT - 64.0)
                s.loop_start = a
                s.loop_length = n
                s.loop = True
        self.emit({"t": "loop", "loop": loop} if action == "loop" else {"t": "pos", "b": s.current_song_time, "p": bool(s.is_playing)})

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
        if slot != "W":      # exclusive: nothing else soloed
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
            target.mixer_device.volume.value = _db_to_volume(target.mixer_device.volume, gain_db)
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
                t = _Macro(self.song, spec, self) if "macro" in spec else _Target(self.song, spec)
                self.targets[(i, slot)] = t
                if t.key and not t.error:
                    self.by_key.setdefault(t.key, t)
                if isinstance(t, _Macro):      # the parameters a macro moves report (and can be set) like any control
                    for j, (sub, _a, _b) in enumerate(t.subs):
                        sslot = "%s/%d" % (slot, j)
                        self.targets[(i, sslot)] = sub
                        self.by_key.setdefault(sub.key, sub)
                        fn = self._watcher(i, sslot)
                        sub.listen(fn)
                        self.listeners.append((sub, fn))
                if not t.error:
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
        return changed

    # ---- the controller -----------------------------------------------------------------------------------------
    def attach(self):
        self.release()
        cs = _minilab()
        if cs is None:
            return False
        e = cs.elements
        g = []
        for k, enc in enumerate(list(e.encoders_raw)[:8]):
            g.append(_Grab(enc, self._knob("k%d" % (k + 1))))
        for k, name in enumerate(FADERS):
            g.append(_Grab(getattr(e, name), self._fader("f%d" % (k + 1))))
        for k, pad in enumerate(list(e.pad_bank_a_raw)[:8]):
            g.append(_Grab(pad, self._page_pad(k)))
        for k, pad in enumerate(list(e.pad_bank_b_raw)[:8]):
            g.append(_Grab(pad, self._toggle_pad("b%d" % (k + 1))))
        g.append(_Grab(e.display_encoder, self._page_encoder))
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
            try:
                self.cs.request_rebuild_midi_map()
            except Exception:
                pass
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
            if not self.picked.get(slot):
                v = t.norm()
                if abs(n - v) <= PICKUP or (last is not None and (last - v) * (n - v) <= 0):
                    self.picked[slot] = True
            if self.picked.get(slot):
                self._apply(t, n)
                if isinstance(t, _Macro):
                    self.send_value(self.page, slot)
            self.emit({"t": "hw", "page": self.page, "slot": slot, "hw": n, "picked": bool(self.picked.get(slot))})
        return on

    def _page_pad(self, k):
        """Pad A(k+1) arms the first page on that pad; pressed again, the next page on the same pad (a layer)."""
        def on(value):
            if not value:
                return
            on_pad = [i for i, _ in enumerate(self.cfg["pages"]) if pad_of(self.cfg, i) == k + 1]
            if not on_pad:
                return
            if self.page in on_pad:
                self.arm(on_pad[(on_pad.index(self.page) + 1) % len(on_pad)])
            else:
                self.arm(on_pad[0])
        return on

    def _toggle_pad(self, slot):
        def on(value):
            if value:
                self.toggle(slot)
        return on

    def _page_encoder(self, value):
        step = 1 if value > 64 else -1 if value < 64 else 0
        if step:
            self.arm((self.page + step) % len(self.cfg["pages"]))

    def _apply(self, t, n):
        try:
            t.set_norm(n)
        except RuntimeError:   # a change asked for while Live notifies: try again on the next tick
            try:
                self.cs.schedule_message(1, lambda: t.set_norm(n))
            except Exception:
                pass

    # ---- what the server asks ------------------------------------------------------------------------------------
    def arm(self, page):
        if not 0 <= page < len(self.cfg["pages"]):
            return
        self.page = page
        self.picked = {}
        if self.cs is not None:
            encs = list(self.cs.elements.encoders_raw)[:8]
            for k, enc in enumerate(encs):
                t = self.targets.get((page, "k%d" % (k + 1)))
                v = int(round(127 * t.norm())) if t is not None and not t.error else 0
                try:
                    enc.realign_value(v)
                except Exception:
                    try:
                        enc.send_value(v, force=True)
                    except Exception:
                        pass
        self.emit({"t": "page", "page": page, "picked": {}})

    def toggle(self, slot, page=None):
        page = self.page if page is None else page
        t = self.targets.get((page, slot))
        if t is not None and not t.error:
            try:
                t.toggle()
            except RuntimeError:
                pass
            if isinstance(t, _Macro):
                self.send_value(page, slot)
        self.emit({"t": "hw", "page": page, "slot": slot, "hw": None, "picked": True})

    def send_value(self, page, slot):
        t = self.targets[(page, slot)]
        # "sys": the desk itself moved it (a monitor switch bypassing Main's devices), so it is not a mix change
        self.emit({"t": "v", "page": page, "slot": slot, "n": t.norm(), "s": t.text(), "r": t.raw(), "key": t.key,
                   "sys": time.time() < self.sys_until})

    def inventory(self):
        """Everything a surface can hold, one line each: track, device ("" for the mixer), parameter, what it shows
        now, at its lowest and at its highest, and Q for a switch or list. Tab-separated (one flat string: the
        bridge garbles deep lists)."""
        s, out = self.song, []
        rets = list(s.return_tracks)
        for t in list(s.tracks) + rets + [s.master_track]:
            name = "Main" if t == s.master_track else _short(t, s)
            if name.startswith("mon "):
                continue
            m = t.mixer_device
            mixer = [("volume", m.volume), ("pan", m.panning)] + [("send:" + _short(r, s), m.sends[k]) for k, r in enumerate(rets) if k < len(m.sends)]
            for pn, p in mixer:
                out.append("\t".join([name, "", pn, str(p), p.str_for_value(p.min), p.str_for_value(p.max), ""]))
            if t != s.master_track:
                out.append("\t".join([name, "", "mute", "on" if t.mute else "off", "off", "on", "Q"]))
                out.append("\t".join([name, "", "solo", "on" if t.solo else "off", "off", "on", "Q"]))
            for d in t.devices:
                bypassed = t == s.master_track and self.main_saved is not None and d.name in self.main_saved
                for k, p in enumerate(d.parameters):
                    try:
                        now = p.str_for_value(self.main_saved[d.name]) if bypassed and k == 0 else str(p)
                        out.append("\t".join([name, d.name, p.name, now, p.str_for_value(p.min), p.str_for_value(p.max), "Q" if p.is_quantized else ""]))
                    except Exception:
                        pass
        return "\n".join(out)

    def macro_skipped(self, page):
        """The macro parts of a page that could not be used (not in the set, or a "from"/"to" Live cannot show)."""
        out = []
        for (pg, slot), t in self.targets.items():
            if pg == page and isinstance(t, _Macro):
                out += ["%s: %s" % (slot, x) for x in t.skipped]
        return out

    def set_raw(self, pairs):
        """[[key, raw], ...] -> the controls with those keys (undo, redo, revert). Returns the keys not found."""
        missing = []
        for key, v in pairs:
            t = self.by_key.get(key)
            if t is None:
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
        try:
            self.sock.sendto(json.dumps(msg).encode("utf-8"), ("127.0.0.1", self.port))
        except Exception:
            pass

    def _loop_mode(self):
        s = self.song
        if not s.loop:
            return "off"
        if abs(s.loop_start) < 0.5 and abs(s.loop_length - 64.0) < 0.5:
            return "build"
        if abs(s.loop_start - 64.0) < 0.5 and abs(s.loop_length - (END_BEAT - 64.0)) < 0.5:
            return "drop"
        return "on"

    def snapshot(self):
        vals = {}
        for (page, slot), t in self.targets.items():
            vals["%d:%s" % (page, slot)] = {"n": t.norm() if not t.error else None, "s": t.text() if not t.error else "",
                                            "q": t.quantized() if not t.error else False, "err": t.error,
                                            "r": t.raw() if not t.error else None, "key": t.key}
        return {"page": self.page, "attached": self.attached(), "values": vals, "hw": self.hw,
                "picked": self.picked, "monitor": {"slot": self.monitor_slot, "ref": self.monitor_ref},
                "pos": self.song.current_song_time, "playing": bool(self.song.is_playing), "loop": self._loop_mode(),
                "set": self.song.name if hasattr(self.song, "name") else "", "main_saved": self.main_saved}

    def stop(self):
        for fn in self._song_listeners:
            for rm in (self.song.remove_current_song_time_listener, self.song.remove_is_playing_listener):
                try:
                    rm(fn)
                except Exception:
                    pass
        self._song_listeners = []
        self.unlisten()
        self.release()
        try:
            self.sock.close()
        except Exception:
            pass


def start(song, cfg, port):
    """(Re)start the desk: drop the old one's grabs and listeners, resolve the pages, grab the MiniLab."""
    global DESK
    if DESK is not None:
        page = DESK.page
        carry = {"main_saved": DESK.main_saved, "slot": DESK.monitor_slot, "ref": DESK.monitor_ref}
        DESK.stop()
    else:
        carry = globals().get("CARRY") or {}      # server.py hands over the old module's state when it reloads this file
        page = carry.get("page", 0)
    DESK = Desk(song, cfg, port)
    DESK.page = page if 0 <= page < len(cfg["pages"]) else 0     # the page it was on may be gone (a surface removed)
    DESK.main_saved = carry.get("main_saved")
    DESK.monitor_slot, DESK.monitor_ref = (lambda s: "W" if s == "B" and carry.get("v") != 2 else s)(carry.get("slot", "W")), carry.get("ref", "C1")
    DESK.attach()
    return DESK.snapshot()
