"""zpkt.live.describe on FakeLive: a value by its state key, and Live's selection."""

from __future__ import annotations

import pytest

from zpkt.live import describe as D
from zpkt.live.inlive import find
from zpkt.live.testing import FakeLive, fake_set, hw002_like


@pytest.fixture
def live():
    with FakeLive(hw002_like()) as fake:
        yield fake


def test_a_gain_is_continuous_with_its_range_unit_default_and_stops(live):
    d = D.describe(live, ["Kick bus/desk EQ/1 Gain A"])["Kick bus/desk EQ/1 Gain A"]
    assert (d["kind"], d["min"], d["max"], d["default"], d["unit"]) == ("continuous", -15.0, 15.0, 0.0, "dB")
    assert [s.shown for s in d["stops"]] == ["-15.0 dB", "-7.50 dB", "0.00 dB", "7.50 dB", "15.0 dB"]
    assert d["now"].shown == "0.00 dB" and d["now"].raw == 0.0
    assert d["steps"] is None and d["items"] == [] and not d["plain"] and d["name"] == "1 Gain A"


def test_a_list_names_its_items_and_a_flag_is_a_switch(live):
    found = D.describe(live, ["Kick bus/desk EQ/1 Filter Type A", "Kick bus/mute"])
    kind = found["Kick bus/desk EQ/1 Filter Type A"]
    assert kind["kind"] == "choice" and kind["steps"] == 8 and kind["items"][3] == "Bell" == kind["now"].shown
    mute = found["Kick bus/mute"]
    assert (mute["kind"], mute["steps"], mute["items"], mute["now"]) == (
        "switch",
        2,
        ["False", "True"],
        ["False", False],
    )


def test_the_mixer_a_send_by_short_name_and_a_param_with_a_slash(live):
    keys = ["Kick bus/volume", "Kick bus/pan", "Kick bus/send Space", "Main/desk Glue/Dry/Wet", "Space/volume"]
    found = D.describe(live, keys)
    assert list(found) == keys
    assert found["Kick bus/volume"]["name"] == "volume" and found["Kick bus/volume"]["stops"][0].shown == "-inf dB"
    assert found["Kick bus/send Space"]["name"] == "send Space"
    assert found["Main/desk Glue/Dry/Wet"]["unit"] == "%"


def test_missing_keys_come_back_with_the_reason_and_describe_raises(live):
    found, missing = D.look(live, ["Kick bus/volume", "Nope/volume", "Kick bus/x/y", "Main/mute", "volume"])
    assert list(found) == ["Kick bus/volume"]
    assert missing["Nope/volume"] == "no track, return or Main named 'Nope'"
    assert missing["Kick bus/x/y"].startswith("'Kick bus' has no device 'x'; it has: desk EQ")
    assert missing["Main/mute"] == "Main has no mute" and "not a state key" in missing["volume"]
    _, missing = D.look(live, ["Kick bus/desk EQ/Gian"])  # a parameter that is not there: the ones that are, named
    assert missing["Kick bus/desk EQ/Gian"].startswith("Kick bus/desk EQ has no parameter 'Gian'; it has: Device On")
    with pytest.raises(D.Missing) as err:
        D.describe(live, ["Nope/volume"])
    assert err.value.missing == {"Nope/volume": "no track, return or Main named 'Nope'"}


def test_many_keys_take_one_call_per_32(live):
    keys = [f"Kick bus/desk EQ/{band} Gain A" for band in range(1, 9)] * 5
    before = len(live.codes)
    assert len(D.describe(live, keys)) == 8
    assert len(live.codes) - before == 1


def test_the_second_device_of_a_name_is_hash_two():
    song = fake_set({"tracks": [{"name": "a", "devices": ["EQ Eight", "EQ Eight"]}]})
    song.tracks[0].devices[1].parameters[1].value = song.tracks[0].devices[1].parameters[1].max
    name = song.tracks[0].devices[1].parameters[1].name
    assert find.find_value(song, f"a/EQ Eight#2/{name}") is song.tracks[0].devices[1].parameters[1]
    assert find.find_value(song, f"a/EQ Eight/{name}") is song.tracks[0].devices[0].parameters[1]
    with pytest.raises(LookupError, match="no device 'EQ Eight#3'"):
        find.find_value(song, f"a/EQ Eight#3/{name}")


def test_selection_follows_live(live):
    assert D.selection(live) == {"track": None, "device": None, "param": None, "key": None}
    bus = next(t for t in live.song.tracks if t.name == "Kick bus")
    with live.main_thread():
        live.song.view.select_device(bus.devices[0])
    assert D.selection(live) == {"track": "Kick bus", "device": "desk EQ", "param": None, "key": None}
    param = next(p for p in bus.devices[0].parameters if p.name == "1 Gain A")
    with live.main_thread():
        live.song.view.selected_parameter = param
    assert D.selection(live)["key"] == "Kick bus/desk EQ/1 Gain A"
    with live.main_thread():
        live.song.view.selected_track = live.song.return_tracks[0]
    assert D.selection(live)["track"] == "Space"


def test_a_selected_key_can_be_described(live):
    bus = next(t for t in live.song.tracks if t.name == "Kick bus")
    with live.main_thread():
        live.song.view.select_device(bus.devices[0])
        live.song.view.selected_parameter = bus.devices[0].parameters[3]
    key = D.selection(live)["key"]
    assert D.describe(live, [key])[key]["name"] == bus.devices[0].parameters[3].name


def test_shown_for_says_what_live_would_show_for_a_value_without_writing_it(live):
    vol = live.song.tracks[0].mixer_device.volume.value
    calls = len(live.calls)
    texts = D.shown_for(
        live,
        [
            ("Kick bus/desk EQ/1 Gain A", 7.5),
            ("Kick bus/mute", 1),
            ("Kick bus/solo", 0),
            ("Kick bus/desk EQ/1 Gain A", -15.0),  # the same key twice: each pair gets its own text
            ("Nobody/volume", 0.5),
        ],
    )
    assert texts == ["7.50 dB", "True", "False", "-15.0 dB", None]
    assert len(live.calls) == calls + 1 and D.shown_for(live, []) == []
    assert D.describe(live, ["Kick bus/desk EQ/1 Gain A"])["Kick bus/desk EQ/1 Gain A"]["now"].raw == 0.0
    assert live.song.tracks[0].mixer_device.volume.value == vol
