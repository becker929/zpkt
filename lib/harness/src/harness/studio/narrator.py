"""Narration: while Claude works in silence, a small model says in a few words what it is doing.

Rules (plan V2): speak only after Claude has been quiet for a while, never more often than a minimum gap, never
twice about the same activity, and drop a line that went stale while it was being written (Claude spoke, or the
turn ended). If the model fails or is slow, say nothing rather than something generic.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

log = logging.getLogger(__name__)

PROMPT = """You narrate, in ONE short spoken sentence (at most 12 words), what an AI music-production assistant is \
doing right now, for its user, who is listening (maybe driving) and cannot see the screen. First person ("I'm..."). \
Plain words: no file names, paths, code, tool names or numbers that need reading. Say what it means for the music or \
the task. Do not repeat what was already said. Reply with the sentence only.

The user asked: {request}
Already said: {said}
What the assistant did since then, oldest first:
{activity}"""


Summarize = Callable[[str], Awaitable[str]]


class Narrator:
    QUIET_S = 6.0       # Claude has said nothing for this long while working
    MIN_GAP_S = 10.0    # between two narrations
    TIMEOUT_S = 8.0     # a line that takes longer is stale anyway
    MAX_WORDS = 16

    def __init__(self, summarize: Summarize, speak: Callable[[str], None], clock: Callable[[], float] = time.monotonic):
        self._summarize, self._speak, self._now = summarize, speak, clock
        self._task: asyncio.Task | None = None
        self._turn = 0
        self.request = ""
        self.activity: list[str] = []
        self.said: list[str] = []
        self.last_voice = 0.0      # when anything was last said (by Claude or by the narrator)
        self.last_line = 0.0
        self.narrated_upto = 0     # activity before this index has been narrated

    def turn_started(self, request: str) -> None:
        self._turn += 1
        self.request, self.activity, self.said = request[:400], [], []
        self.last_voice = self._now()
        self.last_line = 0.0
        self.narrated_upto = 0
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._watch(self._turn), name="narrator")

    def note(self, line: str) -> None:
        """Something Claude did (a tool call, in a few words)."""
        self.activity.append(line[:200])

    def spoke(self) -> None:
        """Claude itself said something: that is narration enough for now."""
        self.last_voice = self._now()
        self.narrated_upto = len(self.activity)

    def turn_ended(self) -> None:
        self._turn += 1
        if self._task:
            self._task.cancel()
            self._task = None

    def due(self) -> bool:
        now = self._now()
        return (len(self.activity) > self.narrated_upto and now - self.last_voice >= self.QUIET_S
                and now - self.last_line >= self.MIN_GAP_S)

    async def _watch(self, turn: int) -> None:
        while turn == self._turn:
            await asyncio.sleep(0.5)
            if not self.due():
                continue
            upto = len(self.activity)
            prompt = PROMPT.format(request=self.request or "(nothing yet)",
                                   said=" / ".join(self.said[-3:]) or "(nothing yet)",
                                   activity="\n".join(f"- {a}" for a in self.activity[self.narrated_upto:upto][-8:]))
            asked = self._now()
            try:
                line = await asyncio.wait_for(self._summarize(prompt), self.TIMEOUT_S)
            except Exception as exc:  # noqa: BLE001 - narration is optional
                log.info("no narration: %s", exc)
                self.last_line = self._now()
                continue
            line = clean(line, self.MAX_WORDS)
            if turn != self._turn or not line or self.last_voice > asked:
                continue   # stale: the turn ended, or Claude spoke meanwhile
            self.said.append(line)
            self.narrated_upto = upto
            self.last_line = self.last_voice = self._now()
            self._speak(line)


def clean(line: str, max_words: int) -> str:
    line = " ".join(line.replace("\n", " ").strip().strip('"').split())
    words = line.split()
    if len(words) > max_words:
        line = " ".join(words[:max_words]).rstrip(",;:") + "."
    return line


def haiku(model: str, cli_path: str | None, env: dict[str, str]) -> Summarize:
    """One line from a small model through the Mac's own Claude login: no tools, no settings, one turn."""
    options = ClaudeAgentOptions(model=model, cli_path=cli_path, env=env, tools=[], setting_sources=[],
                                 system_prompt="You write one short spoken sentence.", max_turns=1)

    async def summarize(prompt: str) -> str:
        parts: list[str] = []
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, AssistantMessage):
                parts += [b.text for b in msg.content if isinstance(b, TextBlock)]
        return " ".join(parts)

    return summarize
