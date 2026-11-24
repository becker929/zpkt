"""Rendering a panel: its riff or its bars recorded in real time through a resampling track (record_span), cut to
the span (cut_take) and measured (levels). The set is put back after each render, however it ends (hands.live.hold).
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from pathlib import Path

from hands.live import hold
from hands.live.agent import with_prelude
from hands.live.panel_base import LEAD_SECONDS, Note, PanelError, _device, _track
from hands.live.transport import McpTransport


def lead_beats(tempo: float) -> float:
    """Whole beats rendered before the riff, enough to cover LEAD_SECONDS."""
    return float(max(2, math.ceil(LEAD_SECONDS * tempo / 60.0)))


def record_span(
    transport: McpTransport,
    *,
    filename: str,
    output_dir: str,
    start_beat: float,
    duration_beats: float,
    tail_beats: float,
    tempo: float,
    n_tracks: int,
    armed: list[int],
    before: str = "",
    after: str = "",
) -> str | None:
    """Record the arrangement from start_beat through a resampling track, in as few round trips as Live allows.

    The same method as hands.live.record.record_arrangement (which see for why), batched: `before` (writes
    only) runs in the first call and `after` in the last, which always runs and also removes the render track
    and puts the arm states back. Writes <output_dir>/<filename> and its .timing.json; returns the path.
    """
    import shutil

    from hands.live import sweep
    from hands.live.record import _beat_to_seconds

    idx, out, take = n_tracks, str(Path(output_dir) / filename), None
    sweep.make_room(Path(output_dir), (duration_beats + tail_beats) * 60.0 / tempo)
    put_back = with_prelude(
        f"song.stop_playing()\nsong.record_mode = False\n"
        f"if len(song.tracks) > {idx} and song.tracks[{idx}].name == 'Render':\n    song.delete_track({idx})\n"
        f"for _i in {armed!r}:\n    if _i < len(song.tracks) and song.tracks[_i].can_be_armed:\n        song.tracks[_i].arm = 1\n"
        + after
        + "\nresult = 'ok'"
    )
    try:
        with hold.undo(
            transport, "the set as it was before a render (its Render track, record mode, tempo and playhead)", put_back
        ):
            transport.run(
                before + "\nsong.stop_playing()\nsong.loop = False\nsong.back_to_arranger = False\n"
                f"for _i in {armed!r}:\n    song.tracks[_i].arm = 0\nsong.create_audio_track(-1)\nresult = 'ok'"
            )
            for k in range(10):  # a new track can report no input types for a moment
                if k:
                    time.sleep(0.3)
                if transport.run(
                    f"_t = song.tracks[{idx}]\n_t.name = 'Render'\n"
                    "_rt = next((r for r in _t.available_input_routing_types if 'Resampling' in r.display_name), None)\n"
                    "if _rt is not None:\n    _t.input_routing_type = _rt\nresult = _rt is not None"
                ):
                    break
            transport.run(
                f"_t = song.tracks[{idx}]\nif 'Resampling' not in str(_t.input_routing_type.display_name):\n"
                "    raise RuntimeError('could not set the render track to Resampling')\n_t.arm = 1\nresult = 'ok'"
            )
            transport.run(
                f"song.start_time = {float(start_beat)!r}\nsong.current_song_time = {float(start_beat)!r}\n"
                "song.record_mode = True\nsong.start_playing()\nresult = 'ok'"
            )
            from hands.live.record import AUDIO_STALLED, playhead_moves

            if not playhead_moves(transport, float(start_beat)):
                raise PanelError(AUDIO_STALLED)
            time.sleep((duration_beats + tail_beats) * 60.0 / tempo + 0.3)
            transport.run("song.stop_playing()\nsong.record_mode = False\nresult = 'ok'")
            clip = None
            for k in range(6):  # the take appears on the track a moment after the stop
                time.sleep(0.2 if k else 0.1)
                clip = transport.run(
                    f"_c = list(song.tracks[{idx}].arrangement_clips)[:1]\n"
                    "result = [_c[0].file_path, _c[0].start_marker, [[w.beat_time, w.sample_time] for w in _c[0].warp_markers], _c[0].start_time] if _c else None"
                )
                if clip and Path(clip[0]).exists():
                    break
            if not clip or not Path(clip[0]).exists():
                return None
            take = clip[0]
            sweep.note_takes(Path(output_dir), Path(take).parent)
            shutil.copy2(take, out)
            Path(out + ".timing.json").write_text(
                json.dumps(
                    {"song_zero_seconds": _beat_to_seconds(clip[2], clip[1]), "clip_start": clip[3], "tempo": tempo}
                )
            )
            return out
    finally:
        for leftover in [take, take + ".asd"] if take else []:  # Live's own take file in the project
            Path(leftover).unlink(missing_ok=True)


def _render(
    client: McpTransport,
    track: str,
    state: dict,
    notes: list[Note],
    beats: float,
    tail: float,
    tempo: float | None,
    out: Path,
    recorder: Callable[..., str | None],
    values: dict[str, float] | None = None,
) -> dict:
    """Set the values, write the riff past the end of the arrangement, record it, cut the take to the riff, put the set back."""
    tempo = float(tempo or state["tempo"])
    lead = lead_beats(tempo)
    start = (int(state["end"] / 4) + 4) * 4.0 + math.ceil(lead / 4) * 4.0
    out.parent.mkdir(parents=True, exist_ok=True)
    take = out.with_name(f".{out.stem}.take.wav")
    sel = state.get("selected")
    before = (
        (
            f"_by = {{p.name: p for p in {_device(track)}.parameters}}\nfor _n, _v in {sorted(values.items())!r}:\n    _by[_n].value = _v\n"
            if values
            else ""
        )
        + (f"song.tempo = {tempo!r}\n" if abs(tempo - state["tempo"]) > 1e-6 else "")
        + f"_c = {_track(track)}.create_midi_clip({start!r}, {float(beats)!r})\n_c.name = 'panel riff'\n"
        "_c.add_new_notes(tuple(Live.Clip.MidiNoteSpecification(pitch=p, start_time=s, duration=d, velocity=v)"
        f" for p, s, d, v in {notes!r}))\n"
    )
    after = (
        f"_t = next((x for x in song.tracks if x.name == {track!r}), None)\n"
        "for _c in (list(_t.arrangement_clips) if _t else []):\n    _t.delete_clip(_c)\n"
        f"song.tempo = {state['tempo']!r}\nsong.loop = {state['loop']!r}\nsong.start_time = {state['start_time']!r}\n"
        f"song.current_song_time = {state['pos']!r}\n"
        + (f"select_track(song.tracks[{sel}])\n" if sel is not None and sel < len(state["names"]) else "")
    )
    try:
        path = recorder(
            transport=client,
            filename=take.name,
            output_dir=str(out.parent),
            start_beat=start - lead,
            duration_beats=lead + beats,
            tail_beats=tail,
            tempo=tempo,
            n_tracks=len(state["names"]),
            armed=state["armed"],
            before=before,
            after=after,
        )
        if not path:
            raise PanelError("Live recorded nothing; check its audio output (`hands live check`)")
        return cut_take(path, out, start, beats + tail, lead)
    finally:
        for f in (take, Path(f"{take}.timing.json")):
            f.unlink(missing_ok=True)


def cut_take(path: str, out: Path, start: float, length_beats: float, lead: float, fade_s: float = 0.03) -> dict:
    """Cut a take made by record_span to `length_beats` from the song beat `start`; write it and say how loud it is."""
    import numpy as np
    import soundfile as sf

    timing = json.loads(Path(f"{path}.timing.json").read_text())
    x, sr = sf.read(path, always_2d=True, dtype="float64")
    spb = 60.0 / timing["tempo"]
    a = int(round((timing["song_zero_seconds"] + (start - timing.get("clip_start", start - lead)) * spb) * sr))
    y = x[max(0, a) : max(0, a) + int(round(length_beats * spb * sr))].copy()
    if not len(y):
        raise PanelError("the take ended before the part to keep began")
    fade = min(len(y), int(fade_s * sr))
    if fade:
        y[len(y) - fade :] *= np.linspace(1, 0, fade)[:, None]
    sf.write(out, y, sr, subtype="PCM_24")
    return {**levels(y), "seconds": round(len(y) / sr, 2), "tempo": timing["tempo"]}


def levels(y) -> dict:
    import numpy as np

    peak, rms = float(np.max(np.abs(y))), float(np.sqrt(np.mean(y**2)))
    db = lambda v: round(20 * math.log10(v), 1) if v > 0 else -120.0  # noqa: E731
    return {"peak_dbfs": db(peak), "rms_dbfs": db(rms)}


def set_code(panel: dict, values: dict[str, float]) -> str:
    """Live code that sets a panel's values: an instrument's parameters by name, a mix panel's by where each one is."""
    if not values:
        return ""
    if panel.get("kind") == "mix":
        return "".join(f"{panel['exprs'][k]}.value = {float(v)!r}\n" for k, v in sorted(values.items()))
    return (
        f"_by = {{p.name: p for p in {_device(panel['track'])}.parameters}}\n"
        f"for _n, _v in {sorted(values.items())!r}:\n    _by[_n].value = _v\n"
    )
