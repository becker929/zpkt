"""Compare states on a Page, in the app (on FakeLive): a press writes a state's values as one move and one History
row, one undo takes it back, the lit state is derived from the values, an agent makes and updates the page but
never switches it, and the same pad on the (fake) MiniLab does what the pad on the screen does."""

from __future__ import annotations

import json

import pytest

from tests.app.conftest import wait_for
from zpkt.app import agent_commands
from zpkt.app import pages as app_pages
from zpkt.app.bus import Command
from zpkt.live import describe
from zpkt.live import page as P

VOL, GAIN, DRYWET = "Kick bus/volume", "Kick bus/desk EQ/1 Gain A", "Kick bus/desk Glue/Dry/Wet"
SPEC = {
    "title": "Kick: hotter?",
    "groups": [{"name": "Kick", "controls": [{"target": VOL, "label": "Level"}, {"target": GAIN, "label": "Sub"}]}],
    "compare": {
        "name": "Kick",
        "states": [
            {"name": "as it is"},
            {"name": "hotter", "writes": [{"target": VOL, "to": 0.8}, {"target": GAIN, "to": 0.7}]},
            {"name": "drier", "writes": [{"target": DRYWET, "to": 0.2}]},  # a value no control of the page shows
        ],
    },
}


@pytest.fixture()
def rig(rig):
    """The rig with the agent's commands on its bus (the Agents adapter puts them there in the app)."""
    agent_commands.register(rig.desk.bus, rig.desk)
    return rig


def raw(rig, key):
    """A value in Live itself, asked afresh."""
    return describe.look(rig.live, [key])[0][key]["now"].raw


def draft(rig, spec, who="agent"):
    return rig.desk.bus.submit(Command("page.draft", who, {"spec": spec}, group="ask-s1"))


def opened(rig, spec=SPEC):
    """The page as an agent drafted it and the person opened it: on the desk and armed."""
    code, reply = draft(rig, spec)
    assert code == 200, reply
    code, shown = rig.command("page.open", {"id": reply["id"]})
    assert code == 200, shown
    return reply["id"]


def press(rig, page_id, state):
    return rig.command("page.compare", {"id": page_id, "state": state})


def on(rig, page_id):
    view = next(c for c in rig.command("desk.state")[1]["compare"] if c["page"] == page_id)
    return view["on"]


def settled(rig, key, want):
    assert wait_for(lambda: abs((rig.desk.history.value(key) or [0, -9])[1] - want) < 1e-5)


def test_a_draft_keeps_the_values_the_controls_had_and_moves_nothing(rig):
    before = {k: raw(rig, k) for k in (VOL, GAIN)}
    code, reply = draft(rig, SPEC)
    assert code == 200 and reply["compare"]["states"] == ["as it is", "hotter", "drier"]
    saved = json.loads((app_pages.pages_dir(rig.desk) / reply["file"]).read_text())
    base = saved["compare"]["baseline"]
    assert base[VOL] == pytest.approx(before[VOL]) and base[GAIN] == pytest.approx(before[GAIN]) and DRYWET in base
    # every state is whole on disk: the first is the mix as it was, the others take what they do not name from it
    writes = [{w["target"]: w["to"] for w in s["writes"]} for s in saved["compare"]["states"]]
    assert writes[0] == base
    assert writes[1] == {VOL: 0.8, GAIN: 0.7, DRYWET: base[DRYWET]}
    assert writes[2] == {VOL: base[VOL], GAIN: base[GAIN], DRYWET: 0.2}
    assert rig.desk.history.entries == [] and raw(rig, VOL) == pytest.approx(before[VOL])
    assert all(pg.get("page_id") != reply["id"] for pg in rig.desk.cfg()["pages"])  # drafted, not on the desk


def test_a_press_is_one_write_one_history_row_and_one_undo(rig, monkeypatch):
    page_id = opened(rig)
    base = {k: raw(rig, k) for k in (VOL, GAIN, DRYWET)}
    assert on(rig, page_id) == "as it is"
    sent: list[str] = []
    real = rig.desk.call
    monkeypatch.setattr(rig.desk, "call", lambda expr: (sent.append(expr), real(expr))[1])
    code, reply = press(rig, page_id, 1)
    assert code == 200 and reply["missing"] == []
    assert [s for s in sent if "set_raw" in s] and len([s for s in sent if "set_raw" in s]) == 1  # one command to Live
    assert raw(rig, VOL) == pytest.approx(0.8) and raw(rig, GAIN) == pytest.approx(0.7)
    assert raw(rig, DRYWET) == pytest.approx(base[DRYWET])
    moves = [e for e in rig.desk.history.entries if e["k"] == "move"]
    assert len(moves) == 1 and moves[0]["who"] == "you"
    assert moves[0]["compare"] == {"page": page_id, "name": "Kick", "from": "as it is", "to": "hotter"}
    assert {m["key"] for m in moves[0]["moves"]} == {VOL, GAIN}  # what did not differ did not move
    settled(rig, VOL, 0.8)
    assert on(rig, page_id) == "hotter"
    # the state is named or numbered; the third writes a value that is on no knob of the page
    assert press(rig, page_id, "drier")[0] == 200
    assert raw(rig, DRYWET) == pytest.approx(0.2) and raw(rig, VOL) == pytest.approx(base[VOL])
    assert [e.get("compare", {}).get("to") for e in rig.desk.history.entries if e["k"] == "move"] == ["hotter", "drier"]
    # one undo is one whole switch back
    assert rig.command("history.undo")[0] == 200
    assert raw(rig, VOL) == pytest.approx(0.8) and raw(rig, DRYWET) == pytest.approx(base[DRYWET])
    assert rig.command("history.undo")[0] == 200
    assert {k: raw(rig, k) for k in base} == pytest.approx(base)
    settled(rig, VOL, base[VOL])
    assert on(rig, page_id) == "as it is"
    assert press(rig, page_id, 0)[1]["entry"] is None  # already there: nothing to write, no row


def test_the_lit_state_is_derived_so_a_turned_knob_puts_every_pad_out(rig):
    page_id = opened(rig)
    press(rig, page_id, 1)
    settled(rig, VOL, 0.8)
    assert on(rig, page_id) == "hotter"
    assert rig.command("mix.set", {"writes": [[VOL, 0.6]]})[0] == 200  # somebody turns one of its knobs
    settled(rig, VOL, 0.6)
    assert on(rig, page_id) is None
    assert rig.command("mix.set", {"writes": [[VOL, 0.8]]})[0] == 200  # and back, by hand: it is on again
    settled(rig, VOL, 0.8)
    assert on(rig, page_id) == "hotter"
    saved = json.loads((app_pages.pages_dir(rig.desk) / f"{page_id}.json").read_text())
    assert "on" not in saved["compare"] and "lit" not in json.dumps(saved)  # nothing about it is stored


def test_an_agent_makes_the_page_and_cannot_switch_it(rig):
    page_id = opened(rig)
    before = raw(rig, VOL)
    code, reply = rig.desk.bus.submit(Command("page.compare", "agent", {"id": page_id, "state": 1}))
    assert code == 403 and "cannot change Live" in reply["error"]
    assert (
        rig.desk.bus.submit(Command("page.compare", "agent", {"id": page_id, "state": 1}, approval="option:x"))[0]
        == 403
    )
    assert raw(rig, VOL) == pytest.approx(before) and rig.desk.history.entries == []


def test_an_agent_updates_its_page_in_place_and_keeps_the_way_back(rig):
    page_id = opened(rig)
    base_vol = raw(rig, VOL)
    names = rig.desk.page_names()
    at = rig.state()["page"]
    press(rig, page_id, 1)  # the person is listening to "hotter"
    settled(rig, VOL, 0.8)
    entries = len(rig.desk.history.entries)
    brighter = json.loads(json.dumps(SPEC))
    brighter["id"] = page_id
    brighter["compare"]["states"][1]["writes"] = [{"target": VOL, "to": 0.8}, {"target": GAIN, "to": 0.9}]
    brighter["compare"]["states"][2] = {"name": "brighter", "writes": [{"target": GAIN, "to": 1.0}]}
    brighter["groups"][0]["controls"].append({"target": DRYWET, "label": "Glue"})
    code, reply = draft(rig, brighter)
    assert code == 200 and reply["updated"] and reply["id"] == page_id
    # the same page, in the same place, and the desk still on it; no second page piles up
    assert rig.desk.page_names() == names and rig.state()["page"] == at
    assert [p["id"] for p in rig.get("/api/pages")[1]["pages"]].count(page_id) == 1
    assert len(list(app_pages.pages_dir(rig.desk).glob("*.json"))) == 1
    # updating moved nothing in Live and wrote no history
    assert raw(rig, VOL) == pytest.approx(0.8) and len(rig.desk.history.entries) == entries
    # the way back is still the mix as it was when the page was first made, not as it is now
    saved = json.loads((app_pages.pages_dir(rig.desk) / f"{page_id}.json").read_text())
    assert saved["compare"]["baseline"][VOL] == pytest.approx(base_vol)
    assert [s["name"] for s in saved["compare"]["states"]] == ["as it is", "hotter", "brighter"]
    layout = rig.command("page.layout", {"id": page_id})[1]["layout"]
    assert [s["name"] for s in layout["compare"]["states"]] == ["as it is", "hotter", "brighter"]
    assert any(c["target"] == DRYWET for g in layout["groups"] for c in g["controls"])  # the new knob is drawn
    assert on(rig, page_id) is None  # "hotter" now means other values: no pad is lit until the person presses
    assert press(rig, page_id, "as it is")[0] == 200 and raw(rig, VOL) == pytest.approx(base_vol)


def test_an_agent_cannot_write_over_a_page_it_did_not_make_or_guess_an_id(rig):
    code, mine = rig.command("page.make", {"spec": SPEC})
    assert code == 200
    code, reply = draft(rig, {**SPEC, "id": mine["id"]})
    assert code == 400 and "not made by an agent" in reply["error"]
    code, reply = draft(rig, {**SPEC, "id": "no-such-page"})
    assert code == 400 and "leave 'id' out" in reply["error"]
    assert draft(rig, {**SPEC, "id": "../x"})[0] == 400


def test_the_linter_is_the_gate_for_compare_states(rig):
    bad = json.loads(json.dumps(SPEC))
    bad["compare"]["states"][1]["writes"] = [{"target": VOL, "to": 7.0}, {"target": "No such/volume", "to": 0.1}]
    code, reply = draft(rig, bad)
    assert code == 422
    text = " ".join(p["text"] for p in reply["problems"])
    assert "outside its raw range" in text and "not in the open set" in text
    assert list(app_pages.pages_dir(rig.desk).glob("*.json")) == []


def test_a_press_for_a_page_that_is_not_on_the_desk_is_refused_with_what_to_do(rig):
    _, reply = draft(rig, SPEC)
    code, body = press(rig, reply["id"], 1)
    assert code == 409 and "Open the page again" in body["error"]
    assert press(rig, "nope", 1)[0] == 400
    page_id = opened(rig, {**SPEC, "title": "Second"})
    assert press(rig, page_id, 9)[0] == 400 and press(rig, page_id, "louder")[0] == 400


# ---- the MiniLab's pad (the fake controller; the real one is not tested here) ------------------------------------------


def pad(rig, bank, number):
    getattr(rig.minilab.elements, f"pad_bank_{bank}_raw")[number - 1].receive(127)


def test_the_same_pad_on_the_minilab_switches_the_state_as_the_minilab(rig):
    page_id = opened(rig)
    base = raw(rig, VOL)
    layout = rig.command("page.layout", {"id": page_id})[1]["layout"]
    slots = {s["name"]: s["slot"] for s in layout["compare"]["states"]}
    assert slots == {"as it is": "b6", "hotter": "b7", "drier": "b8"}  # the last pads, one each
    page = rig.state()["page"]
    pad(rig, "a", 7)
    assert wait_for(lambda: any(e.get("compare") for e in rig.desk.history.entries))
    entry = next(e for e in rig.desk.history.entries if e.get("compare"))
    assert entry["who"] == "minilab" and entry["compare"]["to"] == "hotter" and entry["compare"]["from"] == "as it is"
    assert raw(rig, VOL) == pytest.approx(0.8)
    assert rig.state()["page"] == page  # the pad switched the state: it did not arm another page
    settled(rig, VOL, 0.8)
    assert on(rig, page_id) == "hotter"
    # bank B does the same; one undo takes a switch back
    pad(rig, "b", 6)
    assert wait_for(lambda: abs(raw(rig, VOL) - base) < 1e-6)
    assert wait_for(lambda: len([e for e in rig.desk.history.entries if e.get("compare")]) == 2)
    assert rig.command("history.undo")[0] == 200 and raw(rig, VOL) == pytest.approx(0.8)


def test_the_pads_light_follows_the_values_and_other_pads_still_arm_pages(rig):
    page_id = opened(rig)
    pads = rig.minilab.elements.pad_bank_a_raw

    def lights():
        return [p.sent[-1] if p.sent else None for p in pads[5:8]]

    assert lights() == [127, 0, 0]  # "as it is" holds when the page is armed
    press(rig, page_id, 1)  # from the screen
    assert wait_for(lambda: lights() == [0, 127, 0])
    rig.command("mix.set", {"writes": [[VOL, 0.55]]})  # a knob turned: no state holds
    assert wait_for(lambda: lights() == [0, 0, 0])
    assert rig.minilab.elements.pad_bank_b_raw[6].sent[-1] == 0  # both banks show the same
    armed = rig.state()["page"]
    pad(rig, "a", 1)  # a pad that holds no state arms its page, as always
    assert wait_for(lambda: rig.state()["page"] == 0) and armed != 0
    assert lights() == [0, 0, 0]


def test_the_pager_and_the_page_model_hold_a_state_by_the_same_rule():
    from zpkt.app.minilab.core import pagercore

    core = pagercore()
    for value, want, lo, hi, quantized in [
        (0.8, 0.8, 0.0, 1.0, False),
        (0.8009, 0.8, 0.0, 1.0, False),
        (0.802, 0.8, 0.0, 1.0, False),
        (-11.9, -12.0, -36.0, 36.0, False),
        (-11.99, -12.0, -36.0, 36.0, False),
        (1.0, 1, 0.0, 3.0, True),
        (2.0, 1, 0.0, 3.0, True),
        (True, 1.0, 0.0, 1.0, True),
        (None, 1.0, 0.0, 1.0, True),
    ]:
        assert core.holds(value, want, lo, hi, quantized) == P.holds(value, want, lo, hi, quantized)
    assert core.COMPARE_STEP == P.COMPARE_STEP
