"""The agent's tools: they are bus commands tagged `agent` and reach nothing else. Three move nothing in Live; the
fourth, change_live, changes it and can be undone (tests/app/test_live_change.py); the fifth, propose_live, changes
it only after the person's tap (tests/app/test_propose_tool.py)."""

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


def test_there_are_exactly_five_tools_and_each_is_a_registered_command(asked):
    assert [t.name for t in TOOLS] == ["make_page", "read_state", "read_measurement", "change_live", "propose_live"]
    assert {t.name: t.kind for t in TOOLS}["change_live"] == "live.change"
    assert {t.name: t.kind for t in TOOLS}["propose_live"] == "live.propose"
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
    assert code == 200 and "sources" in (m.get("analysis") or m)  # whole, or a summary when long
    assert {row["who"] for row in asked.rig.desk.bus.log} == {"agent"}
    assert {row["group"] for row in asked.rig.desk.bus.log} == {"ask-s1"}


def test_make_page_checks_against_live_and_saves_only_a_clean_page(asked, tmp_path):
    code, ok = call(asked, "make_page", {"spec": PAGE})
    assert code == 200 and ok["ok"] and ok["id"] == "kick-level"
    saved = pages.folder("HW002_121_pp_finish") / ok["file"]
    page = json.loads(saved.read_text())
    assert page["made_by"] == "agent"  # the bus's who, whatever the spec says
    code, bad = call(
        asked,
        "make_page",
        {"spec": {**PAGE, "title": "Bad", "groups": [{"name": "G", "controls": [{"target": "No such/volume"}]}]}},
    )
    assert code == 422 and any(p["level"] == "error" for p in bad["problems"]) and "not saved" in bad["error"]
    assert not (pages.folder("HW002_121_pp_finish") / "bad.json").exists()
    assert call(asked, "make_page", {})[0] == 400
    assert call(asked, "make_page", {"spec": {"title": "x"}})[0] == 400


def test_make_page_says_agent_even_when_the_spec_claims_otherwise(asked):
    code, ok = call(asked, "make_page", {"spec": {**PAGE, "made_by": "you"}})
    assert code == 200
    assert json.loads((pages.folder("HW002_121_pp_finish") / ok["file"]).read_text())["made_by"] == "agent"


def test_propose_option_is_gone(asked):
    assert call(asked, "propose_option", {"option": {"title": "x", "why": "y"}})[0] == 404
    assert not {"options.propose", "option.propose", "options.pick", "option.pick"} & set(asked.rig.desk.bus.kinds())
    assert not (asked.adapter.data_dir / "options.json").exists()


def test_an_agents_move_command_would_still_need_your_word(asked):
    """Even if a tool were added by mistake, the bus's agent rule stands: the tools table is not the only guard."""
    from zpkt.app.bus import Command

    code, body = asked.rig.desk.bus.submit(Command("mix.set", "agent", {"norms": [["Kick bus/volume", 0.3]]}))
    assert code == 403 and "cannot change Live" in body["error"]


@pytest.mark.parametrize("name", [t.name for t in TOOLS])
def test_every_tool_has_a_description_a_schema_and_a_unique_name(name):
    tool = BY_NAME[name]
    assert tool.description and tool.schema["type"] == "object"


def test_the_older_command_names_and_keys_still_work(asked):
    from zpkt.app.bus import Command

    bus = asked.rig.desk.bus
    assert {"desk.state", "state.read", "panel.apply", "page.apply"} <= set(bus.kinds())
    assert bus.submit(Command("state.read", "agent", {}))[0] == 200
    for key in ("spec", "page"):  # `page` is the older key of page.draft
        code, reply = bus.submit(Command("page.draft", "agent", {key: PAGE}))
        assert code in (200, 422), reply


def desk_pages(asked):
    return asked.rig.get("/api/desk")[1]["pages"]


def test_make_page_returns_a_link_and_the_page_is_listed_but_not_on_the_desk(asked):
    before = desk_pages(asked)
    code, ok = call(asked, "make_page", {"spec": PAGE})
    assert code == 200 and ok["title"] == "Kick: level"
    assert ok["link"] == "/app/#page=kick-level" and ok["markdown"] == "[Kick: level](/app/#page=kick-level)"
    listed = asked.rig.get("/api/pages")[1]["pages"]
    assert [(p["id"], p["made_by"]) for p in listed] == [("kick-level", "agent")]
    assert desk_pages(asked) == before  # drafted, not opened: the agent moved nothing
    assert asked.rig.command("page.layout", {"id": "kick-level"})[0] == 200


def test_opening_the_link_is_the_persons_act_and_puts_the_page_on_the_desk(asked):
    from zpkt.app.bus import Command

    bus = asked.rig.desk.bus
    _, ok = call(asked, "make_page", {"spec": PAGE})
    before = len(desk_pages(asked))
    code, _ = bus.submit(Command("page.open", "agent", {"id": ok["id"]}))
    assert code == 403 and len(desk_pages(asked)) == before  # an agent cannot open its own page
    assert call(asked, "page.open", {"id": ok["id"]})[0] == 404  # and it is not a tool
    code, opened = asked.rig.command("page.open", {"id": ok["id"]})
    assert code == 200 and opened["added"] is True and opened["pages"] == [before] and opened["title"] == "Kick: level"
    mine = desk_pages(asked)[before]
    assert mine["page_id"] == "kick-level" and mine["name"] == "Kick: level"
    code, again = asked.rig.command("page.open", {"id": ok["id"]})  # a second click arms it; no second copy
    assert code == 200 and again["added"] is False and again["pages"] == [before]
    assert len(desk_pages(asked)) == before + 1
    assert asked.rig.command("page.open", {"id": "nothing"})[0] == 400
    assert asked.rig.command("page.open", {"id": "../x"})[0] == 400


def test_the_guide_teaches_links_and_no_longer_the_surface_block():
    from zpkt.app.adapters.agents import GUIDE

    guide = GUIDE.read_text()
    assert "/app/#page=" in guide and "make_page" in guide and "```audio" in guide
    assert "```zpkt-surface" not in guide and "midiSlot" not in guide
