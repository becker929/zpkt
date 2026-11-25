"""only_reads: the strict test the app's live.read uses before an agent's code runs."""

import pytest

from zpkt.live.agent import only_reads, writes


@pytest.mark.parametrize(
    "code",
    [
        "result = song.tempo",
        "result = [t.name for t in song.tracks]",
        "result = song.view.selected_track.name",
        "result = song.tracks[0].clip_slots[0].clip.playing_position",
        "result = song.record_mode",
        "result = len(song.tracks)",
    ],
)
def test_plain_reads_pass(code):
    assert only_reads(code)


@pytest.mark.parametrize(
    "code",
    [
        "song.tempo = 90",
        "song.stop_playing()",
        "setattr(song, 'tempo', 90)",
        "getattr(song, 'stop_playing')()",
        "f = song.stop_playing\nf()",
        "[song.start_playing][0]()",
        "exec('song.tempo = 90')",
        "eval('1')",
        "song.__class__",
        "import os",
        "result = (",
    ],
)
def test_anything_that_may_change_live_or_hides_what_it_does_is_refused(code):
    assert not only_reads(code)


def test_the_bypasses_are_ones_the_old_test_misses():
    assert not writes("setattr(song, 'tempo', 90)")
    assert not only_reads("setattr(song, 'tempo', 90)")
