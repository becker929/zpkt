"""Claude Code as an engine, against a stand-in `claude` that calls no model: a real process, real streams."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from zpkt.app.ask.claude import AUTH_HELP, ClaudeProvider
from zpkt.app.ask.service import Ask
from zpkt.app.ask.tools import ToolGate
from zpkt.app.bus import Bus

FAKE = Path(__file__).parent / "fakes" / "fake_claude.py"


@pytest.fixture()
def claude_bin(tmp_path) -> str:
    script = tmp_path / "claude"
    script.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def make(tmp_path, claude_bin, secret=lambda name: "tok-1") -> tuple[Ask, Path]:
    log = tmp_path / "claude.log"
    env = {"PATH": os.environ["PATH"], "FAKE_CLAUDE_LOG": str(log)}
    provider = ClaudeProvider(secret, claude_bin=claude_bin, environ=env, home=tmp_path)
    (tmp_path / "work").mkdir(exist_ok=True)
    ask = Ask(tmp_path / "ask", {"claude": provider}, ToolGate(Bus()), guide="GUIDE", home=tmp_path)
    ask.workspaces.list.append({"id": "work", "name": "Work", "path": str(tmp_path / "work")})
    return ask, log


def test_a_turn_streams_text_and_a_result_and_the_session_is_marked_started(tmp_path, claude_bin):
    ask, log = make(tmp_path, claude_bin)
    s = ask.create("work", "hello there", engine="claude")
    assert ask.wait_idle()
    events = ask.store.replay(s["id"])
    assert [e["type"] for e in events] == ["prompt", "init", "message", "result", "run_end"]
    assert events[2]["content"] == "echo: hello there"
    assert events[3]["stats"]["total_tokens"] == 5 and events[3]["cost_usd"] == 0.01
    assert events[-1]["code"] == 0
    seen = json.loads(log.read_text().splitlines()[0])
    assert seen["args"][seen["args"].index("--session-id") + 1] == s["id"]
    assert seen["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "tok-1" and seen["env"]["ZPKT_AGENT"] == "1"
    assert seen["prompt"] == "hello there"
    assert ask.store.get(s["id"])["engines"]["claude"]["started"] is True  # it counted tokens: it really answered


def test_a_session_that_answered_is_resumed_next_time(tmp_path, claude_bin):
    ask, log = make(tmp_path, claude_bin)
    s = ask.create("work", "tool please", engine="claude")
    ask.wait_idle()
    assert ask.store.get(s["id"])["engines"]["claude"]["started"] is True
    ask.send(s, "and again", engine="claude")
    ask.wait_idle()
    second = json.loads(log.read_text().splitlines()[1])
    assert "--resume" in second["args"] and "--session-id" not in second["args"]
    kinds = [e["type"] for e in ask.store.replay(s["id"])]
    assert "tool_use" in kinds and kinds.count("run_end") == 2
    result = next(e for e in ask.store.replay(s["id"]) if e["type"] == "tool_result")
    assert result["output"] == "file text" and result["status"] == "success"


def test_not_signed_in_says_what_to_do_and_hides_the_clis_own_words(tmp_path, claude_bin):
    ask, _ = make(tmp_path, claude_bin)
    s = ask.create("work", "auth please", engine="claude")
    ask.wait_idle()
    events = ask.store.replay(s["id"])
    assert not any("Failed to authenticate" in json.dumps(e) for e in events if e["type"] == "message")
    assert any(e["type"] == "error" and e["message"] == AUTH_HELP for e in events)
    assert events[-1]["type"] == "run_end" and events[-1]["code"] == 1


def test_stop_ends_the_process(tmp_path, claude_bin):
    ask, _ = make(tmp_path, claude_bin)
    s = ask.create("work", "slow one", engine="claude")
    import time

    for _ in range(100):
        if any(e["type"] == "message" for e in ask.store.replay(s["id"])):
            break
        time.sleep(0.05)
    assert ask.stop(s["id"]) and ask.wait_idle()
    end = ask.store.replay(s["id"])[-1]
    assert end["type"] == "run_end" and end["signal"] == "SIGTERM"


def test_a_missing_program_is_a_run_end_with_the_reason(tmp_path):
    ask, _ = make(tmp_path, str(tmp_path / "no-such-claude"))
    s = ask.create("work", "hi", engine="claude")
    ask.wait_idle()
    end = ask.store.replay(s["id"])[-1]
    assert end["type"] == "run_end" and end["error"] and end["code"] is None


def test_the_token_comes_only_from_the_secret_lookup_it_was_given(tmp_path, claude_bin):
    asked_for: list[str] = []

    def secret(name: str) -> str | None:
        asked_for.append(name)
        return None

    ask, log = make(tmp_path, claude_bin, secret)
    ask.create("work", "hello", engine="claude")
    ask.wait_idle()
    assert asked_for == ["oauth"]
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in json.loads(log.read_text().splitlines()[0])["env"]
