"""The `zpkt live` commands that change Live go through the app; with the app down they stop, unless --direct.

The app is the rig's (FakeLive, an API on a free port). Direct commands use a second FakeLive served on a free port.
Nothing reaches the real Live: the discard port stands in for it.
"""

from __future__ import annotations

import json
import socket

import pytest
from typer.testing import CliRunner

from zpkt.live import session, ui
from zpkt.live.cli import app
from zpkt.live.cli_options import APP_NOT_RUNNING, NOT_RECORDED
from zpkt.live.testing import FakeLive, hw002_like


def invoke(*argv: str, **kw):
    return CliRunner().invoke(app, list(argv), **kw)


@pytest.fixture(autouse=True)
def the_app_way(monkeypatch):
    monkeypatch.delenv("ZPKT_LIVE_VIA", raising=False)
    monkeypatch.delenv("ZPKT_AGENT", raising=False)


@pytest.fixture()
def via(api, monkeypatch):
    monkeypatch.setenv("ZPKT_APP_URL", api.url)
    return api


@pytest.fixture()
def app_down(tmp_path, monkeypatch):
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    url = f"http://127.0.0.1:{free.getsockname()[1]}"
    free.close()
    monkeypatch.setenv("ZPKT_APP_URL", url)
    monkeypatch.setenv("ZPKT_CONFIG_DIR", str(tmp_path / "no-token-here"))


@pytest.fixture()
def direct_live():
    with FakeLive(hw002_like()) as fake:
        yield fake, ["--port", str(fake.serve())]


def test_a_change_goes_through_the_app_and_is_recorded_as_cli(via, rig):
    res = invoke("live", "exec", "song.tempo = 101.0", "--raw")
    assert res.exit_code == 0, res.output
    assert rig.live.song.tempo == 101.0
    ran = [e for e in rig.desk.bus.log if e["kind"] == "live.run"]
    assert ran and {e["who"] for e in ran} == {"cli"} and ran[-1]["group"].startswith("cli-")


def test_a_read_may_run_direct_even_with_the_app_down(app_down, direct_live):
    fake, port = direct_live
    res = invoke("live", "exec", "result = song.tempo", "--json", "--raw", *port)
    assert res.exit_code == 0 and json.loads(res.stdout) == fake.song.tempo


def test_with_the_app_down_a_change_stops_and_says_what_to_do(app_down, direct_live):
    fake, port = direct_live
    before = fake.song.tempo
    res = invoke("live", "exec", "song.tempo = 77.0", "--raw", *port)
    assert res.exit_code == 1 and APP_NOT_RUNNING in res.stderr
    assert fake.song.tempo == before


def test_direct_goes_to_live_and_says_the_change_is_not_recorded(app_down, direct_live):
    fake, port = direct_live
    res = invoke("live", "exec", "song.tempo = 77.0", "--raw", "--direct", *port)
    assert res.exit_code == 0 and NOT_RECORDED in res.stderr
    assert fake.song.tempo == 77.0


def test_the_environment_can_keep_the_old_direct_way(app_down, direct_live, monkeypatch):
    fake, port = direct_live
    monkeypatch.setenv("ZPKT_LIVE_VIA", "direct")
    res = invoke("live", "exec", "song.tempo = 78.0", "--raw", *port)
    assert res.exit_code == 0 and NOT_RECORDED not in res.stderr and fake.song.tempo == 78.0


def test_exec_prints_the_same_through_the_app(via, rig):
    res = invoke("live", "exec", "song.tempo = 100.0\nresult = [1, 'a']", "--json", "--raw")
    assert res.exit_code == 0 and json.loads(res.stdout) == [1, "a"]
    bad = invoke("live", "exec", "song.tempo = nonsense", "--raw")
    assert bad.exit_code == 1 and bad.stderr.startswith("ERROR:")


def test_state_put_through_the_app(via, rig, tmp_path, monkeypatch):
    from zpkt.live import ui as _ui

    monkeypatch.setattr(_ui, "front_title", lambda: "HW002_121_pp_finish")
    monkeypatch.setattr(_ui, "dialogs", lambda: 0)
    monkeypatch.setenv("ZPKT_SET_PREFIXES", "HW002")
    taken = invoke("live", "state", "take", "mine", "--port", str(rig.live.serve()))  # a read: direct
    assert taken.exit_code == 0, taken.output
    put = invoke("live", "state", "put", "mine")
    assert put.exit_code == 0, put.output
    assert any(e["kind"] == "live.run" and e["who"] == "cli" for e in rig.desk.bus.log)


def test_open_through_the_app_uses_the_apps_connection(via, rig, monkeypatch):
    seen = []
    monkeypatch.setattr(session, "open_set", lambda live, name, save_current: seen.append(type(live).__name__) or 1.0)
    res = invoke("live", "open", "somewhere")
    assert res.exit_code == 0, res.output
    assert seen == ["AppTransport"]  # the CLI hands the app's transport to the library; nothing opens a socket


def test_reload_hands_the_probe_a_connection(app_down, direct_live, monkeypatch, tmp_path):
    import subprocess

    fake, _ = direct_live
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 0))
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(ui, "dialogs", lambda: 0)
    monkeypatch.setattr(ui, "front_title", lambda: "test_set")
    monkeypatch.setenv("ZPKT_LIVE_PORT", str(fake.port))
    from zpkt.live import config

    config.rig.cache_clear()
    res = invoke("live", "reload", str(tmp_path / "test_set.als"), "--direct")
    assert res.exit_code == 0 and "reloaded: test_set" in res.stdout and NOT_RECORDED in res.stderr
    stopped = invoke("live", "reload", str(tmp_path / "test_set.als"))
    assert stopped.exit_code == 1 and APP_NOT_RUNNING in stopped.stderr


# the commands that only look at Live (or at files): they take no --direct and may run with the app down
LOOK_ONLY = {
    "sweep", "live ping", "live check", "live save", "live describe", "live selection", "live state take",
    "live state diff", "live device list", "live page lint", "panel params", "live modals", "live state ls",
    "build", "library inventory", "serum2 presets", "serum2 render", "serum2 apply", "als check", "als params",
    "als mix", "rig check", "rig reset", "rig output",
}  # fmt: skip


def test_every_command_that_can_change_live_takes_direct():
    """Walk the command tree: a command with --host or --port that is not a look-only one must take --direct."""
    from typer.main import get_command

    def walk(cmd, path):
        if hasattr(cmd, "commands"):
            for name, sub in cmd.commands.items():
                yield from walk(sub, [*path, name])
        else:
            yield " ".join(path), {o for p in cmd.params for o in getattr(p, "opts", [])}

    missing = [
        name
        for name, opts in walk(get_command(app), [])
        if ("--port" in opts or "--host" in opts) and "--direct" not in opts and name not in LOOK_ONLY
    ]
    assert missing == [], f"these may change Live but take no --direct: {missing}"


def test_the_app_down_message_for_a_panel_command(app_down):
    res = invoke("panel", "drop", "x")
    assert res.exit_code == 1 and APP_NOT_RUNNING in res.stderr


def test_a_read_goes_through_the_app_when_it_is_running(via, rig):
    res = invoke("live", "exec", "result = song.tempo", "--raw")
    assert res.exit_code == 0, res.output
    assert [e["who"] for e in rig.desk.bus.log if e["kind"] == "live.read"] == ["cli"]


def test_a_read_with_the_app_down_goes_direct_without_complaint(app_down, direct_live, monkeypatch):
    fake, _ = direct_live
    monkeypatch.setenv("ZPKT_LIVE_PORT", str(fake.port))
    res = invoke("live", "exec", "result = song.tempo", "--raw")
    assert res.exit_code == 0, res.output
    assert NOT_RECORDED not in res.output and APP_NOT_RUNNING not in res.output


def test_a_read_with_direct_skips_the_app(via, rig, direct_live):
    _, port = direct_live
    before = len(rig.desk.bus.log)
    res = invoke("live", "exec", "result = song.tempo", "--raw", "--direct", *port)
    assert res.exit_code == 0, res.output
    assert len(rig.desk.bus.log) == before
