"""In an agent's shell (ZPKT_AGENT=1) no `zpkt live` command changes Live, by any route: through the app, with
--direct, with ZPKT_LIVE_VIA=direct. The refusal names the app's change_live tool. Commands that only read still
run. A guard against accidents: an agent with a shell can unset a variable, so it is no security boundary."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from zpkt.live import cli_options, rig, session, ui
from zpkt.live.agent import AGENT_NOT_FROM_SHELL
from zpkt.live.cli import app as cli
from zpkt.live.transport import LiveClient

runner = CliRunner()


@pytest.fixture()
def shell(rig, monkeypatch):
    """An agent's shell beside a Live that answers on a port: a direct connection would reach it."""
    port = rig.live.serve()
    monkeypatch.setenv("ZPKT_LIVE_PORT", str(port))
    monkeypatch.setenv("ZPKT_APP_URL", "http://127.0.0.1:9")  # no app: only a direct route could change Live
    monkeypatch.setenv("ZPKT_AGENT", "1")
    monkeypatch.delenv("ZPKT_LIVE_VIA", raising=False)
    from zpkt.live import config

    config.rig.cache_clear()
    return rig


WRITES = [
    ["live", "exec", "song.tempo = 91.0"],
    ["live", "exec", "song.tempo = 91.0", "--direct"],
    ["live", "exec", "setattr(song, 'tempo', 91.0)", "--direct"],  # a write `writes` alone would not see
    ["live", "exec", "getattr(song, 'stop_playing')()", "--direct"],
    ["live", "exec", "exec('song.tempo = 91.0')", "--direct"],
    ["live", "device", "load", "Kick bus", "Saturator", "--direct"],
    ["live", "device", "set", "Kick bus", "--device", "desk EQ", "--param", "1 Gain A=3", "--direct"],
    ["live", "reset", "--force", "--direct"],
    ["live", "open", "other", "--direct"],
    ["live", "reopen", "--direct"],
    ["live", "save"],
    ["live", "modals", "--reap"],
    ["live", "export", "x.wav", "--direct"],
    ["panel", "make", "--spec", '{"name": "m", "bars": [1, 1], "faders": ["Kick bus"]}', "--direct"],
    ["panel", "drop", "m", "--direct"],
    ["rig", "reset"],
    ["rig", "output", "Yeti"],
]


def state_of(rig):
    song = rig.live.song
    return song.tempo, [(t.name, t.mixer_device.volume.value, [d.name for d in t.devices]) for t in song.tracks]


@pytest.mark.parametrize("via", ["", "direct"])
@pytest.mark.parametrize("argv", WRITES, ids=[" ".join(a[:4]) for a in WRITES])
def test_a_command_that_changes_live_is_refused_in_an_agents_shell(shell, monkeypatch, argv, via):
    if via:
        monkeypatch.setenv("ZPKT_LIVE_VIA", via)
    touched = []
    monkeypatch.setattr(ui, "reap_modals", lambda reap: touched.append("reap") or "CLEAN")
    monkeypatch.setattr(ui, "osa_file", lambda *a, **k: touched.append("osa") or "NONE")
    monkeypatch.setattr(session, "save", lambda *a, **k: touched.append("save"))
    monkeypatch.setattr(rig, "reset", lambda **k: touched.append("reset"))
    before, calls = state_of(shell), len(shell.live.calls)
    result = runner.invoke(cli, argv)
    assert result.exit_code == 1, (argv, result.output)
    assert "change_live" in result.output and "never from the shell" in result.output
    assert state_of(shell) == before and touched == []
    assert len(shell.live.calls) == calls  # nothing was sent to Live at all


def test_reads_still_work_in_an_agents_shell(shell, monkeypatch):
    monkeypatch.setattr(ui, "front_title", lambda: "HW002_121_pp_finish")
    monkeypatch.setattr(ui, "dialogs", lambda: 0)
    read = runner.invoke(cli, ["live", "exec", "result = song.tempo"])
    assert read.exit_code == 0 and read.output.strip() == str(shell.live.song.tempo)
    described = runner.invoke(cli, ["live", "describe", "Kick bus/volume"])
    assert described.exit_code == 0 and "Kick bus/volume" in described.output
    listed = runner.invoke(cli, ["live", "device", "list", "Kick bus"])
    assert listed.exit_code == 0 and "Device On" in listed.output
    assert runner.invoke(cli, ["live", "modals"]).exit_code in (0, 1)  # looking at the dialogs is a read


def test_a_person_is_not_held_by_the_guard(shell, monkeypatch):
    monkeypatch.delenv("ZPKT_AGENT")
    done = runner.invoke(cli, ["live", "exec", "song.tempo = 91.0", "--direct"])
    assert done.exit_code == 0 and shell.live.song.tempo == 91.0


def test_the_words_name_the_tool_and_connect_is_the_one_door(monkeypatch):
    assert "change_live" in AGENT_NOT_FROM_SHELL and "live.change" in AGENT_NOT_FROM_SHELL
    monkeypatch.setenv("ZPKT_AGENT", "1")
    import typer

    with pytest.raises(typer.Exit):
        cli_options.connect(LiveClient, "127.0.0.1", 9)  # any command that says it changes Live stops here
    with pytest.raises(typer.Exit):
        cli_options.connect(LiveClient, "127.0.0.1", 9, direct=True)
    assert isinstance(cli_options.connect(LiveClient, "127.0.0.1", 9, changes=False), LiveClient)
