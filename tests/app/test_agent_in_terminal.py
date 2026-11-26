"""A coding agent in a terminal (ZPKT_AGENT=1) is `agent` to the app, not `cli`: the agent rule holds it."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from zpkt.app.client import AppClient, caller
from zpkt.live.app_transport import AppTransport
from zpkt.live.cli import app as cli


@pytest.fixture()
def app_env(api, monkeypatch):
    monkeypatch.setenv("ZPKT_APP_URL", api.url)
    monkeypatch.delenv("ZPKT_LIVE_VIA", raising=False)
    monkeypatch.delenv("ZPKT_AGENT", raising=False)
    return api


def test_the_cli_is_the_agent_when_an_agent_drives_it(monkeypatch):
    monkeypatch.delenv("ZPKT_AGENT", raising=False)
    assert caller() == "cli" and caller("booth") == "booth"
    monkeypatch.setenv("ZPKT_AGENT", "1")
    assert caller() == "agent" and caller("cli") == "agent"
    assert caller("booth") == "booth" and caller("demo") == "demo"  # a program that names itself stays that
    assert AppClient().who == "agent" and AppClient("cli").who == "agent"


def test_an_agents_change_through_the_transport_is_stamped_agent_and_refused(app_env, rig, monkeypatch):
    monkeypatch.setenv("ZPKT_AGENT", "1")
    before = rig.live.song.tempo
    transport = AppTransport("cli")
    assert transport.group.startswith("agent-")
    res = transport.execute("song.tempo = 105.0")
    assert res.status == "error" and "cannot change Live" in str(res.error)
    assert rig.live.song.tempo == before
    last = rig.desk.bus.log[-1]
    assert (last["kind"], last["who"], last["status"]) == ("live.run", "agent", 403)


def test_an_agent_may_still_read_through_the_transport(app_env, rig, monkeypatch):
    monkeypatch.setenv("ZPKT_AGENT", "1")
    assert AppTransport().run("result = song.tempo") == rig.live.song.tempo
    last = rig.desk.bus.log[-1]
    assert (last["kind"], last["who"], last["status"]) == ("live.read", "agent", 200)


def test_naming_an_option_gives_the_agent_nothing(app_env, rig, monkeypatch):
    """Options are gone: ZPKT_OPTION is not read, and no approval of an agent's passes from outside the app."""
    monkeypatch.setenv("ZPKT_AGENT", "1")
    monkeypatch.setenv("ZPKT_OPTION", "kick-down")
    before = rig.live.song.tempo
    assert AppTransport().execute("song.tempo = 106.0").status == "error"
    assert rig.live.song.tempo == before
    agent = AppClient()
    sent = []
    original = agent._send
    agent._send = lambda m, p, body, auth=True: sent.append(body) or original(m, p, body, auth)  # type: ignore[method-assign]
    agent.submit("live.read", {"code": "result = 1"})
    assert "approval" not in sent[0]


def test_a_command_of_the_zpkt_cli_that_changes_live_stops_in_an_agents_shell(app_env, rig, monkeypatch):
    """`zpkt live state put` changes Live: in an agent's shell (ZPKT_AGENT) it stops before it asks the app, and
    says how an agent changes Live (the app's change_live tool). tests/app/test_agent_shell_guard.py has the rest."""
    from zpkt.live import ui

    monkeypatch.setattr(ui, "front_title", lambda: "HW002_121_pp_finish")
    monkeypatch.setattr(ui, "dialogs", lambda: 0)
    monkeypatch.setenv("ZPKT_SET_PREFIXES", "HW002")
    runner = CliRunner()
    taken = runner.invoke(cli, ["live", "state", "take", "mine", "--port", str(rig.live.serve())])  # a read: direct
    assert taken.exit_code == 0, taken.output
    monkeypatch.setenv("ZPKT_AGENT", "1")
    rig.track("Kick bus").mixer_device.volume.value = 0.2  # so the put has something to change
    for route in ([], ["--direct"]):
        put = runner.invoke(cli, ["live", "state", "put", "mine", *route])
        assert put.exit_code == 1 and "change_live" in put.output
    assert not [e for e in rig.desk.bus.log if e["kind"] == "live.run"]
    assert rig.track("Kick bus").mixer_device.volume.value == 0.2
