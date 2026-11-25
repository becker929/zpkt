"""One store of Options. What an agent proposes is an Option like any other: listed with the rendered ones, shown
in the Options sheet, and picked with the same command. A pick by you puts it on Now, tagged `you`."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from zpkt.app import options as O
from zpkt.app.bus import Command

from .test_ask_tools import call

SCHEMAS = Path(__file__).resolve().parents[2] / "lib" / "contracts"
KEY = "Kick bus/volume"
KICK_DOWN = {"title": "Kick down", "why": "It masks the bass.", "moves": [{"target": KEY, "to": 0.3}]}


def propose(asked, option: dict = KICK_DOWN) -> str:
    code, body = call(asked, "propose_option", {"option": option})
    assert code == 200, body
    return body["option"]["id"]


def volume(rig) -> float:
    return rig.track("Kick bus").mixer_device.volume.value


# ---- one store -------------------------------------------------------------------------------------------------------


def test_the_app_has_one_store_and_the_agents_adapter_makes_none(asked):
    from zpkt.app import agent_commands
    from zpkt.app.adapters import agents

    assert not hasattr(agents, "OptionStore") and not hasattr(agent_commands, "OptionStore")
    options = asked.rig.desk.options
    assert asked.rig.desk.bus.option_picked == options.is_picked
    assert options.proposals.file == asked.adapter.data_dir / "options.json"  # the file stays where it was


def test_a_proposal_is_an_option_in_the_one_list(asked):
    oid = propose(asked)
    code, body = asked.rig.command("options.list")
    listed = {o["id"]: o for o in body["options"]}
    assert code == 200 and oid in listed
    option = listed[oid]
    jsonschema.validate(option, json.loads((SCHEMAS / "option.schema.json").read_text()))
    assert option["kind"] == "proposal" and option["title"] == "Kick down" and option["note"] == "It masks the bass."
    assert option["progress"] == "proposed" and option["now"] is None and option["made_by"] == "agent"
    assert [v["writes"] for v in option["versions"]] == [[[KEY, 0.3]]]
    assert asked.rig.command("options.get", {"option": oid})[1]["option"]["id"] == oid
    assert asked.rig.get(f"/api/options?option={oid}")[1]["kind"] == "proposal"


def test_a_proposal_reaches_the_shell_as_it_is_made(asked):
    q = asked.rig.desk.subscribe(app=True)
    oid = propose(asked)
    seen = []
    while not q.empty():
        seen.append(q.get_nowait())
    assert any(m["t"] == "options" and oid in {o["id"] for o in m["options"]} for m in seen)


def test_proposing_moves_nothing(asked):
    before, entries = volume(asked.rig), list(asked.rig.desk.history.entries)
    propose(asked)
    assert volume(asked.rig) == before and asked.rig.desk.history.entries == entries


# ---- picking ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["options.pick", "option.pick"])
def test_your_pick_puts_the_proposal_on_now_tagged_you(asked, kind):
    rig = asked.rig
    oid = propose(asked)
    code, body = rig.command(kind, {"option": oid})
    assert code == 200 and body["option"]["state"] == "picked", body
    assert volume(rig) == pytest.approx(0.3)
    last = rig.desk.history.entries[-1]
    assert last["who"] == "you" and body["entry"] == last["id"]
    assert rig.desk.bus.log[-1]["who"] == "you"
    option = rig.command("options.get", {"option": oid})[1]["option"]
    assert option["progress"] == "picked" and option["now"] == "v1"
    assert rig.desk.options.is_picked(oid)
    assert rig.post("/api/undo")[0] == 200  # one undo takes the pick back
    assert volume(rig) != pytest.approx(0.3)


def test_only_your_pick_lets_the_agents_own_move_pass(asked):
    bus = asked.rig.desk.bus
    oid = propose(asked)
    move = Command("mix.set", "agent", {"writes": [[KEY, 0.4]]}, approval=f"option:{oid}", group="g")
    assert bus.submit(move)[0] == 403  # proposed, not picked
    assert asked.rig.command("options.pick", {"option": oid})[0] == 200
    assert bus.submit(move)[0] == 200


def test_an_agent_cannot_pick_and_its_use_of_a_picked_option_picks_no_other(asked):
    bus = asked.rig.desk.bus
    first, second = propose(asked), propose(asked, {**KICK_DOWN, "title": "Kick lower"})
    assert bus.submit(Command("options.pick", "agent", {"option": first}))[0] == 403
    assert bus.submit(Command("option.pick", "agent", {"option": first}))[0] == 403
    assert asked.rig.command("options.pick", {"option": first})[0] == 200
    approved = f"option:{first}"
    code, _ = bus.submit(Command("options.pick", "agent", {"option": second}, approval=approved, group="g"))
    assert code == 200  # its move passes on your pick of the first ...
    assert not asked.rig.desk.options.is_picked(second)  # ... but that does not pick the second for it
    assert bus.submit(Command("mix.set", "agent", {"writes": [[KEY, 0.5]]}, approval=f"option:{second}"))[0] == 403


def test_a_pick_is_held_by_the_wrong_set_guard(asked):
    rig = asked.rig
    oid = propose(asked)
    rig.live.song.file_path = "/Sets/other Project/other.als"
    rig.desk.bus.guard.forget()
    before = volume(rig)
    code, body = rig.command("options.pick", {"option": oid})
    assert code == 409 and "this page is for" in body["error"]
    assert volume(rig) == before and not rig.desk.options.is_picked(oid)


def test_a_proposal_with_no_moves_is_picked_without_moving(asked):
    oid = propose(asked, {"title": "Leave it", "why": "It is fine."})
    entries = list(asked.rig.desk.history.entries)
    code, body = asked.rig.command("options.pick", {"option": oid})
    assert code == 200 and body["option"]["state"] == "picked" and body["entry"] is None
    assert asked.rig.desk.history.entries == entries


def test_a_proposal_whose_value_is_text_says_why_it_cannot_be_made_now(asked):
    oid = propose(asked, {**KICK_DOWN, "moves": [{"target": KEY, "to": "-6 dB"}]})
    option = asked.rig.command("options.get", {"option": oid})[1]["option"]
    assert option["versions"][0]["writes"] is None and "as text" in option["note"]
    code, body = asked.rig.command("options.pick", {"option": oid})
    assert code == 400 and "as text" in body["error"]
    assert not asked.rig.desk.options.is_picked(oid)


def test_a_pick_of_an_option_with_several_versions_must_name_one(asked):
    oid = propose(asked)
    assert asked.rig.command("options.pick", {"option": oid, "version": "v1"})[0] == 200
    assert asked.rig.command("options.pick", {"option": oid, "version": "v9"})[0] == 400
    assert asked.rig.command("options.pick", {"option": "nope"})[0] == 400


# ---- the pure part ---------------------------------------------------------------------------------------------------


def test_from_proposal():
    proposal = {
        "id": "ab12cd34",
        "title": "Kick down",
        "why": "It masks the bass.",
        "moves": [{"target": KEY, "to": 0.3}, {"target": "Bass/volume", "to": 1}],
        "made_by": "agent",
        "at": "2026-11-24 10:00:00",
        "session": "s1",
        "state": "picked",
    }
    option = O.from_proposal(proposal)
    assert option["id"] == "ab12cd34" and option["kind"] == "proposal" and option["status"] == "ready"
    assert option["now"] == "v1" and option["progress"] == "picked" and option["made"] > 0
    assert option["versions"][0]["writes"] == [[KEY, 0.3], ["Bass/volume", 1.0]]
    assert O.from_proposal({**proposal, "state": "proposed", "at": "?"})["made"] == 0.0
    assert "proposal" in O.KINDS


# ---- the button ------------------------------------------------------------------------------------------------------


def test_the_shell_has_a_pick_button_and_no_emoji_in_it():
    page = (Path(O.__file__).parent / "static" / "app.html").read_text()
    assert 'id="onow"' in page and '<use href="#i-pick"/>' in page and '<symbol id="i-pick"' in page
    assert "options.pick" in page
