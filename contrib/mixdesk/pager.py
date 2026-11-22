"""The mix desk's pager, running inside Live (loaded by server.py through hands' Remote Script, never imported here).

It rides on Live's factory MiniLab_3 control surface the way hands/remote_scripts/ZpktMiniLabTempo does: every
MiniLab control is a StackingResource, and grabbing it above the factory script's own layers makes the script let
go of it while we hold it. Bank-A pads (and the big encoder) arm one of desk.json's pages; the 4 faders, 8 knobs and
8 bank-B pads then drive what that page lists. Knobs are realigned to the parameter when a page is armed; faders
pick up (they act once they pass the value Live has), so arming a page never makes a value jump.

Every change (a value moved in Live by anything, a control touched, a page armed) goes out as one small JSON UDP
datagram to the server, which shows it on the surface. Live's Python is 3.11; keep this file free of newer syntax.
"""
import json
import socket

import Live

PRIORITY = 20          # above ZpktMiniLabTempo (10): while the desk holds fader 4, the tempo script does not
FADERS = ["volume_fader", "send_a_fader", "send_b_fader", "pan_fader"]   # CC 14, 15, 30, 31: left to right
PICKUP = 0.03

DESK = None


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
        try:
            self.track = _track(song, spec["track"])
            p = spec["param"]
            if "device" in spec:
                dev = next(d for d in self.track.devices if d.name == spec["device"])
                self.param = next(x for x in dev.parameters if x.name == p)
            elif p == "volume":
                self.param = self.track.mixer_device.volume
            elif p == "pan":
                self.param = self.track.mixer_device.panning
            elif p.startswith("send:"):
                rets = list(song.return_tracks)
                i = next(k for k, r in enumerate(rets) if _named(r, p[5:]))
                self.param = self.track.mixer_device.sends[i]
            elif p in ("mute", "solo"):
                self.flag = p
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


def _named(track, name):
    # a return shows as "A-Space": the letter is part of its name
    return track.name == name or track.name[1:] == "-" + name


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
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        self.resolve()

    # ---- the set ------------------------------------------------------------------------------------------------
    def resolve(self):
        self.unlisten()
        self.targets = {}
        for i, page in enumerate(self.cfg["pages"]):
            for slot, spec in page["controls"].items():
                t = _Target(self.song, spec)
                self.targets[(i, slot)] = t
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
            self.emit({"t": "hw", "page": self.page, "slot": slot, "hw": n, "picked": bool(self.picked.get(slot))})
        return on

    def _page_pad(self, k):
        def on(value):
            if value:
                self.arm(k)
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
        self.emit({"t": "hw", "page": page, "slot": slot, "hw": None, "picked": True})

    def send_value(self, page, slot):
        t = self.targets[(page, slot)]
        self.emit({"t": "v", "page": page, "slot": slot, "n": t.norm(), "s": t.text()})

    def emit(self, msg):
        try:
            self.sock.sendto(json.dumps(msg).encode("utf-8"), ("127.0.0.1", self.port))
        except Exception:
            pass

    def snapshot(self):
        vals = {}
        for (page, slot), t in self.targets.items():
            vals["%d:%s" % (page, slot)] = {"n": t.norm() if not t.error else None, "s": t.text() if not t.error else "",
                                            "q": t.quantized() if not t.error else False, "err": t.error}
        return {"page": self.page, "attached": self.attached(), "values": vals, "hw": self.hw,
                "picked": self.picked, "set": self.song.name if hasattr(self.song, "name") else ""}

    def stop(self):
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
        DESK.stop()
    else:
        page = 0
    DESK = Desk(song, cfg, port)
    DESK.page = page
    DESK.attach()
    return DESK.snapshot()
