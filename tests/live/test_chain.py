"""zpkt.live.chain on FakeLive: what is on a chain, add an audio effect, move a device, delete one."""

from __future__ import annotations

import pytest

from zpkt.live import chain
from zpkt.live.testing import FakeLive, hw002_like, lom

KICK = "Kick bus"
START = ["desk EQ", "desk Sat", "desk Glue"]


@pytest.fixture()
def live():
    fake = FakeLive(hw002_like())
    yield fake
    fake.close()


def still(_seconds: float) -> None:
    pass


def test_look_reads_several_chains_in_one_call_and_says_which_track_is_missing(live):
    calls = len(live.calls)
    found = chain.look(live, [KICK, "Main", "Space", "nobody", KICK])
    assert found == {
        KICK: START,
        "Main": ["desk Glue", "desk Utility", "desk headroom"],
        "Space": ["Reverb"],
        "nobody": None,
    }
    assert len(live.calls) == calls + 1 and chain.look(live, []) == {}


def test_the_browser_is_asked_whether_it_has_an_audio_effect(live):
    assert chain.has_effect(live, ["Saturator", "saturator", "No Such Thing"]) == {
        "Saturator": True,
        "saturator": True,
        "No Such Thing": False,
    }


def test_add_puts_the_effect_last_or_at_an_index_and_says_where(live):
    assert chain.add(live, KICK, "Saturator", pause=still) == {"track": KICK, "device": "Saturator", "at": 3}
    assert chain.add(live, KICK, "Utility", at=1, pause=still) == {"track": KICK, "device": "Utility", "at": 1}
    assert chain.names(live, KICK) == ["desk EQ", "Utility", "desk Sat", "desk Glue", "Saturator"]
    with pytest.raises(Exception, match="no audio effect"):
        chain.add(live, KICK, "No Such Thing", pause=still)
    assert len(chain.names(live, KICK)) == 5


@pytest.mark.parametrize(("index", "to", "want"), [(0, 2, ["desk Sat", "desk Glue", "desk EQ"]), (2, 0, ["desk Glue", "desk EQ", "desk Sat"]), (1, 1, START), (0, 9, ["desk Sat", "desk Glue", "desk EQ"])])  # fmt: skip
def test_move_ends_at_the_index_asked_for(live, index, to, want):
    assert chain.move(live, KICK, index, to, pause=still) == want.index(START[index])
    assert chain.names(live, KICK) == want


def test_move_reads_the_chain_back_and_tries_the_other_reading_of_position(live, monkeypatch):
    """If Live took `position` as the index the device ends at (not "before the device now there"), the first try
    lands one too far right; the read-back sees it and the second try puts it where it was asked."""

    def final_index(self, device, target, position):
        target._devices.remove(device)
        target._devices.insert(max(0, min(len(target._devices), position)), device)
        return target._devices.index(device)

    monkeypatch.setattr(lom.Song, "move_device", final_index)
    assert chain.move(live, KICK, 0, 1, pause=still) == 1
    assert chain.names(live, KICK) == ["desk Sat", "desk EQ", "desk Glue"]
    assert chain.move(live, KICK, 2, 0, pause=still) == 0
    assert chain.names(live, KICK) == ["desk Glue", "desk Sat", "desk EQ"]


def test_delete_takes_the_named_device_and_nothing_else(live):
    assert chain.delete(live, KICK, 1, "desk Sat") is True and chain.names(live, KICK) == ["desk EQ", "desk Glue"]
    # not where it was recorded: the chain was changed by hand, and a device we cannot be sure of is never deleted
    assert chain.delete(live, KICK, 0, "desk Glue") is False and chain.names(live, KICK) == ["desk EQ", "desk Glue"]
    assert chain.delete(live, KICK, 0, "gone") is False and chain.names(live, KICK) == ["desk EQ", "desk Glue"]


def test_landed_and_index_of():
    assert chain.landed(["a", "b"], ["a", "b", "x"]) == 2 and chain.landed(["a", "b"], ["a", "x", "b"]) == 1
    assert chain.index_of(["a", "x", "b", "x"], "x", 3) == 3 and chain.index_of(["a", "x", "b", "x"], "x", 0) == 1
    assert chain.index_of(["a"], "x", 0) is None
