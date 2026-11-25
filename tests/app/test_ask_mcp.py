"""The MCP server of the tools: its messages, and a call all the way to the app over HTTP."""

from __future__ import annotations

import io
import json

from zpkt.app.ask import mcp
from zpkt.app.ask.tools import TOOLS


def talk(messages, post=None, session="s", token="t"):
    out = io.StringIO()
    mcp.serve(
        io.StringIO("\n".join(json.dumps(m) for m in messages) + "\n"),
        out,
        post or (lambda body: (200, {})),
        session,
        token,
    )
    return [json.loads(x) for x in out.getvalue().splitlines()]


def test_initialize_list_and_unknown_method():
    replies = talk([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "resources/list"},
    ])  # fmt: skip
    assert [r["id"] for r in replies] == [1, 2, 3]  # the notification is not answered
    assert replies[0]["result"]["serverInfo"]["name"] == "zpkt"
    assert [t["name"] for t in replies[1]["result"]["tools"]] == [t.name for t in TOOLS]
    assert replies[2]["error"]["code"] == -32601


def test_a_call_sends_the_session_and_token_and_marks_errors():
    sent = []

    def post(body):
        sent.append(body)
        return (422, {"error": "bad page"}) if body["tool"] == "make_page" else (200, {"ok": True})

    replies = talk([
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "read_state", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "make_page", "arguments": {"page": {}}}},
    ], post)  # fmt: skip
    assert sent[0] == {"session": "s", "token": "t", "tool": "read_state", "args": {}}
    assert replies[0]["result"]["isError"] is False and json.loads(replies[0]["result"]["content"][0]["text"]) == {
        "ok": True
    }
    assert replies[1]["result"]["isError"] is True and "bad page" in replies[1]["result"]["content"][0]["text"]


def test_a_call_over_http_reaches_the_bus_as_agent(asked):
    post = mcp.http_post(f"{asked.rig.url}/app/ask/api/tool")
    gate = asked.ask.gate
    (reply,) = talk(
        [{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "read_state", "arguments": {}}}],
        post,
        "sess-9",
        gate.token("sess-9"),
    )
    assert reply["result"]["isError"] is False
    assert json.loads(reply["result"]["content"][0]["text"])["set"] == "HW002_121_pp_finish"
    assert asked.rig.desk.bus.log[-1]["who"] == "agent" and asked.rig.desk.bus.log[-1]["group"] == "ask-sess-9"
    (denied,) = talk(
        [{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "read_state", "arguments": {}}}],
        post,
        "sess-9",
        "wrong",
    )
    assert denied["result"]["isError"] is True and "not for this session" in denied["result"]["content"][0]["text"]


def test_an_app_that_is_down_is_an_error_the_agent_can_read():
    status, body = mcp.http_post("http://127.0.0.1:9/app/ask/api/tool")({"tool": "read_state"})
    assert status == 503 and "not reachable" in body["error"]
