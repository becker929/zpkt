"""Every test runs against a throwaway rig: its own folders, no rig.toml, no studio endpoint."""
from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from hands import config
from hands.live import render as live_render
from hands.live import session


@pytest.fixture(autouse=True)
def rig(tmp_path, monkeypatch):
    for key in ("sets", "data", "renders", "prefs"):
        (tmp_path / key).mkdir()
    monkeypatch.setenv("ZPKT_RIG_CONFIG", str(tmp_path / "no-rig.toml"))
    monkeypatch.setenv("ZPKT_SETS_DIR", str(tmp_path / "sets"))
    monkeypatch.setenv("ZPKT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ZPKT_RENDERS_DIR", str(tmp_path / "renders"))
    monkeypatch.setenv("ZPKT_LIVE_PREFS_DIR", str(tmp_path / "prefs"))
    monkeypatch.setenv("ZPKT_SET_PREFIXES", "test_")
    for name in ("ZPKT_LIVE_APP", "STUDIO_STEP_URL", "STUDIO_STEP_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    config.rig.cache_clear()
    yield config.rig()
    config.rig.cache_clear()


@pytest.fixture
def fake_live(monkeypatch):
    """session and export faked: export writes `level` audio of `seconds` length at 160 BPM."""
    calls = []
    monkeypatch.setattr(session, "check", lambda client, where, **kw: calls.append(("check", where)) or "test_x")
    monkeypatch.setattr(session, "open_set", lambda client, name, **kw: calls.append(("open", name)) or 5.0)

    def export(client, out, start, length, mode="Main"):
        calls.append(("export", start, length, mode))
        seconds = length * 60 / 160 if export.seconds is None else export.seconds
        sf.write(out, np.full((int(seconds * 44100), 2), export.level), 44100, subtype="FLOAT")
        return [out]
    export.level, export.seconds = 0.1, None
    monkeypatch.setattr(live_render, "export", export)
    return calls, export
