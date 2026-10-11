"""What one Claude turn puts in the chat as it happens: replies (spoken while they stream in), thinking (summarized,
never spoken) and tool calls. conversation.py runs the turn; this turns its events into messages.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .activity import describe, detail
from .agent import AgentEvent, TextDelta, TextDone, ThinkingDelta, ThinkingDone, ToolDone, ToolStart, TurnDone
from .model import Kind, Message, Phase
from .speech import Utterance
from .timing import TurnClock

if TYPE_CHECKING:
    from .conversation import Conversation


class TurnMessages:
    def __init__(self, conv: "Conversation", clock: TurnClock):
        self.conv, self.clock = conv, clock
        self.replies: dict[int, tuple[Message, Utterance]] = {}     # by block: replies still streaming
        self.thoughts: dict[int, Message] = {}                      # ... thinking still streaming
        self.tools: dict[str, tuple[Message, float]] = {}           # by tool use id: calls still running

    def handle(self, ev: AgentEvent) -> None:
        conv, clock = self.conv, self.clock
        if isinstance(ev, TextDelta):
            if ev.block not in self.replies:
                self.replies[ev.block] = self._reply()
            msg, utt = self.replies[ev.block]
            msg.data["text"] += ev.text
            utt.feed(ev.text)
            conv.narrator.spoke()
            clock.mark("first_text", once=True)
            conv.push_soon(msg)
        elif isinstance(ev, TextDone) and ev.block in self.replies:
            msg, utt = self.replies.pop(ev.block)
            msg.data.update(text=ev.text, streaming=False)
            conv.save(msg)
            utt.close()
        elif isinstance(ev, ThinkingDelta):
            if ev.block not in self.thoughts:
                self.thoughts[ev.block] = conv.add(Kind.THINKING, {"text": "", "streaming": True})
            self.thoughts[ev.block].data["text"] += ev.text
            conv.push_soon(self.thoughts[ev.block])
        elif isinstance(ev, ThinkingDone):
            msg = self.thoughts.pop(ev.block, None)
            if msg is None:
                conv.add(Kind.THINKING, {"text": ev.text, "streaming": False})
            else:
                msg.data.update(text=ev.text, streaming=False)
                conv.save(msg)
        elif isinstance(ev, ToolStart):
            title = describe(ev.name, ev.input)
            act = conv.add(Kind.ACTIVITY, {"tool": ev.name, "title": title, "status": "running",
                                           "detail": detail(ev.input)})
            self.tools[ev.id] = (act, time.monotonic())
            conv.set_phase(Phase.WORKING, title)
            conv.narrator.note(title)
            clock.mark("tool", tool=ev.name)
        elif isinstance(ev, ToolDone) and ev.id in self.tools:
            act, t0 = self.tools.pop(ev.id)
            act.data.update(status="ok" if ev.ok else "error", ms=round((time.monotonic() - t0) * 1000),
                            output=ev.output[-1500:])
            conv.save(act)
            conv.set_phase(Phase.WORKING, "Thinking")
        elif isinstance(ev, TurnDone):
            conv.remember_session(ev.session_id)
            clock.mark("agent_done", cost_usd=ev.cost_usd)
            if not ev.ok and not conv.interrupted:
                conv.notice(f"Claude stopped: {ev.text[:300]}", "error", keep=True)

    def finish(self, interrupted: bool) -> None:
        """The turn is over, however it ended: nothing it started is left streaming or running."""
        for msg, utt in self.replies.values():
            utt.close()                          # first: the speaker waits for it
            msg.data["streaming"] = False
            self.conv.save(msg)
        for msg in self.thoughts.values():
            msg.data["streaming"] = False
            self.conv.save(msg)
        for act, _ in self.tools.values():
            act.data["status"] = "error" if interrupted else "ok"
            self.conv.save(act)
        self.replies, self.thoughts, self.tools = {}, {}, {}

    def _reply(self) -> tuple[Message, Utterance]:
        msg = self.conv.add(Kind.AGENT, {"text": "", "role": "reply", "audio": None, "duration": None,
                                         "streaming": True})
        clock = self.clock
        utt = self.conv.speaker.say(Utterance(msg, on_first_audio=lambda: clock.mark("first_audio", once=True)))
        return msg, utt
