"""The commands the MiniLab uses that the web did not: page.set, mix.reset, tempo.set and tempo.scale."""

from __future__ import annotations

import pytest

from tests.app.test_midi_adapter import key_of, raw
from zpkt.app.bus import Command


def test_page_set_moves_a_batch_of_the_pages_controls_as_one_history_entry(rig):
    k3, k4 = key_of(rig, "k3"), key_of(rig, "k4")
    code, reply = rig.command("page.set", {"page": 0, "controls": [{"slot": "k3", "n": 1.0}, {"slot": "k4", "n": 0.5}]})
    assert code == 200 and reply["entry"] and reply["missing"] == []
    assert raw(rig, k3) == pytest.approx(1.0) and raw(rig, k4) > 0
    assert len(rig.desk.history.entries) == 1 and len(rig.desk.history.entries[0]["moves"]) == 2


def test_page_set_asks_live_for_a_controls_range_once(rig):
    body = {"page": 0, "controls": [{"slot": "k3", "n": 0.3}]}
    rig.command("page.set", body)
    described = len(rig.desk.descriptions)
    calls = len(rig.live.calls)
    rig.command("page.set", {"page": 0, "controls": [{"slot": "k3", "n": 0.6}]})
    assert described == 1 and len(rig.desk.descriptions) == 1
    assert len(rig.live.calls) - calls == 1  # the write alone: no second description (the guard's answer is kept)


def test_page_set_skips_what_the_page_does_not_have_and_says_what_and_rejects_a_bad_body(rig):
    code, reply = rig.command("page.set", {"page": 0, "controls": [{"slot": "k9", "n": 1.0}]})
    assert code == 200 and reply["missing"] == ["k9"] and rig.desk.history.entries == []
    assert rig.command("page.set", {"page": 0, "controls": []})[0] == 400
    assert rig.command("page.set", {"page": "x", "controls": [{"slot": "k1", "n": 1}]})[0] == 400
    assert rig.command("page.set", {"page": 0, "controls": [{"slot": "k1"}]})[0] == 400


def test_an_agent_still_needs_your_word_for_page_set(rig):
    body = {"page": 0, "controls": [{"slot": "k3", "n": 1.0}]}
    assert rig.desk.bus.submit(Command("page.set", "agent", body))[0] == 403
    assert rig.desk.bus.submit(Command("page.set", "minilab", body))[0] == 200


def test_mix_reset_puts_a_control_back_to_its_default_and_undo_takes_it_back(rig):
    key = key_of(rig, "k3")
    rig.command("page.set", {"page": 0, "controls": [{"slot": "k3", "n": 1.0}]})
    rig.command("history.checkpoint", {"name": "turned up"})  # a checkpoint ends the step: the reset is its own
    code, reply = rig.command("mix.reset", {"keys": [key]})
    assert code == 200 and reply["entry"]
    assert raw(rig, key) != pytest.approx(1.0)
    assert rig.post("/api/undo")[0] == 200
    assert raw(rig, key) == pytest.approx(1.0)
    assert rig.command("mix.reset", {"keys": []})[0] == 400
    assert rig.command("mix.reset", {"keys": ["No such/key"]})[0] == 400


def test_tempo_commands_set_it_and_double_or_halve_it_and_clamp_to_what_live_takes(rig):
    assert rig.command("tempo.set", {"bpm": 150})[0] == 200 and rig.live.song.tempo == 150
    assert rig.command("tempo.scale", {"factor": 2})[0] == 200 and rig.live.song.tempo == 300
    assert rig.command("tempo.scale", {"factor": 0.5})[0] == 200 and rig.live.song.tempo == 150
    rig.command("tempo.set", {"bpm": 5000})
    assert rig.live.song.tempo == 999
    assert rig.command("tempo.set", {"bpm": "fast"})[0] == 400
    assert rig.command("tempo.scale", {"factor": 0})[0] == 400


def test_tempo_commands_are_guarded_like_every_move(rig):
    rig.live.song.file_path = "/Sets/Other Project/Other.als"
    rig.desk.bus.guard.forget()
    assert rig.command("tempo.set", {"bpm": 150})[0] == 409


def test_what_live_said_of_a_range_is_forgotten_when_the_pager_loads_again(rig):
    rig.command("page.set", {"page": 0, "controls": [{"slot": "k3", "n": 0.3}]})
    assert rig.desk.descriptions
    rig.desk.restart_pager()
    assert rig.desk.descriptions == {}


def test_what_live_said_of_a_range_is_forgotten_when_a_set_is_opened(rig):
    rig.command("page.set", {"page": 0, "controls": [{"slot": "k3", "n": 0.3}]})
    assert rig.desk.descriptions
    rig.desk.bus.submit(Command("live.open_set", "cli", {"name": "HW002_121_pp_finish", "save_current": False}))
    assert rig.desk.descriptions == {}
