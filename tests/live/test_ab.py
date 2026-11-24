"""hands.ab builds one LOM code block per action; check each compiles and runs
against a fake song, so a hotkey never ships a syntax error into Live."""

from types import SimpleNamespace

import pytest

from hands import ab
from hands.live.transport import McpResult, MockTransport, Transport


class FakeTrack(SimpleNamespace):
    pass


class FakeSong:
    def __init__(self, names):
        self.tracks = [FakeTrack(name=n, mute=n.startswith("REF "), solo=False) for n in names]
        self._data = {}

    def get_data(self, key, default):
        return self._data.get(key, default)

    def set_data(self, key, value):
        self._data[key] = value


class LocalTransport(Transport):
    """Executes the code like the remote script does: exec, then read `result`."""

    def __init__(self, song):
        self.song = song

    def execute(self, code):
        compile(code, "<lom>", "exec")
        scope = {"song": self.song}
        exec(code, scope)
        return McpResult(status="ok", result=scope.get("result"))


@pytest.fixture
def song():
    return FakeSong(["kick", "perc", "REF A", "REF B"])


def audible_refs(song):
    return [t.name for t in song.tracks if t.name.startswith("REF ") and t.solo and not t.mute]


def test_toggle_round_trip(song):
    t = LocalTransport(song)
    assert ab.toggle(t)["mode"] == "ref"
    assert audible_refs(song) == ["REF A"]
    assert ab.toggle(t)["mode"] == "mix"
    assert audible_refs(song) == []
    assert all(x.mute for x in song.tracks if x.name.startswith("REF "))
    assert not any(x.mute for x in song.tracks if not x.name.startswith("REF "))


def test_next_switches_the_playing_reference(song):
    t = LocalTransport(song)
    ab.toggle(t)
    assert ab.next_ref(t)["ref"] == "REF B"
    assert audible_refs(song) == ["REF B"]
    assert ab.next_ref(t)["ref"] == "REF A"  # wraps
    assert ab.status(t)["ref"] == "REF A"


def test_next_while_on_mix_stays_on_mix(song):
    t = LocalTransport(song)
    assert ab.next_ref(t) == {"mode": "mix", "ref": "REF B", "spectrum": None}
    assert audible_refs(song) == []


def test_no_reference_tracks_is_an_error():
    with pytest.raises(RuntimeError, match="no reference tracks"):
        ab.status(LocalTransport(FakeSong(["kick"])))


@pytest.mark.parametrize("spectrum", [True, False])
def test_spectrum_code_compiles(spectrum):
    mock = MockTransport([McpResult(status="ok", result={"mode": "ref", "ref": "REF A", "spectrum": spectrum})])
    ab.toggle(mock, spectrum=spectrum)
    compile(mock.calls[0], "<lom>", "exec")
    assert ("SpectrumAnalyzer" in mock.calls[0]) is spectrum


def test_spectrum_toggle_and_show():
    for toggle in (True, False):
        mock = MockTransport([McpResult(status="ok", result={"spectrum": True})])
        ab.spectrum(mock, toggle=toggle)
        compile(mock.calls[0], "<lom>", "exec")
        assert f"TOGGLE = {toggle!r}" in mock.calls[0]


def test_live_error_is_raised():
    mock = MockTransport([McpResult(status="error", error="Cannot reach Ableton")])
    with pytest.raises(RuntimeError, match="Cannot reach Ableton"):
        ab.toggle(mock)
