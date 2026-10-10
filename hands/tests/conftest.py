"""Every test runs against a throwaway rig: its own folders, no rig.toml, no studio endpoint."""
from __future__ import annotations

import pytest

from hands import config


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
