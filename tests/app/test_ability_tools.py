"""Abilities as the agent has them: kept by the tap on "Always" (and by nothing else), each a tool of its own that
runs with no card, listed by the gate, the routes and the MCP server. A scripted agent on the real server, FakeLive."""

from __future__ import annotations

import dataclasses
import io
import json
import threading

import jsonschema
import pytest

from tests.app.conftest import wait_for
from tests.app.test_abilities import BPM, DOUBLE, READ_TEMPO, SET_TEMPO, batch
from tests.app.test_ask_http import API, CONTRACTS, raw, script, start, text
from tests.app.test_propose_tool import events, proposing, tap
from zpkt.app.ask import mcp, tools
from zpkt.app.ask.gemini import is_app_tool
from zpkt.app.ask.testing import Call, Hold
from zpkt.live import chain, newtrack


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(chain.time, "sleep", lambda s: None)
    monkeypatch.setattr(newtrack.time, "sleep", lambda s: None)


def kept(asked):
    return asked.rig.desk.abilities.names()


def keep(asked, *steps):
    """Keep steps as abilities the way the gate does after "Always"."""
    from tests.app import test_abilities

    return test_abilities.keep(asked.rig, *steps)


def test_always_runs_the_batch_and_keeps_its_code_and_the_reply_names_the_new_tool(asked):
    p, s, card = proposing(asked, batch(SET_TEMPO, why="tempo"))
    assert [o["id"] for o in card["options"]] == ["yes", "always", "no"]
    step = card["tool"]["steps"][0]
    assert step["name"] == "set_tempo" and step["args"] == [["bpm", 91.0]] and "replaces" not in step
    assert kept(asked) == [] and asked.rig.live.song.tempo != 91.0  # nothing before the tap
    assert tap(asked, s, card, "always")[0] == 200
    assert asked.ask.wait_idle()
    ((code, reply),) = p.replies
    assert code == 200 and reply["approved"] and reply["always"] is True and reply["done"] == 1, reply
    assert reply["abilities"] == [{"name": "set_tempo", "replaced": False, "tool": "ability_set_tempo"}]
    assert asked.rig.live.song.tempo == 91.0 and kept(asked) == ["set_tempo"]
    assert asked.rig.desk.abilities.get("set_tempo")["session"] == s["id"]
    told = events(asked, s["id"], "proposal")[0]
    assert told["state"] == "done" and told["saved"] == ["set_tempo"] and "unsaved" not in told
    assert events(asked, s["id"], "permission_answer")[0]["answered"] == "always"
    schema = json.loads((CONTRACTS / "ask-event.schema.json").read_text())
    for e in events(asked, s["id"]):
        if e["type"] in ("permission", "permission_answer", "proposal"):
            jsonschema.validate(e, schema)
    body = {"session": "s", "token": "t", "tool": "ability_set_tempo", "args": {"bpm": 1}}
    jsonschema.validate(
        body, {"$ref": "#/$defs/request", **json.loads((CONTRACTS / "ask-tool.schema.json").read_text())}
    )
    assert "ability_set_tempo" in [t.name for t in asked.ask.gate.tools()]


@pytest.mark.parametrize("answer", ["yes", "no", None])
def test_do_it_dont_and_no_answer_keep_nothing(asked, monkeypatch, answer):
    if answer is None:
        quick = dataclasses.replace(tools.BY_NAME["propose_live"], wait_s=0.3)
        monkeypatch.setitem(tools.BY_NAME, "propose_live", quick)
    p, s, card = proposing(asked, {**batch(SET_TEMPO), "always": True})  # the agent's own "always" is dropped
    if answer:
        assert tap(asked, s, card, answer)[0] == 200
    assert asked.ask.wait_idle()
    ((code, reply),) = p.replies
    assert code == 200 and "abilities" not in reply and "always" not in reply and kept(asked) == []
    assert (asked.rig.live.song.tempo == 91.0) == (answer == "yes")
    assert "saved" not in events(asked, s["id"], "proposal")[0]


def test_a_proposal_with_no_code_has_two_buttons_and_always_is_not_an_answer_to_it(asked):
    _, s, card = proposing(asked, batch({"remove": "desk Sat", "track": "Hats bus"}))
    assert [o["id"] for o in card["options"]] == ["yes", "no"]
    assert tap(asked, s, card, "always")[0] == 400  # not offered
    assert tap(asked, s, card, "no")[0] == 200 and asked.ask.wait_idle()


def test_the_hints_reach_the_agent_after_the_tap_and_are_not_on_the_card(asked):
    literal = {"code": "find_track('kick').mute = True", "does": "Mutes the kick."}
    p, s, card = proposing(asked, batch(literal))
    assert "hints" not in json.dumps(card)
    assert tap(asked, s, card, "always")[0] == 200 and asked.ask.wait_idle()
    ((code, reply),) = p.replies
    assert (
        code == 200
        and 'spells out "kick"' in reply["hints"][0]
        and reply["abilities"][0]["tool"] == "ability_mutes_the_kick"
    )


def test_an_ability_is_a_tool_with_its_documentation_and_schema(asked):
    keep(asked, {**SET_TEMPO, "params": {"bpm": {**BPM["bpm"], "default": 120}}})
    keep(asked, READ_TEMPO)
    keep(asked, DOUBLE)
    listed = {t.name: t for t in asked.ask.gate.tools()}
    assert list(listed) == [
        "make_page", "read_state", "read_measurement", "change_live", "propose_live",
        "ability_double_tempo", "ability_read_tempo", "ability_set_tempo",
    ]  # fmt: skip
    tool = listed["ability_set_tempo"]
    assert tool.kind == "ability.run" and tool.description.splitlines() == [
        "Sets the tempo.",
        "- bpm (number, default 120): the tempo, in BPM",
        "An ability (the person's Always): runs at once, no card. One History row a run; undo does not take it "
        'back. Reply {"ok", "result"}; after an error part of it may have run.',
    ]
    assert tool.schema == {
        "type": "object",
        "properties": {"bpm": {"type": "number", "description": "the tempo, in BPM", "default": 120}},
        "required": [],
        "additionalProperties": False,
    }
    assert listed["ability_double_tempo"].schema["required"] == ["bpm"]
    assert "Uses set_tempo." in listed["ability_double_tempo"].description.splitlines()
    assert "Only reads: no History row." in listed["ability_read_tempo"].description
    _, body = asked.rig.get(f"{API}/tools")
    assert [t["name"] for t in body["tools"]] == list(listed) and body["tools"][-1]["input"] == tool.schema
    assert is_app_tool({"toolCallId": "zpkt__ability_set_tempo-1", "title": "ability_set_tempo (zpkt MCP Server)"})
    assert not is_app_tool({"toolCallId": "x", "title": "ability_set_tempo", "kind": "execute"})  # Gemini's own shell


def test_a_call_runs_it_with_no_card_in_any_turn_or_none(asked):
    keep(asked, SET_TEMPO)
    gate = asked.ask.gate
    code, reply = gate.call("s1", gate.token("s1"), "ability_set_tempo", {"bpm": 140})  # no turn is running
    assert code == 200 and reply["result"] == {"tempo": 140} and asked.rig.live.song.tempo == 140.0
    last = asked.rig.desk.bus.log[-1]
    assert (last["kind"], last["who"], last["group"]) == ("ability.run", "agent", "ask-s1")
    p = script(asked, "claude", Call("ability_set_tempo", {"bpm": 141}), Call("ability_set_tempo", {"bpm": "x"}))
    s = start(asked, "faster")
    assert asked.ask.wait_idle()
    assert [c for c, _ in p.replies] == [200, 400] and asked.rig.live.song.tempo == 141.0
    assert events(asked, s["id"], "permission") == []  # nobody was asked: the standing yes is the "Always"
    assert gate.call("s1", "wrong", "ability_set_tempo", {"bpm": 1})[0] == 403
    assert gate.call("s1", gate.token("s1"), "ability_nobody", {})[0] == 404
    for name in ("ability.remove", "ability.list", "ability_", "ability_Set"):  # an agent names tools, not commands
        code, reply = gate.call("s1", gate.token("s1"), name, {"name": "set_tempo"})
        assert code == 404 and "the tools are" in reply["error"] and "ability_set_tempo" in reply["error"], name
    assert kept(asked) == ["set_tempo"]


def test_the_abilities_as_json_and_as_a_page_to_read(asked):
    code, body = asked.rig.get(f"{API}/abilities")
    assert code == 200 and body == {"abilities": [], "max": 50}
    keep(asked, SET_TEMPO)
    keep(asked, DOUBLE)
    asked.rig.desk.bus.submit(__import__("zpkt.app.bus", fromlist=["Command"]).Command(
        "ability.run", "agent", {"name": "set_tempo", "args": {"bpm": 99}}))  # fmt: skip
    code, body = asked.rig.get(f"{API}/abilities")
    one = {a["name"]: a for a in body["abilities"]}["set_tempo"]
    assert one["tool"] == "ability_set_tempo" and one["code"] == SET_TEMPO["code"] and one["runs"] == 1
    assert one["used_by"] == ["double_tempo"] and one["uses"] == [] and one["missing"] == [] and one["reads"] is False
    code, page, headers = raw(asked, "GET", f"{API}/abilities.md")
    md = page.decode()
    assert code == 200 and headers["Content-Type"].startswith("text/markdown")
    assert md.startswith("# Abilities\n") and "2 of at most 50" in md
    for words in ("## ability_set_tempo", "- `bpm` (number): the tempo, in BPM", "- Used by double_tempo.",
                  "- Uses set_tempo.", "Run 1 time, last ", "```python\nsong.tempo = args['bpm']"):  # fmt: skip
        assert words in md, words
    code, state = asked.ask.gate.call("s1", asked.ask.gate.token("s1"), "read_state", {})
    assert [a["tool"] for a in state["abilities"]] == ["ability_double_tempo", "ability_set_tempo"]
    assert state["abilities"][0] == {
        "tool": "ability_double_tempo",
        "name": "double_tempo",
        "does": DOUBLE["does"],
        "params": BPM,
        "uses": ["set_tempo"],
    }


# ---- the MCP server: the list is the app's, and it says when it changed ------------------------------------------


def talk(messages, post, lister):
    out = io.StringIO()
    mcp.serve(io.StringIO("\n".join(json.dumps(m) for m in messages) + "\n"), out, post, "s", "t", lister)
    return [json.loads(x) for x in out.getvalue().splitlines()]


def test_the_mcp_server_lists_the_apps_tools_and_tells_when_a_call_changed_them(asked):
    lister = mcp.http_tools(f"{asked.rig.url}{API}/tools")
    post = mcp.http_post(f"{asked.rig.url}{API}/tool")
    go = threading.Event()
    script(asked, "claude", Hold(go))
    s = start(asked, "wait")
    wait_for(lambda: asked.ask.is_live(s["id"]))
    out = io.StringIO()

    def answer_always():
        card = wait_for(lambda: next(iter(events(asked, s["id"], "permission")), None))
        tap(asked, s, card, "always")

    threading.Thread(target=answer_always, daemon=True).start()
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "propose_live", "arguments": batch(SET_TEMPO)}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "ability_set_tempo", "arguments": {"bpm": 77}}},
    ]  # fmt: skip
    mcp.serve(
        io.StringIO("\n".join(json.dumps(m) for m in messages) + "\n"),
        out,
        post,
        s["id"],
        asked.ask.gate.token(s["id"]),
        lister,
    )
    go.set()
    replies = [json.loads(x) for x in out.getvalue().splitlines()]
    assert replies[0]["result"]["capabilities"] == {"tools": {"listChanged": True}}
    assert len(replies[1]["result"]["tools"]) == 5
    assert json.loads(replies[2]["result"]["content"][0]["text"])["abilities"][0]["tool"] == "ability_set_tempo"
    assert replies[3] == {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}  # right after that call
    names = [t["name"] for t in replies[4]["result"]["tools"]]
    assert names[-1] == "ability_set_tempo" and replies[4]["result"]["tools"][-1]["inputSchema"]["required"] == ["bpm"]
    assert replies[5]["result"]["isError"] is False and asked.rig.live.song.tempo == 77.0
    assert len(replies) == 6  # the second call changed nothing in the list: no second notification
    assert asked.ask.wait_idle()


def test_a_waiting_mcp_server_notices_a_change_made_elsewhere(asked):
    out = io.StringIO()
    watch = mcp.Watch(out, mcp.http_tools(f"{asked.rig.url}{API}/tools"))
    assert watch.seen() is False and out.getvalue() == ""  # the client has not asked for the list yet
    watch.gave(watch.tools())
    assert watch.seen() is False
    keep(asked, READ_TEMPO)  # another chat's "Always"
    stop = threading.Event()
    watch.every(0.02, stop)
    assert wait_for(lambda: out.getvalue().count("list_changed") == 1)
    asked.rig.command("ability.remove", {"name": "read_tempo"})  # the person takes it back
    assert wait_for(lambda: out.getvalue().count("list_changed") == 2)
    stop.set()
    assert all(json.loads(x)["method"] == "notifications/tools/list_changed" for x in out.getvalue().splitlines())


def test_with_the_app_down_the_mcp_server_lists_the_built_in_tools():
    assert [t["name"] for t in mcp.http_tools("http://127.0.0.1:9/app/ask/api/tools")()] == [
        t.name for t in tools.TOOLS
    ]
    replies = talk([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}], lambda body: (200, {}), mcp.tool_list)
    assert [t["name"] for t in replies[0]["result"]["tools"]] == [t.name for t in tools.TOOLS]


def test_the_agent_is_told_how_to_write_an_ability(asked):
    said = tools.BY_NAME["propose_live"].description
    for words in ("Always", "ability_<name>", '"params"', '"args"', "args[", "verb_noun", "use(", "default",
                  "read_state", "same name"):  # fmt: skip
        assert words in said, words
    assert '"use"' in tools.BY_NAME["change_live"].description
    for tool in ("change_live", "propose_live"):
        props = tools.BY_NAME[tool].schema["properties"]["steps"]["items"]["properties"]
        assert {"use", "args"} <= set(props), tool
    assert text("x")  # (the helper is used by the other tests of this folder)
