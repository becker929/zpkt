"""Low-level code generation for Ableton MCP execute() calls.

Returns `Step` (label, code, optional note) ready for MCP execute().
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict

from hands.models import (
    ArrangementClip, ArrangementConfig, DeviceSource, DeviceSpec,
    EQ8Band, EQ8Spec, MidiNote, MidiPattern, ParallelRack, SamplePad,
)


class Step(BaseModel):
    """One atomic MCP execute() call."""
    model_config = ConfigDict(frozen=True)

    label: str
    code: str
    note: str | None = None


def hz_to_eq8_norm(hz: float) -> float:
    """Convert Hz to EQ Eight normalised frequency (0-1)."""
    return math.log10(hz / 20.0) / math.log10(1000.0)


def _browser_attr(source: DeviceSource) -> str:
    return f"browser.{source.value}"


def gen_set_tempo(bpm: float) -> Step:
    return Step(label=f"Set tempo to {bpm} BPM", code=f"song.tempo = {bpm}")


def gen_create_tracks(names: list[tuple[str, str]]) -> Step:
    """(name, type) pairs; type is 'audio' or 'midi'."""
    lines = [
        "for i in range(len(song.tracks) - 1, 0, -1):",
        "    song.delete_track(i)",
        "t0 = song.tracks[0]",
        f't0.name = {names[0][0]!r}',
        "for i in range(len(t0.devices) - 1, -1, -1):",
        "    t0.delete_device(i)",
    ]
    for idx, (name, ttype) in enumerate(names[1:], start=1):
        method = "create_midi_track" if ttype == "midi" else "create_audio_track"
        lines.append(f"song.{method}({idx})")
        lines.append("time.sleep(0.3)")
    lines.append("result = [(i, t.name) for i, t in enumerate(song.tracks)]")
    return Step(label="Create tracks", code="\n".join(lines))


def gen_rename_tracks(names: list[tuple[str, str]]) -> Step:
    lines = [f'song.tracks[{i}].name = {n!r}' for i, (n, _) in enumerate(names)]
    lines.append("result = [(i, t.name) for i, t in enumerate(song.tracks)]")
    return Step(label="Rename tracks", code="\n".join(lines))


def gen_load_device(track_idx: int, device: DeviceSpec) -> Step:
    attr = _browser_attr(device.source)
    code = (
        f"t = song.tracks[{track_idx}]\n"
        f'load_to(t, {attr}, {device.name!r})\n'
        "time.sleep(0.3)\n"
        "result = [d.name for d in t.devices]"
    )
    return Step(label=f"Load {device.name} on track {track_idx}", code=code)


def gen_load_devices(track_idx: int, devices: list[DeviceSpec]) -> Step:
    lines = [f"t = song.tracks[{track_idx}]"]
    for d in devices:
        lines.append(f'load_to(t, {_browser_attr(d.source)}, {d.name!r})')
        lines.append("time.sleep(0.3)")
    lines.append("result = [d.name for d in t.devices]")
    return Step(
        label=f"Load [{', '.join(d.name for d in devices)}] on track {track_idx}",
        code="\n".join(lines),
    )


def gen_set_params(track_idx: int, device_idx: int,
                   params: dict[str, float], label: str) -> Step:
    lines = [
        f"t = song.tracks[{track_idx}]",
        f"dev = t.devices[{device_idx}]",
        "for p in dev.parameters:",
    ]
    for k, v in params.items():
        lines.append(f"    if p.name == '{k}': p.value = {v}")
    lines.append(f'result = "{label} configured"')
    return Step(label=f"Configure {label}", code="\n".join(lines))


def gen_configure_eq8(track_idx: int, device_idx: int,
                      spec: EQ8Spec, label: str) -> Step:
    lines = [
        f"t = song.tracks[{track_idx}]",
        f"eq = t.devices[{device_idx}]",
        "for p in eq.parameters:",
    ]
    for band in spec.bands:
        freq_n = hz_to_eq8_norm(band.freq_hz)
        b = band.band
        lines += [
            f"    if p.name == '{b} Filter On A': p.value = 1.0",
            f"    if p.name == '{b} Filter Type A': p.value = {band.mode:.1f}",
            f"    if p.name == '{b} Frequency A': p.value = {freq_n:.6f}",
            f"    if p.name == '{b} Gain A': p.value = {band.gain}",
            f"    if p.name == '{b} Resonance A': p.value = {band.q_norm}",
        ]
    lines.append(f'result = "EQ8 {label} configured"')
    return Step(label=f"Configure EQ8 ({label})", code="\n".join(lines))


def gen_midi_clip(track_idx: int, slot: int, pattern: MidiPattern) -> Step:
    def _note(n: MidiNote) -> str:
        return (f"notes.append(MidiNoteSpecification(pitch={n.pitch}, "
                f"start_time={n.time}, duration={n.duration}, velocity={n.velocity}))")
    lines = [
        f"t = song.tracks[{track_idx}]",
        f"cs = t.clip_slots[{slot}]",
        f"cs.create_clip({pattern.length_beats})",
        "clip = cs.clip",
        f'clip.name = {pattern.name!r}',
        "notes = []",
        *(_note(n) for n in pattern.notes),
        "clip.add_new_notes(tuple(notes))",
    ]
    if pattern.loop:
        lines.append("clip.looping = True")
    lines.append('result = "Created " + str(len(notes)) + " notes"')
    return Step(label=f"Create MIDI clip '{pattern.name}'", code="\n".join(lines))


def gen_select_drum_pad(track_idx: int, device_idx: int, note: int) -> Step:
    code = (
        f"t = song.tracks[{track_idx}]\n"
        f"dr = t.devices[{device_idx}]\n"
        f"song.view.selected_track = t\n"
        "time.sleep(0.1)\n"
        f"pad = dr.drum_pads[{note}]\n"
        "dr.view.selected_drum_pad = pad\n"
        f'result = "Selected pad note={note} name=" + pad.name'
    )
    return Step(label=f"Select drum pad note={note} on track {track_idx}", code=code)


def gen_load_sample_to_pad(
    track_idx: int, device_idx: int, note: int, sample_query: str,
) -> Step:
    lines = [
        f"t = song.tracks[{track_idx}]",
        f"dr = t.devices[{device_idx}]",
        f"dr.view.selected_drum_pad = dr.drum_pads[{note}]",
        "time.sleep(0.1)",
        f"item = find_item(browser.samples, {sample_query!r})",
        "if item is None:",
        f'    result = "WARNING: no sample matching {sample_query!r}"',
        "else:",
        "    browser.load_item(item)",
        "    time.sleep(0.3)",
        f'    result = "Loaded " + item.name + " into pad {note}"',
    ]
    return Step(
        label=f"Load sample '{sample_query}' into pad note={note} on track {track_idx}",
        code="\n".join(lines),
    )


def gen_set_simpler_params(
    track_idx: int, device_idx: int, note: int, pad: SamplePad,
) -> Step:
    s_start = pad.start / 100.0
    s_length = max(0.0, (pad.end - pad.start) / 100.0) if pad.end is not None else (1.0 - s_start)
    volume_db = max(-36.0, 20.0 * math.log10(pad.volume)) if pad.volume > 0 else -36.0
    lines = [
        f"t = song.tracks[{track_idx}]",
        f"dr = t.devices[{device_idx}]",
        f"chain = dr.drum_pads[{note}].chains[0]",
        "simpler = chain.devices[0]",
        "for p in simpler.parameters:",
        f"    if p.name == 'Transpose': p.value = {float(pad.transpose)}",
        f"    if p.name == 'S Start': p.value = {s_start:.6f}",
        f"    if p.name == 'S Length': p.value = {s_length:.6f}",
        f"    if p.name == 'Volume': p.value = {volume_db:.4f}",
        f'result = "Simpler params set on pad {note}"',
    ]
    return Step(label=f"Set Simpler params on pad note={note} (track {track_idx})", code="\n".join(lines))


def gen_load_device_to_pad(
    track_idx: int, device_idx: int, note: int, device: DeviceSpec,
) -> Step:
    attr = _browser_attr(device.source)
    lines = [
        f"t = song.tracks[{track_idx}]",
        f"dr = t.devices[{device_idx}]",
        f"chain = dr.drum_pads[{note}].chains[0]",
        "song.view.selected_chain = chain",
        "time.sleep(0.1)",
        f"item = find_item({attr}, {device.name!r})",
        "if item is None:",
        f'    result = "WARNING: no device matching {device.name!r}"',
        "else:",
        "    browser.load_item(item)",
        "    time.sleep(0.3)",
        f'    result = "Loaded {device.name} onto pad {note} chain"',
    ]
    return Step(
        label=f"Load '{device.name}' onto pad note={note} chain (track {track_idx})",
        code="\n".join(lines),
    )


def gen_set_pad_chain_device_params(
    track_idx: int, device_idx: int, note: int,
    chain_device_idx: int, params: dict[str, float], label: str,
) -> Step:
    """Set params on a device in a pad chain (0=Simpler, 1+=effects)."""
    lines = [
        f"t = song.tracks[{track_idx}]",
        f"dr = t.devices[{device_idx}]",
        f"chain = dr.drum_pads[{note}].chains[0]",
        f"dev = chain.devices[{chain_device_idx}]",
        "for p in dev.parameters:",
        *[f"    if p.name == {k!r}: p.value = {v}" for k, v in params.items()],
        f'result = "{label} configured on pad {note} chain"',
    ]
    return Step(label=f"Configure {label} on pad note={note} chain (track {track_idx})", code="\n".join(lines))


def gen_manual_rack_setup(track_idx: int, rack: ParallelRack) -> Step:
    chain_desc = ", ".join(
        f"'{c.name}' ({', '.join(d.name for d in c.devices) or 'empty'})"
        for c in rack.chains
    )
    return Step(
        label=f"MANUAL: Audio Effect Rack chains on track {track_idx}",
        code="result = 'MANUAL STEP — see note'",
        note=(
            f"In Live: expand Audio Effect Rack on track {track_idx}. "
            f"Create chains: {chain_desc}. "
            "Then run the next step to configure plugin params."
        ),
    )


def gen_configure_rack_chain(track_idx: int, rack_device_idx: int,
                             chain_idx: int, device_in_chain: int,
                             params: dict[str, float], label: str) -> Step:
    lines = [
        f"t = song.tracks[{track_idx}]",
        f"aer = t.devices[{rack_device_idx}]",
        f"if len(aer.chains) > {chain_idx}:",
        f"    chain = aer.chains[{chain_idx}]",
        f"    if len(chain.devices) > {device_in_chain}:",
        f"        dev = chain.devices[{device_in_chain}]",
        "        for p in dev.parameters:",
        *[f"            if p.name == '{k}': p.value = {v}" for k, v in params.items()],
        f'        result = "{label} configured"',
        "    else:",
        f'        result = "No device at index {device_in_chain}"',
        "else:",
        f'    result = "Need chain {chain_idx} first"',
    ]
    return Step(label=f"Configure {label}", code="\n".join(lines))


def gen_tile_session_to_arrangement(
    track_idx: int, session_slot: int,
    start_beat: float, end_beat: float, clip_length: float,
) -> Step:
    """Tile a session clip across a range in the arrangement."""
    code = (
        f"t = song.tracks[{track_idx}]\n"
        f"clip = t.clip_slots[{session_slot}].clip\n"
        f"beat = {start_beat}\n"
        f"while beat < {end_beat}:\n"
        "    t.duplicate_clip_to_arrangement(clip, beat)\n"
        "    time.sleep(0.1)\n"
        f"    beat += {clip_length}\n"
        f'result = "Tiled track {track_idx} from {start_beat} to {end_beat}"'
    )
    return Step(label=f"Arrange: tile track {track_idx} beats {start_beat}-{end_beat}", code=code)


def gen_set_arrangement_loop(loop: bool, start: float, length: float) -> Step:
    code = (
        f"song.loop_start = {start}\n"
        f"song.loop_length = {length}\n"
        f"song.loop = {loop}\n"
        f'result = "Loop: on={loop}, start={start}, length={length}"'
    )
    return Step(label="Set arrangement loop", code=code)
