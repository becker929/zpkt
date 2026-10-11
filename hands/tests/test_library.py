"""hands.library: set facts, the seven step scorers, records, and the inventory, on synthetic sets."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hands.cli import app
from hands.library import facts, inventory, records, score, workflow
from hands.library.score import Export, Project
from synth_set import T, finished_short, write_set

DAY = 86400.0


def project(folder: Path, *sets: Path, exports=()) -> Project:
    p = Project(inventory.track_name(folder), folder,
                sets=sorted((facts.read_set(s) for s in sets), key=lambda s: -s.mtime))
    p.exports = list(exports)
    return p


def export(path: Path, kind: str, **kw) -> Export:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * 64)
    return Export(path, 64, path.stat().st_mtime, kind, **kw)


# --------------------------------------------------------------------------- facts

def test_read_set_facts(tmp_path):
    s = facts.read_set(finished_short(tmp_path))
    assert s.tempo == 160
    names = [t.name for t in s.tracks]
    assert names[:3] == ["kick group", "kick", "rumble"]
    kick = s.tracks[1]
    assert kick.kind == "midi" and kick.group == "10"
    assert [g.name for g in s.groups_of(kick)] == ["kick group"]
    assert kick.rack_samples == ["/lib/sounds/Kicks/k1.wav"]
    assert "DrumGroupDevice" in kick.devices and kick.effects == ["Eq8"]
    assert s.main.devices == ["Eq8", "AudioEffectGroupDevice", "GlueCompressor", "Limiter", "SPAN"]
    assert s.main.effects == ["Eq8", "GlueCompressor", "Limiter", "SPAN"]
    ref = next(t for t in s.tracks if t.name == "ref")
    assert ref.reference and ref not in s.content_tracks()
    assert s.span() == (0, 96) and s.seconds(96) == 36


def test_disabled_clips_off_devices_and_muted_references(tmp_path):
    s = facts.read_set(write_set(tmp_path / "a.als", [
        T("pad", devices=["Eq8", "!Reverb"], clips=[(0, 16, "/s/a.wav")], disabled=[(16, 400)]),
        T("Lethal Storm", muted=True, clips=[(0, 64, "/s/ref.mp3")]),  # an A/B reference without the name
        T("Trash", "group"),
        T("old idea", group=12, clips=[(0, 60, "/s/b.wav")]),
    ]))
    pad, storm, _, parked = s.tracks
    assert pad.devices == ["Eq8"] and len(pad.clips) == 1
    assert storm.reference and parked.reference
    assert s.span() == (0, 16)


def test_live11_master_track(tmp_path):
    path = write_set(tmp_path / "old.als", [T("a", clips=[(0, 4, "/s/a.wav")])], tempo=140, main=["Limiter"])
    import gzip
    xml = gzip.decompress(path.read_bytes()).replace(b"MainTrack", b"MasterTrack")
    path.write_bytes(gzip.compress(xml))
    s = facts.read_set(path)
    assert s.tempo == 140 and s.main.effects == ["Limiter"]


# --------------------------------------------------------------------------- the scorers

def test_a_finished_short_scores_at_the_caps(tmp_path):
    p = project(tmp_path, finished_short(tmp_path),
                exports=[export(tmp_path / "HW900 master.wav", "master", lufs=-12.0, true_peak=-1.6, seconds=36)])
    got = {k: f(p)[0] for k, f in score.SCORERS.items()}
    assert got["collage"] == 100 and got["drums"] == 100
    assert got["arrange"] == 90 and got["kick"] == 80 and got["master"] == 80
    assert got["release"] == 0
    assert 50 <= got["mix"] <= 80


def test_collage_counts_sources_resampling_and_clips(tmp_path):
    p = project(tmp_path, finished_short(tmp_path))
    pct, ev = score.collage(p)
    assert pct == 100
    assert "6 distinct audio files in 8 timeline clips over 24 bars on 4 non-drum audio tracks" in ev[0]
    assert "drone-resampled.wav" in ev[1]
    bare = project(tmp_path, write_set(tmp_path / "d.als", [T("kick", "midi", clips=[(0, 64, None)])]))
    assert score.collage(bare)[0] == 0


def test_collage_from_an_audio_browser_project(tmp_path):
    p = Project("HW011", None, browser={"id": "hw011", "column": "collage", "sounds": [{}] * 15,
                                        "collage": {"regions": [{}, {}, {}]}})
    pct, ev = score.collage(p)
    assert pct == 70 and "column collage, 15 sounds taken, 3 collage regions" in ev[0]
    stored = Project("HW012", None, browser={"id": "hw012", "column": "stored", "sounds": [{}] * 4})
    assert score.collage(stored)[0] == 18


def test_drums_names_and_rack_samples(tmp_path):
    p = project(tmp_path, write_set(tmp_path / "d.als", [
        T("1-Drum Rack", "midi", clips=[(0, 128, None)],
          rack_samples=["/s/VEC2 Bassdrums/VEC2 Clubby Kicks/k.wav", "/s/VEC1 Cymbals/VEC1 Open HH/oh.wav"]),
    ]))
    pct, ev = score.drums(p)
    assert pct == 30 + 25 + 15  # kick and hats from the rack's samples, placed over 32 bars; no rumble, no perc
    assert "rumble: none found" in ev
    pct, ev = score.kick(p)
    assert pct == 10 and "shares a drum rack" in ev[0]  # no dedicated kick track


@pytest.mark.parametrize("bars, sections, want", [
    (2, 1, 20),     # a loop
    (24, 1, 35),    # Short length but one section
    (24, 3, 90),    # 36 s at 160 BPM, three sections: Short length
    (40, 3, 75),    # 60 s: near Short length
    (96, 3, 60),    # 144 s: longer than a Short
    (16, 3, 40),    # 24 s: shorter than a Short
])
def test_arrange_bands(tmp_path, bars, sections, want):
    beats = bars * 4
    step = beats / sections
    tracks = [T(f"t{i}", clips=[(i * step, (i + 1) * step, f"/s/{i}.wav")]) for i in range(sections)]
    s = facts.read_set(write_set(tmp_path / "a.als", tracks))
    got, line = score.arrange_one(s)
    assert got == want, line


def test_arrange_takes_the_best_set_and_locators_count_as_sections(tmp_path):
    full = write_set(tmp_path / "x_full.als", [T("a", clips=[(0, 640, "/s/a.wav")])],
                     locators=[(0, "INTRO"), (128, "BREAK"), (256, "DROP")], mtime=2 * DAY)
    cut = write_set(tmp_path / "x_short.als", [T("a", clips=[(0, 32, "/s/a.wav")]), T("b", clips=[(32, 64, "/s/b.wav")]),
                                               T("c", clips=[(64, 96, "/s/c.wav")])], mtime=1 * DAY)
    s = facts.read_set(full)
    assert score.sections(s) == 3  # one clip, but three named locators
    p = project(tmp_path, full, cut)
    pct, ev = score.arrange(p)
    assert pct == 90 and ev[0].startswith("x_short.als") and ev[1].startswith("newest set: x_full.als")


def test_mix_needs_sends_into_a_return_with_devices(tmp_path):
    base = [T("a", clips=[(0, 64, "/s/a.wav")], sends=[0.5]), T("Rev", "return")]
    p = project(tmp_path, write_set(tmp_path / "m.als", base))
    assert "no send effects in use" in score.mix(p)[1]
    base[1] = T("Rev", "return", devices=["Reverb"])
    p = project(tmp_path, write_set(tmp_path / "m2.als", base))
    pct, ev = score.mix(p)
    assert pct == 15 and "1 returns with devices, fed by 1 tracks" in ev
    p.exports = [export(tmp_path / "x mix.wav", "mix")]
    assert score.mix(p)[0] == 30


def test_master_measured_outside_the_target_gets_no_points(tmp_path):
    p = project(tmp_path, finished_short(tmp_path),
                exports=[export(tmp_path / "HW900 master.wav", "master", lufs=-8.0, true_peak=0.2, seconds=36)])
    pct, ev = score.master(p)
    assert pct == 70 and "(target -14 to -11 LUFS" in ev[-1]


def test_release_candidates(tmp_path):
    p = Project("x", tmp_path, exports=[export(tmp_path / "x final.wav", "release", seconds=40),
                                        export(tmp_path / "x.mp4", "release")])
    pct, ev = score.release(p)
    assert pct == 60 and "one is Short length" in ev
    assert score.release(Project("y", tmp_path))[0] == 0


def test_export_kinds():
    k = inventory.export_kind
    assert k(Path("HW002 final.wav")) == "release" and k(Path("HW002.mp4")) == "release"
    assert k(Path("HW002 master -11.wav")) == "master" and k(Path("HW002 premaster.wav")) == "mix"
    assert k(Path("2026-10-06-hw002-b43-04-short-splash-only-30s.mp3")) == "render"
    assert k(Path("HW002_16_kick-scoop-37.wav")) == "render"


# --------------------------------------------------------------------------- records and the inventory

def test_lowest_incomplete():
    pc = dict.fromkeys(workflow.KEYS, 100)
    assert workflow.lowest_incomplete(pc) is None
    pc.update(arrange=90, mix=10)
    assert workflow.lowest_incomplete(pc) == "arrange"


def test_records_central_and_project_file(tmp_path):
    central = tmp_path / "records.toml"
    central.write_text('[HW1]\nnote = "the first"\n[HW1.mix]\npercent = 40\nby = "docs"\ndate = 2026-10-09\n'
                       '[HW1.kick]\npercent = 70\n')
    recs, notes, _ = records.load_central(central)
    assert recs["hw1"]["mix"].by == "docs" and recs["hw1"]["mix"].date == "2026-10-09"
    assert recs["hw1"]["kick"].by == "agent" and notes["hw1"] == "the first"
    (tmp_path / "HW1").mkdir()
    (tmp_path / "HW1" / records.PROJECT_FILE).write_text('[kick]\npercent = 100\nnote = "picked"\n')
    own, _ = records.load_project(tmp_path / "HW1")
    assert own["kick"].by == "anthony" and own["kick"].percent == 100
    central.write_text('[HW1.sound_design]\npercent = 1\n')
    with pytest.raises(ValueError, match="unknown step 'sound_design'"):
        records.load_central(central)
    assert records.load_central(tmp_path / "missing.toml") == ({}, {}, {})
    central.write_text('[HW1]\nstatus = "parked"\n')
    with pytest.raises(ValueError, match="unknown status 'parked'"):
        records.load_central(central)


def build_library(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "current projects"
    finished_short(root / "HW900", mtime=10 * DAY)
    write_set(root / "HW900" / "debug_1.als", [T("a")], mtime=20 * DAY)  # newest, but a debug set
    (root / "HW900" / "HW900 final master.wav").write_bytes(b"\0" * 64)
    (root / "HW900" / "field recording.wav").write_bytes(b"\0" * 64)  # not named like an export
    write_set(root / "HW901 Project" / "HW901.als", [
        T("kick", "midi", clips=[(0, 16, None)]),
        T("pad", clips=[(0, 16, str(root / "HW900" / "Samples" / "Imported" / "pad.wav"))]),
    ], mtime=5 * DAY)
    (root / "notes").mkdir()
    (root / "notes" / "todo.txt").write_text("x")
    records_file = tmp_path / "records.toml"
    records_file.write_text('[HW900]\nnote = "the Short"\n[HW900.release]\npercent = 100\nby = "anthony"\n'
                            'url = "https://youtube.com/shorts/x"\n[HW900.mix]\npercent = 100\n'
                            '[HW900.kick]\npercent = 100\n[HW900.arrange]\npercent = 100\n')
    return root, records_file


def test_inventory_end_to_end(tmp_path):
    root, records_file = build_library(tmp_path)
    renders = tmp_path / "renders"
    (renders / "sub").mkdir(parents=True)
    (renders / "sub" / "hw901_mix_v2.wav").write_bytes(b"\0" * 64)
    (renders / "hw9010 other.wav").write_bytes(b"\0" * 64)  # another track's id
    browser = tmp_path / "ab"
    browser.mkdir()
    (browser / "hw950.json").write_text(json.dumps({"id": "hw950", "name": "HW950", "column": "stored",
                                                     "sounds": [{}, {}], "abandoned": None}))
    measured = []

    def fake_measure(path):
        measured.append(path.name)
        return {"lufs": -12.0, "true_peak": -1.5, "seconds": 36.0}

    inv = inventory.inventory([root], exports=[renders], records_file=records_file, browser=browser,
                              measure=fake_measure)
    by = {t.track: t for t in inv.tracks}
    # HW900 is furthest; HW950 and HW901 both stop at collage, HW950's (14 %) is further than HW901's (12 %)
    assert [t.track for t in inv.tracks] == ["HW900", "HW950", "HW901"]
    hw900 = by["HW900"]
    assert hw900.set == "HW900_kick-final.als" and hw900.sets == 1
    assert hw900.lowest_incomplete == "master"  # records lift III-V and VII; VI stays at its 80 % cap
    steps = {s.step: s for s in hw900.steps}
    assert steps["master"].percent == 80 and steps["master"].record is None
    assert steps["release"].record.url.endswith("/x") and steps["release"].heuristic == 60
    assert steps["release"].evidence[0].startswith("record (anthony): no note")
    assert measured == ["HW900 final master.wav"]
    assert hw900.notes == ["the Short"]
    hw901 = by["HW901"]
    assert any("HW900: 1" in n for n in hw901.notes)
    assert "1 renders, newest hw901_mix_v2.wav" in {s.step: s for s in hw901.steps}["mix"].evidence
    assert by["HW950"].lowest_incomplete == "collage" and by["HW950"].folder is None
    assert any("debug_1.als" in s for s in inv.skipped) and any("notes: no Live set" in s for s in inv.skipped)
    md = inventory.markdown(inv)
    assert "| HW900 | VI. master | 100 | 100 | 100* | 100* | 100* | 80 | 100* |" in md


def test_project_file_beats_the_central_records(tmp_path):
    root, records_file = build_library(tmp_path)
    (root / "HW900" / records.PROJECT_FILE).write_text('[master]\npercent = 100\n[release]\npercent = 50\n')
    inv = inventory.inventory([root], records_file=records_file, browser=None)
    hw900 = next(t for t in inv.tracks if t.track == "HW900")
    assert hw900.lowest_incomplete == "release" and hw900.steps[-1].record.by == "anthony"


def test_a_canceled_track_leaves_the_inventory(tmp_path):
    root, records_file = build_library(tmp_path)
    records_file.write_text(records_file.read_text() + '[HW901]\nstatus = "canceled"\nnote = "a copy of HW900"\n')
    inv = inventory.inventory([root], records_file=records_file, browser=None)
    assert [t.track for t in inv.tracks] == ["HW900"]
    assert "HW901: canceled (a copy of HW900)" in inv.skipped
    # Anthony's own file in the project folder says so too, and wins.
    records_file.write_text(records_file.read_text().replace('status = "canceled"', ''))
    (root / "HW901 Project" / records.PROJECT_FILE).write_text('status = "canceled"\n')
    inv = inventory.inventory([root], records_file=records_file, browser=None)
    assert [t.track for t in inv.tracks] == ["HW900"]

def test_inventory_is_read_only(tmp_path):
    root, records_file = build_library(tmp_path)
    before = {p: (p.stat().st_mtime, p.stat().st_size) for p in root.rglob("*")}
    inventory.inventory([root], records_file=records_file, browser=None)
    assert {p: (p.stat().st_mtime, p.stat().st_size) for p in root.rglob("*")} == before


def test_cli_json_and_table(tmp_path, monkeypatch):
    root, records_file = build_library(tmp_path)
    monkeypatch.setenv("ZPKT_LIBRARY_DIR", str(root))
    from hands import config
    config.rig.cache_clear()
    runner = CliRunner()
    res = runner.invoke(app, ["library", "inventory", "--json", "--records", str(records_file),
                              "--browser", str(tmp_path / "none")])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["roots"] == [str(root)] and data["tracks"][0]["track"] == "HW900"
    res = runner.invoke(app, ["library", "inventory", "--root", str(root), "--records", str(records_file),
                              "--browser", str(tmp_path / "none")])
    assert res.exit_code == 0 and "HW901" in res.output and "VI. master" in res.output


def test_measure_mlab_is_none_without_uv(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert inventory.measure_mlab(tmp_path / "x.wav") is None
    assert os.environ["PATH"] == str(tmp_path)
