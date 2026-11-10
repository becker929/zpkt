"""A Plan into Live: the job's set, its tracks, notes, mixer and returns, then the export. One checked step at a time.

Every LOM call is built here from a Plan: numbers go in through repr(int|float), names are the booth's ("p1") or the
palette's. Each call stays short (notes go in 400 to a call) and is read back in a separate call, since reading
what a call just wrote crashes Live. Before each step `session.check` makes sure no dialog is open and the job's set
is in front; anything else raises Stop.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Callable

from . import HOME, PREFIX, SETS_DIR, TEMPLATE
from .compile import PLAYBACK_MODES, WARP_MODES, Plan, TrackPlan
from .gui import Stop, ops, stops

NOTES_PER_CALL = 400
COPIES_PER_CALL = 8          # duplicate_clip_to_arrangement calls in one LOM call
SLICING_MANUAL = 3           # Sample.slicing_style: 0 Transient, 1 Beat, 2 Region, 3 Manual


def set_name(job: str) -> str:
    return f"{PREFIX}{job}"


class Builder:
    def __init__(self, client, *, step: Callable[[str], None] = lambda s: None) -> None:
        self.live = client
        self.step = step                     # reports the stage name ("load p3") to the job's record
        self.L = ops(client)

    def run(self, code: str):
        with stops("lom"):
            return self.live.run(code)

    def guard(self, where: str, front: str) -> None:
        from hands.live import session
        self.step(where)
        with stops(where):
            session.check(self.live, where, expect_front=front)

    # ---- the set -------------------------------------------------------------------------------------------------
    def open(self, job: str) -> str:
        """Copy the template to the job's set and open it (the set in front, the template or an old job, is saved
        first by open_set, so Live never asks about unsaved changes)."""
        from hands.live import session
        name = set_name(job)
        if not session.config.rig().set_path(TEMPLATE).exists():
            raise Stop(f"no template set {TEMPLATE} in {SETS_DIR}: run `booth template` once, watched")
        self.step("open")
        with stops("open"):
            if session._front() == name:          # a held job run again: its half-built set is still in front
                session.open_set(self.live, TEMPLATE)
            session.copy_set(TEMPLATE, name)
            session.open_set(self.live, name)
        self.guard("opened", name)
        got = self.run("result = ([(t.name, t.has_midi_input, len(t.devices), len(t.arrangement_clips)) for t in song.tracks], "
                       "[r.name for r in song.return_tracks])")
        if [list(t) for t in got[0]] != [["p1", True, 0, 0]] or len(got[1]) < 2:      # the LOM answers lists
            raise Stop(f"open: the template is not one empty MIDI track p1 and two returns: {got}")
        return name

    def close(self, job: str) -> None:
        """Back to the template (open_set saves the job's set first, so no prompt), then delete the job's file."""
        from hands.live import session
        self.step("close")
        with stops("close"):
            session.open_set(self.live, TEMPLATE)
        path = session.config.rig().set_path(set_name(job))
        path.unlink(missing_ok=True)

    # ---- the build -----------------------------------------------------------------------------------------------
    def build(self, plan: Plan, front: str) -> None:
        self.guard("tempo", front)
        self.run(f"song.tempo = {float(plan.bpm)!r}\nsong.signature_numerator = 4\nsong.signature_denominator = 4\nresult = 'ok'")
        got = self.run("result = (song.tempo, [d.name for d in song.master_track.devices])")
        if abs(got[0] - plan.bpm) > 1e-6:
            raise Stop(f"tempo: Live has {got[0]}, wanted {plan.bpm}")
        if tuple(got[1]) != tuple(plan.master_devices):
            raise Stop(f"master: Main has {got[1]}, the palette's chain is {list(plan.master_devices)}")

        self.guard("tracks", front)
        for k, t in enumerate(plan.tracks[1:], start=1):      # Live keeps at least one track: the template's is p1
            self.run(f"song.create_{t.kind}_track(-1)\nsong.tracks[{k}].name = {t.name!r}\nresult = 'ok'")
        if plan.tracks[0].kind == "audio":                   # the template's p1 is MIDI: an audio track takes its place
            self.run("song.create_audio_track(0)\nresult = 'ok'")
            self.run("song.delete_track(1)\nsong.tracks[0].name = 'p1'\nresult = 'ok'")
        got = self.run("result = [(t.name, t.has_midi_input) for t in song.tracks]")
        if [list(g) for g in got] != [[t.name, t.kind == "midi"] for t in plan.tracks]:
            raise Stop(f"tracks: Live has {got}")

        for k, t in enumerate(plan.tracks):
            if t.kind == "audio":
                self.clips(k, t, plan.bpm, front)
            elif t.sample:
                self.simpler(k, t, front)
            else:
                self.instrument(k, t, front)
        for k, t in enumerate(plan.tracks):
            if t.kind == "midi":
                self.notes(k, t, plan.beats, front)
        self.mix(plan, front)

    def instrument(self, k: int, t: TrackPlan, front: str) -> None:
        path = f"song.tracks[{k}]"
        root, folder, item = t.instrument.load
        self.guard(f"load {t.name}", front)
        with stops(f"load {t.name}"):
            self.L.load_item(path, root, folder or None, item)
            for fx in t.instrument.fx:
                self.L.load_item(path, "audio_effects", None, fx)
            devs = self.L.devices(path)
        want = [t.instrument.device_name, *t.instrument.fx]
        if devs != want:
            raise Stop(f"load {t.name}: devices {devs}, wanted {want}")
        for dev, values in sorted(t.settings.items()):
            with stops(f"set {t.name} device {dev}"):
                self.L.setp(f"{path}.devices[{dev}]", values)

    # ---- samples ---------------------------------------------------------------------------------------------------
    def clips(self, k: int, t: TrackPlan, bpm: float, front: str) -> None:
        """A clip-mode sample on audio track k: the file at its first position, warped or not, transposed, cut to its
        length; then copied back to back for a loop, and the last copy cut. Each write is read back in its own call."""
        sp = t.sample
        path = f"song.tracks[{k}]"
        at0, len0 = sp.clips[0]
        first = f"[c for c in {path}.arrangement_clips if abs(c.start_time - {float(at0)!r}) < 1e-4][0]"
        self.guard(f"sample {t.name}", front)
        self.run(f"t = {path}\nfor c in list(t.arrangement_clips):\n    t.delete_clip(c)\n"
                 f"t.create_audio_clip({str(sp.path)!r}, {float(at0)!r})\nresult = 'ok'")
        got = self.run(f"result = [(c.start_time, c.is_audio_clip, c.file_path) for c in {path}.arrangement_clips]")
        if len(got) != 1 or abs(got[0][0] - at0) > 1e-4 or not got[0][1] or Path(str(got[0][2])).name != sp.path.name:
            raise Stop(f"sample {t.name}: the track has {got}, wanted {sp.path.name} at beat {at0}")

        # warp first: it changes what the markers mean (beats warped, file seconds not), and unwarping moves the start
        # marker to the first transient (hands/scripts/proptest), so the markers are set after it
        warp = f"c.warping = True\nc.warp_mode = {WARP_MODES[sp.warp]}" if sp.warp != "off" else "c.warping = False"
        self.run(f"c = {first}\nc.looping = False\n{warp}\nresult = 'ok'")
        got = self.run(f"c = {first}\nresult = (c.warping, c.warp_mode, c.looping)")
        if bool(got[0]) != (sp.warp != "off") or got[2] or (sp.warp != "off" and got[1] != WARP_MODES[sp.warp]):
            raise Stop(f"sample {t.name}: warping, warp mode, looping are {got}, wanted {sp.warp}")
        if sp.warp != "off":
            self.fit(first, t)
        if sp.transpose:
            self.run(f"c = {first}\nc.pitch_coarse = {int(sp.transpose)}\nresult = 'ok'")

        end = sp.end_marker(len0, bpm) if sp.warp != "off" else min(sp.seconds, sp.end_marker(len0, bpm))
        self.run(f"c = {first}\nc.loop_end = {end!r}\nc.end_marker = {end!r}\nresult = 'ok'")       # the end, then the start
        self.run(f"c = {first}\nc.loop_start = 0.0\nc.start_marker = 0.0\nresult = 'ok'")
        got = self.run(f"c = {first}\nresult = (c.start_time, c.end_time, c.start_marker, c.pitch_coarse)")
        if abs(got[0] - at0) > 1e-4 or abs(got[1] - got[0] - len0) > 0.02 or abs(got[2]) > 1e-4 or got[3] != sp.transpose:
            raise Stop(f"sample {t.name}: the clip is {got}, wanted {at0}+{len0} beats from 0, {sp.transpose} st")

        rest = sp.clips[1:]
        for i in range(0, len(rest), COPIES_PER_CALL):     # the first clip is a whole play whenever copies follow it
            self.run(f"t = {path}\nsrc = {first}\n" + "".join(
                f"t.duplicate_clip_to_arrangement(src, {float(a)!r})\n" for a, _ in rest[i:i + COPIES_PER_CALL]) + "result = 'ok'")
        if rest and rest[-1][1] < sp.natural_beats - 1e-6:
            a, length = rest[-1]
            end = sp.end_marker(length, bpm)
            self.run(f"c = [c for c in {path}.arrangement_clips if abs(c.start_time - {float(a)!r}) < 1e-4][0]\n"
                     f"c.loop_end = {end!r}\nc.end_marker = {end!r}\nresult = 'ok'")
        got = self.run(f"result = sorted((c.start_time, c.end_time) for c in {path}.arrangement_clips)")
        want = [(a, a + n) for a, n in sp.clips]
        if len(got) != len(want) or any(abs(g[0] - w[0]) > 1e-3 or abs(g[1] - w[1]) > 0.02 for g, w in zip(got, want)):
            raise Stop(f"sample {t.name}: clips {got}, wanted {want}")

    def fit(self, first: str, t: TrackPlan) -> None:
        """Warp the whole file evenly onto fit_beats. Live auto-warps a new clip at a tempo it guesses: keep only its
        first marker, add one near the file's end on the even stretch, then move the first onto it too. Read back:
        every marker on the line beat = seconds * fit / length. Live lists a shadow marker last, 1/32 beat after the
        last real one at the tempo before it; it can't be deleted or placed, so it's left out of all of this."""
        sp = t.sample
        slope = sp.fit_beats / sp.seconds
        markers = self.markers(first)
        if not markers:
            raise Stop(f"sample {t.name}: a warped clip with no warp markers")
        drop = [float(b) for _, b in markers[1:]]
        if drop:
            self.run(f"c = {first}\nfor b in {drop!r}:\n    c.remove_warp_marker(b)\nresult = 'ok'")
        got = self.markers(first)
        if len(got) != 1:
            raise Stop(f"sample {t.name}: warp markers {got} after removing all but the first")
        (s0, b0), s1 = got[0], round(max(sp.seconds - 0.005, sp.seconds * 0.99), 6)
        self.run(f"import Live\nc = {first}\nc.add_warp_marker(Live.Clip.WarpMarker({s1!r}, {round(s1 * slope, 6)!r}))\nresult = 'ok'")
        if abs(b0 - s0 * slope) > 1e-6:
            self.run(f"c = {first}\nc.move_warp_marker({float(b0)!r}, {round(s0 * slope - b0, 6)!r})\nresult = 'ok'")
        got = self.markers(first)
        if len(got) < 2 or any(abs(b - s * slope) > 1e-3 for s, b in got) or abs(got[-1][0] - s1) > 1e-3:
            raise Stop(f"sample {t.name}: warp markers {got}, wanted the line beat = {slope:.4f} * seconds")

    def markers(self, first: str) -> list[tuple[float, float]]:
        """A warped clip's warp markers (sample seconds, clip beats), without Live's shadow marker."""
        got = self.run(f"c = {first}\nresult = [(w.sample_time, w.beat_time) for w in c.warp_markers]")
        shadow = len(got) > 1 and abs(got[-1][1] - got[-2][1] - 1 / 32) < 1e-6
        return [tuple(m) for m in (got[:-1] if shadow else got)]

    def simpler(self, k: int, t: TrackPlan, front: str) -> None:
        """A one-shot or sliced sample: Simpler on MIDI track k, holding the file (replace_sample, as in
        hands/scripts/proptest), unwarped, in One-Shot or Slicing mode; slices placed by hand (Manual)."""
        sp = t.sample
        path, dev = f"song.tracks[{k}]", f"song.tracks[{k}].devices[0]"
        self.guard(f"load {t.name}", front)
        with stops(f"load {t.name}"):
            self.L.load_item(path, "instruments", None, "Simpler")
            devs = self.L.devices(path)
        if devs != ["Simpler"]:
            raise Stop(f"load {t.name}: devices {devs}, wanted Simpler")
        self.run(f"{dev}.replace_sample({str(sp.path)!r})\nresult = 'ok'")
        time.sleep(0.5)
        got = self.run(f"d = {dev}\nresult = d.sample.file_path if d.sample else None")
        if not got or Path(str(got)).name != sp.path.name:
            raise Stop(f"load {t.name}: Simpler holds {got}, wanted {sp.path.name}")
        self.run(f"{dev}.playback_mode = {PLAYBACK_MODES[sp.mode]}\nresult = 'ok'")
        self.run(f"{dev}.sample.warping = False\nresult = 'ok'")
        if sp.mode == "slices":
            self.run(f"s = {dev}.sample\ns.slicing_style = {SLICING_MANUAL}\nresult = 'ok'")
            self.run(f"s = {dev}.sample\ns.clear_slices()\nfor f in {[int(f) for f in sp.slices]!r}:\n    s.insert_slice(f)\nresult = 'ok'")
        got = self.run(f"d = {dev}\nresult = (d.playback_mode, d.sample.warping, "
                       f"sorted(int(x) for x in d.sample.slices if x > 0) if d.playback_mode == 2 else [])")
        if [got[0], bool(got[1]), list(got[2])] != [PLAYBACK_MODES[sp.mode], False, sp.slices]:
            raise Stop(f"load {t.name}: Simpler's mode, warping, slices are {got}, wanted {sp.mode}, unwarped, {sp.slices}")

    def notes(self, k: int, t: TrackPlan, beats: float, front: str) -> None:
        path = f"song.tracks[{k}]"
        self.guard(f"notes {t.name}", front)
        self.run(f"t = {path}\nfor c in list(t.arrangement_clips):\n    t.delete_clip(c)\nt.create_midi_clip(0.0, {float(beats)!r})\nresult = 'ok'")
        for i in range(0, len(t.notes), NOTES_PER_CALL):
            chunk = [(int(p), float(s), float(d), float(v)) for p, s, d, v in t.notes[i:i + NOTES_PER_CALL]]
            self.run(f"import Live\nc = {path}.arrangement_clips[0]\n"
                     "c.add_new_notes(tuple(Live.Clip.MidiNoteSpecification(pitch=p, start_time=s, duration=d, velocity=v) "
                     f"for p, s, d, v in {chunk!r}))\nresult = 'ok'")
        got = self.run(f"c = {path}.arrangement_clips[0]\nresult = (len(c.get_notes_extended(0, 128, 0.0, {float(beats)!r})), c.start_time, c.end_time)")
        if got[0] != len(t.notes) or got[1] != 0.0 or got[2] != float(beats):
            raise Stop(f"notes {t.name}: clip has {got}, wanted {len(t.notes)} notes over 0-{beats}")

    def mix(self, plan: Plan, front: str) -> None:
        self.guard("mix", front)
        with stops("mix"):
            for k, t in enumerate(plan.tracks):
                self.L.mixer(f"song.tracks[{k}]", t.volume_db, (t.room_db, t.echo_db), t.pan)
            for r, values in sorted(plan.returns.items()):
                self.L.setp(f"song.return_tracks[{r}].devices[0]", values)
        got = self.run("result = [(round(t.mixer_device.panning.value, 3), len(t.mixer_device.sends)) for t in song.tracks]")
        if [g[0] for g in got] != [round(t.pan, 3) for t in plan.tracks]:
            raise Stop(f"mix: pans are {got}")

    def master_gain(self, plan: Plan, db: float, front: str) -> float:
        """Main's Limiter Input Gain, in dB, read back; answers what Live reads. Live shows it in whole dB from 10 up
        ("12 dB"), and a "12.0 dB" sent there lands on the step below (2026-11-02: 11 dB), so whole dB are sent then;
        a readback within 1 dB is Live's own rounding, not a surprise."""
        self.guard("loudness", front)
        k = plan.master_devices.index("Limiter")
        text = f"{round(db):.0f} dB" if abs(db) >= 10 else f"{float(db):.1f} dB"
        with stops("loudness"):
            self.L.setp(f"song.master_track.devices[{k}]", {"Input Gain": text})
        got = self.run(f"p = [p for p in song.master_track.devices[{k}].parameters if p.name == 'Input Gain'][0]\nresult = p.str_for_value(p.value)")
        read = float(str(got).split()[0])
        if abs(read - db) > 1.0:
            raise Stop(f"loudness: the Limiter's Input Gain reads {got}, wanted {db:.1f} dB")
        return read

    # ---- the render ----------------------------------------------------------------------------------------------
    def export(self, plan: Plan, out: Path, front: str) -> Path:
        from hands import audio
        self.guard("export", front)
        with stops("export"):
            self.L.export(out, 0.0, plan.render_beats, bits=24)
        self.step("check audio")
        seconds = plan.render_beats * 60.0 / plan.bpm
        try:
            audio.check_audio(out, seconds=seconds)
        except Exception as exc:          # silent, wrong length or unreadable: Live's audio engine, most likely
            raise Stop(f"render: {exc}") from None
        return out


SURVEY_BPM = 120.0
SLOT_BEATS = 12.0           # each instrument plays 8 beats, then 4 of silence for its tail


def audition(inst, slot: int) -> list[tuple[int, float, float, int]]:
    """A short phrase in the instrument's range for its role, at velocity 100, starting at its slot: enough to hear it
    load and to compare levels, not music."""
    t0 = slot * SLOT_BEATS
    lo, hi = inst.range
    if inst.role == "drums":            # every pad once, then a plain beat on the first three
        hits = [(lo + k, k * 0.25) for k in range(min(16, hi - lo + 1))]
        hits += [(lo, 4.0), (lo + 2, 5.0), (lo, 6.0), (lo + 2, 7.0)] + [(min(hi, lo + 6), 4.0 + k * 0.5) for k in range(8)]
        return [(p, t0 + t, 0.25, 100) for p, t in hits]
    root = max(lo, min(hi - 7, (lo + hi) // 2 - 6 if inst.role != "bass" else lo + 12))
    if inst.role in ("pad", "texture"):
        return [(min(hi, root + i), t0, 8.0, 100) for i in (0, 4, 7)]
    if inst.role == "keys":
        return [(min(hi, root + i), t0 + b, 0.9, 100) for b in range(8) for i in (0, 4, 7)]
    steps = [0, 2, 4, 7, 4, 2, 0, 7] if inst.role != "bass" else [0, 0, 7, 0, 5, 0, 7, 12]
    return [(min(hi, root + d), t0 + k, 0.9, 100) for k, d in enumerate(steps)]


def survey(client, palette, out: Path, *, only: list[str] | None = None, listen: bool = False,
           render: Path | None = None) -> dict:
    """Load palette instruments into a copy of the template, the way a job does (preset, fx, settings, the device
    check), and record their devices, drum pad names and rack macros (name, value, min, max as Live shows them) for
    the guide (`booth survey`, watched). With `listen`, each also plays a short phrase at 0 dB with Main's chain
    switched off in that copy, and one export to `render` measures each (`lufs`, `peak_db`), so a silent instrument
    shows and trims can be set. `only` surveys some ids and keeps the rest of `out`. Returns what it found."""
    from . import measure as M
    insts = [palette.instruments[i] for i in only] if only else list(palette.instruments.values())
    b = Builder(client)
    front = b.open("survey")
    found = {}
    try:
        tracks = [TrackPlan(name=f"s{k + 1}", instrument=inst, settings={d: dict(v) for d, v in inst.set.items()},
                            notes=audition(inst, k) if listen else [])
                  for k, inst in enumerate(insts)]
        for k, t in enumerate(tracks):
            if k:
                b.run(f"song.create_midi_track(-1)\nsong.tracks[{k}].name = {t.name!r}\nresult = 'ok'")
            b.instrument(k, t, front)           # raises Stop if the devices are not what the palette says
            # a kit preset is often an Instrument Rack around the Drum Rack (SH001's Perc Kitchen Kit): look one level in
            pads = b.run(f"d = song.tracks[{k}].devices[0]\n"
                         "if not d.can_have_drum_pads and d.can_have_chains and d.chains and d.chains[0].devices:\n"
                         "    d = d.chains[0].devices[0]\n"
                         "result = [(p.note, p.name) for p in d.drum_pads if len(p.chains)] if d.can_have_drum_pads else []")
            macros = b.run(f"d = song.tracks[{k}].devices[0]\n"
                           "result = [(p.name, p.str_for_value(p.value), p.str_for_value(p.min), p.str_for_value(p.max)) "
                           "for p in list(d.parameters)[1:17] if not p.name.startswith('Macro ')] if d.can_have_chains else []")
            found[t.instrument.id] = {"devices": b.L.devices(f"song.tracks[{k}]"), "pads": pads, "macros": macros}
            time.sleep(0.2)
        if listen:
            beats = SLOT_BEATS * len(tracks)
            b.guard("survey tempo", front)
            b.run(f"song.tempo = {SURVEY_BPM!r}\nresult = 'ok'")
            for k, t in enumerate(tracks):
                b.notes(k, t, beats, front)
            b.guard("survey mix", front)
            with stops("survey mix"):
                for k, _ in enumerate(tracks):
                    b.L.mixer(f"song.tracks[{k}]", 0.0, (None, None), 0.0)
                for k, _ in enumerate(palette.master_devices):        # the instruments as they are, not as Main makes them
                    b.L.setp(f"song.master_track.devices[{k}]", {"Device On": 0})
            plan = Plan(bpm=SURVEY_BPM, beats=beats, render_beats=beats, tracks=tracks, returns={},
                        master_devices=palette.master_devices, master_set={})
            wav = b.export(plan, render or HOME / "survey" / f"{palette.version}.wav", front)
            beat_s = 60.0 / SURVEY_BPM
            levels = M.levels(wav, [(k * SLOT_BEATS * beat_s, (k + 1) * SLOT_BEATS * beat_s) for k in range(len(tracks))])
            for t, (lufs, peak) in zip(tracks, levels):
                found[t.instrument.id].update(lufs=lufs, peak_db=peak)
    finally:
        b.close("survey")
    old = json.loads(out.read_text()) if out.is_file() and only else {}
    merged = {i: found.get(i, old.get(i)) for i in palette.instruments if i in found or i in old}
    out.write_text(json.dumps(merged, indent=2) + "\n")
    return found


def make_template(client, palette, seed_dir: Path) -> Path:
    """`booth template`, once and watched: File > New Live Set (Live 12-native, with A Reverb and B Delay), saved by
    the Save panel into `seed_dir` (a folder its Where popup reaches), copied into the booth's sets folder, then
    Main's chain from the palette loaded and set, and saved."""
    from hands.live import session, ui
    L = ops(client)
    if ui.menu_enabled("File", "Save Live Set"):
        raise Stop(f"template: {ui.front_title()} has unsaved changes; save it first")
    target = SETS_DIR / f"{TEMPLATE}.als"
    if target.exists():
        raise Stop(f"template: {target} exists already")
    with stops("template"):
        if not ui.menu("File", "New Live Set"):
            raise Stop("template: File > New Live Set stayed disabled")
        for _ in range(40):
            if ui.front_title() == "Untitled":
                break
            time.sleep(0.25)
        else:
            raise Stop(f"template: no new set in front ({ui.windows()})")
        time.sleep(1.0)
        if ui.dialogs():
            raise Stop(f"template: a dialog after New Live Set: {ui.windows()}")
        seed = L.save_as(seed_dir, "booth_seed")
        SETS_DIR.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(seed.parent, SETS_DIR)
        (SETS_DIR / "booth_seed.als").rename(target)
        session.open_set(client, TEMPLATE, save_current=False)
    finish_template(client, palette)
    return target


def finish_template(client, palette) -> None:
    """The template's contents, with booth_template in front: one empty MIDI track p1 (Live won't delete a set's
    last track), Main's chain from the palette, the two returns checked; then saved."""
    from hands.live import session
    L = ops(client)
    b = Builder(client)
    b.guard("template", TEMPLATE)
    with stops("template"):
        b.run("while len(song.tracks) > 1:\n    song.delete_track(len(song.tracks) - 1)\nresult = 'ok'")
        t0 = b.run("t = song.tracks[0]\nresult = (t.has_midi_input, len(t.devices), len(t.arrangement_clips))")
        if t0 != [True, 0, 0]:
            raise Stop(f"template: its last track is not an empty MIDI track: {t0}")
        b.run("song.tracks[0].name = 'p1'\nresult = 'ok'")
        for name in palette.master_devices:
            if name not in L.devices("song.master_track"):
                L.load_item("song.master_track", "audio_effects", None, name)
        devs = L.devices("song.master_track")
        if tuple(devs) != tuple(palette.master_devices):
            raise Stop(f"template: Main has {devs}")
        for k, values in sorted(palette.master_set.items()):
            L.setp(f"song.master_track.devices[{k}]", values)
        rets = b.run("result = [[d.name for d in r.devices] for r in song.return_tracks]")
        for name, r in palette.returns.items():
            if len(rets) <= r.track or rets[r.track][:1] != [r.device]:
                raise Stop(f"template: return {r.track} has {rets}, wanted {r.device} for {name}")
        session.save(TEMPLATE)
