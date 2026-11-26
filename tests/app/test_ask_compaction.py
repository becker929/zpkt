"""Auto compaction: past the budget the engine writes a summary, starts afresh on it and the last turns, and the
transcript keeps everything and gains a marker. A summary that fails loses nothing."""

from __future__ import annotations

import threading
from pathlib import Path

from zpkt.app.ask import compaction
from zpkt.app.ask.claude import ClaudeProvider
from zpkt.app.ask.provider import Outcome, Turn
from zpkt.app.ask.service import Ask
from zpkt.app.ask.testing import ScriptedProvider, Started, Wait
from zpkt.app.ask.tools import ToolGate
from zpkt.app.bus import Bus

from .conftest import wait_for

LINK = "[Kick: level](/app/#page=kick-level)"


def said(t: str) -> dict:
    return {"type": "message", "role": "assistant", "content": t, "delta": True}


def page_made() -> list[dict]:
    return [
        {"type": "tool_use", "tool_name": "mcp__zpkt__make_page", "tool_id": "t1", "parameters": {"spec": {}}},
        {
            "type": "tool_result",
            "tool_id": "t1",
            "status": "success",
            "output": f'{{"ok": true, "markdown": "{LINK}"}}',
        },
    ]


def make(tmp_path: Path, budget: int = 200, **providers: ScriptedProvider) -> Ask:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    ask = Ask(
        tmp_path / "ask",
        dict(providers),
        ToolGate(Bus()),
        guide="THE GUIDE",
        home=tmp_path,
        budgets=dict.fromkeys(providers, budget),
    )
    ask.workspaces.list.insert(0, {"id": "work", "name": "Work", "path": str(work)})
    return ask


def talk(ask: Ask, s: dict, *prompts: str, engine: str = "claude") -> None:
    for p in prompts:
        ask.send(s, p, engine=engine)
        assert ask.wait_idle()


def scripted(engine: str = "claude", **kw) -> ScriptedProvider:
    script = [
        Started(),
        *page_made(),
        said("x" * 100),
        {"type": "result", "status": "success", "stats": {"total_tokens": 9}},
    ]
    return ScriptedProvider(engine, script, summary=[said("## What the user wants\nA louder kick.")], **kw)


def test_under_the_budget_nothing_is_compacted_and_claude_resumes(tmp_path):
    claude = scripted()
    ask = make(tmp_path, budget=100_000, claude=claude)
    s = ask.store.get(ask.main("work")["id"])
    talk(ask, s, "one", "two")
    assert claude.summaries == [] and [t.resume for t in claude.seen] == [False, True]
    assert "compacted" not in [e["type"] for e in ask.store.replay(s["id"])]


def test_past_the_budget_the_engine_gets_the_summary_and_the_last_turns(tmp_path):
    claude = scripted()
    ask = make(tmp_path, claude=claude)
    s = ask.store.get(ask.main("work")["id"])
    talk(ask, s, "turn one", "turn two", "turn three", "turn four", "turn five")
    assert len(claude.summaries) == 1  # it happened once, before the fifth turn (about 50 tokens a turn)
    asked = claude.summaries[0]
    assert asked.resume is False and asked.tools is None and asked.session.get("engines") == {}
    assert "turn one" in asked.prompt and "turn four" not in asked.prompt and "turn five" not in asked.prompt
    assert LINK in asked.prompt and "## Pages made" in asked.prompt
    assert asked.engine_session and asked.engine_session != s["id"]

    events = ask.store.replay(s["id"])
    kinds = [e["type"] for e in events]
    assert kinds.count("prompt") == 5 and kinds.count("run_end") == 5  # the transcript keeps everything
    mark = next(e for e in events if e["type"] == "compacted")
    prompts = [e for e in events if e["type"] == "prompt"]
    assert mark["summary"].endswith("A louder kick.") and mark["turns"] == 1 and "failed" not in mark
    assert mark["keep_from"] == prompts[1]["seq"] and mark["tokens"] > 200 and mark["engine"] == "claude"
    assert mark["pages"] == [{"id": "kick-level", "title": "Kick: level", "link": "/app/#page=kick-level"}]
    assert kinds.index("compacting") == prompts[4]["seq"] + 1 == kinds.index("compacted") - 1

    fifth = claude.seen[4]
    assert fifth.resume is False and fifth.system == "THE GUIDE"  # a new Claude session, not the old one resumed
    assert fifth.engine_session and fifth.engine_session not in (s["id"], asked.engine_session)
    assert "A louder kick." in fifth.prompt and LINK in fifth.prompt
    assert "turn two" in fifth.prompt and "turn four" in fifth.prompt and "turn one" not in fifth.prompt
    assert fifth.prompt.endswith("turn five") and fifth.prompt.count("turn five") == 1

    talk(ask, s, "turn six")  # the new session is resumed, and nothing is compacted again yet
    sixth = claude.seen[5]
    assert sixth.resume is True and sixth.engine_session == fifth.engine_session and sixth.prompt == "turn six"
    assert len(claude.summaries) == 1


def test_a_second_compaction_carries_the_first_summary_and_the_pages(tmp_path):
    claude = scripted()
    ask = make(tmp_path, claude=claude)
    s = ask.store.get(ask.main("work")["id"])
    talk(ask, s, *(f"turn {n}" for n in range(1, 12)))
    assert len(claude.summaries) >= 2
    second = claude.summaries[1]
    assert "<earlier-summary>" in second.prompt and "A louder kick." in second.prompt and LINK in second.prompt
    marks = [e for e in ask.store.replay(s["id"]) if e["type"] == "compacted"]
    assert marks[1]["keep_from"] > marks[0]["keep_from"] and marks[1]["pages"][0]["id"] == "kick-level"
    assert sum(e["type"] == "prompt" for e in ask.store.replay(s["id"])) == 11


def test_a_failed_summary_loses_nothing_and_the_turn_goes_on_with_the_last_turns(tmp_path):
    claude = scripted(summary_outcome=Outcome(1, None, "no model today"))
    ask = make(tmp_path, claude=claude)
    s = ask.store.get(ask.main("work")["id"])
    talk(ask, s, "turn one", "turn two", "turn three", "turn four", "turn five")
    events = ask.store.replay(s["id"])
    mark = next(e for e in events if e["type"] == "compacted")
    assert mark["failed"] is True and mark["error"] == "no model today" and mark["summary"] == ""
    assert [e["text"] for e in events if e["type"] == "prompt"][-1] == "turn five"
    fifth = claude.seen[4]
    assert fifth.resume is False and fifth.prompt.endswith("turn five")
    assert "turn four" in fifth.prompt and "turn one" not in fifth.prompt and "could not be written" in fifth.prompt
    assert events[-1]["type"] == "run_end" and events[-1]["code"] == 0  # the turn itself ran


def test_a_provider_that_raises_or_says_nothing_is_a_failed_summary_too(tmp_path):
    class Broken(ScriptedProvider):
        def run(self, turn: Turn, emit, cancel):
            if turn.prompt.startswith(compaction.INSTRUCTIONS):
                raise RuntimeError("boom")
            return super().run(turn, emit, cancel)

    for provider, why in ((Broken("claude", [said("x" * 500)]), "RuntimeError: boom"), (None, "wrote no summary")):
        claude = provider or ScriptedProvider("claude", [said("x" * 500)], summary=[])
        (tmp_path / why[:4]).mkdir()
        ask = make(tmp_path / why[:4], claude=claude)
        s = ask.store.get(ask.main("work")["id"])
        talk(ask, s, "a", "b", "c")
        mark = next(e for e in ask.store.replay(s["id"]) if e["type"] == "compacted")
        assert mark["failed"] is True and why in mark["error"]
        assert claude.seen[-1].prompt.endswith("c")


def test_stop_during_the_summary_ends_the_run_and_the_next_message_tries_again(tmp_path):
    claude = ScriptedProvider("claude", [said("x" * 500)], summary=[Wait()])
    ask = make(tmp_path, claude=claude)
    s = ask.store.get(ask.main("work")["id"])
    talk(ask, s, "a", "b")
    ask.send(s, "c", engine="claude")
    assert wait_for(lambda: claude.summaries)
    assert ask.stop(s["id"]) and ask.wait_idle()
    events = ask.store.replay(s["id"])
    assert events[-1]["type"] == "run_end" and events[-1]["signal"] == "SIGTERM"
    assert "compacted" not in [e["type"] for e in events] and len(claude.seen) == 2
    assert [e["text"] for e in events if e["type"] == "prompt"] == ["a", "b", "c"]
    claude.summary = [said("Summary.")]
    talk(ask, s, "d")
    assert "Summary." in claude.seen[-1].prompt and "### User\nc" in claude.seen[-1].prompt


def test_the_other_engine_joins_after_a_compaction_from_the_summary(tmp_path):
    claude, gemini = scripted(), scripted("gemini")
    ask = make(tmp_path, claude=claude, gemini=gemini)
    ask.budgets["gemini"] = 100_000
    s = ask.store.get(ask.main("work")["id"])
    talk(ask, s, "turn one", "turn two", "turn three", "turn four", "turn five")
    assert len(claude.summaries) == 1
    talk(ask, s, "turn six", engine="gemini")
    joined = gemini.seen[0]
    assert joined.resume is False and joined.prompt.startswith("THE GUIDE")
    assert "A louder kick." in joined.prompt and "turn five" in joined.prompt and "turn one" not in joined.prompt
    assert joined.prompt.endswith("turn six")


def test_a_compaction_gives_gemini_a_fresh_acp_session(tmp_path):
    known: list = []

    class Gemini(ScriptedProvider):
        def run(self, turn: Turn, emit, cancel):
            known.append((turn.session.get("engines") or {}).get("gemini", {}).get("acp"))
            return super().run(turn, emit, cancel)

    gemini = Gemini("gemini", [Started("acp-1"), said("x" * 500)], summary=[said("Summary.")])
    ask = make(tmp_path, gemini=gemini)
    s = ask.store.get(ask.main("work")["id"])
    talk(ask, s, "a", "b", "c", engine="gemini")
    # a new session, the old one loaded, then the summary and the next turn each in a session of their own
    assert known == [None, "acp-1", None, None] and len(gemini.summaries) == 1
    assert gemini.seen[2].prompt.startswith("THE GUIDE") and "Summary." in gemini.seen[2].prompt


def test_the_budget_setting_and_the_estimate():
    assert compaction.budgets({}) == compaction.BUDGET_TOKENS
    assert compaction.budgets({"ZPKT_ASK_COMPACT_TOKENS": "5000"}) == {"claude": 5000, "gemini": 5000}
    assert compaction.budgets({"ZPKT_ASK_COMPACT_TOKENS": "gemini=7, nonsense, x=3"})["gemini"] == 7
    assert compaction.budgets({"ZPKT_ASK_COMPACT_TOKENS": "claude=1"}, {"claude": 2})["claude"] == 2
    events = [
        {"type": "prompt", "text": "a" * 400, "seq": 0},
        {"type": "message", "content": "b" * 400, "seq": 1},
        {"type": "tool_result", "output": "c" * 4000, "seq": 2, "parent": "sub"},  # a subagent's: not counted
        {"type": "tool_result", "output": "d" * 400, "seq": 3},
    ]
    assert compaction.estimate(events) == 300
    assert compaction.plan(events, 300) is None and compaction.plan(events, 0) is None
    one = compaction.plan(events, 299)
    assert one is not None and one.keep_from == 4 and one.turns == 1  # one huge turn: it is summarised whole
    after = [*events, {"type": "compacted", "summary": "s" * 40, "keep_from": 4, "seq": 4}]
    assert compaction.estimate(after) == 10 and compaction.preamble(events) == ""


def test_claude_starts_a_new_session_by_the_id_the_turn_names(tmp_path):
    seen = tmp_path / "argv"
    fake = tmp_path / "claude"
    fake.write_text(f'#!/bin/sh\necho "$@" > {seen}\ncat > /dev/null\n')
    fake.chmod(0o755)
    provider = ClaudeProvider(lambda name: None, claude_bin=str(fake), environ={"PATH": "/usr/bin:/bin"}, home=tmp_path)
    s = {"id": "11111111-1111-1111-1111-111111111111", "cwd": str(tmp_path)}
    provider.run(Turn(s, "hi", "plan", "", False, engine_session="new-id"), lambda e: None, threading.Event())
    assert "--session-id new-id" in seen.read_text()
    provider.run(Turn(s, "hi", "plan", "", True, engine_session="new-id"), lambda e: None, threading.Event())
    assert "--resume new-id" in seen.read_text()
    provider.run(Turn(s, "hi", "plan", "", True), lambda e: None, threading.Event())
    assert f"--resume {s['id']}" in seen.read_text()
