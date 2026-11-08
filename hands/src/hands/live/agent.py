"""Agent conveniences on top of LiveClient, learned the hard way driving Live headless (Nov 2026).

- PRELUDE: helpers prepended to `hands live exec` code (opt out with --raw):
    param(dev, name)       the DeviceParameter called name (KeyError lists the names)
    set_norm(p, frac)      p.value at frac of its range (native params are often 0..1, not dB)
    set_clamped(p, value)  p.value clamped to [p.min, p.max] (avoids "Invalid value")
    select_track(t)        select t and put the arm states back (selecting auto-arms)
- audition(): arrangement-only listen test. A call that sleeps blocks Live's main thread, so a
  clip fired inside it never starts: set up in one call, read meters in later calls, clean up.
"""

from __future__ import annotations

import ast
import time

from hands.live.transport import LiveClient

PRELUDE = '''
def param(dev, name):
    for _p in dev.parameters:
        if _p.name == name:
            return _p
    raise KeyError("%s has no %r; it has %s" % (dev.name, name, [p.name for p in dev.parameters]))

def set_norm(p, frac):
    p.value = p.min + max(0.0, min(1.0, float(frac))) * (p.max - p.min)

def set_clamped(p, value):
    p.value = max(p.min, min(p.max, float(value)))

def select_track(t):
    _armed = [x for x in song.tracks if x.can_be_armed and x.arm]
    song.view.selected_track = t
    for x in song.tracks:
        if x.can_be_armed and x.arm != (x in _armed):
            x.arm = x in _armed
'''


def with_prelude(code: str) -> str:
    """Prepend PRELUDE; an expression becomes `result = (...)` so its value still comes back."""
    try:
        ast.parse(code.strip(), mode="eval")
        code = f"result = ({code.strip()})"
    except SyntaxError:
        pass
    return PRELUDE + "\n" + code


def audition(live: LiveClient, track: str, notes: list[int], beats: float = 2.0,
             listen_s: float = 2.0, force: bool = False) -> dict:
    """Play a chord on TRACK from a temporary arrangement clip past the end; return meter peaks."""
    setup = f'''
_t = next(x for x in song.tracks if x.name == {track!r})
if song.is_playing and not {force!r}:
    raise RuntimeError("Live is playing (maybe the user): not auditioning; pass --force")
_end = max([c.end_time for x in song.tracks for c in x.arrangement_clips] + [0.0])
_start = (int(_end / 4) + 4) * 4.0
_c = _t.create_midi_clip(_start, {beats!r})
_c.name = "agent audition"
_c.add_new_notes(tuple(Live.Clip.MidiNoteSpecification(pitch=n, start_time=0.0, duration={beats!r} * 0.75, velocity=110) for n in {notes!r}))
result = {{"pos": song.current_song_time, "mute": _t.mute, "start": _start, "loop": song.loop,
          "start_time": song.start_time}}
_t.mute = False
song.loop = False
# start_playing() plays from song.start_time (the start marker), not current_song_time
song.start_time = _start
song.current_song_time = _start
song.start_playing()
'''
    before = live.run(setup)
    peaks: list[float] = []
    t0 = time.time()
    while time.time() - t0 < listen_s:
        time.sleep(0.25)
        peaks.append(live.run(f"_t = next(x for x in song.tracks if x.name == {track!r}); "
                              "result = max(_t.output_meter_left, _t.output_meter_right)"))
    live.run(f'''
song.stop_playing()
_t = next(x for x in song.tracks if x.name == {track!r})
for _c in list(_t.arrangement_clips):
    if _c.name == "agent audition" and abs(_c.start_time - {before["start"]!r}) < 1e-6:
        _t.delete_clip(_c)
_t.mute = {before["mute"]!r}
song.loop = {before["loop"]!r}
song.start_time = {before["start_time"]!r}
song.current_song_time = {before["pos"]!r}
result = "ok"
''')
    return {"peak": round(max(peaks, default=0.0), 3), "series": [round(p, 2) for p in peaks],
            "sound": max(peaks, default=0.0) > 0.05}
