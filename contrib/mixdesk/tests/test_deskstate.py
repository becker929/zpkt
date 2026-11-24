"""deskstate.py: the server's pure rules, with no Live, sockets or threads."""

from __future__ import annotations

import copy

import deskstate as D
import pytest


def test_reduce_folds_each_pager_message_into_a_new_state():
    st = D.initial()
    before = copy.deepcopy(st)
    st = D.reduce(st, {"t": "v", "page": 0, "slot": "f1", "n": 0.5, "s": "-6.0 dB", "r": 0.5, "key": "Kick bus/volume"}, 1.0)
    st = D.reduce(st, {"t": "v", "page": 0, "slot": "f1", "n": 0.6, "s": "-4.0 dB", "r": 0.6, "key": "Kick bus/volume"}, 1.0)
    assert st["values"]["0:f1"] == {"n": 0.6, "s": "-4.0 dB", "r": 0.6, "key": "Kick bus/volume"}
    st = D.reduce(st, {"t": "pos", "b": 16, "p": True}, 1.0)
    assert (st["pos"], st["playing"]) == (16.0, True)
    st = D.reduce(st, {"t": "mon", "slot": "C", "ref": "C2"}, 1.0)
    assert st["monitor"] == {"slot": "C", "ref": "C2"}
    st = D.reduce(st, {"t": "loop", "loop": "drop"}, 1.0)
    st = D.reduce(st, {"t": "hw", "page": 0, "slot": "f2", "hw": 0.25, "picked": False}, 7.0)
    assert st["hw"] == {"f2": 0.25} and st["picked"] == {"f2": False} and st["touch"] == {"page": 0, "slot": "f2", "at": 7.0}
    st = D.reduce(st, {"t": "hw", "page": 0, "slot": "k1", "hw": 0.25, "picked": True}, 8.0)
    assert st["hw"] == {"f2": 0.25} and st["touch"]["slot"] == "k1"  # knobs do not pick up: no place kept
    st = D.reduce(st, {"t": "page", "page": 3, "picked": {}}, 9.0)
    assert st["page"] == 3 and st["picked"] == {} and st["loop"] == "drop"
    assert D.initial() == before  # nothing was changed in place


def test_with_snapshot_keeps_the_loop_mode_an_older_pager_reports_as_a_bool():
    st = {**D.initial(), "loop": "build"}
    assert D.with_snapshot(st, {"loop": True, "page": 2}, "attached")["loop"] == "build"
    assert D.with_snapshot(D.initial(), {"loop": True}, "attached")["loop"] == "on"
    assert D.with_snapshot(st, {"loop": False}, "attached")["loop"] == "off"
    new = D.with_snapshot(st, None, "Live does not answer")
    assert new["live"] == "Live does not answer" and new["page"] == 0 and st["live"] == "starting"


def test_labels_name_each_control_by_its_spec():
    pages = [{"controls": {"f1": {"track": "Kick bus", "param": "volume"},
                           "k1": {"track": "Kick bus", "param": "send:Space"},
                           "k2": {"track": "Hats bus", "device": "desk EQ", "param": "7 Gain A"},
                           "k3": {"track": "kick", "device": "EQ Eight", "param": "1 Gain A", "label": "Sub"},
                           "k4": {"label": "Dark", "macro": []}}}]
    values = {"0:f1": {"key": "Kick bus/volume"}, "0:k1": {"key": "Kick bus/send Space"},
              "0:k2": {"key": "Hats bus/desk EQ/7 Gain A"}, "0:k3": {"key": "kick/EQ Eight/1 Gain A"},
              "0:k4": {"key": None}, "0:k4/0": {"key": "Hats bus/desk EQ/7 Gain A"}, "9:k1": {"key": "x"}}
    assert D.labels(pages, values) == {"Kick bus/volume": "Kick bus volume", "Kick bus/send Space": "Kick bus send Space",
                                       "Hats bus/desk EQ/7 Gain A": "Hats bus: desk EQ 7 Gain A",
                                       "kick/EQ Eight/1 Gain A": "kick: Sub"}


SOURCES = {"A": {"sections": {"drop": {"lufs": -9.0}}}, "B": {"sections": {"drop": {"lufs": -10.0}}},
           "C1": {"sections": {"drop": {"lufs": -12.0}}}}


@pytest.mark.parametrize(("slot", "match", "db"), [("A", True, -3.0), ("B", True, -2.0), ("C", True, 0.0),
                                                   ("W", True, 0.0), ("A", False, 0.0)])
def test_the_loudness_match_brings_each_to_the_quietest_drop(slot, match, db):
    assert D.matched_gain_db(SOURCES, slot, "C1", match) == db


def test_no_match_without_an_analysis_and_c_seeks_from_the_drop():
    assert D.matched_gain_db(SOURCES, "A", "C2", True) == 0.0
    assert D.seek_beat(8.0, "C", 64.0) == 64.0 and D.seek_beat(8.0, "A", 64.0) == 8.0
