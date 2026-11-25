"""Tests for live harness extensions: reset, clip, device, surface CLI commands."""

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent))
from test_transport import FakeRemoteScript

from zpkt.live.cli import app


@pytest.fixture
def remote():
    servers = []

    def start(answer):
        servers.append(FakeRemoteScript(answer))
        return servers[-1]

    yield start
    for s in servers:
        s.close()


def test_cli_live_reset_refuses_a_set_in_use(remote):
    live = remote(lambda m: {"status": "ok", "result": [25, 140]})
    res = CliRunner().invoke(app, ["live", "reset", "--port", str(live.port)])
    assert res.exit_code == 1 and "25 tracks and 140 arrangement clips" in res.output


def test_cli_live_reset(remote):
    done = {"status": "ok", "track": "Operator", "tempo": 124.0, "clips_count": 0}
    live = remote(lambda m: {"status": "ok", "result": [1, 0] if "arrangement_clips) for" in json.dumps(m) else done})
    runner = CliRunner()
    res = runner.invoke(
        app, ["live", "reset", "--track-name", "Operator", "--tempo", "124.0", "--port", str(live.port)]
    )
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert data["track"] == "Operator"
    assert data["tempo"] == 124.0


def test_cli_live_clip_create(remote):
    live = remote(lambda m: {"status": "ok", "result": {"track": "Operator", "clip": "Pattern", "notes_count": 60}})
    runner = CliRunner()
    res = runner.invoke(
        app,
        [
            "live",
            "clip",
            "create",
            "Operator",
            "--chords",
            "Dm9,Bbmaj9,Gm9,C9",
            "--beats",
            "32",
            "--name",
            "Pattern",
            "--port",
            str(live.port),
        ],
    )
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert data["clip"] == "Pattern"
    assert data["notes_count"] == 60


def test_cli_live_device_commands(remote):
    def handle(m):
        code = m.get("code", "")
        if "browser.load_item" in code:
            return {"status": "ok", "result": {"track": "Operator", "device": "Operator", "device_index": 0}}
        if "_d.parameters" in code and "_applied" in code:
            return {
                "status": "ok",
                "result": {"track": "Operator", "device": "Operator", "applied": ["Filter Freq"], "count": 1},
            }
        return {
            "status": "ok",
            "result": [{"name": "Filter Freq", "min": 0.0, "max": 1.0, "value": 0.76, "is_quantized": False}],
        }

    live = remote(handle)
    port = ["--port", str(live.port)]
    runner = CliRunner()

    res_load = runner.invoke(app, ["live", "device", "load", "Operator", "Operator", *port])
    assert res_load.exit_code == 0
    assert json.loads(res_load.stdout)["device"] == "Operator"

    res_set = runner.invoke(app, ["live", "device", "set", "Operator", "--param", "Filter Freq=0.76", *port])
    assert res_set.exit_code == 0
    assert json.loads(res_set.stdout)["count"] == 1

    res_list = runner.invoke(app, ["live", "device", "list", "Operator", *port])
    assert res_list.exit_code == 0
    assert json.loads(res_list.stdout)[0]["name"] == "Filter Freq"


def test_cli_live_surface_apply(remote):
    live = remote(
        lambda m: {
            "status": "ok",
            "result": {"track": "Operator", "device": "Operator", "applied": ["Filter Freq", "Spread"], "count": 2},
        }
    )
    runner = CliRunner()
    state = json.dumps({"values": {"cutoff": 3800, "spread": 65}})
    res = runner.invoke(app, ["live", "surface", "apply", state, "--track", "Operator", "--port", str(live.port)])
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert data["count"] == 2
