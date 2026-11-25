"""Small behaviours that a mutation run showed no test pinned: hold's lock file and busy message, infer_role's
choice and unit rules, and the desk's first state."""

from __future__ import annotations

import pytest

from zpkt.app import deskstate
from zpkt.live import hold, page


def test_looking_for_the_holder_creates_the_lock_file_and_finds_nobody():
    assert hold.holder() == {}
    assert (hold._dir() / hold.LOCK).exists()  # opened for appending, not read-only


def test_busy_says_how_long_the_holder_has_held_live(monkeypatch):
    monkeypatch.setattr(hold.time, "time", lambda: 1100.0)
    msg = str(hold.Busy({"what": "panel make", "at": 1000.0}, 3.0))
    assert "`panel make`" in msg and "for 100 s" in msg and "waited 3 s" in msg


def test_busy_without_a_time_says_no_duration():
    msg = str(hold.Busy({}, 0.0))
    assert "another hands command" in msg and "(waited 0 s)" in msg


def desc(kind="continuous", name="Thing", unit=""):
    return {"kind": kind, "name": name, "unit": unit}


@pytest.mark.parametrize(
    ("d", "role"),
    [
        (desc("switch"), "switch"),
        (desc("choice"), "choice"),
        (desc(name="Whatever", unit="Hz"), "tone"),
        (desc(name="Whatever", unit="kHz"), "tone"),
        (desc(name="Whatever", unit="KHZ"), "tone"),  # the unit is compared in lower case
        (desc(name="Whatever", unit="dB"), "level"),
        (desc(name="Whatever", unit="ms"), "time"),
        (desc(name="Whatever", unit="s"), "time"),
        (desc(name="Cutoff"), "tone"),
        (desc(name="Gain"), "level"),
        (desc(name="Attack"), "time"),
        (desc(name="Whatever", unit="%"), "amount"),
    ],
)
def test_infer_role(d, role):
    assert page.infer_role(d) == role  # type: ignore[arg-type]


def test_the_desks_first_state():
    s = deskstate.initial()
    assert s["page"] == 0 and s["attached"] is False and s["live"] == "starting"
    assert s["values"] == {} and s["hw"] == {} and s["picked"] == {} and s["touch"] is None
    assert s["monitor"] == {"slot": "W", "ref": "C1"}
    assert s["match"] is True and s["pos"] == 0.0 and s["playing"] is False and s["loop"] == "off"
    assert deskstate.initial() is not deskstate.initial()
    assert deskstate.initial()["values"] is not deskstate.initial()["values"]
