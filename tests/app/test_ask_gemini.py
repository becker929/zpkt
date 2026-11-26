"""Gemini as an engine over ACP, against a stand-in `gemini --acp` that calls no model: permission prompts and cost."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

from zpkt.app.ask.acp import AcpError
from zpkt.app.ask.cost import price, turn_cost
from zpkt.app.ask.gemini import GeminiProvider
from zpkt.app.ask.service import Ask
from zpkt.app.ask.tools import ToolGate
from zpkt.app.bus import Bus

FAKE = Path(__file__).parent / "fakes" / "fake_acp.py"


def make(tmp_path, secret=lambda name: "key-1") -> tuple[Ask, GeminiProvider, Path]:
    log = tmp_path / "acp.log"
    provider = GeminiProvider(
        secret, command=[sys.executable, str(FAKE)], environ={"PATH": "/usr/bin:/bin", "FAKE_ACP_LOG": str(log)},
        home=tmp_path, usage_file=tmp_path / "usage.jsonl",
    )  # fmt: skip
    (tmp_path / "work").mkdir(exist_ok=True)
    ask = Ask(tmp_path / "ask", {"gemini": provider}, ToolGate(Bus()), guide="GUIDE", home=tmp_path)
    ask.workspaces.list.append({"id": "work", "name": "Work", "path": str(tmp_path / "work")})
    ask.app_url = "http://127.0.0.1:9"
    return ask, provider, log


def lines(log: Path) -> list[dict]:
    return [json.loads(x) for x in log.read_text().splitlines()]


def wait_for(check, seconds=10.0):
    end = time.time() + seconds
    while time.time() < end:
        if got := check():
            return got
        time.sleep(0.02)
    return check()


def test_the_cost_estimate_matches_the_harnesss_rates():
    assert price("gemini-flash-lite-latest") == (0.1, 0.4) and price("gemini-flash-latest") == (0.5, 3.0)
    assert price("gemini-3-pro") == (2.0, 12.0) and price("gemini-2.5-pro") == (1.25, 10.0)
    cost = turn_cost(
        "gemini-flash-latest", {"inputTokens": 1000, "cachedReadTokens": 400, "outputTokens": 100, "thoughtTokens": 50}
    )
    assert cost == pytest.approx((600 * 0.5 + 400 * 0.05 + 150 * 3.0) / 1e6)


def test_a_turn_makes_an_acp_session_streams_text_and_reports_dollars(tmp_path):
    ask, provider, log = make(tmp_path)
    try:
        s = ask.create("work", "hello", engine="gemini")
        assert ask.wait_idle()
        events = ask.store.replay(s["id"])
        assert [e["type"] for e in events] == ["prompt", "message", "result", "run_end"]
        assert events[1]["content"].startswith("echo: ") and "hello" in events[1]["content"]
        assert events[2]["cost_usd"] == pytest.approx(0.00077) and events[2]["stats"]["total_tokens"] == 1150
        assert events[3]["code"] == 0
        acp = ask.store.get(s["id"])["engines"]["gemini"]
        assert acp["started"] is True and acp["acp"].startswith("acp-")
        sent = lines(log)
        new = next(m for m in sent if m.get("method") == "session/new")
        assert new["params"]["cwd"] == str(tmp_path / "work")
        assert new["params"]["mcpServers"][0]["name"] == "zpkt"
        assert {e["name"] for e in new["params"]["mcpServers"][0]["env"]} == {
            "ZPKT_DESK_URL",
            "ZPKT_APP_SESSION",
            "ZPKT_APP_TOKEN",
        }
        row = json.loads((tmp_path / "usage.jsonl").read_text())
        assert row["session"] == s["id"] and row["dollars"] == pytest.approx(0.00077)
    finally:
        provider.close()


def test_the_key_comes_only_from_the_secret_lookup_and_a_missing_key_is_said(tmp_path):
    ask, _provider, _ = make(tmp_path, secret=lambda name: None)
    s = ask.create("work", "hello", engine="gemini")
    ask.wait_idle()
    events = ask.store.replay(s["id"])
    assert any(e["type"] == "error" and "No Gemini key" in e["message"] for e in events)
    assert events[-1]["type"] == "run_end" and events[-1]["code"] == 1
    assert not hasattr(AcpError, "key")


def test_ask_first_edits_wait_for_the_page_then_go_on(tmp_path):
    ask, provider, log = make(tmp_path)
    try:
        s = ask.create("work", "edit the readme", engine="gemini", mode="ask")
        q = wait_for(lambda: next((e for e in ask.store.replay(s["id"]) if e["type"] == "permission"), None))
        assert q["tool"]["title"] == "Edit README.md" and q["tool"]["paths"] == ["/r/README.md"]
        assert q["tool"]["content"][0]["diff"] == "/r/README.md"
        assert {o["id"] for o in q["options"]} == {"proceed_once", "cancel"}
        assert ask.permissions.answer(s["id"], q["id"], "proceed_once")
        assert ask.wait_idle()
        events = ask.store.replay(s["id"])
        assert next(e for e in events if e["type"] == "tool_result")["status"] == "success"
        assert "Done." in "".join(e.get("content", "") for e in events if e["type"] == "message")
        mode = next(m for m in lines(log) if m.get("method") == "session/set_mode")
        assert mode["params"]["modeId"] == "default"  # "ask" is Gemini's default: it asks
    finally:
        provider.close()


def test_the_apps_tools_run_in_every_mode_with_no_question_to_the_person(tmp_path):
    for n, mode in enumerate(("build", "ask", "auto_edit", "yolo")):
        (tmp_path / str(n)).mkdir()
        ask, provider, _ = make(tmp_path / str(n))
        try:
            s = ask.create("work", "page for the kick", engine="gemini", mode=mode)
            assert ask.wait_idle()
            events = ask.store.replay(s["id"])
            assert not any(e["type"] == "permission" for e in events), mode  # the app answered for the person
            assert next(e for e in events if e["type"] == "tool_result")["status"] == "success", mode
            assert "Done." in "".join(e.get("content", "") for e in events if e["type"] == "message")
        finally:
            provider.close()


def test_the_default_mode_refuses_an_edit_at_once_and_asks_nobody(tmp_path):
    ask, provider, log = make(tmp_path)
    try:
        s = ask.create("work", "edit the readme", engine="gemini")  # no mode named: the default
        assert ask.wait_idle()
        events = ask.store.replay(s["id"])
        assert events[0]["mode"] == "build" and not any(e["type"] == "permission" for e in events)
        assert next(e for e in events if e["type"] == "tool_result")["status"] == "error"
        assert "Skipped." in "".join(e.get("content", "") for e in events if e["type"] == "message")
        mode = next(m for m in lines(log) if m.get("method") == "session/set_mode")
        assert mode["params"]["modeId"] == "default"  # not Gemini's plan mode: there it would make no page
    finally:
        provider.close()


def test_only_a_call_that_names_the_apps_server_and_tool_is_taken_for_one():
    from zpkt.app.ask.gemini import decide, is_app_tool

    assert is_app_tool({"toolCallId": "x1", "title": "make_page (zpkt MCP Server)", "kind": "other"})
    assert is_app_tool({"toolCallId": "mcp_zpkt_read_state-17", "title": "read_state"})
    assert is_app_tool({"toolCallId": "t", "title": "propose_option (zpkt MCP Server)"})
    assert not is_app_tool({"toolCallId": "t", "title": "make_page (other MCP Server)"})
    assert not is_app_tool({"toolCallId": "t", "title": "Edit zpkt/make_page.py", "kind": "edit"})
    assert not is_app_tool({"toolCallId": "t", "title": "rm -rf zpkt", "kind": "execute"})
    assert not is_app_tool({"toolCallId": "t", "title": "delete_everything (zpkt MCP Server)"})
    options = [
        {"id": "always", "kind": "allow_always"},
        {"id": "once", "kind": "allow_once"},
        {"id": "no", "kind": "reject_once"},
    ]
    asked: list[str] = []

    def person(tool, opts):
        asked.append(tool["title"])
        return "once"

    assert decide("build", {"title": "make_page (zpkt MCP Server)"}, options, person) == "once"
    assert decide("build", {"title": "Shell: ls", "kind": "execute"}, options, person) == "no" and asked == []
    assert decide("ask", {"title": "Shell: ls", "kind": "execute"}, options, person) == "once" and asked == [
        "Shell: ls"
    ]
    assert decide("build", {"title": "Shell: ls"}, [], person) is None  # nothing offered: cancelled


def test_a_rejected_edit_is_skipped(tmp_path):
    ask, provider, _ = make(tmp_path)
    try:
        s = ask.create("work", "edit the readme", engine="gemini", mode="ask")
        q = wait_for(lambda: next((e for e in ask.store.replay(s["id"]) if e["type"] == "permission"), None))
        ask.permissions.answer(s["id"], q["id"], "cancel")
        assert ask.wait_idle()
        events = ask.store.replay(s["id"])
        assert next(e for e in events if e["type"] == "tool_result")["status"] == "error"
        assert "Skipped." in "".join(e.get("content", "") for e in events if e["type"] == "message")
    finally:
        provider.close()


def test_stop_cancels_the_turn_and_a_waiting_question(tmp_path):
    ask, provider, _ = make(tmp_path)
    try:
        s = ask.create("work", "slow", engine="gemini")
        wait_for(lambda: any(e["type"] == "message" for e in ask.store.replay(s["id"])))
        ask.stop(s["id"])
        assert ask.wait_idle()
        assert ask.store.replay(s["id"])[-1]["signal"] == "SIGTERM"
        t = ask.create("work", "edit now", engine="gemini", mode="ask")
        wait_for(lambda: ask.permissions.asking(t["id"]))
        ask.stop(t["id"])
        assert ask.wait_idle()
        assert any(e["type"] == "permission_answer" and e["answered"] == "cancelled" for e in ask.store.replay(t["id"]))
    finally:
        provider.close()


def test_a_session_is_loaded_into_a_new_process_after_a_restart(tmp_path):
    ask, provider, log = make(tmp_path)
    s = ask.create("work", "first", engine="gemini")
    ask.wait_idle()
    acp_id = ask.store.get(s["id"])["engines"]["gemini"]["acp"]
    provider.close()
    time.sleep(0.2)
    ask.send(s, "second", engine="gemini")  # the process died: a new one is started and loads the session
    try:
        assert ask.wait_idle()
        loads = [m for m in lines(log) if m.get("method") == "session/load"]
        assert loads and loads[-1]["params"]["sessionId"] == acp_id
        assert ask.store.replay(s["id"])[-1]["code"] == 0
    finally:
        provider.close()


def test_updates_for_no_running_turn_are_dropped(tmp_path):
    _ask, provider, _ = make(tmp_path)
    provider._notify(
        "session/update",
        {
            "sessionId": "x",
            "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "late"}},
        },
    )
    assert provider._request("session/request_permission", {"sessionId": "x"}) == {"outcome": {"outcome": "cancelled"}}
    with pytest.raises(AcpError):
        provider._request("fs/read_text_file", {})
    assert threading.active_count() >= 1
