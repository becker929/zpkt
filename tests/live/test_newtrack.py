"""zpkt.live.newtrack on FakeLive: a new audio, MIDI or return track, made and named in short calls of their own."""

from __future__ import annotations

import pytest

from zpkt.live import chain, newtrack
from zpkt.live.testing import FakeLive, hw002_like


@pytest.fixture()
def live():
    fake = FakeLive(hw002_like())
    yield fake
    fake.close()


def still(_seconds: float) -> None:
    pass


def test_an_audio_and_a_midi_track_are_made_last_and_named(live):
    before = [t.name for t in live.song.tracks]
    calls = len(live.calls)
    index = newtrack.make(live, "audio", "Parallel", still)
    assert index == len(before) and [t.name for t in live.song.tracks] == [*before, "Parallel"]
    codes = [c.code for c in live.calls[calls:]]
    assert len(codes) == 4  # count, make, count, name: the name is never set in the call that made the track
    assert "create_audio_track" in codes[1] and ".name" not in codes[1] and "create" not in codes[3]
    assert newtrack.make(live, "midi", "Keys", still) == index + 1
    assert live.song.tracks[-1].name == "Keys" and live.song.tracks[-1].has_midi_input


def test_a_return_gets_lives_letter_and_is_found_by_its_short_name(live):
    index = newtrack.make(live, "return", "Drive", still)
    assert index == 2 and [t.name for t in live.song.return_tracks] == ["A-Space", "B-Echo", "C-Drive"]
    assert chain.look(live, ["Drive"]) == {"Drive": []}


def test_a_set_that_did_not_grow_is_an_error_and_an_unknown_kind_is_refused(live, monkeypatch):
    with pytest.raises(ValueError, match="audio, midi, return"):
        newtrack.make(live, "group", "X", still)
    monkeypatch.setitem(newtrack._MAKE, "audio", "pass")  # Live says ok and makes nothing
    before = len(live.song.tracks)
    with pytest.raises(newtrack.NewTrackError, match="did not make the audio track"):
        newtrack.make(live, "audio", "Ghost", still)
    assert len(live.song.tracks) == before
