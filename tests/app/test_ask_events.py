"""Ask's events: Claude's stream-json translated into the page's shape, the hand-off text and the failure budget."""

from __future__ import annotations

import json

import pytest

from zpkt.app.ask.events import FAILED_RUN, Budget, ClaudeStream, handoff_context


def feed(*lines: dict) -> list[dict]:
    stream = ClaudeStream()
    return [e for line in lines for e in stream.feed(line)]


def test_init_and_compact_boundary():
    assert feed({"type": "system", "subtype": "init", "session_id": "s", "model": "m"}) == [
        {"type": "init", "session_id": "s", "model": "m"}
    ]
    assert feed({"type": "system", "subtype": "compact_boundary"}) == [{"type": "compact"}]
    assert feed({"type": "system", "subtype": "hook"}) == []


def test_streamed_text_is_not_repeated_by_the_final_message():
    events = feed(
        {"type": "stream_event", "event": {"type": "message_start", "message": {"id": "m1"}}},
        {
            "type": "stream_event",
            "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi"}},
        },
        {"type": "assistant", "message": {"id": "m1", "content": [{"type": "text", "text": "Hi"}]}},
    )
    assert events == [{"type": "message", "role": "assistant", "content": "Hi", "delta": True}]


def test_text_that_was_not_streamed_comes_from_the_final_message():
    events = feed({"type": "assistant", "message": {"id": "m2", "content": [{"type": "text", "text": "Whole"}]}})
    assert events == [{"type": "message", "role": "assistant", "content": "Whole", "delta": True}]


def test_a_second_text_block_gets_a_paragraph_break():
    events = feed(
        {"type": "stream_event", "event": {"type": "message_start", "message": {"id": "m1"}}},
        {
            "type": "stream_event",
            "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "a"}},
        },
        {"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "text"}}},
    )
    assert [e["content"] for e in events] == ["a", "\n\n"]


def test_tool_use_and_result_and_subagent_parent():
    events = feed(
        {
            "type": "assistant",
            "message": {"id": "m", "content": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {"p": 1}}]},
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t1",
                        "content": [{"type": "text", "text": "ok"}, {"type": "image"}],
                    }
                ]
            },
        },
        {
            "type": "assistant",
            "parent_tool_use_id": "t1",
            "message": {"id": "n", "content": [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {}}]},
        },
    )
    assert events[0] == {"type": "tool_use", "tool_name": "Read", "tool_id": "t1", "parameters": {"p": 1}}
    assert events[1] == {"type": "tool_result", "tool_id": "t1", "status": "success", "output": "ok\n[image]"}
    assert events[2]["parent"] == "t1"


def test_result_has_tokens_tool_count_and_cost():
    stream = ClaudeStream()
    stream.feed(
        {"type": "assistant", "message": {"id": "m", "content": [{"type": "tool_use", "id": "t", "name": "x"}]}}
    )
    (ev,) = stream.feed(
        {"type": "result", "is_error": False, "duration_ms": 5, "total_cost_usd": 0.02,
         "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100}}
    )  # fmt: skip
    assert ev["status"] == "success" and ev["stats"]["total_tokens"] == 115 and ev["stats"]["tool_calls"] == 1
    assert ev["cost_usd"] == 0.02
    (zero,) = ClaudeStream().feed({"type": "result", "is_error": True, "total_cost_usd": 0})
    assert zero["status"] == "error" and "cost_usd" not in zero


def test_handoff_context_lists_turns_and_cuts_long_text():
    events = [
        {"type": "prompt", "text": "make a bass", "engine": "gemini"},
        {"type": "message", "role": "assistant", "content": "Done."},
        {"type": "tool_use", "tool_name": "Bash"},
        {"type": "message", "role": "assistant", "content": "sub", "parent": "x"},
        {"type": "prompt", "text": "again", "engine": "claude", "auto": True},
    ]
    text = handoff_context(events)
    assert "### User\nmake a bass" in text and "### Gemini CLI\nDone." in text and "[used tool Bash]" in text
    assert "sub" not in text and "again" not in text
    assert handoff_context([]) == ""
    assert "While you were away" in handoff_context(events, since=True)
    long = [{"type": "prompt", "text": "x" * 500, "engine": "claude"}]
    assert "earlier turns cut" in handoff_context(long, max_chars=100)


def test_failed_run_pattern():
    assert FAILED_RUN.search("ERROR: no")
    assert FAILED_RUN.search("ok\nExit Code: 2")
    assert not FAILED_RUN.search("Exit Code: 0")


def call(i: int, args: dict | None = None) -> dict:
    return {"type": "tool_use", "tool_name": "Bash", "parameters": args if args is not None else {"n": i}}


def fail() -> dict:
    return {"type": "tool_result", "status": "error", "output": "ERROR: boom\nmore"}


def test_budget_stops_after_failures_in_a_row_and_a_success_resets():
    b = Budget()
    for i in range(3):
        assert b.watch(call(i)) is None and b.watch(fail()) is None
    assert b.watch({"type": "tool_result", "status": "success", "output": "fine"}) is None
    for _ in range(3):
        assert b.watch(fail()) is None
    why = b.watch(fail())
    assert why and "4 commands failed in a row" in why and "boom" in why
    assert b.watch(fail()) is None  # it says it once


def test_budget_stops_the_same_call_and_too_many_calls_and_ignores_subagents():
    b = Budget()
    assert [b.watch(call(0, {"same": 1})) for _ in range(3)] == [None, None, None]
    assert "ran the same command 4 times" in (b.watch(call(0, {"same": 1})) or "")
    b2 = Budget(calls=5)
    reasons = [b2.watch(call(i)) for i in range(6)]
    assert reasons[-1] and "more than 5 tool calls" in reasons[-1]
    b3 = Budget(same=2)
    assert (
        b3.watch({**call(0, {"a": 1}), "parent": "p"}) is None
        and b3.watch({**call(0, {"a": 1}), "parent": "p"}) is None
    )


@pytest.mark.parametrize("output", ["Traceback (most recent call last)\n  x", "WARNING: the render is silent"])
def test_budget_counts_a_failed_shell_run_whatever_its_status(output):
    b = Budget(fails=1)
    assert b.watch({"type": "tool_result", "status": "success", "output": output})


def test_events_are_json():
    assert json.dumps(feed({"type": "system", "subtype": "init"}))
