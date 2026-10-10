"""The Claude Code session behind the chat: one long-lived Agent SDK client, started in zpkt.

A turn is one user message. Its reply arrives as a stream of events the conversation can act on as they happen:
text as it is generated (so speech can start before the reply is finished), tool calls as they start and end,
and the end of the turn. The session id is kept so the conversation survives a restart of the harness.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from claude_agent_sdk.types import StreamEvent

log = logging.getLogger(__name__)


@dataclass
class TextDelta:
    block: int
    text: str


@dataclass
class TextDone:
    block: int
    text: str


@dataclass
class ToolStart:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ToolDone:
    id: str
    name: str
    ok: bool
    output: str


@dataclass
class TurnDone:
    text: str
    ok: bool
    cost_usd: float | None
    session_id: str | None


AgentEvent = TextDelta | TextDone | ToolStart | ToolDone | TurnDone

OptionsFactory = Callable[[str | None], ClaudeAgentOptions]


class AgentSession:
    def __init__(self, options: OptionsFactory, client_factory: Callable[[ClaudeAgentOptions], Any] = ClaudeSDKClient):
        self._options, self._client_factory = options, client_factory
        self._client: Any = None
        self._lock = asyncio.Lock()          # one turn at a time
        self.session_id: str | None = None

    @property
    def connected(self) -> bool:
        return self._client is not None

    async def connect(self, resume: str | None = None) -> None:
        if self._client is not None:
            return
        client = self._client_factory(self._options(resume))
        try:
            await client.connect()
        except Exception:
            if resume is None:
                raise
            log.warning("could not resume Claude session %s; starting a new one", resume)
            client = self._client_factory(self._options(None))
            await client.connect()
        self._client, self.session_id = client, resume

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001 - closing a dead CLI is not an error worth raising
                log.debug("disconnect failed", exc_info=True)

    async def interrupt(self) -> None:
        if self._client is not None:
            try:
                await self._client.interrupt()
            except Exception:  # noqa: BLE001
                log.warning("interrupt failed", exc_info=True)

    async def turn(self, prompt: str) -> AsyncIterator[AgentEvent]:
        """Send one user message; yield what happens until the turn ends."""
        async with self._lock:
            await self.connect(self.session_id)
            await self._client.query(prompt)
            reader = _Reader()
            try:
                async for msg in self._client.receive_response():
                    for event in reader.read(msg):
                        if isinstance(event, TurnDone) and event.session_id:
                            self.session_id = event.session_id
                        yield event
                    sid = getattr(msg, "session_id", None) or (msg.data.get("session_id")
                                                                if isinstance(msg, SystemMessage) else None)
                    if sid:
                        self.session_id = sid
            except Exception:
                # A dead CLI can't take the next turn: drop it, and the next turn reconnects (resuming).
                await self.close()
                raise


class _Reader:
    """Turns the SDK's messages into AgentEvents for one turn.

    Text comes from the stream events (partial messages), so it arrives as it is generated. Subagents' messages
    (parent_tool_use_id set) are left out: what they say is not Claude talking to Anthony.
    """

    def __init__(self) -> None:
        self.blocks: dict[int, list[str]] = {}
        self.block_base = 0           # stream indexes restart at 0 with each API message
        self.next_block = 0
        self.tools: dict[str, str] = {}
        self.spoken: list[str] = []

    def read(self, msg: Any) -> list[AgentEvent]:
        if isinstance(msg, StreamEvent):
            return [] if msg.parent_tool_use_id else self._stream(msg.event)
        if isinstance(msg, AssistantMessage):
            if msg.parent_tool_use_id:
                return []
            out: list[AgentEvent] = []
            for b in msg.content:
                if isinstance(b, ToolUseBlock) and b.id not in self.tools:
                    self.tools[b.id] = b.name
                    out.append(ToolStart(b.id, b.name, b.input))
            return out
        if isinstance(msg, UserMessage) and isinstance(msg.content, list):
            out = []
            for b in msg.content:
                if isinstance(b, ToolResultBlock) and b.tool_use_id in self.tools:
                    out.append(ToolDone(b.tool_use_id, self.tools[b.tool_use_id], not b.is_error, _text(b.content)))
            return out
        if isinstance(msg, ResultMessage):
            return [TurnDone(text=msg.result or "\n\n".join(self.spoken), ok=not msg.is_error,
                             cost_usd=msg.total_cost_usd, session_id=msg.session_id)]
        return []

    def _stream(self, ev: dict[str, Any]) -> list[AgentEvent]:
        kind = ev.get("type")
        if kind == "message_start":
            self.block_base = self.next_block
            return []
        index = self.block_base + int(ev.get("index", 0))
        if kind == "content_block_start" and (ev.get("content_block") or {}).get("type") == "text":
            self.blocks[index] = []
            self.next_block = max(self.next_block, index + 1)
        elif kind == "content_block_delta" and index in self.blocks:
            delta = ev.get("delta") or {}
            if delta.get("type") == "text_delta" and delta.get("text"):
                self.blocks[index].append(delta["text"])
                return [TextDelta(index, delta["text"])]
        elif kind == "content_block_stop" and index in self.blocks:
            text = "".join(self.blocks.pop(index))
            if text.strip():
                self.spoken.append(text)
            return [TextDone(index, text)]
        elif kind == "content_block_start":
            self.next_block = max(self.next_block, index + 1)
        return []


def _text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
    return json.dumps(content)[:4000]
