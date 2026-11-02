from booth import compile as C
from booth import palette as P
from booth.check import check
from conftest import example


def plan(raw):
    r = check(raw)
    assert r.ok, r.errors
    return C.compile(r.score, P.load(r.score.palette))


def test_patterns_repeat_and_are_cut_at_sections():
    s = example()
    s["feel"] = {"swing": 0, "humanize_ms": 0, "velocity_jitter": 0, "seed": 0}
    p = plan(s)
    drums = p.tracks[0]
    # 4 bars kick only (4 a bar), 3 bars beat (14 a bar), 1 bar fill (9), 8 bars beat
    assert len(drums.notes) == 4 * 4 + 3 * 14 + 9 + 8 * 14
    assert all(0 <= n[1] < p.beats for t in p.tracks for n in t.notes)
    keys = p.tracks[2]
    assert max(n[1] + n[2] for n in keys.notes) <= p.beats
    assert p.render_beats == p.beats + 4


def test_names_are_the_booths():
    p = plan(example())
    assert [t.name for t in p.tracks] == ["p1", "p2", "p3"]


def test_feel_is_seeded():
    a, b = plan(example()), plan(example())
    assert a.tracks[0].notes == b.tracks[0].notes
    s = example()
    s["feel"]["seed"] = 8
    assert plan(s).tracks[0].notes != a.tracks[0].notes


def test_swing_moves_off_beat_sixteenths():
    s = example()
    s["feel"] = {"swing": 0.4, "humanize_ms": 0, "velocity_jitter": 0, "seed": 0}
    s["patterns"][0]["notes"] = [{"p": 42, "t": 0.25, "d": 0.1, "v": 80}, {"p": 42, "t": 0.5, "d": 0.1, "v": 80}]
    starts = [n[1] for n in plan(s).tracks[0].notes if n[0] == 42][:2]
    assert starts == [16.35, 16.5]     # the beat first plays in section 2, bar 5


def test_mixer_and_macros():
    p = plan(example())
    bass = p.tracks[1]
    assert bass.room_db is None and p.tracks[0].room_db == round(-36 + 30 * 0.15, 2)
    assert bass.settings[1]["Drive"] == "9.60 dB"         # 0.6 of 0-16 dB
    assert bass.settings[1]["Type"] == "Bass Shaper"      # the palette's own settings stay
    assert bass.volume_db == round(-6 - 8.5 - 2, 2)
    assert p.returns == {0: P.load("2026-11").returns["room"].settings["hall"], 1: P.load("2026-11").returns["echo"].settings["dotted_eighth"]}


def test_same_pitch_and_start_merge():
    s = example()
    s["patterns"][0]["notes"] = [{"p": 36, "t": 0, "d": 0.25, "v": 60}, {"p": 36, "t": 0, "d": 0.25, "v": 100}]
    s["feel"] = {"swing": 0, "humanize_ms": 0, "velocity_jitter": 0, "seed": 0}
    first = plan(s).tracks[0].notes
    assert [n for n in first if n[1] == 16.0] == [(36, 16.0, 0.25, 100)]
