"""The agent's four tools: they are bus commands tagged `agent`, they reach nothing else, and none moves Live."""

from __future__ import annotations

import json

import jsonschema
import pytest

from zpkt.app.ask.tools import BY_NAME, TOOLS
from zpkt.live import page as pages

SCHEMAS = __import__("pathlib").Path(__file__).resolve().parents[2] / "lib" / "contracts"
PAGE = {
    "title": "Kick: level",
    "groups": [{"name": "Level", "controls": [{"target": "Kick bus/volume", "role": "level"}]}],
}


def call(asked, tool, args=None, session="s1"):
    gate = asked.ask.gate
    return gate.call(session, gate.token(session), tool, args or {})


def test_there_are_exactly_four_tools_and_each_is_a_registered_command(asked):
    assert [t.name for t in TOOLS] == ["make_page", "read_state", "read_measurement", "propose_option"]
    assert {t.kind for t in TOOLS} <= set(asked.rig.desk.bus.kinds())
    assert not {t.kind for t in TOOLS} & {
        "mix.set",
        "mix.toggle",
        "transport",
        "history.undo",
        "history.revert",
        "monitor.choose",
    }
    for t in TOOLS:
        jsonschema.Draft202012Validator.check_schema(t.schema)


def test_an_agent_cannot_name_a_command_that_is_not_a_tool(asked):
    for name in ("mix.set", "transport", "page.make", "history.undo", "nope"):
        code, body = call(asked, name, {"norms": [["Kick bus/volume", 0.1]]})
        assert code == 404 and "the tools are make_page" in body["error"]
    assert asked.rig.desk.history.entries == []  # nothing moved


def test_the_wrong_token_is_refused_before_anything_runs(asked):
    gate = asked.ask.gate
    assert gate.call("s1", gate.token("other"), "read_state", {})[0] == 403
    assert gate.call("s1", "", "read_state", {})[0] == 403
    assert asked.rig.desk.bus.log == [] or all(row["who"] != "agent" for row in asked.rig.desk.bus.log)


def test_read_state_and_read_measurement(asked):
    code, state = call(asked, "read_state")
    assert code == 200 and state["set"] == "HW002_121_pp_finish" and "monitor" in state and "values" in state
    code, m = call(asked, "read_measurement")
    assert code == 200 and "analysis" in m and "sources" in m["analysis"]
    assert {row["who"] for row in asked.rig.desk.bus.log} == {"agent"}
    assert {row["group"] for row in asked.rig.desk.bus.log} == {"ask-s1"}


def test_make_page_checks_against_live_and_saves_only_a_clean_page(asked, tmp_path):
    code, ok = call(asked, "make_page", {"page": PAGE})
    assert code == 200 and ok["ok"] and ok["id"] == "kick-level"
    saved = pages.folder("HW002_121_pp_finish") / ok["file"]
    page = json.loads(saved.read_text())
    assert page["made_by"] == "agent"  # the bus's who, whatever the spec says
    code, bad = call(
        asked,
        "make_page",
        {"page": {**PAGE, "title": "Bad", "groups": [{"name": "G", "controls": [{"target": "No such/volume"}]}]}},
    )
    assert code == 422 and any(p["level"] == "error" for p in bad["problems"]) and "not saved" in bad["error"]
    assert not (pages.folder("HW002_121_pp_finish") / "bad.json").exists()
    assert call(asked, "make_page", {})[0] == 400
    assert call(asked, "make_page", {"page": {"title": "x"}})[0] == 400


def test_make_page_says_agent_even_when_the_spec_claims_otherwise(asked):
    code, ok = call(asked, "make_page", {"page": {**PAGE, "made_by": "you"}})
    assert code == 200
    assert json.loads((pages.folder("HW002_121_pp_finish") / ok["file"]).read_text())["made_by"] == "agent"


def test_propose_option_is_recorded_and_moves_nothing(asked):
    before = asked.rig.desk.history.entries[:]
    code, ok = call(
        asked,
        "propose_option",
        {
            "option": {
                "title": "Kick down 2 dB",
                "why": "It masks the bass.",
                "moves": [{"target": "Kick bus/volume", "to": "-2 dB"}],
            }
        },
    )
    assert (
        code == 200
        and ok["option"]["state"] == "proposed"
        and ok["option"]["made_by"] == "agent"
        and ok["option"]["session"] == "ask-s1"
    )
    stored = json.loads((asked.adapter.data_dir / "options.json").read_text())
    assert stored == [ok["option"]]
    jsonschema.validate(stored[0], json.loads((SCHEMAS / "proposal.schema.json").read_text()))
    assert asked.rig.desk.history.entries == before
    for bad in ({}, {"option": {"title": "x"}}, {"option": {"title": "x", "why": "y", "moves": [{"target": 1}]}}):
        assert call(asked, "propose_option", bad)[0] == 400


def test_an_agents_move_command_would_still_need_an_option_or_a_word(asked):
    """Even if a tool were added by mistake, the bus's agent rule stands: the tools table is not the only guard."""
    from zpkt.app.bus import Command

    code, body = asked.rig.desk.bus.submit(Command("mix.set", "agent", {"norms": [["Kick bus/volume", 0.3]]}))
    assert code == 403 and "cannot change Live" in body["error"]


@pytest.mark.parametrize("name", [t.name for t in TOOLS])
def test_every_tool_has_a_description_a_schema_and_a_unique_name(name):
    tool = BY_NAME[name]
    assert tool.description and tool.schema["type"] == "object"


def test_an_agent_cannot_pick_its_own_option_and_only_your_pick_lets_its_move_pass(asked):
    from zpkt.app.bus import Command

    bus = asked.rig.desk.bus
    move = {"norms": [["Kick bus/volume", 0.3]]}
    _, ok = call(
        asked,
        "propose_option",
        {
            "option": {
                "title": "Kick down",
                "why": "It masks the bass.",
                "moves": [{"target": "Kick bus/volume", "to": 0.3}],
            }
        },
    )
    oid = ok["option"]["id"]
    assert bus.submit(Command("mix.set", "agent", move, approval=f"option:{oid}"))[0] == 403  # proposed, not picked
    assert bus.submit(Command("option.pick", "agent", {"option": oid}))[0] == 403  # an agent cannot pick
    assert bus.submit(Command("option.pick", "you", {"option": "nope"}))[0] == 400
    code, picked = bus.submit(Command("option.pick", "you", {"option": oid}))
    assert code == 200 and picked["option"]["state"] == "picked"
    stored = json.loads((asked.adapter.data_dir / "options.json").read_text())
    jsonschema.validate(stored[0], json.loads((SCHEMAS / "proposal.schema.json").read_text()))
    assert bus.submit(Command("mix.set", "agent", move, approval=f"option:{oid}", group="g"))[0] == 200
