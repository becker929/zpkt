"""Samples: the upload's checks, scores that play them, their plan, and the LOM code that places them (in the fake)."""

import shutil
import subprocess

import numpy as np
import pytest
import soundfile as sf

from booth import compile as C
from booth import palette as P
from booth import samples as S
from booth.check import check
from booth.gui import Stop
from booth.live import Builder
from conftest import example, make_sample
from test_server import client  # noqa: F401  - the API fixture

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg (the booth Mac has it; CI may not)")


def codes(raw, **k):
    return [e["code"] for e in check(raw, **k).errors]


def with_sample(sample: dict, *, part: str = "found", replace: int | None = None, **fields) -> dict:
    """clockwork (16 bars, 120 BPM: 64 beats) with a sample part added, or put in place of parts[replace]."""
    s = example()
    p = {"id": part, "sample": {"id": sample["sample"], **fields}, "gain_db": -3}
    if replace is None:
        s["parts"].append(p)
    else:
        old = s["parts"][replace]["id"]
        s["parts"][replace] = {**p, "id": old}
        if fields.get("mode", "clip") == "clip":
            s["patterns"] = [x for x in s["patterns"] if x["part"] != old]
            for sec in s["song"]:
                sec["play"] = [x for x in sec["play"] if x["part"] != old]
    return s


def plan_of(raw):
    r = check(raw)
    assert r.ok, r.errors
    return C.compile(r.score, P.load(r.score.palette))


# ---- the file -------------------------------------------------------------------------------------------------------
def test_sniff():
    assert S.sniff(b"RIFF\x00\x00\x00\x00WAVEfmt ") == "wav"
    assert S.sniff(b"FORM\x00\x00\x00\x00AIFFCOMM") == "aiff" and S.sniff(b"FORM\x00\x00\x00\x00AIFC") == "aiff"
    assert S.sniff(b"fLaC\x00\x00\x00\x22") == "flac"
    assert S.sniff(b"ID3\x04\x00") == "mp3" and S.sniff(b"\xff\xfb\x90\x00") == "mp3"
    assert S.sniff(b"\xff\xf1\x50\x80") is None                      # AAC's ADTS has the same sync word
    for other in (b"#EXTM3U\nhttp://x/a.ts", b"\x00\x00\x00\x20ftypM4A ", b"OggS\x00", b"RIFF\x00\x00\x00\x00AVI ", b""):
        assert S.sniff(other) is None


def wav_bytes(tmp_path, seconds=1.0, sr=48000, channels=1, level=0.3, name="in.wav") -> bytes:
    t = np.arange(int(seconds * sr)) / sr
    y = level * np.sin(2 * np.pi * 220 * t) * (t % 0.5 < 0.2)
    sf.write(tmp_path / name, np.stack([y] * channels, 1), sr)
    return (tmp_path / name).read_bytes()


@needs_ffmpeg
def test_an_upload_is_converted_kept_by_its_hash_and_measured(tmp_path):
    data = wav_bytes(tmp_path, seconds=1.5, sr=48000, channels=1)
    meta, new = S.add(data)
    assert new and S.ID.fullmatch(meta["sample"]) and meta["format"] == "wav"
    info = sf.info(str(S.path(meta["sample"])))
    assert info.samplerate == S.SAMPLE_RATE and info.channels == 1 and info.subtype == "PCM_24"
    assert abs(meta["seconds"] - 1.5) < 0.01 and meta["peak_db"] < 0 and meta["lufs"] < 0
    assert meta["onsets_s"][0] == 0.0 and any(abs(t - 0.5) < 0.03 for t in meta["onsets_s"])   # the tone's bursts
    assert meta["trim_db"] == round(min(12.0, max(-30.0, S.REF_LUFS - meta["lufs"])), 1)
    again, new = S.add(data)
    assert not new and again == meta
    assert not list(S.DIR.glob(".in-*"))                             # nothing left half-made


@needs_ffmpeg
def test_mp3_and_aiff_and_flac_are_taken(tmp_path):
    wav_bytes(tmp_path, seconds=1.0, sr=44100, channels=2)
    for ext in ("mp3", "aiff", "flac"):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp_path / "in.wav"), str(tmp_path / f"in.{ext}")], check=True)
        meta, _ = S.add((tmp_path / f"in.{ext}").read_bytes())
        assert meta["format"] == ext and meta["channels"] == 2 and 0.9 < meta["seconds"] < 1.2


@needs_ffmpeg
def test_uploads_it_refuses(tmp_path):
    def code(data):
        with pytest.raises(S.SampleError) as e:
            S.add(data)
        return e.value.code, e.value.status
    assert code(b"x" * (S.MAX_BYTES + 1)) == ("too_large", 413)
    assert code(b"#EXTM3U\n#EXTINF:1,\nfile:///etc/passwd\n") == ("bad_format", 415)
    assert code(b"RIFF\x10\x00\x00\x00WAVEjunkjunkjunk") == ("unreadable", 400)
    assert code(wav_bytes(tmp_path, seconds=1.0, level=0.0, name="silent.wav")) == ("silent", 400)
    assert code(wav_bytes(tmp_path, seconds=0.02, name="blip.wav")) == ("too_short", 400)
    long = tmp_path / "long.wav"
    sf.write(long, np.full((int(61 * 8000), 1), 0.1), 8000)
    assert code(long.read_bytes()) == ("too_long", 400)
    assert S.info("0" * 16) is None and S.info("../booth.db") is None


# ---- the score ------------------------------------------------------------------------------------------------------
def test_a_clip_part_checks_and_is_refused_where_it_should_be():
    smp = make_sample(4.0)
    assert check(with_sample(smp, start_beat=16, warp="beats", loop=True)).ok
    assert "unknown_sample" in codes(with_sample({"sample": "0123456789abcdef"}))
    assert codes(with_sample(smp), samples=[]) == ["samples_off"]
    assert codes(with_sample(smp, mode="one_shot"), samples=["clip"]) == ["samples_off"]
    assert check(with_sample(smp), samples=["clip"]).ok
    both = with_sample(smp)
    both["parts"][-1]["instrument"] = "keys.upright"
    assert "part_source" in codes(both)
    neither = with_sample(smp)
    del neither["parts"][-1]["sample"]
    assert "part_source" in codes(neither)
    s = with_sample(smp)
    s["song"][0]["play"].append({"part": "found", "pattern": "chords"})
    assert "clip_part_pattern" in codes(s)
    s = with_sample(smp)
    s["patterns"].append({"id": "hits", "part": "found", "bars": 1, "notes": [{"p": 60, "t": 0, "d": 1, "v": 100}]})
    assert "clip_part_pattern" in codes(s)
    assert "sample_after_end" in codes(with_sample(smp, start_beat=64))
    assert "sample_field_mode" in codes(with_sample(smp, fit_beats=8))           # fit_beats needs warp
    assert "schema" in codes(with_sample(smp, path="/etc/passwd"))                # no paths, ever
    assert "schema" in codes(with_sample({"sample": "../../booth.db"}))
    r = check(with_sample(smp))
    assert r.ok and not [w for w in r.warnings if w["code"] == "unused_part"] and r.estimate["clips"] == 1


def test_a_score_of_samples_alone_is_music():
    smp = make_sample(2.0)
    s = example()
    s["parts"] = [{"id": "loop", "sample": {"id": smp["sample"], "warp": "beats", "loop": True}}]
    s["patterns"], s["song"] = [], [{"bars": 8, "play": []}]
    r = check(s)
    assert r.ok and r.estimate["notes"] == 0 and r.estimate["clips"] == 8 and not r.warnings, r.errors
    s["parts"][0]["sample"]["start_beat"] = 31.5
    s["parts"][0]["sample"]["loop"] = False
    assert check(s).ok
    s["patterns"] = [{"id": "rest", "part": "loop", "bars": 1, "notes": []}]
    assert "clip_part_pattern" in codes(s)
    s = example()
    s["patterns"] = []
    assert "unknown_pattern" in codes(s)                           # instruments still need their patterns
    s = with_sample(smp, replace=0, warp="beats", loop=True)       # in place of the drums
    r = check(s)
    assert r.ok, r.errors


def test_too_many_loop_copies():
    smp = make_sample(0.2, hits=1)
    assert "too_many_clips" in codes(with_sample(smp, warp="beats", fit_beats=0.5, loop=True))   # 128 copies
    assert check(with_sample(smp, warp="beats", fit_beats=1, loop=True)).ok                      # 64


def test_one_shot_and_slices_check():
    smp = make_sample(2.0)
    hits = {"id": "hits", "part": "found", "bars": 1, "notes": [{"p": 60, "t": 0, "d": 0.5, "v": 100}]}

    def played(**fields):
        s = with_sample(smp, **fields)
        s["patterns"].append(hits)
        s["song"][1]["play"].append({"part": "found", "pattern": "hits"})
        return s
    assert check(played(mode="one_shot")).ok
    assert "sample_field_mode" in codes(played(mode="one_shot", start_beat=4))
    assert "sample_field_mode" in codes(played(mode="one_shot", slices=[0, 0.5]))
    ok = played(mode="one_shot", start_beat=0, loop=False, warp="off", transpose=0, slices=[])   # every default sent
    assert check(ok).ok
    s = played(mode="slices", slices=[0, 0.5, 1.0, 1.5])
    assert "pitch_out_of_range" in codes(s)                         # 60 is past the fourth slice (36-39)
    s["patterns"][-1]["notes"][0]["p"] = 39
    assert check(s).ok
    for bad in ([0.5, 1.0], [0, 1.0, 0.5], [0, 2.5], [0]):
        assert "bad_slices" in codes(played(mode="slices", slices=bad))


# ---- the plan -------------------------------------------------------------------------------------------------------
def test_a_warped_loop_fits_whole_bars_and_is_cut_at_the_song_end():
    smp = make_sample(3.7)                                       # 7.4 beats at 120 BPM: two bars once fitted
    p = plan_of(with_sample(smp, start_beat=36, warp="complex", loop=True))
    t = p.tracks[-1]
    assert t.kind == "audio" and t.name == "p4" and t.notes == []
    sp = t.sample
    assert sp.fit_beats == 8.0 and sp.natural_beats == 8.0 and sp.path == S.DIR / f"{smp['sample']}.wav"
    assert sp.clips == [(36.0, 8.0), (44.0, 8.0), (52.0, 8.0), (60.0, 4.0)]         # the last copy cut at beat 64
    assert t.volume_db == round(min(6.0, C.HEADROOM_DB + smp["trim_db"] - 3), 2)
    assert sp.end_marker(4.0, 120) == 4.0


def test_an_unwarped_clip_plays_its_own_length_and_a_transpose_changes_it():
    smp = make_sample(3.0)
    sp = plan_of(with_sample(smp, start_beat=2)).tracks[-1].sample
    assert sp.fit_beats is None and sp.clips == [(2.0, 6.0)]
    sp = plan_of(with_sample(smp, start_beat=2, transpose=12)).tracks[-1].sample
    assert sp.clips == [(2.0, 3.0)]                               # an octave up: twice as fast
    assert sp.end_marker(3.0, 120) == pytest.approx(3.0)          # 3 beats at 120 BPM, twice as fast: 3 s of file
    sp = plan_of(with_sample(smp, start_beat=0, length_beats=5, loop=True)).tracks[-1].sample
    assert sp.clips == [(0.0, 5.0)] and sp.end_marker(5.0, 120) == 2.5
    sp = plan_of(with_sample(smp, warp="beats", fit_beats=6)).tracks[-1].sample
    assert sp.clips == [(0.0, 6.0)]


def test_slices_become_frames():
    smp = make_sample(2.0)
    s = with_sample(smp, mode="slices", slices=[0, 0.5, 1.25])
    s["patterns"].append({"id": "hits", "part": "found", "bars": 1, "notes": [{"p": 38, "t": 0, "d": 0.5, "v": 100}]})
    s["song"][1]["play"].append({"part": "found", "pattern": "hits"})
    t = plan_of(s).tracks[-1]
    assert t.kind == "midi" and t.sample.slices == [22050, 55125] and t.range == (36, 38) and t.notes


# ---- in Live (the fake) ---------------------------------------------------------------------------------------------
def build(fake, raw):
    lv, fo = fake
    p = plan_of(raw)
    b = Builder(lv)
    b.build(p, b.open("abc"))
    return lv.song, p


def test_a_warped_loop_is_placed_fitted_and_copied(fake):
    smp = make_sample(3.7)
    song, p = build(fake, with_sample(smp, start_beat=36, warp="complex", loop=True))
    tr = song.tracks[3]
    assert tr.name == "p4" and not tr.has_midi_input
    clips = sorted(tr.arrangement_clips, key=lambda c: c.start_time)
    assert [(c.start_time, round(c.end_time, 4)) for c in clips] == [(36.0, 44.0), (44.0, 52.0), (52.0, 60.0), (60.0, 64.0)]
    c = clips[0]
    assert c.warping and c.warp_mode == 4 and not c.looping and c.start_marker == 0.0
    slope = 8.0 / smp["seconds"]
    assert all(abs(m.beat_time - m.sample_time * slope) < 1e-3 for m in c.warp_markers) and len(c.warp_markers) == 2
    assert all(len(t.arrangement_clips) == 1 for t in song.tracks[:3])          # the instruments' MIDI clips as before


def test_an_unwarped_transposed_clip_first_in_the_score_takes_p1s_place(fake):
    smp = make_sample(3.0)
    song, p = build(fake, with_sample(smp, replace=0, start_beat=2, transpose=-12))
    assert [(t.name, t.has_midi_input) for t in song.tracks] == [("p1", False), ("p2", True), ("p3", True)]
    (c,) = song.tracks[0].arrangement_clips
    assert not c.warping and c.pitch_coarse == -12 and c.start_marker == 0.0        # the transient's offset undone
    assert (c.start_time, round(c.end_time, 4)) == (2.0, 14.0)                      # an octave down: 12 beats
    lv, _ = fake
    assert not any("/etc" in call for call in lv.calls)
    assert any(f"create_audio_clip({str(S.path(smp['sample']))!r}, 2.0)" in call for call in lv.calls)


def test_a_wrong_clip_stops(fake, monkeypatch):
    from conftest import AudioClip
    smp = make_sample(3.0)
    monkeypatch.setattr(AudioClip, "GUESS_BPM", 0.0)          # Live keeps no markers: fit can't work, so it stops
    with pytest.raises(Stop, match="sample p4"):
        build(fake, with_sample(smp, warp="beats"))


def test_one_shot_and_slices_load_a_simpler(fake):
    lv, fo = fake
    smp = make_sample(2.0)
    s = with_sample(smp, mode="slices", slices=[0, 0.5, 1.0, 1.5])
    s["patterns"].append({"id": "chop", "part": "found", "bars": 1,
                          "notes": [{"p": 36 + k % 4, "t": k * 0.5, "d": 0.5, "v": 100} for k in range(8)]})
    s["song"][3]["play"].append({"part": "found", "pattern": "chop"})
    song, p = build(fake, s)
    d = song.tracks[3].devices[0]
    assert ("song.tracks[3]", "instruments", None, "Simpler") in fo.loads
    assert d.playback_mode == 2 and not d.sample.warping and d.sample.slicing_style == 3
    assert d.sample.slices == [0, 22050, 44100, 66150] and d.sample.file_path.endswith(f"{smp['sample']}.wav")
    assert len(song.tracks[3].arrangement_clips[0].notes) == len(p.tracks[3].notes) == 8 * 8
    s = with_sample(smp, mode="one_shot")
    s["patterns"].append({"id": "hit", "part": "found", "bars": 1, "notes": [{"p": 60, "t": 0, "d": 1, "v": 100}]})
    s["song"][0]["play"].append({"part": "found", "pattern": "hit"})
    song, _ = build(fake, s)
    assert song.tracks[3].devices[0].playback_mode == 1


def test_a_simpler_that_doesnt_take_the_sample_stops(fake, monkeypatch):
    from conftest import Simpler
    monkeypatch.setattr(Simpler, "replace_sample", lambda self, path: None)
    smp = make_sample(2.0)
    s = with_sample(smp, mode="one_shot")
    s["patterns"].append({"id": "hit", "part": "found", "bars": 1, "notes": [{"p": 60, "t": 0, "d": 1, "v": 100}]})
    s["song"][0]["play"].append({"part": "found", "pattern": "hit"})
    with pytest.raises(Stop, match="Simpler holds None"):
        build(fake, s)


def test_a_job_with_a_sample_runs_to_done_and_draws_it(tmp_path, fake):
    from booth import video
    from test_runner import Rig
    smp = make_sample(3.7)
    raw = with_sample(smp, start_beat=4, warp="beats", loop=True)
    r = Rig(tmp_path, fake)
    job, _ = r.jobs.add("at://s/1#v1", check(raw).score.model_dump(), {})
    r.runner.tick()
    assert r.jobs.get(job["id"])["state"] == "done", r.jobs.get(job["id"])["error"]
    p = plan_of(raw)
    video.roll(p, "t", "c", (540, 960), tmp_path / "still.jpg")
    assert (tmp_path / "still.jpg").stat().st_size > 0


# ---- the API --------------------------------------------------------------------------------------------------------
async def test_the_guide_mentions_samples_only_when_the_booth_takes_them(client):
    from test_server import AUTH
    g = await (await client.get("/v1/guide", headers=AUTH)).json()
    assert "samples" not in g and "sample" not in g["rules"].lower()
    client.rig.settings.samples = ["clip"]
    g = await (await client.get("/v1/guide", headers=AUTH)).json()
    assert g["samples"]["modes"] == ["clip"] and g["samples"]["upload"]["bytes"] == S.MAX_BYTES
    assert 'mode "clip"' in g["rules"] and "one_shot" not in g["rules"] and g["limits"]["sample_clips"] == 64
    client.rig.settings.samples = ["slices", "clip", "one_shot"]
    g = await (await client.get("/v1/guide", headers=AUTH)).json()
    assert g["samples"]["modes"] == ["clip", "one_shot", "slices"] and 'mode "slices"' in g["rules"]
    assert "Sample" in g["schema"]["$defs"]


async def test_check_and_jobs_follow_the_booths_sample_modes(client):
    from test_server import AUTH
    raw = with_sample(make_sample(2.0), warp="beats")
    res = await (await client.post("/v1/check", json={"score": raw}, headers=AUTH)).json()
    assert not res["ok"] and res["errors"][0]["code"] == "samples_off"
    client.rig.runner.open()
    r = await client.post("/v1/jobs", json={"key": "k", "score": raw}, headers=AUTH)
    assert r.status == 400
    client.rig.settings.samples = ["clip"]
    assert (await (await client.post("/v1/check", json={"score": raw}, headers=AUTH)).json())["ok"]
    r = await client.post("/v1/jobs", json={"key": "k", "score": raw}, headers=AUTH)
    assert r.status == 202
    client.rig.runner.tick()
    done = await (await client.get(f"/v1/jobs/{(await r.json())['job']}", headers=AUTH)).json()
    assert done["state"] == "done", done["error"]


@needs_ffmpeg
async def test_upload(client, tmp_path):
    from test_server import AUTH
    data = wav_bytes(tmp_path, seconds=1.0)
    assert (await client.post("/v1/samples", data=data)).status == 401
    r = await client.post("/v1/samples", data=data, headers=AUTH)
    assert r.status == 403 and (await r.json())["error"] == "samples_off"
    client.rig.settings.samples = ["clip"]
    r = await client.post("/v1/samples", data=data, headers={**AUTH, "Content-Type": "audio/wav"})
    assert r.status == 201
    got = await r.json()
    assert set(got) == {"sample", "seconds", "channels", "sample_rate", "peak_db", "lufs", "onsets_s", "format"}
    assert (await client.post("/v1/samples", data=data, headers=AUTH)).status == 200
    assert await (await client.get(f"/v1/samples/{got['sample']}", headers=AUTH)).json() == got
    assert (await client.get("/v1/samples/0123456789abcdef", headers=AUTH)).status == 404
    assert (await client.get("/v1/samples/..%2Fbooth.db", headers=AUTH)).status == 404
    r = await client.post("/v1/samples", data=b"OggS" + b"\0" * 100, headers=AUTH)
    assert r.status == 415 and (await r.json())["error"] == "bad_format"
    r = await client.post("/v1/samples", data=b"RIFF" + b"\0" * (S.MAX_BYTES + 10), headers=AUTH)
    assert r.status == 413 and (await r.json())["error"] == "too_large"       # past the app's own 1 MB body limit too
    assert (await client.post("/v1/samples", data=b"", headers=AUTH)).status == 400
