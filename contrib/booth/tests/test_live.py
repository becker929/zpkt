import pytest

from booth import compile as C
from booth import palette as P
from booth.check import check
from booth.gui import Stop
from booth.live import Builder
from conftest import example


def plan(name="clockwork"):
    r = check(example(name))
    return C.compile(r.score, P.load(r.score.palette))


def test_build_runs_the_generated_lom_code(fake, tmp_path):
    lv, fo = fake
    p = plan()
    b = Builder(lv)
    front = b.open("abc")
    b.build(p, front)
    song = lv.song
    assert song.tempo == 120.0 and [t.name for t in song.tracks] == ["p1", "p2", "p3"]
    assert [len(t.arrangement_clips[0].notes) for t in song.tracks] == [len(t.notes) for t in p.tracks]
    assert ("song.tracks[1]", "audio_effects", None, "Saturator") in fo.loads
    assert ("song.tracks[1].devices[1]", {"Type": "Bass Shaper", "Drive": "9.60 dB", "Output": "-7 dB"}) in fo.sets
    assert [m[0] for m in fo.mixes] == ["song.tracks[0]", "song.tracks[1]", "song.tracks[2]"]
    out = b.export(p, tmp_path / "render.wav", front)
    assert out.exists()


def test_notes_go_in_short_calls(fake):
    lv, fo = fake
    s = example()
    s["patterns"][0]["notes"] = [{"p": 42, "t": i / 8, "d": 0.1, "v": 60} for i in range(32)]
    s["feel"] = {"swing": 0, "humanize_ms": 0, "velocity_jitter": 0, "seed": 0}
    r = check(s)
    p = C.compile(r.score, P.load("2026-11"))
    b = Builder(lv)
    b.build(p, b.open("abc"))
    note_calls = [c for c in lv.calls if "add_new_notes" in c]
    assert len(note_calls) >= 2 and all(len(c) < 40_000 for c in note_calls)


def test_no_score_text_reaches_live(fake):
    lv, fo = fake
    s = example()
    s["title"] = "'); import os; os.system('say hi') #"
    s["key"] = "\"; song.tracks = None"
    r = check(s)
    assert r.ok
    b = Builder(lv)
    b.build(C.compile(r.score, P.load("2026-11")), b.open("abc"))
    assert not any("say hi" in c or "song.tracks = None" in c for c in lv.calls)


def test_wrong_devices_stop(fake, monkeypatch):
    lv, fo = fake
    fo.devices_override = ["Something Else"]
    b = Builder(lv)
    with pytest.raises(Stop, match="load p1"):
        b.build(plan(), b.open("abc"))


def test_a_template_with_tracks_stops(fake, monkeypatch):
    from conftest import Song
    from hands.live import session
    lv, fo = fake

    def open_set(client, name, **k):
        lv.song = Song()
        lv.song.create_midi_track(-1)
    monkeypatch.setattr(session, "open_set", open_set)
    with pytest.raises(Stop, match="not one empty MIDI track"):
        Builder(lv).open("abc")


def test_silent_render_stops(fake, tmp_path):
    lv, fo = fake
    fo.export_silent = True
    p = plan()
    b = Builder(lv)
    front = b.open("abc")
    b.build(p, front)
    with pytest.raises(Stop, match="render"):
        b.export(p, tmp_path / "render.wav", front)


def test_a_guard_failure_is_a_stop(fake, monkeypatch):
    from hands.live import session
    lv, fo = fake

    def guard(client, where, **k):
        session.stop(f"{where}: 1 dialog(s) open in Live")
    monkeypatch.setattr(session, "check", guard)
    with pytest.raises(Stop, match="dialog"):
        Builder(lv).open("abc")


def test_sh001s_helpers_load_and_point_at_the_booth():
    from booth import gui
    L = gui.ops(object())
    for name in ("load_item", "devices", "setp", "mixer", "export", "save_as"):
        assert callable(getattr(L, name))
    assert L.EXPORT_DIR.name == "rummage" and L.LIVE is not None


def test_survey_listens_and_keeps_the_rest(fake, tmp_path):
    import json
    from booth.live import SLOT_BEATS, audition, survey
    lv, fo = fake
    pal = P.load("2026-12")
    out = tmp_path / "s.json"
    out.write_text(json.dumps({"keys.upright": {"devices": ["Childhood Home Piano"], "pads": []}}))
    got = survey(lv, pal, out, only=["bass.sub_mellow", "drums.909"], listen=True, render=tmp_path / "s.wav")
    assert set(got) == {"bass.sub_mellow", "drums.909"}
    assert got["bass.sub_mellow"]["devices"] == ["Sub Mellow", "Saturator"]            # the preset, its fx, its settings
    assert ("song.tracks[0].devices[1]", pal.instruments["bass.sub_mellow"].set[1]) in fo.sets
    assert all(v["lufs"] is not None and v["peak_db"] < 0 for v in got.values())
    assert [s for s in fo.sets if s[0].startswith("song.master_track")] == [
        (f"song.master_track.devices[{k}]", {"Device On": 0}) for k in range(3)]       # Main's chain off in the copy
    assert list(json.loads(out.read_text())) == ["keys.upright", "bass.sub_mellow", "drums.909"]   # palette order
    for k, inst in enumerate(pal.instruments.values()):                                    # every phrase in range, in its slot
        notes = audition(inst, k)
        assert notes and all(inst.range[0] <= p <= inst.range[1] for p, *_ in notes)
        assert all(k * SLOT_BEATS <= t and t + d <= (k + 1) * SLOT_BEATS for _, t, d, _ in notes)
