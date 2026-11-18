"""A song from panels: each panel's riff, looped over the sections it plays in, laid out in the arrangement.

    hands song make --spec '{"name": "night-drive", "tempo": 124, "sections": [
        {"name": "intro", "bars": 8, "parts": ["nd-pad"]},
        {"name": "drop", "bars": 16, "parts": ["nd-pad", "nd-bass", "nd-kick"]}]}'

The clips go past the end of whatever is already in the set, stay there (so mix panels can render bars of the
song: {"song": "night-drive", "bars": [9, 8], ...}), and are deleted by `hands song drop`. Rendered in Live,
through Main, in real time.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Callable

from hands.live import panel as P
from hands.live.transport import McpTransport

BARS_MAX = 200
CLIP = "song "


def _file(out_dir: Path, name: str) -> Path:
    return out_dir / f"{name}.song.json"


def layout(spec: dict, panels: dict[str, dict]) -> tuple[list[dict], dict[str, list[tuple[float, float, list]]], float]:
    """Sections with their start beats, and per panel the runs it plays: (start, length, notes), in beats from the song's start."""
    sections, at = [], 0.0
    for i, s in enumerate(spec.get("sections") or []):
        bars = int(s.get("bars") or 0)
        if bars < 1:
            raise P.PanelError(f"section {i + 1} needs \"bars\" (1 or more)")
        parts = [str(p) for p in s.get("parts") or []]
        for p in parts:
            if p not in panels:
                raise P.PanelError(f"section {i + 1} plays {p!r}, which is not an instrument panel here; panels: {', '.join(panels) or 'none'}")
        sections.append({"name": str(s.get("name") or f"part {i + 1}"), "bars": bars, "start": at, "parts": parts})
        at += bars * 4.0
    if not sections:
        raise P.PanelError('a song needs "sections": [{"name", "bars", "parts": [panel names]}, ...]')
    if at / 4 > BARS_MAX:
        raise P.PanelError(f"a song is at most {BARS_MAX} bars (it renders in real time); this one is {at / 4:g}")
    runs: dict[str, list[tuple[float, float, list]]] = {}
    for name, panel in panels.items():
        spans: list[list[float]] = []            # runs of sections next to each other, so a riff carries across them
        for s in sections:
            if name in s["parts"]:
                if spans and abs(spans[-1][1] - s["start"]) < 1e-9:
                    spans[-1][1] = s["start"] + s["bars"] * 4.0
                else:
                    spans.append([s["start"], s["start"] + s["bars"] * 4.0])
        period = float(panel["beats"])
        for a, b in spans:
            notes = []
            for rep in range(int(math.ceil((b - a) / period))):
                for p, st, d, v in panel["notes"]:
                    t = rep * period + st
                    if t < b - a - 1e-9:
                        notes.append((int(p), t, min(d, b - a - t), int(v)))
            runs.setdefault(name, []).append((a, b - a, notes))
    return sections, runs, at


def _clear(client: McpTransport, name: str) -> None:
    client.run(f"for _t in song.tracks:\n    for _c in [c for c in _t.arrangement_clips if c.name == {CLIP + name!r}]:\n        _t.delete_clip(_c)\nresult = 'ok'")


def _record(client: McpTransport, song: dict, state: dict, out: Path, recorder, start_bar: int = 1, bars: int | None = None) -> dict:
    tempo, lead = float(song["tempo"]), P.lead_beats(float(song["tempo"]))
    start = song["start"] + (start_bar - 1) * 4.0
    beats = (bars * 4.0) if bars else song["beats"] - (start_bar - 1) * 4.0
    tail = float(song.get("tail", 4.0))
    take = out.with_name(f".{out.stem}.take.wav")
    out.parent.mkdir(parents=True, exist_ok=True)
    sel = state.get("selected")
    after = (f"song.tempo = {state['tempo']!r}\nsong.loop = {state['loop']!r}\nsong.start_time = {state['start_time']!r}\n"
             f"song.current_song_time = {state['pos']!r}\n"
             + (f"select_track(song.tracks[{sel}])\n" if sel is not None and sel < len(state["names"]) else ""))
    try:
        path = recorder(transport=client, filename=take.name, output_dir=str(out.parent), start_beat=start - lead,
                        duration_beats=lead + beats, tail_beats=tail, tempo=tempo, n_tracks=len(state["names"]),
                        armed=state["armed"], before=f"song.tempo = {tempo!r}\n", after=after)
        if not path:
            raise P.PanelError("Live recorded nothing; check its audio output (`hands live check`)")
        return P.cut_take(path, out, start, beats + tail, lead, fade_s=0.5)
    finally:
        for f in (take, Path(f"{take}.timing.json")):
            f.unlink(missing_ok=True)


def _text(song: dict, result: dict) -> str:
    lines = [f"song {song['name']} v{song['version']}: {song['beats'] / 4:g} bars at {song['tempo']:g} BPM, "
             f"peak {result['peak_dbfs']:g} dBFS, RMS {result['rms_dbfs']:g} dBFS, {result['seconds']:g} s",
             "  " + " | ".join(f"{s['name']} {int(s['start'] / 4) + 1}-{int(s['start'] / 4) + s['bars']}" for s in song["sections"])]
    if result["peak_dbfs"] > -0.3:
        lines.append("WARNING: the render reaches full scale. Turn the parts down (a mix panel with their faders) and render again.")
    lines += ["Paste this block into your answer as it is:", "", "```audio", song["renders"][-1], "```", "",
              f"To balance it: hands panel make --spec '{{\"name\": \"{song['name']}-mix\", \"song\": \"{song['name']}\", \"bars\": [1, 8], "
              f"\"faders\": [\"panel NAME\", ...]}}', then `hands song render {song['name']}`."]
    return "\n".join(lines)


def make(client: McpTransport, spec: dict, out_dir: Path, *, force: bool = False, recorder: Callable[..., str | None] | None = None) -> str:
    """Lay the song out in the arrangement and render it; return the text to print."""
    name = P._name(spec)
    wanted = sorted({str(p) for s in spec.get("sections") or [] for p in s.get("parts") or []})
    panels = {}
    for p in wanted:
        f = P._file(out_dir, p)
        if f.exists():
            d = json.loads(f.read_text())
            if d.get("kind") != "mix":
                panels[p] = d
    sections, runs, total = layout(spec, panels)
    _clear(client, name)
    state = P._state(client)
    if state["playing"] and not force:
        raise P.PanelError("Live is playing (maybe the user): not rendering; pass --force to stop it")
    for p in panels.values():
        if p["track"] not in state["names"]:
            raise P.PanelError(f"the track {p['track']!r} is not in the open set; make that panel again")
    tempo = float(spec.get("tempo") or state["tempo"])
    lead = P.lead_beats(tempo)
    start = (int(state["end"] / 4) + 4) * 4.0 + math.ceil(lead / 4) * 4.0
    for pname, spans in runs.items():
        code = f"_t = {P._track(panels[pname]['track'])}\n"
        for a, length, notes in spans:
            code += (f"_c = _t.create_midi_clip({start + a!r}, {float(length)!r})\n_c.name = {CLIP + name!r}\n"
                     "_c.add_new_notes(tuple(Live.Clip.MidiNoteSpecification(pitch=p, start_time=s, duration=d, velocity=v)"
                     f" for p, s, d, v in {notes!r}))\n")
        client.run(code + "result = 'ok'")
    old = json.loads(_file(out_dir, name).read_text()) if _file(out_dir, name).exists() else {}
    song = {"name": name, "tempo": tempo, "start": start, "beats": total, "tail": float(spec.get("tail", 4.0)), "sections": sections,
            "parts": sorted(runs), "version": int(old.get("version", 0)) + 1, "renders": list(old.get("renders") or [])}
    out = out_dir / (f"{name}.wav" if song["version"] == 1 else f"{name}-{song['version']}.wav")
    try:
        result = _record(client, song, {**state, "end": start + total}, out, recorder or P._recorder())
    except Exception:
        _clear(client, name)
        raise
    song["renders"].append(P._shown_path(out))
    _file(out_dir, name).write_text(json.dumps(song))
    return _text(song, result)


def render(client: McpTransport, name: str, out_dir: Path, *, force: bool = False, recorder: Callable[..., str | None] | None = None) -> str:
    """Render the song again as it now stands in the set (after its panels or its mix changed)."""
    from hands.live.mix import song_of
    song = song_of(out_dir, name)
    state = P._state(client)
    if state["playing"] and not force:
        raise P.PanelError("Live is playing (maybe the user): not rendering; pass --force to stop it")
    song["version"] += 1
    out = out_dir / f"{name}-{song['version']}.wav"
    result = _record(client, song, state, out, recorder or P._recorder())
    song["renders"].append(P._shown_path(out))
    _file(out_dir, name).write_text(json.dumps(song))
    return _text(song, result)


def drop(client: McpTransport, name: str, out_dir: Path) -> str:
    """Delete the song's clips from the arrangement; its panels' tracks and its renders stay."""
    _clear(client, name)
    _file(out_dir, name).unlink(missing_ok=True)
    return f"deleted the clips of the song {name!r}; its renders stay"

