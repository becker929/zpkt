"""The `propose_live` tool: the call blocks while the person decides, nothing moves before the tap, and the reply
says plainly what came of it. On the real server in this process, with a scripted agent and FakeLive."""

from __future__ import annotations

import dataclasses
import threading
import time
from http.server import ThreadingHTTPServer

import pytest

from tests.app.conftest import wait_for
from tests.app.test_ask_http import API, script, start, text
from tests.app.test_live_change import KICK, VOL, names
from tests.app.test_live_propose import CODE, HATS, MIXED, whole
from zpkt.app import web
from zpkt.app.ask import mcp, tools
from zpkt.app.ask.testing import Call, Hold
from zpkt.live import chain, newtrack

SMALL = {"why": "less sat", "steps": [{"set": VOL, "to": 0.5}, {"remove": "desk Sat", "track": HATS}]}


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(chain.time, "sleep", lambda s: None)
    monkeypatch.setattr(newtrack.time, "sleep", lambda s: None)


def events(asked, sid, kind=None):
    return [e for e in asked.ask.store.replay(sid) if kind is None or e["type"] == kind]


def proposing(asked, args, *after):
    """A turn whose agent proposes `args`; returns (the provider, the session, the card's event) once the card shows."""
    p = script(asked, "claude", Call("propose_live", args), *after)
    s = start(asked, "go on")
    card = wait_for(lambda: next(iter(events(asked, s["id"], "permission")), None))
    assert card is not None, events(asked, s["id"])
    return p, s, card


def tap(asked, s, card, option):
    return asked.rig.post(f"{API}/sessions/{s['id']}/permission", {"id": card["id"], "option": option})


def kinds(asked):
    return [(row["kind"], row["status"]) for row in asked.rig.desk.bus.log if row["kind"].startswith("live.")]


def test_the_card_waits_and_nothing_moves_before_the_tap_then_do_it_runs_the_batch(asked):
    rig = asked.rig
    before = whole(rig)
    p, s, card = proposing(asked, MIXED)
    assert card["tool"]["kind"] == "propose_live" and card["tool"]["title"] == "parallel drive"
    assert [o["id"] for o in card["options"]] == ["yes", "no"]
    assert [o["name"] for o in card["options"]] == ["Do it", "Don't"]
    steps = card["tool"]["steps"]
    assert len(steps) == 10 and steps[7] == {"n": 8, "text": "Remove desk Sat from Hats bus", "no_undo": True}
    assert steps[9] == {"n": 10, "text": "Sets the tempo to 91.", "no_undo": True, "code": CODE}
    time.sleep(0.2)  # the call is blocked: the agent has no reply, and nothing has moved or been saved
    assert p.replies == [] and asked.ask.permissions.asking(s["id"]) and asked.ask.is_live(s["id"])
    assert whole(rig) == before and rig.desk.history.entries == [] and rig.desk.history.checkpoints() == []
    assert kinds(asked) == [("live.propose.check", 200)]
    assert tap(asked, s, card, "maybe")[0] == 400 and p.replies == []  # not an offered answer: still waiting
    assert tap(asked, s, card, "yes")[0] == 200
    assert asked.ask.wait_idle()
    ((code, reply),) = p.replies
    assert code == 200 and reply["ok"] and reply["approved"] and reply["done"] == 10, reply
    assert reply["undo"] == "parallel drive (4 controls, 3 devices)" and len(reply["no_undo"]) == 3
    assert rig.live.song.tempo == 91.0 and "desk Sat" not in names(rig, HATS)
    assert kinds(asked) == [("live.propose.check", 200), ("live.propose", 200)]
    row = rig.desk.history.entries[-1]
    assert row["k"] == "change" and row["who"] == "agent" and row["group"] == f"ask-{s['id']}"
    seen = [e for e in events(asked, s["id"]) if e["type"] in ("permission", "permission_answer", "proposal")]
    assert [e["type"] for e in seen] == ["permission", "permission_answer", "proposal"]
    assert seen[1]["answered"] == "yes" and {e["id"] for e in seen} == {card["id"]}
    assert {"state": "done", "done": 10}.items() <= seen[2].items()
    assert tap(asked, s, card, "yes")[0] == 409  # answered once: a second tap finds nothing waiting


def test_dont_changes_nothing_and_the_reply_says_declined(asked):
    rig = asked.rig
    before = whole(rig)
    p, s, card = proposing(asked, MIXED)
    assert tap(asked, s, card, "no")[0] == 200
    assert asked.ask.wait_idle()
    ((code, reply),) = p.replies
    assert code == 200 and reply["ok"] is False and reply["declined"] is True and "nothing changed" in reply["message"]
    assert whole(rig) == before and rig.desk.history.entries == [] and rig.desk.history.checkpoints() == []
    assert kinds(asked) == [("live.propose.check", 200)]  # the move was never sent
    assert events(asked, s["id"], "permission_answer")[0]["answered"] == "no"
    assert {"id": card["id"], "state": "declined", "done": 0}.items() <= events(asked, s["id"], "proposal")[0].items()


def test_no_answer_in_time_changes_nothing_and_the_reply_says_unanswered(asked, monkeypatch):
    rig = asked.rig
    before = whole(rig)
    quick = dataclasses.replace(tools.BY_NAME["propose_live"], wait_s=0.3)
    monkeypatch.setitem(tools.BY_NAME, "propose_live", quick)
    p, s, card = proposing(asked, MIXED)
    assert asked.ask.wait_idle()
    ((code, reply),) = p.replies
    assert code == 200 and reply["ok"] is False and reply["unanswered"] is True and "stopped" not in reply
    assert "nothing changed" in reply["message"]
    assert whole(rig) == before and rig.desk.history.entries == []
    assert events(asked, s["id"], "permission_answer")[0]["answered"] == "cancelled"
    assert events(asked, s["id"], "proposal")[0]["state"] == "unanswered"
    assert tap(asked, s, card, "yes")[0] == 409 and whole(rig) == before  # a late tap moves nothing
    assert events(asked, s["id"], "run_end")[0]["code"] == 0  # the turn went on and ended by itself


def test_stopping_the_turn_ends_the_wait_and_changes_nothing(asked):
    rig = asked.rig
    before = whole(rig)
    p, s, card = proposing(asked, MIXED, text("never said"))
    assert rig.post(f"{API}/sessions/{s['id']}/stop")[1] == {"stopped": True}
    assert asked.ask.wait_idle()
    ((code, reply),) = p.replies
    assert code == 200 and reply["ok"] is False and reply["unanswered"] is True and reply["stopped"] is True
    assert whole(rig) == before and rig.desk.history.entries == []
    assert events(asked, s["id"], "proposal")[0]["state"] == "stopped"
    assert tap(asked, s, card, "yes")[0] == 409 and whole(rig) == before
    assert events(asked, s["id"], "run_end")[0]["signal"] == "SIGTERM" and not events(asked, s["id"], "message")


def test_a_proposal_with_a_problem_shows_no_card(asked):
    rig = asked.rig
    before = whole(rig)
    bad = {"why": "no", "steps": [{"remove": "ghost", "track": KICK}, {"new_track": "audio", "name": "mon X"}]}
    p = script(asked, "claude", Call("propose_live", bad))
    s = start(asked, "go on")
    assert asked.ask.wait_idle()
    ((code, reply),) = p.replies
    assert code == 400 and len(reply["problems"]) == 2 and "nobody was asked" in reply["error"]
    assert events(asked, s["id"], "permission") == [] and events(asked, s["id"], "proposal") == []
    assert whole(rig) == before


def test_with_no_turn_running_nobody_is_asked(asked):
    s = start(asked, "hello")
    assert asked.ask.wait_idle()
    gate = asked.ask.gate
    code, reply = gate.call(s["id"], gate.token(s["id"]), "propose_live", SMALL)
    assert code == 409 and reply["ok"] is False and "nobody to ask" in reply["error"]
    assert events(asked, s["id"], "permission") == [] and asked.rig.desk.history.entries == []
    assert gate.call(s["id"], "wrong", "propose_live", SMALL)[0] == 403


def test_the_set_changed_while_the_card_waited_so_the_batch_is_refused_whole(asked):
    rig = asked.rig
    p, s, card = proposing(asked, SMALL)
    rig.track(HATS).delete_device(1)  # by hand in Live: desk Sat is gone before the tap
    before = whole(rig)
    assert tap(asked, s, card, "yes")[0] == 200
    assert asked.ask.wait_idle()
    ((code, reply),) = p.replies
    assert code == 400 and reply["approved"] and "set changed while the card waited" in reply["error"], reply
    assert 'no device "desk Sat"' in reply["problems"][0]
    assert whole(rig) == before and rig.desk.history.entries == []
    told = events(asked, s["id"], "proposal")[0]
    assert told["state"] == "refused" and told["done"] == 0 and "desk Sat" in told["note"]


def test_a_step_that_fails_after_the_tap_is_told_to_the_agent_and_to_the_card(asked):
    rig = asked.rig
    half = {
        "why": "half",
        "steps": [
            {"remove": "desk Sat", "track": HATS},
            {"code": "raise ValueError('no such clip')", "does": "Breaks."},
            {"set": VOL, "to": 0.5},
        ],
    }
    p, s, card = proposing(asked, half)
    assert tap(asked, s, card, "yes")[0] == 200
    assert asked.ask.wait_idle()
    ((code, reply),) = p.replies
    assert code == 502 and reply["approved"] and reply["done"] == 1 and reply["not_done"] == [2, 3]
    assert "desk Sat" not in names(rig, HATS) and rig.track(KICK).mixer_device.volume.value != 0.5
    told = events(asked, s["id"], "proposal")[0]
    assert told["state"] == "failed" and told["done"] == 1 and told["step"] == 2 and "no such clip" in told["note"]


def test_the_server_answers_other_requests_while_a_proposal_waits(asked):
    """Each request has a thread of its own, so a tool call that waits four minutes holds nothing else up: the
    state is served, a command moves Live (the bus is not held), and the tap itself arrives over HTTP."""
    rig = asked.rig
    assert issubclass(web.DeskHTTPServer, ThreadingHTTPServer) and web.DeskHTTPServer.daemon_threads
    go = threading.Event()
    script(asked, "claude", Hold(go))  # a turn that is running, so there is somebody to ask
    s = start(asked, "wait")
    wait_for(lambda: asked.ask.is_live(s["id"]))
    body = {"session": s["id"], "token": asked.ask.gate.token(s["id"]), "tool": "propose_live", "args": SMALL}
    got: list[tuple[int, dict]] = []
    caller = threading.Thread(target=lambda: got.append(rig.post(f"{API}/tool", body)), daemon=True)
    caller.start()  # this request blocks inside the server until the tap
    card = wait_for(lambda: next(iter(events(asked, s["id"], "permission")), None))
    assert card is not None and caller.is_alive() and got == []
    t0 = time.monotonic()
    assert rig.get("/api/state")[0] == 200
    assert rig.get(f"{API}/sessions/{s['id']}/events")[0] == 200
    code, state = rig.post(f"{API}/tool", {**body, "tool": "read_state", "args": {}})  # the same agent's other tool
    assert code == 200 and state["set"] == "HW002_121_pp_finish"
    assert rig.command("mix.set", {"writes": [["Hats bus/volume", 0.3]]})[0] == 200  # Live is not held either
    assert time.monotonic() - t0 < 5.0 and caller.is_alive() and got == []
    assert rig.track(HATS).mixer_device.volume.value == pytest.approx(0.3) and "desk Sat" in names(rig, HATS)
    assert tap(asked, s, card, "yes")[0] == 200
    caller.join(10)
    assert not caller.is_alive() and got[0][0] == 200 and got[0][1]["approved"] and got[0][1]["done"] == 2
    assert "desk Sat" not in names(rig, HATS)
    go.set()
    assert asked.ask.wait_idle()


def test_the_tool_servers_http_timeout_is_longer_than_the_wait():
    wait = tools.BY_NAME["propose_live"].wait_s
    assert wait == tools.PROPOSE_WAIT_S == 240.0
    assert mcp.timeout_for("propose_live") == wait + mcp.TIMEOUT_S > wait
    assert mcp.timeout_for("propose_live") < 600  # Gemini CLI gives an MCP call ten minutes
    assert all(mcp.timeout_for(t.name) == mcp.TIMEOUT_S for t in tools.TOOLS if t.name != "propose_live")
    assert mcp.timeout_for(None) == mcp.TIMEOUT_S


def test_the_tool_is_described_and_its_commands_are_registered(asked):
    tool = tools.BY_NAME["propose_live"]
    assert (tool.kind, tool.check) == ("live.propose", "live.propose.check")
    assert {tool.kind, tool.check} <= set(asked.rig.desk.bus.kinds())
    for words in ("Do it", "Don't", "declined", "unanswered", "no_undo", "remove", "new_track", "does", "4 minutes"):
        assert words in tool.description, words
    props = tool.schema["properties"]["steps"]["items"]["properties"]
    assert {"remove", "new_track", "name", "code", "does", "set", "add", "device", "move"} <= set(props)
    assert [t.name for t in tools.TOOLS if t.check] == ["propose_live"]
