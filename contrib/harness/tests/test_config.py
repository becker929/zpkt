"""Where the harness looks for things: the environment every Claude session gets."""

from __future__ import annotations

from harness.config import ZPKT, Config, claude_env


def test_claude_sessions_find_uv_and_ears(monkeypatch):
    monkeypatch.setattr("harness.config.secret", lambda name: None)
    env = claude_env(Config(extra_env={"PATH": "/usr/bin:/bin", "X": "1"}))
    path = env["PATH"].split(":")
    assert any(p.endswith("/.local/bin") for p in path)
    assert str(ZPKT / ".venv" / "bin") in path  # zpkt's commands, ears and mlab among them
    assert path[-2:] == ["/usr/bin", "/bin"] and env["X"] == "1" and "CLAUDE_CODE_OAUTH_TOKEN" not in env


def test_the_keychain_login_is_passed_on(monkeypatch):
    monkeypatch.setattr("harness.config.secret", lambda name: "tok" if name == "oauth" else None)
    assert claude_env(Config())["CLAUDE_CODE_OAUTH_TOKEN"] == "tok"
