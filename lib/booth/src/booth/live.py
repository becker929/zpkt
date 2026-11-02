"""A Plan into Live: the job's set, its tracks, notes, mixer and returns, then the export. One checked step at a time.

Every LOM call is built here from a Plan: numbers go in through repr(int|float), names are the booth's ("p1") or the
palette's. Each call stays short (notes go in 400 to a call) and is read back in a separate call, since reading
what a call just wrote crashes Live. Before each step `session.check` makes sure no dialog is open and the job's set
is in front; anything else raises Stop.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Callable

from . import PREFIX, SETS_DIR, TEMPLATE
from .compile import Plan, TrackPlan
from .gui import Stop, ops, stops

NOTES_PER_CALL = 400


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
            self.run(f"song.create_midi_track(-1)\nsong.tracks[{k}].name = {t.name!r}\nresult = 'ok'")
        names = self.run("result = [t.name for t in song.tracks]")
        if names != [t.name for t in plan.tracks]:
            raise Stop(f"tracks: Live has {names}")

        for k, t in enumerate(plan.tracks):
            self.instrument(k, t, front)
        for k, t in enumerate(plan.tracks):
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

    def master_gain(self, plan: Plan, db: float, front: str) -> None:
        """Main's Limiter Input Gain, in dB, read back."""
        self.guard("loudness", front)
        k = plan.master_devices.index("Limiter")
        with stops("loudness"):
            self.L.setp(f"song.master_track.devices[{k}]", {"Input Gain": f"{float(db):.1f} dB"})
        got = self.run(f"p = [p for p in song.master_track.devices[{k}].parameters if p.name == 'Input Gain'][0]\nresult = p.str_for_value(p.value)")
        if abs(float(str(got).split()[0]) - db) > 0.5:
            raise Stop(f"loudness: the Limiter's Input Gain reads {got}, wanted {db:.1f} dB")

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


def survey(client, palette, out: Path) -> dict:
    """Load each palette instrument once into the template's copy and record its devices and drum pad names, for
    the guide (`booth palette survey`, watched). Returns {instrument id: {devices, pads}}."""
    b = Builder(client)
    front = b.open("survey")
    found = {}
    try:
        for k, inst in enumerate(palette.instruments.values()):
            if k:
                b.run(f"song.create_midi_track(-1)\nsong.tracks[{k}].name = {('s' + str(k + 1))!r}\nresult = 'ok'")
            b.guard(f"survey {inst.id}", front)
            root, folder, item = inst.load
            with stops(f"survey {inst.id}"):
                b.L.load_item(f"song.tracks[{k}]", root, folder or None, item)
            devs = b.run(f"result = [d.name for d in song.tracks[{k}].devices]")
            # a kit preset is often an Instrument Rack around the Drum Rack (SH001's Perc Kitchen Kit): look one level in
            pads = b.run(f"d = song.tracks[{k}].devices[0]\n"
                         "if not d.can_have_drum_pads and d.can_have_chains and d.chains and d.chains[0].devices:\n"
                         "    d = d.chains[0].devices[0]\n"
                         "result = [(p.note, p.name) for p in d.drum_pads if len(p.chains)] if d.can_have_drum_pads else []")
            found[inst.id] = {"devices": devs, "pads": pads}
            time.sleep(0.2)
    finally:
        b.close("survey")
    out.write_text(__import__("json").dumps(found, indent=2) + "\n")
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
