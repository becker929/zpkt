"""The tools Claude gets from the app: an in-process MCP server named "studio".

They are about the chat, not about music making (that is skills and scripts in zpkt): put a render in front of
Anthony, play it again a number of times, stop, show him the screen.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import create_sdk_mcp_server, tool
from claude_agent_sdk.types import McpSdkServerConfig

from .model import ShotLevel

if TYPE_CHECKING:
    from .conversation import Conversation

SERVER = "studio"
NAMES = [f"mcp__{SERVER}__{n}" for n in ("present_music", "play_music", "stop_audio", "screenshot")]
MAX_LOOPS = 16

PRESENT = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "An audio file you rendered (WAV, FLAC, AIFF or MP3)."},
        "title": {"type": "string", "description": "A short title to show and say, e.g. 'Kick drive 43% vs 50%'."},
        "note": {"type": "string", "description": "Optional: what to listen for, one or two sentences."},
        "ab": {
            "type": "object",
            "description": "Give this when the file alternates two versions bar by bar.",
            "properties": {
                "bar_seconds": {"type": "number", "description": "Length of one bar in seconds."},
                "bars": {"type": "integer", "description": "How many bars the file has."},
                "first": {"type": "string", "enum": ["A", "B"], "description": "Which version plays first."},
                "every": {"type": "integer", "description": "Bars per switch (1 = every bar)."},
                "a": {"type": "string", "description": "What A is."},
                "b": {"type": "string", "description": "What B is."},
            },
            "required": ["bar_seconds", "bars"],
        },
    },
    "required": ["path", "title"],
}

PLAY = {
    "type": "object",
    "properties": {
        "loops": {"type": "integer", "minimum": 1, "maximum": MAX_LOOPS,
                  "description": "How many times in a row: 'play again' is 1, 'loop that three times' is 3."},
        "seq": {"type": "integer", "description": "Which music bubble (its number); the last one if left out."},
    },
    "required": ["loops"],
}

SCREENSHOT = {
    "type": "object",
    "properties": {
        "caption": {"type": "string", "description": "What he is looking at, in a few words."},
        "x": {"type": "integer", "description": "Optional point to zoom on (screen pixels)."},
        "y": {"type": "integer"},
    },
    "required": ["caption"],
}


def _ok(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


def _error(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "is_error": True}


def server(conversation: "Conversation") -> McpSdkServerConfig:
    @tool("present_music",
          "Put a rendered audio file in Anthony's chat as a music bubble. It plays on his phone at once if he has "
          "autoplay on. Use it for every render he should hear. For an A/B that switches every bar, fill in `ab`.",
          PRESENT)
    async def present_music(args: dict[str, Any]) -> dict[str, Any]:
        path = Path(str(args["path"])).expanduser()
        if not path.is_file():
            return _error(f"No such file: {path}")
        ab = args.get("ab") or None
        if ab is not None:
            ab = {"bar_seconds": float(ab["bar_seconds"]), "bars": int(ab["bars"]), "first": ab.get("first", "A"),
                  "every": int(ab.get("every", 1)), "labels": {"A": ab.get("a", "A"), "B": ab.get("b", "B")}}
        try:
            msg = await conversation.present_music(path, str(args["title"])[:120], ab, str(args.get("note", ""))[:600])
        except Exception as exc:  # noqa: BLE001 - report to Claude, which can fix the file and retry
            return _error(f"Could not present it: {exc}")
        playing = "It is playing on his phone now." if conversation.hub.autoplay else "Autoplay is off: it waits in the chat."
        return _ok(f"Music #{msg.seq}, {msg.data['duration']:.1f} s. {playing}")

    @tool("play_music", "Play a music bubble again on Anthony's phone, `loops` times in a row (the last one unless "
          "you give `seq`). Use it for 'play again' (1) or 'loop that three times' (3).", PLAY)
    async def play_music(args: dict[str, Any]) -> dict[str, Any]:
        loops = max(1, min(int(args.get("loops", 1)), MAX_LOOPS))
        seq = args.get("seq")
        if seq is None:
            last = conversation.last_music()
            if last is None:
                return _error("There is no music in this conversation yet.")
            seq = last.seq
        try:
            msg = conversation.play(int(seq), loops)
        except ValueError as exc:
            return _error(str(exc))
        if conversation.hub.owner is None:
            return _ok(f"No phone is connected, so nothing plays now. Music #{msg.seq} is in the chat.")
        return _ok(f"Playing music #{msg.seq} ({msg.data.get('title')}) {loops} time(s).")

    @tool("stop_audio", "Stop whatever is playing on Anthony's phone.", {"type": "object", "properties": {}})
    async def stop_audio(_args: dict[str, Any]) -> dict[str, Any]:
        conversation.stop_audio()
        return _ok("Stopped.")

    @tool("screenshot", "Show Anthony the Mac's screen now: the full screen plus a zoom on what changed (or on x, y). "
          "Screenshots of your tool calls are already taken at the level he chose; use this for something specific.",
          SCREENSHOT)
    async def screenshot(args: dict[str, Any]) -> dict[str, Any]:
        hint = (int(args["x"]), int(args["y"])) if "x" in args and "y" in args else None
        msg = await conversation.screens.shot(ShotLevel.MAJOR, str(args["caption"]), hint=hint)
        if msg is None:
            return _ok("Not shown: he has screenshots turned off (or screen capture is unavailable).")
        return _ok(f"Shown as screenshot #{msg.seq}.")

    return create_sdk_mcp_server(SERVER, tools=[present_music, play_music, stop_audio, screenshot])
