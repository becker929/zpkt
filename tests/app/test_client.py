"""The client of the app and the transport on top of it: the one-line switch for callers that used LiveClient."""

from __future__ import annotations

import ast
import socket
from pathlib import Path

import pytest

from zpkt.app import client as client_module
from zpkt.app.client import AppClient, AppDown
from zpkt.live.app_transport import APP_DOWN, AppTransport, configured_via
from zpkt.live.transport import LiveClient, LiveError


@pytest.fixture()
def app_env(api, monkeypatch):
    monkeypatch.setenv("ZPKT_APP_URL", api.url)
    monkeypatch.delenv("ZPKT_LIVE_VIA", raising=False)
    return api


def test_the_client_has_no_live_code():
    """zpkt.app.client imports the standard library and the token module, and nothing from zpkt.live."""
    tree = ast.parse(Path(client_module.__file__).read_text())
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    modules |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not [m for m in modules if m.startswith("zpkt.live")], modules


def test_up_and_the_command_list(app_env):
    c = AppClient("booth")
    assert c.up()
    assert "live.run" in {k["kind"] for k in c.commands()}


def test_each_named_job_has_a_method(app_env, api):
    c = AppClient("demo")
    assert c.run("result = 2 + 2")[1]["reply"]["result"] == 4
    assert c.set_tempo(111.0)[0] == 200
    assert c.transport("play")[0] == 200
    assert c.state_take()[0] == 200
    assert c.describe(["Kick bus/volume"])[1]["ok"]
    assert c.render_loop("x.mp3")[0] == 409  # a refusal is a status, not an exception
    assert c.page_apply("ghost")[0] == 409
    _, state = c.state_take()
    assert c.state_put(state["state"])[0] == 200


def test_a_wrong_token_is_a_message_that_says_what_to_do(api):
    with pytest.raises(AppDown, match="restart `zpkt app`"):
        AppClient(url=api.url, token="wrong").commands()


def test_no_token_file_says_to_start_the_app(tmp_path):
    with pytest.raises(AppDown, match="start the app with `zpkt app`"):
        AppClient(url="http://127.0.0.1:9", config_dir=tmp_path).token()


def test_the_app_down_is_a_message_and_up_is_false():
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    url = f"http://127.0.0.1:{free.getsockname()[1]}"
    free.close()
    c = AppClient(url=url, token="x")
    assert not c.up()
    with pytest.raises(AppDown, match="start it with `zpkt app`"):
        c.commands()


def test_the_transport_runs_code_like_a_liveclient(app_env, rig):
    t = AppTransport("booth")
    assert t.run("result = song.tempo") == rig.live.song.tempo
    res = t.execute("song.tempo = 99.0")
    assert res.status == "ok" and rig.live.song.tempo == 99.0
    bad = t.execute("song.nonsense_attribute")
    assert bad.status == "error" and bad.error
    with pytest.raises(LiveError):
        t.run("song.nonsense_attribute")


def test_one_transport_makes_one_group_so_its_changes_undo_together(app_env, rig):
    t = AppTransport("booth")
    t.run("song.tempo = 90.0")
    t.run("song.tempo = 91.0")
    groups = {e["group"] for e in rig.desk.bus.log if e["kind"] == "live.run"}
    assert groups == {t.group} and t.group.startswith("booth-")
    assert {e["who"] for e in rig.desk.bus.log if e["kind"] == "live.run"} == {"booth"}


def test_the_transport_says_when_the_app_is_down(tmp_path, monkeypatch):
    monkeypatch.setenv("ZPKT_CONFIG_DIR", str(tmp_path))
    res = AppTransport("demo", AppClient("demo", url="http://127.0.0.1:9", token="x")).execute("1")
    assert res.status == "error" and res.error.startswith(APP_DOWN)


def test_the_transport_carries_a_refusal_as_an_error(app_env):
    res = AppTransport("agent").execute("song.tempo = 80.0")  # an agent's change needs approval
    assert res.status == "error" and "403" in str(res.error) and "cannot change Live" in str(res.error)


def test_ping_asks_the_app(app_env, tmp_path):
    assert AppTransport("cli").ping() >= 0
    with pytest.raises(LiveError, match=APP_DOWN):
        AppTransport("cli", AppClient("cli", url="http://127.0.0.1:9", token="x")).ping()


def test_via_app_is_the_one_line_switch(app_env, rig):
    live = LiveClient.via_app("booth")
    assert isinstance(live, AppTransport) and live.run("result = 1 + 1") == 2


def test_zpkt_live_via_chooses_for_default(app_env, monkeypatch):
    monkeypatch.setenv("ZPKT_LIVE_VIA", "app")
    assert isinstance(LiveClient.default("demo"), AppTransport)
    monkeypatch.setenv("ZPKT_LIVE_VIA", "direct")
    assert isinstance(LiveClient.default(port=9), LiveClient)
    monkeypatch.delenv("ZPKT_LIVE_VIA")
    assert configured_via() is None and isinstance(LiveClient.default(port=9), LiveClient)
    monkeypatch.setenv("ZPKT_LIVE_VIA", "maybe")
    with pytest.raises(ValueError, match="'app' or 'direct'"):
        configured_via()
