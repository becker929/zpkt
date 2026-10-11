"""The Claude session bridge, against a stand-in SDK client that plays recorded message shapes."""

import asyncio

from claude_agent_sdk import AssistantMessage, ResultMessage, SystemMessage, ToolResultBlock, ToolUseBlock, UserMessage
from claude_agent_sdk.types import StreamEvent

from harness.studio.agent import (AgentSession, TextDelta, TextDone, ThinkingDelta, ThinkingDone, ToolDone, ToolStart,
                                  TurnDone)

END = object()


def ev(event, parent=None):
    return StreamEvent(uuid="u", session_id="sess-1", event=event, parent_tool_use_id=parent)


def text_block(index, *parts):
    out = [ev({"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}})]
    out += [ev({"type": "content_block_delta", "index": index, "delta": {"type": "text_delta", "text": p}}) for p in parts]
    return out + [ev({"type": "content_block_stop", "index": index})]


def thinking_block(index, *parts):
    """A thinking block as the CLI streams it: summarized text in thinking_delta, then the signature."""
    out = [ev({"type": "content_block_start", "index": index,
               "content_block": {"type": "thinking", "thinking": "", "signature": ""}})]
    out += [ev({"type": "content_block_delta", "index": index, "delta": {"type": "thinking_delta", "thinking": p}})
            for p in parts]
    out.append(ev({"type": "content_block_delta", "index": index, "delta": {"type": "signature_delta", "signature": "x"}}))
    return out + [ev({"type": "content_block_stop", "index": index})]


def result(text="done", error=False):
    return ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=error, num_turns=1,
                         session_id="sess-1", result=text)


class FakeClient:
    """Answers each query with the next scripted list of messages; END stands for the CLI dying."""

    instances: list["FakeClient"] = []
    next_scripts: list[list] = []          # what the next client created will answer

    def __init__(self, options):
        self.options, self.scripts, self.prompts = options, FakeClient.next_scripts, []
        FakeClient.next_scripts = []
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.interrupted = False
        FakeClient.instances.append(self)

    async def connect(self):
        pass

    async def query(self, prompt):
        self.prompts.append(prompt)
        for msg in self.scripts.pop(0):
            self.inbox.put_nowait(msg)

    async def receive_messages(self):
        while (msg := await self.inbox.get()) is not END:
            yield msg
        raise RuntimeError("CLI exited")

    async def interrupt(self):
        self.interrupted = True

    async def disconnect(self):
        self.disconnected = True

    disconnected = False


async def collect(session, prompt):
    return [e async for e in session.turn(prompt)]


async def test_a_turn_streams_text_and_tools_and_ignores_subagents():
    FakeClient.instances.clear()
    session = AgentSession(lambda resume: {"resume": resume}, FakeClient)
    await session.connect()
    client = FakeClient.instances[0]
    client.scripts.append([
        SystemMessage("init", {"session_id": "sess-1"}),
        ev({"type": "message_start", "message": {}}),
        *text_block(0, "Let me ", "check."),
        AssistantMessage([ToolUseBlock("t1", "Bash", {"command": "ls"})], model="m"),
        *[ev(e["event"] if isinstance(e, dict) else e.event, parent="t1") for e in text_block(0, "subagent talk")],
        UserMessage([ToolResultBlock("t1", "a\nb", False)]),
        ev({"type": "message_start", "message": {}}),
        *text_block(0, "Two files."),
        result("Two files."),
    ])
    events = await collect(session, "what's here?")
    assert [type(e).__name__ for e in events] == ["TextDelta", "TextDelta", "TextDone", "ToolStart", "ToolDone",
                                                  "TextDelta", "TextDone", "TurnDone"]
    assert events[2] == TextDone(0, "Let me check.") and events[6].block != events[2].block   # blocks stay distinct
    assert events[3] == ToolStart("t1", "Bash", {"command": "ls"}) and events[4] == ToolDone("t1", "Bash", True, "a\nb")
    assert events[-1] == TurnDone("Two files.", True, None, "sess-1") and session.session_id == "sess-1"


async def test_events_between_turns_go_to_unprompted_and_a_dead_cli_ends_the_turn():
    FakeClient.instances.clear()
    seen = []
    session = AgentSession(lambda resume: {"resume": resume}, FakeClient, unprompted=seen.append)
    await session.connect()
    first = FakeClient.instances[0]
    first.inbox.put_nowait(AssistantMessage([ToolUseBlock("bg", "Bash", {"command": "sleep 1"})], model="m"))
    first.inbox.put_nowait(result("background finished"))
    await asyncio.sleep(0.05)
    assert [type(e).__name__ for e in seen] == ["ToolStart", "TurnDone"]

    first.scripts.append([*text_block(0, "Working"), END])          # the CLI dies mid-turn
    events = await collect(session, "go")
    assert isinstance(events[-1], TurnDone) and not events[-1].ok and "ended" in events[-1].text
    assert not session.connected

    FakeClient.instances.clear()
    FakeClient.next_scripts = [[result("back")]]
    assert await collect(session, "again") == [TurnDone("back", True, None, "sess-1")]
    assert FakeClient.instances[0].options == {"resume": "sess-1"}      # the new CLI resumed the session


async def test_thinking_streams_as_its_own_events_and_an_omitted_block_yields_nothing():
    FakeClient.instances.clear()
    session = AgentSession(lambda resume: {"resume": resume}, FakeClient)
    await session.connect()
    client = FakeClient.instances[0]
    client.scripts.append([
        ev({"type": "message_start", "message": {}}),
        *thinking_block(0, "Adding ", "3:47 and 2:38."),
        *text_block(1, "Six forty-two."),
        ev({"type": "message_start", "message": {}}),
        *thinking_block(0, ""),                       # display omitted: an empty block with only a signature
        *[ev(e.event, parent="t9") for e in thinking_block(0, "a subagent thinks")],
        *text_block(1, "Done."),
        result("Six forty-two. Done."),
    ])
    events = await collect(session, "when?")
    assert [type(e).__name__ for e in events] == ["ThinkingDelta", "ThinkingDelta", "ThinkingDone", "TextDelta",
                                                  "TextDone", "TextDelta", "TextDone", "TurnDone"]
    assert events[:3] == [ThinkingDelta(0, "Adding "), ThinkingDelta(0, "3:47 and 2:38."),
                          ThinkingDone(0, "Adding 3:47 and 2:38.")]
    assert events[4] == TextDone(1, "Six forty-two.") and events[6].block not in (0, 1)   # blocks stay distinct
    assert events[-1].text == "Six forty-two. Done."            # thinking is never part of what is spoken


async def test_closing_the_session_mid_turn_ends_the_turn():
    FakeClient.instances.clear()
    session = AgentSession(lambda resume: {"resume": resume}, FakeClient)
    await session.connect()
    FakeClient.instances[0].scripts.append([*text_block(0, "Working on it")])     # ...and then nothing

    async def close_soon():
        await asyncio.sleep(0.1)
        await session.close()                    # an interrupt Claude ignored, or a new conversation

    closing = asyncio.create_task(close_soon())
    events = await asyncio.wait_for(collect(session, "go"), 2)
    await closing
    assert isinstance(events[-1], TurnDone) and not events[-1].ok


async def test_a_failing_unprompted_handler_does_not_end_the_session():
    FakeClient.instances.clear()

    def broken(_event):
        raise RuntimeError("the chat could not take it")

    session = AgentSession(lambda resume: {"resume": resume}, FakeClient, unprompted=broken)
    await session.connect()
    client = FakeClient.instances[0]
    client.inbox.put_nowait(AssistantMessage([ToolUseBlock("bg", "Bash", {"command": "true"})], model="m"))
    await asyncio.sleep(0.05)
    assert session.connected
    client.scripts.append([result("still here")])
    assert await collect(session, "hello?") == [TurnDone("still here", True, None, "sess-1")]


async def test_a_cli_that_dies_is_disconnected_so_its_process_is_not_left_behind():
    FakeClient.instances.clear()
    session = AgentSession(lambda resume: {"resume": resume}, FakeClient)
    await session.connect()
    client = FakeClient.instances[0]
    client.inbox.put_nowait(END)
    await asyncio.sleep(0.05)
    assert not session.connected and client.disconnected
