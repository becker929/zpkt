"""Agent conveniences on top of LiveClient, learned the hard way driving Live headless (Nov 2026).

- PRELUDE: helpers prepended to `hands live exec` code (opt out with --raw):
    param(dev, name)       the DeviceParameter called name (KeyError lists the names)
    set_norm(p, frac)      p.value at frac of its range (native params are often 0..1, not dB)
    set_clamped(p, value)  p.value clamped to [p.min, p.max] (avoids "Invalid value")
    select_track(t)        select t and put the arm states back (selecting auto-arms)
- friendly() and writes(): what `hands live exec` forgives in an agent's code, and whether code changes Live (the
  Zpkt agent may only read Live through exec).
- audition(): arrangement-only listen test. A call that sleeps blocks Live's main thread, so a
  clip fired inside it never starts: set up in one call, read meters in later calls, clean up.
"""

from __future__ import annotations

import ast
import re
import time

from hands.live.transport import LiveClient

PRELUDE = """
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
"""


_IMPORT_SONG = re.compile(r"^\s*(import\s+song\b.*|from\s+song\s+import\b.*)$")
_PRINT_SHIM = """_printed = []
def print(*_a, sep=" ", end="\\n", **_k):
    _printed.append(sep.join(str(_x) for _x in _a))
"""
_PRINT_TAIL = """

if _printed and globals().get("result") is None:
    result = "\\n".join(_printed)
"""


_WRITES = re.compile(
    r"^(insert_|delete_|create_|duplicate_|set_|start_|stop_|continue_|fire|jump|tap_|undo|redo|"
    r"load|move|add_|remove_|record|capture|quantize|clear|store|crop|paste|duplicate|append|"
    r"re_enable|trigger|scrub|play|select)"
)
AGENT_READ_ONLY = (
    "`hands live exec` only reads Live when the Zpkt agent runs it, so this changed nothing. To change "
    'levels, pans or devices, make a mix panel: hands panel make --spec \'{"name": "mix", '
    '"bars": [17, 8], "faders": ["Kick bus"], "devices": [{"track": "Kick bus", '
    '"device": "EQ Eight", "params": {...}}]}\'. It renders what it changed and `hands panel drop` '
    "takes it out. For Live itself (a dialog, no sound): hands rig reset."
)


def writes(source: str) -> bool:
    """Does this Live code change anything? An assignment to an attribute or item, a `del`, or a call of a method
    whose name changes Live (insert_device, delete_track, start_playing, ...). Code that does not parse is let
    through: Live reports the syntax error."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                for sub in ast.walk(t):
                    if isinstance(sub, (ast.Attribute, ast.Subscript)) and isinstance(sub.ctx, ast.Store):
                        return True
        if isinstance(node, ast.Delete):
            return True
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
            if _WRITES.match(name) and name not in ("select_track",):
                return True
    return False


def friendly(source: str) -> tuple[str, list[str]]:
    """Forgive the two mistakes agents make most in Live code (2026-11-20, a 32-call loop): `import song`
    (song is already defined) and `print` (it shows nothing in Live; here it becomes the result)."""
    notes: list[str] = []
    lines = source.splitlines()
    kept = [line for line in lines if not _IMPORT_SONG.match(line)]
    if len(kept) != len(lines):
        notes.append("`song` is already defined in Live; `import song` was removed (never import it)")
    source = "\n".join(kept)
    if re.search(r"\bprint\s*\(", source):
        source = _PRINT_SHIM + source + _PRINT_TAIL
    return source, notes


def with_prelude(code: str) -> str:
    """Prepend PRELUDE; an expression becomes `result = (...)` so its value still comes back."""
    try:
        ast.parse(code.strip(), mode="eval")
        code = f"result = ({code.strip()})"
    except SyntaxError:
        pass
    return PRELUDE + "\n" + code


def audition(
    live: LiveClient, track: str, notes: list[int], beats: float = 2.0, listen_s: float = 2.0, force: bool = False
) -> dict:
    """Play a chord on TRACK from a temporary arrangement clip past the end; return meter peaks."""
    setup = f"""
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
"""
    before = live.run(setup)
    peaks: list[float] = []
    t0 = time.time()
    while time.time() - t0 < listen_s:
        time.sleep(0.25)
        peaks.append(
            live.run(
                f"_t = next(x for x in song.tracks if x.name == {track!r}); "
                "result = max(_t.output_meter_left, _t.output_meter_right)"
            )
        )
    live.run(f"""
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
""")
    return {
        "peak": round(max(peaks, default=0.0), 3),
        "series": [round(p, 2) for p in peaks],
        "sound": max(peaks, default=0.0) > 0.05,
    }
