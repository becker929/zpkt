"""Making pages through the app: the gate, the bus, the desk and the old "Make a surface" route (FakeLive only)."""

from __future__ import annotations

import json
import queue

from zpkt.app import pages
from zpkt.app.bus import Command
from zpkt.live import page as P

SPEC = {
    "title": "Kick sub and knock",
    "groups": [
        {"name": "Sub", "controls": [
            {"target": "Kick bus/desk EQ/1 Gain A", "role": "level", "weight": 3},
            {"target": "Kick bus/desk EQ/1 Frequency A", "role": "tone", "range": ["34 Hz", "42 Hz"]}]},
        {"name": "Glue", "controls": [{"target": "Kick bus/desk Glue/Threshold"}, {"target": "Kick bus/mute"}]},
    ],
}  # fmt: skip


def make(rig, spec=SPEC, who="agent", **args):
    return rig.desk.bus.submit(Command("page.make", who, {"spec": spec, **args}))


def desk_pages(rig):
    return rig.get("/api/desk")[1]["pages"]


def test_an_agent_makes_a_page_without_asking_and_it_lands_on_the_desk(rig):
    before = len(desk_pages(rig))
    code, reply = make(rig)
    assert code == 200 and reply["id"] == "kick-sub-and-knock" and reply["made_by"] == "agent"
    saved = json.loads((rig.tmp / "sets" / "pages" / "HW002_121_pp_finish" / "kick-sub-and-knock.json").read_text())
    assert saved["schema"] == 2 and saved["made_by"] == "agent" and saved["at"]
    mine = desk_pages(rig)[before:]
    assert [p["name"] for p in mine] == ["Kick sub and knock"] and mine[0]["page_id"] == reply["id"]
    assert rig.desk.call("m.DESK.page") == reply["pages"][0] == before  # armed
    assert rig.desk.history.entries == []  # making a page moves nothing in the mix


def test_the_gate_rejects_a_bad_spec_with_the_reasons_and_saves_nothing(rig):
    before = len(desk_pages(rig))
    bad = {
        "title": "t",
        "groups": [{"name": "g", "controls": [{"target": "Nope/volume"}, {"target": "Kick bus/volume"}]}],
    }
    code, reply = make(rig, bad)
    assert code == 422 and reply["ok"] is False
    assert "Nope/volume: not in the open set" in reply["error"] and reply["problems"][0]["level"] == "error"
    assert len(desk_pages(rig)) == before and not (rig.tmp / "sets" / "pages").exists()
    assert make(rig, {"title": "no groups"})[0] == 422  # not a page at all
    assert make(rig, "text")[0] == 422


def test_an_agent_may_not_move_live_with_the_same_door(rig):
    assert rig.desk.bus.submit(Command("mix.set", "agent", {"norms": [["Kick bus/volume", 0.1]]}))[0] == 403


def test_the_web_may_say_it_is_an_agent_but_cannot_approve_itself(rig):
    code, reply = rig.command("page.make", {"spec": SPEC}, who="agent")
    assert code == 200 and reply["made_by"] == "agent"
    assert rig.command("mix.set", {"norms": [["Kick bus/volume", 0.1]]}, who="agent", approval="user")[0] == 403
    code, reply = rig.command("page.lint", {"spec": SPEC}, who="minilab")
    assert code == 400 and "who may be" in reply["error"]


def test_lint_checks_and_saves_nothing(rig):
    code, reply = rig.desk.bus.submit(Command("page.lint", "agent", {"spec": SPEC}))
    assert code == 200 and reply["ok"] and reply["layout"]["groups"][0]["name"] == "Sub"
    assert not (rig.tmp / "sets" / "pages").exists()


def test_a_page_for_another_set_is_refused(rig):
    rig.live.song.file_path = "/Sets/HW002_121_pp_B Project/HW002_121_pp_B.als"
    rig.desk.bus.guard.forget()
    code, reply = make(rig)
    assert code == 409 and "Open that set first" in reply["error"]
    assert not (rig.tmp / "sets" / "pages").exists()


def test_a_page_wider_than_the_minilab_becomes_pages_in_order(rig):
    bands = [f"Kick bus/desk EQ/{n} Frequency A" for n in range(1, 9)]
    spec = {"title": "EQ", "groups": [
        {"name": "low", "controls": [{"target": t} for t in bands[:5]]},
        {"name": "high", "controls": [{"target": t} for t in bands[5:]]},
        {"name": "q", "controls": [{"target": "Kick bus/desk EQ/1 Q A"}]}]}  # fmt: skip
    before = len(desk_pages(rig))
    code, reply = make(rig, spec)
    assert code == 200 and reply["pages"] == [before, before + 1]
    mine = desk_pages(rig)[before:]
    assert [p["name"] for p in mine] == ["EQ 1", "EQ 2"] and [p["hardware"] for p in mine] == [0, 1]


def test_layout_greys_a_target_the_set_lost(rig):
    path = rig.tmp / "sets" / "pages" / "HW002_121_pp_finish" / "gone.json"
    path.write_text(json.dumps({"schema": 2, "title": "Gone", "groups": [{"name": "g", "controls": [
        {"target": "Ghost/volume"}, {"target": "Kick bus/volume"}]}]}))  # fmt: skip
    code, reply = rig.command("page.layout", {"id": "gone"})
    assert code == 200
    ghost, kick = reply["layout"]["groups"][0]["controls"]
    assert "Ghost" in ghost["missing"] and ghost["widget"] == "knob" and kick["missing"] is None
    assert rig.command("page.layout", {"id": "../x"})[0] == 400
    assert rig.command("page.layout", {"id": "nothing"})[0] == 400


def test_the_list_of_pages(rig):
    make(rig)
    code, reply = rig.get("/api/pages")
    assert code == 200 and reply["pages"] == [
        {"id": "kick-sub-and-knock", "title": "Kick sub and knock", "made_by": "agent",
         "at": reply["pages"][0]["at"], "controls": 4}
    ]  # fmt: skip


def test_make_a_surface_is_a_caller_of_page_make(rig, monkeypatch):
    from zpkt.app import surfaces

    seen: list[str] = []

    def claude(prompt: str) -> str:
        seen.append(prompt)
        return json.dumps(SPEC)

    monkeypatch.setattr(surfaces, "ask_claude", claude)
    q: queue.Queue = queue.Queue()
    rig.desk.clients.append(q)
    try:
        assert rig.post("/api/surface/make", {"text": "the kick"}) == (200, {"ok": True})
        msgs: list[dict] = []
        while not msgs or msgs[-1]["status"] not in ("done", "error"):
            m = q.get(timeout=10)
            if m["t"] == "surface":
                msgs.append(m)
    finally:
        rig.desk.clients.remove(q)
    assert msgs[-1]["status"] == "done" and "Kick sub and knock" in msgs[-1]["msg"]
    assert "Kick bus/desk EQ/1 Gain A" in seen[0]  # the set's state keys, one a line
    assert desk_pages(rig)[-1]["name"] == "Kick sub and knock"
    assert [e["kind"] for e in rig.desk.bus.log if e["kind"] == "page.make"] == ["page.make"]
    assert pages.listing(rig.desk)[0]["made_by"] == "you"


def test_a_rejected_answer_to_make_a_surface_says_why(rig, monkeypatch):
    from zpkt.app import surfaces

    bad = {"title": "t", "groups": [{"name": "g", "controls": [{"target": "Nope/volume"}]}]}
    monkeypatch.setattr(surfaces, "ask_claude", lambda prompt: json.dumps(bad))
    q: queue.Queue = queue.Queue()
    rig.desk.clients.append(q)
    rig.post("/api/surface/make", {"text": "x"})
    msg = {}
    while msg.get("status") not in ("done", "error"):
        m = q.get(timeout=10)
        if m["t"] == "surface":
            msg = m
    rig.desk.clients.remove(q)
    assert msg["status"] == "error" and "Nope/volume" in msg["msg"]


def test_the_prompt_names_every_key_and_the_rules():
    inv = {("Kick bus", "", "volume"): {"now": "0 dB", "min": "-inf", "max": "6 dB", "q": False},
           ("Kick bus", "desk EQ", "1 Gain A"): {"now": "0 dB", "min": "-15 dB", "max": "15 dB", "q": False},
           ("Kick bus", "", "send:Space"): {"now": "-inf", "min": "-inf", "max": "0 dB", "q": False}}  # fmt: skip
    text = pages.prompt_for("more room", inv, ["A page"])
    for key in ("Kick bus/volume", "Kick bus/desk EQ/1 Gain A", "Kick bus/send Space"):
        assert f"- {key}:" in text
    assert "more room" in text and "Never write widget" in text
    assert P.MAX_LABEL == 10 and "at most 10 characters" in text
