"""Control panels: one instrument on its own track, a riff, a render, and the knobs to play it with.

`make` does in one command what otherwise takes an agent dozens of `hands live exec` calls: add a MIDI
track at the end of the open set, load the instrument, set parameters (by raw value, by "50%", or by the
text Live shows, "800 Hz"), write the riff past the end of the arrangement, render it and print the two
blocks Zpkt web draws (the audio and the control panel). `apply` takes the panel's values as they come
back from the page, sets them and renders the next version with a before/after deck.

The open set is left as it was apart from the panel's own track: the riff's clip, the render track, the
tempo, the loop, the start marker, the position, the selection and the arm states are all put back.
Everything a later `apply` needs is in <out>/<name>.panel.json.
"""

from __future__ import annotations

import contextlib
import difflib
import io
import json
import math
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hands import config
from hands.live.agent import with_prelude
from hands.live.transport import McpTransport

TRACK_PREFIX = "panel "
LEAD_BEATS = 8.0      # rendered before the riff and cut off: the head of a resampled take is not on the timeline
SAMPLES = 33          # points per parameter when reading what Live shows across its range
ROUNDS = 3            # of narrowing in on the value that reads as asked: 1/32768 of the range
ANCHORS = 9           # of those, how many go into a control's `display`
MAX_BEATS = 128.0     # renders are real time
MAX_CONTROLS = 16
CHUNK = 40            # parameters read per call (ableton-guide rule 2)

Note = tuple[int, float, float, int]


class PanelError(RuntimeError):
    """The panel cannot be made or changed as asked; the message says what to change."""


# ---------------------------------------------------------------------------------------------
# The riff

_PITCH_CLASS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def pitch(v: Any) -> int:
    """A MIDI note number from a number or a name. C3 is 60, as Live shows it."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        n = int(v)
    else:
        m = re.fullmatch(r"([A-Ga-g])([#b]?)(-?\d)", str(v).strip())
        if not m:
            raise PanelError(f"cannot read the pitch {v!r}: use a MIDI number or a name like A1 or C#3 (C3 is 60)")
        n = _PITCH_CLASS[m[1].upper()] + {"#": 1, "b": -1, "": 0}[m[2]] + (int(m[3]) + 2) * 12
    if not 0 <= n <= 127:
        raise PanelError(f"the pitch {v!r} is outside MIDI's 0..127")
    return n


def riff(spec: dict) -> tuple[list[Note], float]:
    """A spec's notes as (pitch, start, length, velocity) in beats, and the riff's length.

    `notes` is one pattern ([[pitch, start, length, velocity], ...]), repeated to fill `beats`; the pattern
    is as long as `pattern_beats`, or runs to the end of the bar its last note starts in. `chords` with `rhythm` is the
    other way in (hands.live.midi).
    """
    if spec.get("chords"):
        from hands.live import midi
        try:
            chords = midi.parse_progression(str(spec["chords"]))
            beats = float(spec.get("beats") or 4 * len(chords))
            _check_beats(beats)
            notes = midi.generate_clip_notes(chords, beats=beats, rhythm=str(spec.get("rhythm") or "staccato-16ths"),
                                             base_velocity=int(spec.get("velocity") or 110))
        except ValueError as exc:
            raise PanelError(str(exc)) from exc
        return [(int(p), float(s), float(d), int(v)) for p, s, d, v in notes], beats
    raw = spec.get("notes")
    if not isinstance(raw, list) or not raw:
        raise PanelError('the spec needs "notes" ([[pitch, start, length, velocity], ...], in beats) or "chords"')
    pattern: list[Note] = []
    for n in raw:
        if not isinstance(n, (list, tuple)) or len(n) < 3:
            raise PanelError(f"a note is [pitch, start, length, velocity]; got {n!r}")
        start, length = float(n[1]), float(n[2])
        if start < 0 or length <= 0:
            raise PanelError(f"a note starts at 0 or later and has a length above 0; got {n!r}")
        pattern.append((pitch(n[0]), start, length, max(1, min(127, int(n[3]) if len(n) > 3 else 100))))
    last = max(s for _, s, _, _ in pattern)      # a note may ring past the bar line; its start decides the bar
    period = float(spec.get("pattern_beats") or (math.floor(last / 4 + 1e-9) + 1) * 4)
    beats = float(spec.get("beats") or period)
    _check_beats(beats)
    if period <= 0:
        raise PanelError("pattern_beats must be above 0")
    out: list[Note] = []
    k = 0
    while k * period < beats - 1e-9:
        for p, s, d, v in pattern:
            at = s + k * period
            if at < beats - 1e-9:
                out.append((p, round(at, 6), round(min(d, beats - at), 6), v))
        k += 1
    return out, beats


def _check_beats(beats: float) -> None:
    if not 1 <= beats <= MAX_BEATS:
        raise PanelError(f"a riff is 1 to {MAX_BEATS:g} beats long (it renders in real time); got {beats:g}")


# ---------------------------------------------------------------------------------------------
# What Live shows for a value, and the value for what it shows

_READING = re.compile(r"^\s*([-+]?(?:inf|\d+(?:\.\d+)?))\s*(.*?)\s*$", re.I)
_SCALE = {"khz": ("hz", 1000.0), "hz": ("hz", 1.0), "s": ("ms", 1000.0), "ms": ("ms", 1.0)}


def reading(text: Any) -> tuple[float, str] | None:
    """A displayed value as a number in its base unit: "1.2 kHz" is (1200.0, "hz"), "250 ms" (250.0, "ms")."""
    m = _READING.match(str(text))
    if not m:
        return None
    base, k = _SCALE.get(m[2].lower(), (m[2].lower(), 1.0))
    return float(m[1]) * k, base


def _between(target: float, xs: list[float], shown: list[str], unit: str) -> list[tuple[float, float, float, float]]:
    """Every pair of neighbouring samples whose readings enclose target: (x0, x1, reading0, reading1).
    Live rounds what it shows, so a reading holds over a stretch of values: the first and last pair bound it."""
    reads = [reading(s) for s in shown]
    out = []
    for (x0, r0), (x1, r1) in zip(zip(xs, reads), zip(xs[1:], reads[1:])):
        if r0 is None or r1 is None or not (math.isfinite(r0[0]) and math.isfinite(r1[0])):
            continue
        if unit and (r0[1] != unit or r1[1] != unit):
            continue
        if min(r0[0], r1[0]) <= target <= max(r0[0], r1[0]):
            out.append((x0, x1, r0[0], r1[0]))
    return out


def _grid(lo: float, hi: float, n: int = SAMPLES) -> list[float]:
    return [lo + (hi - lo) * k / (n - 1) for k in range(n)]


def _match(want: str, names: list[str]) -> str | None:
    w = want.strip().lower()
    for test in (lambda n: n.lower() == w, lambda n: n.lower().startswith(w), lambda n: w in n.lower()):
        hits = [n for n in names if test(n)]
        if hits:
            return hits[0]
    return None


def _param(catalog: list[dict], name: str) -> dict:
    by = {p["name"]: p for p in catalog}
    hit = by.get(name) or next((p for p in catalog if p["name"].lower() == str(name).strip().lower()), None)
    if hit is None:
        near = difflib.get_close_matches(str(name), list(by), n=6, cutoff=0.4) or _contains(str(name), list(by))
        raise PanelError(f"no parameter {name!r}; close names: {', '.join(near) or 'none'} "
                         "(`hands panel params NAME --grep WORD` lists them)")
    return hit


def _contains(name: str, names: list[str]) -> list[str]:
    words = [w for w in re.split(r"\W+", name.lower()) if len(w) > 2]
    return [n for n in names if any(w in n.lower() for w in words)][:6]


# ---------------------------------------------------------------------------------------------
# Talking to Live

def _track(name: str) -> str:
    return f"next(x for x in song.tracks if x.name == {name!r})"


def _device(name: str) -> str:
    return f"{_track(name)}.devices[0]"


def read_catalog(client: McpTransport, track: str) -> list[dict]:
    """Every parameter of the panel's instrument: name, range, value, what Live shows, and its choices."""
    count = client.run(f"result = len({_device(track)}.parameters)")
    out: list[dict] = []
    for a in range(0, int(count), CHUNK):
        rows = client.run(
            f"_d = {_device(track)}\n"
            "result = [[p.name, p.min, p.max, p.value, bool(p.is_quantized), p.str_for_value(p.value), "
            f"list(p.value_items) if p.is_quantized else None] for p in list(_d.parameters)[{a}:{a + CHUNK}]]")
        for name, lo, hi, value, quantized, shown, items in rows:
            out.append({"name": name, "min": lo, "max": hi, "value": value, "quantized": quantized,
                        "shown": str(shown), "items": [str(i) for i in items] if items else None})
    return out


def sample(client: McpTransport, track: str, asks: list[tuple[str, float, float]], n: int = SAMPLES) -> dict[str, list[str]]:
    """What Live shows at n even points between lo and hi, for each (parameter, lo, hi)."""
    out: dict[str, list[str]] = {}
    for a in range(0, len(asks), 8):
        part = asks[a:a + 8]
        rows = client.run(
            f"_by = {{p.name: p for p in {_device(track)}.parameters}}\n"
            f"result = [[str(_by[n].str_for_value(lo + (hi - lo) * k / {n - 1})) for k in range({n})] for n, lo, hi in {part!r}]")
        out.update({ask[0]: row for ask, row in zip(part, rows)})
    return out


def resolve(client: McpTransport, track: str, catalog: list[dict], wants: dict[str, Any]) -> tuple[dict[str, float], list[str]]:
    """Raw values for what a spec asks: a number is the raw value, "50%" a point in the range, any other
    text what Live shows ("800 Hz", "Saw D", "On")."""
    values: dict[str, float] = {}
    warnings: list[str] = []
    shown: dict[str, tuple[float, str]] = {}    # continuous parameters asked for by what Live shows
    for key, want in wants.items():
        p = _param(catalog, key)
        lo, hi = p["min"], p["max"]
        if isinstance(want, bool):
            values[p["name"]] = hi if want else lo
        elif isinstance(want, (int, float)):
            values[p["name"]] = max(lo, min(hi, float(want)))
            if not lo <= want <= hi:
                warnings.append(f"{p['name']}: {want:g} is outside {lo:g}..{hi:g}; used {values[p['name']]:g}")
        elif re.fullmatch(r"\s*-?\d+(\.\d+)?\s*%\s*", str(want)) and not (p["shown"] or "").strip().endswith("%"):
            values[p["name"]] = lo + max(0.0, min(1.0, float(str(want).strip().rstrip("% ")) / 100)) * (hi - lo)
        elif p["items"]:
            hit = _match(str(want), p["items"])
            if hit is None:
                raise PanelError(f"{p['name']} has no choice {want!r}; it has: {', '.join(p['items'])}")
            values[p["name"]] = lo + p["items"].index(hit)
        else:
            r = reading(want)
            if r is None:
                raise PanelError(f"{p['name']}: cannot read {want!r}; give a number, \"50%\", or text like {p['shown']!r}")
            shown[p["name"]] = r
    spans = {n: (_param(catalog, n)["min"], _param(catalog, n)["max"]) for n in shown}
    for depth in range(ROUNDS):
        todo = [n for n in shown if n not in values]
        if not todo:
            break
        tables = sample(client, track, [(n, *spans[n]) for n in todo])
        for n in todo:
            target, unit = shown[n]
            xs, table = _grid(*spans[n]), tables[n]
            hits = _between(target, xs, table, unit)
            if not hits:
                ends = [reading(table[0]), reading(table[-1])]
                asked = f"{target:g} {unit}".strip()
                if depth or None in ends or (unit and unit not in (ends[0][1], ends[1][1])) \
                        or min(ends[0][0], ends[1][0]) <= target <= max(ends[0][0], ends[1][0]):
                    raise PanelError(f"{n}: nothing between {table[0]!r} and {table[-1]!r} reads {asked}")
                first = (target < ends[0][0]) == (ends[0][0] <= ends[1][0])   # which end is the nearer one
                values[n] = xs[0] if first else xs[-1]
                warnings.append(f"{n}: {asked} is outside its range; used {table[0] if first else table[-1]}")
            elif depth == ROUNDS - 1:            # the middle of the stretch that reads as asked
                at = [x0 if r1 == r0 else x0 + (x1 - x0) * (target - r0) / (r1 - r0) for x0, x1, r0, r1 in (hits[0], hits[-1])]
                if hits[0][2] == hits[0][3]:
                    at[0] = hits[0][0]
                if hits[-1][2] == hits[-1][3]:
                    at[1] = hits[-1][1]
                values[n] = (at[0] + at[1]) / 2
            else:
                spans[n] = (hits[0][0], hits[-1][1])
    return values, warnings


def set_values(client: McpTransport, track: str, values: dict[str, float]) -> None:
    if values:
        client.run(f"_by = {{p.name: p for p in {_device(track)}.parameters}}\n"
                   f"for _n, _v in {sorted(values.items())!r}:\n    _by[_n].value = _v\nresult = 'ok'")


def _state(client: McpTransport) -> dict:
    return client.run(
        "_sel = song.view.selected_track\n"
        "_leaf = [t for t in song.tracks if not t.is_foldable]\n"
        "result = {'playing': bool(song.is_playing), 'names': [t.name for t in song.tracks], 'tempo': song.tempo,\n"
        "          'end': max([c.end_time for t in _leaf for c in t.arrangement_clips] + [0.0]),\n"
        "          'armed': [i for i, t in enumerate(song.tracks) if t.can_be_armed and t.arm],\n"
        "          'selected': next((i for i, t in enumerate(song.tracks) if t == _sel), None),\n"
        "          'loop': bool(song.loop), 'start_time': song.start_time, 'pos': song.current_song_time}")


_LOAD = '''
_t = song.tracks[{idx}]
_t.name = {track!r}
def _base(n):
    return n.rsplit(".", 1)[0].lower() if n.lower().endswith((".adv", ".adg", ".aupreset", ".vstpreset")) else n.lower()
def _find(root, name, budget):
    queue = [root]
    while queue:
        node = queue.pop(0)
        for c in node.children:
            budget[0] -= 1
            if budget[0] < 0:
                return None
            if _base(c.name) == name:
                return c
            if c.is_folder:
                queue.append(c)
    return None
_item = None
for _root in (browser.instruments, browser.plugins, browser.sounds, browser.drums):
    _node = _root
    for _part in {parts!r}:
        _node = _find(_node, _part, [3000])
        if _node is None:
            break
    if _node is not None and _node.is_loadable:
        _item = _node
        break
if _item is None:
    raise ValueError("no loadable %r in Live's browser (instruments, plug-ins, sounds, drums)" % {instrument!r})
select_track(_t)
browser.load_item(_item)
for _i, _x in enumerate(song.tracks):
    if _x.can_be_armed and _x.arm != (_i in {armed!r}):
        _x.arm = _i in {armed!r}
result = _item.name
'''


def _load(client: McpTransport, track: str, instrument: str, state: dict) -> str:
    """Add the panel's track at the end and load the instrument on it; return the device's name."""
    idx = len(state["names"])
    client.run("song.create_midi_track(-1)\nresult = 'ok'")
    time.sleep(0.3)
    parts = [p.strip().lower() for p in instrument.split("/") if p.strip()]
    client.run(with_prelude(_LOAD.format(idx=idx, track=track, parts=parts, instrument=instrument, armed=state["armed"])))
    for _ in range(12):                          # a plug-in can take a few seconds to appear
        time.sleep(0.5)
        devices = client.run(f"result = [d.name for d in {_track(track)}.devices]")
        if devices:
            return devices[0]
    raise PanelError(f"{instrument!r} did not load onto the track")


def _drop(client: McpTransport, track: str) -> None:
    client.run(f"_i = next((i for i, t in enumerate(song.tracks) if t.name == {track!r}), None)\n"
               "if _i is not None:\n    song.delete_track(_i)\nresult = 'ok'")


def _render(client: McpTransport, track: str, state: dict, notes: list[Note], beats: float, tail: float,
            tempo: float | None, out: Path, recorder: Callable[..., str | None]) -> dict:
    """Write the riff past the end of the arrangement, record it, cut the take to the riff, put the set back."""
    import numpy as np
    import soundfile as sf

    start = (int(state["end"] / 4) + 4) * 4.0 + LEAD_BEATS
    out.parent.mkdir(parents=True, exist_ok=True)
    take = out.with_name(f".{out.stem}.take.wav")
    try:
        if tempo and abs(tempo - state["tempo"]) > 1e-6:
            client.run(f"song.tempo = {float(tempo)!r}\nresult = 'ok'")
        client.run(
            f"_c = {_track(track)}.create_midi_clip({start!r}, {float(beats)!r})\n_c.name = 'panel riff'\n"
            "_c.add_new_notes(tuple(Live.Clip.MidiNoteSpecification(pitch=p, start_time=s, duration=d, velocity=v)"
            f" for p, s, d, v in {notes!r}))\nresult = 'ok'")
        with contextlib.redirect_stdout(io.StringIO()):      # the recorder's progress lines are not part of the answer
            path = recorder(transport=client, filename=take.name, duration_beats=LEAD_BEATS + beats, output_dir=str(out.parent),
                            tail_beats=tail, start_beat=start - LEAD_BEATS, keep_take=False)
        if not path:
            raise PanelError("Live recorded nothing; check its audio output (`hands live check`)")
        timing = json.loads(Path(f"{path}.timing.json").read_text())
        x, sr = sf.read(path, always_2d=True, dtype="float64")
        spb = 60.0 / timing["tempo"]
        a = int(round((timing["song_zero_seconds"] + (start - timing.get("clip_start", start - LEAD_BEATS)) * spb) * sr))
        y = x[max(0, a):max(0, a) + int(round((beats + tail) * spb * sr))].copy()
        if not len(y):
            raise PanelError("the take ended before the riff began")
        fade = min(len(y), int(0.03 * sr))
        y[len(y) - fade:] *= np.linspace(1, 0, fade)[:, None]
        sf.write(out, y, sr, subtype="PCM_24")
        peak, rms = float(np.max(np.abs(y))), float(np.sqrt(np.mean(y ** 2)))
        db = lambda v: round(20 * math.log10(v), 1) if v > 0 else -120.0  # noqa: E731
        return {"seconds": round(len(y) / sr, 2), "peak_dbfs": db(peak), "rms_dbfs": db(rms), "tempo": timing["tempo"]}
    finally:
        for f in (take, Path(f"{take}.timing.json")):
            f.unlink(missing_ok=True)
        sel = state.get("selected")
        client.run(with_prelude(
            "song.stop_playing()\n"
            f"_t = next((x for x in song.tracks if x.name == {track!r}), None)\n"
            "for _c in (list(_t.arrangement_clips) if _t else []):\n    _t.delete_clip(_c)\n"
            f"song.tempo = {state['tempo']!r}\nsong.loop = {state['loop']!r}\nsong.start_time = {state['start_time']!r}\n"
            f"song.current_song_time = {state['pos']!r}\n"
            + (f"select_track(song.tracks[{sel}])\n" if sel is not None and sel < len(state["names"]) else "")
            + "result = 'ok'"))


# ---------------------------------------------------------------------------------------------
# The control panel Zpkt web draws

def _slug(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:34] or "c"
    out, n = base, 2
    while out in taken:
        out, n = f"{base}_{n}", n + 1
    taken.add(out)
    return out


def controls_for(client: McpTransport, track: str, catalog: list[dict], wanted: list[Any]) -> list[dict]:
    """One control per wanted parameter (a name, or {"param", "label"}), with what Live shows across its range."""
    picks = []
    for w in wanted[:MAX_CONTROLS]:
        w = w if isinstance(w, dict) else {"param": w}
        p = _param(catalog, str(w.get("param") or ""))
        picks.append((p, str(w.get("label") or p["name"])[:30]))
    smooth = [p for p, _ in picks if not p["quantized"]]
    tables = sample(client, track, [(p["name"], p["min"], p["max"]) for p in smooth]) if smooth else {}
    taken: set[str] = set()
    out = []
    for slot, (p, label) in enumerate(picks):
        c = {"id": _slug(p["name"], taken), "param": p["name"], "label": label, "min": p["min"], "max": p["max"], "midiSlot": slot}
        if p["quantized"] and p["max"] - p["min"] == 1:
            c["kind"] = "toggle"
        else:
            c["kind"] = "knob"
            if p["quantized"]:
                c["step"] = 1
                if p["items"] and len(p["items"]) <= 24:
                    c["display"] = p["items"]
            else:
                c["display"] = tables[p["name"]][::(SAMPLES - 1) // (ANCHORS - 1)]
        out.append(c)
    return out


def _num(v: float) -> float | int:
    x = float(f"{v:.6g}")
    return int(x) if x == int(x) else x


def surface(panel: dict, ab: tuple[str, str] | None = None) -> dict:
    """The zpkt-surface spec for a panel as it now stands; with `ab`, a before/after deck of two renders."""
    controls = []
    for c in panel["controls"]:
        v = panel["values"].get(c["param"], c["min"])
        if c["kind"] == "toggle":
            controls.append({"kind": "toggle", "id": c["id"], "label": c["label"], "value": v > (c["min"] + c["max"]) / 2, "midiSlot": c["midiSlot"]})
            continue
        k = {"kind": "knob", "id": c["id"], "label": c["label"], "min": _num(c["min"]), "max": _num(c["max"]), "value": _num(v)}
        if c.get("step"):
            k["step"] = c["step"]
        if c.get("display"):
            k["display"] = c["display"]
        controls.append({**k, "midiSlot": c["midiSlot"]})
    if ab:
        side = lambda label, src: {"label": label, "src": src, "bpm": _num(panel["tempo"]), "downbeatMs": 0}  # noqa: E731
        controls.append({"kind": "ab", "id": "ab", "label": "Before / after", "a": side("before", ab[0]), "b": side("after", ab[1]),
                         "loop": {"startBar": 1, "bars": max(1, min(64, int(panel["beats"] // 4)))}, "quantize": "bar"})
    note = f"{panel['device']} · {panel['beats']:g} beats at {panel['tempo']:g} BPM · v{panel['version']}"
    return {"title": panel.get("title") or panel["name"], "note": note, "panel": panel["name"], "controls": controls}


def _shown_path(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(p.resolve())


def blocks(panel: dict, result: dict, warnings: list[str], ab: tuple[str, str] | None = None) -> str:
    """What the command prints: one line of facts, then the two blocks to paste into the answer as they are."""
    spec = surface(panel, ab)
    head, *rows = [json.dumps({k: v for k, v in spec.items() if k != "controls"}, ensure_ascii=False)[:-1] + ', "controls": [',
                   *[" " + json.dumps(c, ensure_ascii=False) for c in spec["controls"]]]
    body = head + "\n" + ",\n".join(rows) + "\n]}"
    level = f"peak {result['peak_dbfs']:g} dBFS, RMS {result['rms_dbfs']:g} dBFS, {result['seconds']:g} s"
    lines = [f"panel {panel['name']} v{panel['version']}: {panel['device']} on track {panel['track']!r}, {level}"]
    if result["peak_dbfs"] < -60:
        lines.append("WARNING: the render is silent. Check the instrument's level, the notes' range and Live's audio output.")
    lines += [f"warning: {w}" for w in warnings]
    lines += ["Paste both blocks into your answer as they are:", "", "```audio", panel["renders"][-1], "```", "",
              "```zpkt-surface", body, "```", "",
              f"When the user's Surface state comes back: hands panel apply {panel['name']} --state '<that JSON>'"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# The commands

def _cache_file(device: str) -> Path:
    return config.rig().data_dir / "panel-params" / (re.sub(r"[^\w.-]+", "_", device) + ".json")


def _remember(device: str, catalog: list[dict]) -> None:
    f = _cache_file(device)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(catalog))


def _file(out_dir: Path, name: str) -> Path:
    return out_dir / f"{name}.panel.json"


def _name(spec: dict) -> str:
    name = re.sub(r"[^a-z0-9]+", "-", str(spec.get("name") or "").lower()).strip("-")[:40]
    if not name:
        raise PanelError('the spec needs a "name" (letters, digits, dashes)')
    return name


def _recorder() -> Callable[..., str | None]:
    from hands.live.record import record_arrangement
    return record_arrangement


def make(client: McpTransport, spec: dict, out_dir: Path, *, replace: bool = False, force: bool = False,
         recorder: Callable[..., str | None] | None = None) -> str:
    """Make a panel from a spec and render it; return the text to print."""
    name = _name(spec)
    instrument = str(spec.get("instrument") or "").strip()
    if not instrument:
        raise PanelError('the spec needs an "instrument": a name from Live\'s browser ("Operator", "Operator/Acid Bass", "Serum 2")')
    notes, beats = riff(spec)
    track = TRACK_PREFIX + name
    state = _state(client)
    if state["playing"] and not force:
        raise PanelError("Live is playing (maybe the user): not rendering; pass --force to stop it")
    if track in state["names"]:
        if not replace:
            raise PanelError(f"a panel called {name!r} exists: change it with `hands panel apply {name}`, or pass --replace")
        _drop(client, track)
        time.sleep(0.3)
        state = _state(client)
    try:
        device = _load(client, track, instrument, state)
        catalog = read_catalog(client, track)
        _remember(device, catalog)
        wants = dict(spec.get("params") or {})
        values, warnings = resolve(client, track, catalog, wants)
        wanted = spec.get("controls") or list(values)[:8] or [p["name"] for p in catalog[1:9]]
        controls = controls_for(client, track, catalog, wanted)
        set_values(client, track, values)
        panel = {"name": name, "title": str(spec.get("title") or name), "track": track, "instrument": instrument, "device": device,
                 "tempo": float(spec.get("tempo") or state["tempo"]), "beats": beats, "tail": float(spec.get("tail", 2.0)),
                 "notes": notes, "controls": controls, "version": 1, "renders": [],
                 "values": {**{c["param"]: _param(catalog, c["param"])["value"] for c in controls}, **values}}
        out = out_dir / f"{name}.wav"
        result = _render(client, track, state, notes, beats, panel["tail"], panel["tempo"], out, recorder or _recorder())
    except Exception:
        _drop(client, track)                     # leave nothing behind: the next try starts clean
        raise
    panel["renders"].append(_shown_path(out))
    _file(out_dir, name).write_text(json.dumps(panel))
    return blocks(panel, result, warnings)


def apply(client: McpTransport, name: str, out_dir: Path, *, state_values: dict | None = None, spec: dict | None = None,
          force: bool = False, recorder: Callable[..., str | None] | None = None) -> str:
    """Set a panel's values (from the page's Surface state, and/or a spec's changes) and render the next version."""
    f = _file(out_dir, name)
    if not f.exists():
        raise PanelError(f"no panel {name!r} in {out_dir} (expected {f.name}); make it with `hands panel make`")
    panel = json.loads(f.read_text())
    spec = spec or {}
    track = panel["track"]
    state = _state(client)
    if state["playing"] and not force:
        raise PanelError("Live is playing (maybe the user): not rendering; pass --force to stop it")
    if track not in state["names"]:
        raise PanelError(f"the track {track!r} is not in the open set; make the panel again (`hands panel make --replace`)")
    cache = _cache_file(panel["device"])
    catalog = json.loads(cache.read_text()) if cache.exists() else read_catalog(client, track)
    by_id = {c["id"]: c for c in panel["controls"]}
    values: dict[str, float] = {}
    for cid, v in ((state_values or {}).get("values", state_values or {})).items():
        c = by_id.get(cid)
        if c is None or isinstance(v, str):      # the deck's side, or a control this panel does not have
            continue
        values[c["param"]] = (c["max"] if v else c["min"]) if isinstance(v, bool) else max(c["min"], min(c["max"], float(v)))
    asked, warnings = resolve(client, track, catalog, dict(spec.get("params") or {}))
    values.update(asked)
    if spec.get("controls"):
        panel["controls"] = controls_for(client, track, catalog, spec["controls"])
        for c in panel["controls"]:
            panel["values"].setdefault(c["param"], _param(catalog, c["param"])["value"])
    if spec.get("notes") or spec.get("chords"):
        panel["notes"], panel["beats"] = riff({"beats": panel["beats"], **spec} if "beats" not in spec else spec)
    for key in ("tempo", "tail"):
        if spec.get(key) is not None:
            panel[key] = float(spec[key])
    if spec.get("title"):
        panel["title"] = str(spec["title"])
    set_values(client, track, values)
    panel["values"].update(values)
    panel["version"] += 1
    out = out_dir / f"{name}-{panel['version']}.wav"
    notes = [tuple(n) for n in panel["notes"]]
    result = _render(client, track, state, notes, panel["beats"], panel["tail"], panel["tempo"], out, recorder or _recorder())
    before = panel["renders"][-1]
    panel["renders"].append(_shown_path(out))
    f.write_text(json.dumps(panel))
    return blocks(panel, result, warnings, ab=(before, panel["renders"][-1]))


def drop(client: McpTransport, name: str, out_dir: Path) -> str:
    """Delete a panel's track from the open set; its renders stay."""
    track = TRACK_PREFIX + name
    names = client.run("result = [t.name for t in song.tracks]")
    if track not in names:
        return f"no track {track!r} in the open set"
    _drop(client, track)
    _file(out_dir, name).unlink(missing_ok=True)
    return f"deleted the track {track!r}; the renders stay"


def params(client: McpTransport | None, instrument: str, grep: str = "") -> str:
    """A device's parameters, one per line: name | range | value = what Live shows | choices. Read from the
    cache when the device has been loaded before; otherwise loaded on a temporary track, read, and removed."""
    cache = _cache_file(instrument)
    if cache.exists():
        catalog = json.loads(cache.read_text())
    else:
        if client is None:
            raise PanelError(f"{instrument!r} has not been read yet and Live is not reachable")
        state = _state(client)
        track = TRACK_PREFIX + "params (temporary)"
        try:
            device = _load(client, track, instrument, state)
            catalog = read_catalog(client, track)
        finally:
            _drop(client, track)
        _remember(device, catalog)
        if device != instrument:
            _remember(instrument, catalog)
    try:
        rx = re.compile(grep, re.I) if grep else None
    except re.error as exc:
        raise PanelError(f"--grep is not a regular expression: {exc}") from exc
    rows = []
    for p in catalog:
        if rx and not rx.search(p["name"]):
            continue
        row = f"{p['name']} | {p['min']:g}..{p['max']:g} | {p['value']:.4g} = {p['shown']}"
        if p["items"]:
            row += " | " + ", ".join(p["items"][:32])
        rows.append(row)
    head = (f"{instrument}: {len(rows)} of {len(catalog)} parameters (name | range | default = shown | choices). "
            'In a spec, a number is the raw value; text is what Live shows ("800 Hz", "50%", a choice).')
    return "\n".join([head, *rows])
