"""playhead_moves: a render stops early when Live's audio engine is not running."""
from hands.live import record


class Fake:
    def __init__(self, times):
        self.times = list(times)

    def run(self, code):
        assert code == "song.current_song_time"
        return self.times.pop(0) if len(self.times) > 1 else self.times[0]


def test_moving_playhead(monkeypatch):
    monkeypatch.setattr(record.time, "sleep", lambda s: None)
    assert record.playhead_moves(Fake([64.0, 64.4]), 64.0)


def test_frozen_playhead(monkeypatch):
    clock = iter(range(100))
    monkeypatch.setattr(record.time, "sleep", lambda s: None)
    monkeypatch.setattr(record.time, "time", lambda: next(clock) * 0.25)
    assert not record.playhead_moves(Fake([64.0]), 64.0)


def test_unreadable_playhead_lets_the_take_go_ahead(monkeypatch):
    class Broken:
        def run(self, code):
            raise RuntimeError("no answer")
    monkeypatch.setattr(record.time, "sleep", lambda s: None)
    assert record.playhead_moves(Broken(), 0.0)
