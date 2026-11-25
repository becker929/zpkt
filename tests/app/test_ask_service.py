"""The Ask service on a scripted provider: a turn from prompt to run_end, the budget, stop, engine switching."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from zpkt.app.ask.provider import Outcome
from zpkt.app.ask.service import Ask
from zpkt.app.ask.store import Refused
from zpkt.app.ask.testing import Call, Permit, ScriptedProvider, Wait
from zpkt.app.ask.tools import ToolGate
from zpkt.app.bus import Bus


def make(tmp_path: Path, **providers: ScriptedProvider) -> Ask:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    ask = Ask(tmp_path / "ask", dict(providers), ToolGate(Bus()), guide="THE GUIDE", home=tmp_path)
    ask.workspaces.list.append({"id": "work", "name": "Work", "path": str(work)})
    ask.app_url = "http://127.0.0.1:1"
    return ask


def text(t: str) -> dict:
    return {"type": "message", "role": "assistant", "content": t, "delta": True}


def types(ask: Ask, sid: str) -> list[str]:
    return [e["type"] for e in ask.store.replay(sid)]


def test_a_turn_runs_to_its_end_and_every_event_is_stored(tmp_path):
    claude = ScriptedProvider("claude", [{"type": "init"}, text("Hello"), {"type": "result", "status": "success"}])
    ask = make(tmp_path, claude=claude)
    s = ask.create("work", "say hi", engine="claude")
    assert ask.wait_idle()
    assert types(ask, s["id"]) == ["prompt", "init", "message", "result", "run_end"]
    prompt, *_, end = ask.store.replay(s["id"])
    assert prompt["engine"] == "claude" and prompt["mode"] == "plan" and prompt["text"] == "say hi"
    assert end["code"] == 0 and end["engine"] == "claude" and not end["signal"]
    assert s["title"] == "say hi" and not ask.is_live(s["id"])
    turn = claude.seen[0]
    assert turn.system == "THE GUIDE" and turn.resume is False and turn.session["cwd"].endswith("work")


def test_the_prompt_event_is_the_persons_words_and_the_agent_gets_more(tmp_path):
    claude = ScriptedProvider("claude", [])
    ask = make(tmp_path, claude=claude)
    s = ask.create("work", "HW002 louder", engine="claude", extra="Surface state: x")
    ask.wait_idle()
    assert ask.store.replay(s["id"])[0]["text"] == "HW002 louder"
    assert ask.store.replay(s["id"])[0]["extra"] is True
    assert "Surface state: x" in claude.seen[0].prompt


def test_refused_turns_say_why_and_leave_no_empty_session(tmp_path):
    ask = make(tmp_path, claude=ScriptedProvider("claude", []))
    for kw, why in (
        ({"prompt": " "}, "Empty prompt"),
        ({"engine": "nope"}, "Invalid engine"),
        ({"mode": "x"}, "Invalid mode"),
        ({"model": "a b"}, "Invalid model"),
    ):
        args = {"prompt": "hi", "engine": "claude", **kw}
        with pytest.raises(Refused, match=why):
            ask.create("work", **args)
    with pytest.raises(Refused, match="Unknown workspace"):
        ask.create("nope", "hi", engine="claude")
    assert ask.store.all_sessions() == []


def test_one_run_per_session_and_a_cap_on_all(tmp_path):
    ask = make(tmp_path, claude=ScriptedProvider("claude", [Wait()]))
    ask.max_live = 2
    a = ask.create("work", "one", engine="claude")
    with pytest.raises(Refused) as busy:
        ask.send(a, "again", engine="claude")
    assert busy.value.code == 409
    ask.create("work", "two", engine="claude")
    with pytest.raises(Refused) as full:
        ask.create("work", "three", engine="claude")
    assert full.value.code == 429
    assert len(ask.store.all_sessions()) == 2  # the refused one left nothing behind
    for s in ask.store.all_sessions():
        assert ask.stop(s["id"])
    assert ask.wait_idle()
    assert not ask.stop(a["id"])


def test_stop_ends_the_run_and_says_stopped(tmp_path):
    ask = make(tmp_path, claude=ScriptedProvider("claude", [text("working"), Wait()]))
    s = ask.create("work", "go", engine="claude")
    assert ask.is_live(s["id"]) and ask.sessions()[0]["running"]
    ask.stop(s["id"])
    assert ask.wait_idle()
    end = ask.store.replay(s["id"])[-1]
    assert end["type"] == "run_end" and end["signal"] == "SIGTERM"
    ask.send(s, "again", engine="claude")
    with pytest.raises(Refused, match="Session is running"):
        ask.remove(s["id"])
    ask.stop(s["id"])
    ask.wait_idle()


def test_the_failure_budget_stops_a_run_that_keeps_failing(tmp_path):
    steps = [
        step
        for i in range(6)
        for step in (
            {"type": "tool_use", "tool_name": "Bash", "parameters": {"i": i}},
            {"type": "tool_result", "status": "error", "output": "ERROR: boom"},
        )
    ]
    steps.append(Wait())
    ask = make(tmp_path, claude=ScriptedProvider("claude", steps))
    s = ask.create("work", "go", engine="claude")
    assert ask.wait_idle()
    events = ask.store.replay(s["id"])
    errors = [e for e in events if e["type"] == "error"]
    assert len(errors) == 1 and "4 commands failed in a row" in errors[0]["message"]
    assert sum(e["type"] == "tool_use" for e in events) == 4  # it stopped the run at the fourth
    assert events[-1]["signal"] == "SIGTERM"


def test_a_provider_that_raises_ends_the_run_cleanly(tmp_path):
    class Broken:
        engine = "claude"

        def available(self):
            return {}

        def run(self, turn, emit, cancel):
            raise RuntimeError("it broke")

    ask = make(tmp_path)
    ask.providers["claude"] = Broken()  # type: ignore[assignment]
    s = ask.create("work", "go", engine="claude")
    assert ask.wait_idle()
    end = ask.store.replay(s["id"])[-1]
    assert end["type"] == "run_end" and "it broke" in end["error"] and not ask.is_live(s["id"])


def test_switching_engine_hands_over_the_conversation_both_ways(tmp_path):
    claude = ScriptedProvider("claude", [text("claude answer")], outcome=Outcome(0))
    gemini = ScriptedProvider("gemini", [text("gemini answer")])
    ask = make(tmp_path, claude=claude, gemini=gemini)
    s = ask.create("work", "first question", engine="claude")
    ask.wait_idle()
    claude.seen[0].mark_started("")  # a real Claude marks itself started once it answers
    ask.send(s, "second question", engine="gemini")
    ask.wait_idle()
    g = gemini.seen[0]
    assert g.resume is False
    assert "first question" in g.prompt and "claude answer" in g.prompt and "THE GUIDE" in g.prompt
    assert g.system == ""  # Gemini has no system-prompt flag: the guide is in the prompt
    gemini.seen[0].mark_started("acp-1")
    ask.send(s, "third question", engine="claude")
    ask.wait_idle()
    c = claude.seen[-1]
    assert (
        c.resume is True
        and "While you were away" in c.prompt
        and "second question" in c.prompt
        and "gemini answer" in c.prompt
    )
    assert "first question" not in c.prompt  # it remembers its own turn
    assert ask.store.get(s["id"])["engines"]["gemini"] == {"started": True, "acp": "acp-1"}


def test_an_agent_tool_call_goes_through_the_bus_as_agent_with_a_group(tmp_path):
    bus = Bus()
    bus.register(
        "desk.state",
        __import__("zpkt.app.bus", fromlist=["Spec"]).Spec(lambda cmd: (200, {"who": cmd.who, "group": cmd.group})),
    )
    ask = make(tmp_path)
    ask.gate = ToolGate(bus)
    provider = ScriptedProvider("claude", [Call("read_state")], gate=ask.gate)
    ask.providers["claude"] = provider
    s = ask.create("work", "look", engine="claude")
    ask.wait_idle()
    assert provider.replies == [(200, {"who": "agent", "group": f"ask-{s['id']}"})]
    assert [e["type"] for e in ask.store.replay(s["id"])][1:3] == ["tool_use", "tool_result"]
    assert bus.log[0]["who"] == "agent"


def test_the_tool_server_is_given_only_when_the_app_url_is_known(tmp_path):
    claude = ScriptedProvider("claude", [])
    ask = make(tmp_path, claude=claude)
    s = ask.create("work", "x", engine="claude")
    ask.wait_idle()
    env = claude.seen[0].tools.env
    assert env["ZPKT_APP_SESSION"] == s["id"] and env["ZPKT_APP_TOKEN"] == ask.gate.token(s["id"])
    ask.app_url = ""
    ask.send(s, "y", engine="claude")
    ask.wait_idle()
    assert claude.seen[1].tools is None


def test_permissions_wait_for_an_answer_and_are_recorded(tmp_path):
    claude = ScriptedProvider("claude", [Permit("Edit a.txt"), text("after")])
    ask = make(tmp_path, claude=claude)
    s = ask.create("work", "edit", engine="claude", mode="ask")
    found = []
    for _ in range(200):
        found = [e for e in ask.store.replay(s["id"]) if e["type"] == "permission"]
        if found:
            break
        threading.Event().wait(0.02)
    (q,) = found
    assert q["tool"]["title"] == "Edit a.txt" and [o["id"] for o in q["options"]] == ["yes", "no"]
    assert ask.sessions()[0]["asking"] is True
    with pytest.raises(ValueError):
        ask.permissions.answer(s["id"], q["id"], "maybe")
    assert ask.permissions.answer(s["id"], q["id"], "yes") is True
    assert ask.permissions.answer(s["id"], q["id"], "yes") is False  # answered once
    assert ask.wait_idle()
    events = ask.store.replay(s["id"])
    assert {"type": "permission_answer", "id": q["id"], "answered": "yes"}.items() <= next(
        e for e in events if e["type"] == "permission_answer"
    ).items()
    assert claude.answers == ["yes"]


def test_a_stopped_run_cancels_its_waiting_question(tmp_path):
    claude = ScriptedProvider("claude", [Permit("Edit a.txt")])
    ask = make(tmp_path, claude=claude)
    s = ask.create("work", "edit", engine="claude", mode="ask")
    for _ in range(200):
        if ask.permissions.asking(s["id"]):
            break
        threading.Event().wait(0.02)
    ask.stop(s["id"])
    assert ask.wait_idle()
    assert claude.answers == [None]
    assert any(e["type"] == "permission_answer" and e["answered"] == "cancelled" for e in ask.store.replay(s["id"]))


def test_notes_are_read_to_the_agent_and_written_after_the_turn(tmp_path):
    work = tmp_path / "work"
    (work / "notes").mkdir(parents=True)
    (work / "notes" / "HW002.md").write_text("# HW002\nkick is 60 Hz\n")
    claude = ScriptedProvider("claude", [text("x" * 250), {"type": "tool_use", "tool_name": "Bash", "parameters": {}}])
    ask = make(tmp_path, claude=claude)
    ask.notes.write = lambda prompt: '{"notes": ["Kick fundamental stays at 60 Hz."]}'
    s = ask.create("work", "how is HW002 going", engine="claude")
    ask.wait_idle()
    assert "kick is 60 Hz" in claude.seen[0].prompt
    for _ in range(200):
        if (work / "notes" / "HW002.md").read_text().count("##") >= 1:
            break
        threading.Event().wait(0.02)
    body = (work / "notes" / "HW002.md").read_text()
    assert "Kick fundamental stays at 60 Hz." in body and "Asked: how is HW002 going" in body
    kinds = [(e["type"], e.get("status")) for e in ask.store.replay(s["id"]) if e["type"] == "notes"]
    assert ("notes", "loaded") in kinds
    ask.send(s, "and HW002 again", engine="claude")  # the file is as the session last saw it: not sent twice
    ask.wait_idle()
    assert "kick is 60 Hz" not in claude.seen[1].prompt
