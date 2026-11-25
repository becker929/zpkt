"""Rig settings (environment over file over defaults) and the bench log."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from zpkt.live import bench, config


def test_defaults_are_neutral(tmp_path):
    rig = config.load(env={}, path=tmp_path / "missing.toml")
    assert rig.live_app == "Ableton Live 12 Suite"
    assert rig.sets_dir == Path("~/Music/zpkt/sets").expanduser()
    assert rig.set_prefixes == ("zpkt_",) and rig.new_set_prefix == "zpkt_"
    assert rig.set_path("x") == rig.sets_dir / "x.als"


def test_environment_beats_the_file(tmp_path):
    file = tmp_path / "rig.toml"
    file.write_text('sets_dir = "/sets"\nset_prefixes = ["A_", "B_"]\nlive_prefs_dir = "/prefs/Live 12"\n')
    rig = config.load(env={"ZPKT_RIG_CONFIG": str(file), "ZPKT_SETS_DIR": "/env-sets"})
    assert rig.sets_dir == Path("/env-sets")
    assert rig.set_prefixes == ("A_", "B_") and rig.is_ours("B_kit") and not rig.is_ours("C_x")
    assert rig.live_log == Path("/prefs/Live 12/Log.txt")
    env = config.load(env={"ZPKT_SET_PREFIXES": "X_, Y_"}, path=file)
    assert env.set_prefixes == ("X_", "Y_")


def test_unknown_keys_and_empty_prefixes_are_refused(tmp_path):
    file = tmp_path / "rig.toml"
    file.write_text('set_prefix = "typo_"\n')
    with pytest.raises(ValueError, match="unknown keys"):
        config.load(env={}, path=file)
    with pytest.raises(ValueError, match="any set"):
        config.load(env={"ZPKT_SET_PREFIXES": " , "}, path=tmp_path / "none.toml")


def test_a_retired_key_in_the_file_is_still_read_and_ignored(tmp_path):
    file = tmp_path / "rig.toml"
    file.write_text('plans_dir = "~/plans"\nsets_dir = "/sets"\n')
    rig = config.load(env={"ZPKT_PLANS_DIR": "/elsewhere"}, path=file)
    assert rig.sets_dir == Path("/sets") and not hasattr(rig, "plans_dir")


def test_live_port_comes_from_the_file_or_the_environment(tmp_path):
    assert config.load(env={}, path=tmp_path / "missing.toml").live_port == 16619
    file = tmp_path / "rig.toml"
    file.write_text("live_port = 17000\n")
    assert config.load(env={}, path=file).live_port == 17000
    assert config.load(env={"ZPKT_LIVE_PORT": "17001"}, path=file).live_port == 17001
    for bad in ("x", "0", "70000", "16619.5"):
        with pytest.raises(ValueError, match="live_port must be a TCP port number"):
            config.load(env={"ZPKT_LIVE_PORT": bad}, path=file)


def test_newest_live_prefs(tmp_path):
    for name in ("Live 12.4.5", "Live 12.4.10", "Live 11.3.2", "Other"):
        (tmp_path / name).mkdir()
    assert config._newest_live_prefs(tmp_path).name == "Live 12.4.10"
    assert config._newest_live_prefs(tmp_path / "absent") is None


@pytest.fixture
def studio():
    """A stand-in for the studio's step endpoint: records each POST, answers 204."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.headers["Authorization"], body))
            if body.get("caption") == "slow":
                time.sleep(1.0)
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/studio/step", seen
    server.shutdown()
    server.server_close()


def test_timing_appends_to_the_bench_log(rig):
    bench.timing("kit_load", 7.2345, kit="c8x4")
    bench.timing("kit_render", 25.0)
    rows = [json.loads(line) for line in (rig.data_dir / "bench.jsonl").read_text().splitlines()]
    assert [(r["step"], r["s"]) for r in rows] == [("kit_load", 7.234), ("kit_render", 25.0)]
    assert rows[0]["kit"] == "c8x4"


def test_desk_folders_come_from_settings_and_env(tmp_path):
    file = tmp_path / "rig.toml"
    file.write_text('mixdesk_dir = "/desk"\narranger_dir = "/arr"\nask_dir = "/ask"\n')
    rig = config.load(env={}, path=file)
    assert (rig.mixdesk_dir, rig.arranger_dir, rig.ask_dir) == (Path("/desk"), Path("/arr"), Path("/ask"))
    env = config.load(env={"ZPKT_ARRANGER_DIR": "/a2", "ZPKT_MIXDESK_DIR": "/d2"}, path=file)
    assert (env.arranger_dir, env.mixdesk_dir) == (Path("/a2"), Path("/d2"))
    assert config.load(env={"ARRANGER_DATA": "/old"}, path=tmp_path / "none.toml").arranger_dir == Path("/old")
