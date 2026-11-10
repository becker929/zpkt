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
MUSIC_TOOLS = set(NAMES[:2])        # what they cue plays at the turn's end, after an intro
MAX_LOOPS = 16

PRESENT = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "An audio file you rendered (WAV, FLAC, AIFF or MP3)."},
        "title": {"type": "string", "description": "A short title, shown on the card and said first in its intro, "
                                                  "e.g. 'Kick drive 43% vs 50%'."},
        "note": {"type": "string",
                 "description": "Its description, spoken right before the music (after the title, before the "
                                "count-in): one or two short spoken sentences, what it is and what to listen for, "
                                "e.g. 'Nine drive settings, clean to crushed, one bar each. Listen for when the "
                                "kick starts to break up.' Your reply need not repeat it."},
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
        "options": {
            "type": "object",
            "description": "Give this for a file of options baked one after another (`hands plan slider`, `line` "
                           "or `options`): pass the printed `options` as it is. His phone keeps all of them in memory "
                           "and switches between them itself, with a slider or a button each.",
            "properties": {
                "layout": {"type": "string", "enum": ["slider", "buttons"]},
                "name": {"type": "string", "description": "What the options change, in a few words."},
                "bar_seconds": {"type": "number"},
                "bars": {"type": "integer", "description": "Bars per option."},
                "now": {"type": ["integer", "null"], "description": "The option that sounds like the set now."},
                "options": {"type": "array", "items": {"type": "object", "properties": {
                    "label": {"type": "string"}, "match_db": {"type": "number"}}, "required": ["label"]}},
            },
            "required": ["bar_seconds", "bars", "options"],
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


MAX_OPTIONS = 32


def baked_options(raw: dict[str, Any]) -> dict[str, Any]:
    """`hands plan slider|line|options` output as the music message keeps it. Raises on anything malformed."""
    opts = raw.get("options") or []
    if not 2 <= len(opts) <= MAX_OPTIONS:
        raise ValueError(f"options needs 2 to {MAX_OPTIONS} options, got {len(opts)}")
    bar_s, bars = float(raw["bar_seconds"]), int(raw["bars"])
    if bar_s <= 0 or bars < 1:
        raise ValueError("options needs bar_seconds > 0 and bars >= 1")
    now = raw.get("now")
    now = int(now) if now is not None and 0 <= int(now) < len(opts) else None
    return {"layout": "buttons" if raw.get("layout") == "buttons" else "slider", "name": str(raw.get("name", ""))[:80],
            "bar_seconds": bar_s, "bars": bars, "now": now,
            "options": [{"label": str(o.get("label", i + 1))[:40], "match_db": round(float(o.get("match_db") or 0), 2)}
                        for i, o in enumerate(opts)]}


def _when(conversation: "Conversation", intro: str) -> str:
    """When music cued now plays, for the tools' answers: Claude should not say it is playing while it waits."""
    after = f" and {intro}" if intro else ""
    if conversation.music_waits:
        return f"when your turn ends, after your reply{after}"
    return f"now, after {intro}" if intro else "now"


def _ok(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


def _error(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "is_error": True}


def server(conversation: "Conversation") -> McpSdkServerConfig:
    @tool("present_music",
          "Put a rendered audio file in Anthony's chat as a music bubble. With autoplay on (his default) it plays on "
          "his phone when your turn ends, after your reply: the app says its `title`, then its `note`, then counts "
          "in (\"Three, two, one.\"), and the music starts. So `note` is its spoken description, and your reply "
          "need not repeat it. Use it for every render he should hear. For an A/B that switches every bar, fill in "
          "`ab`; for options baked into one file (a slider, or buttons), fill in `options`.",
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
            options = baked_options(args["options"]) if args.get("options") else None
            msg = await conversation.present_music(path, str(args["title"])[:120], ab, str(args.get("note", ""))[:600],
                                                   options=options)
        except Exception as exc:  # noqa: BLE001 - report to Claude, which can fix the file and retry
            return _error(f"Could not present it: {exc}")
        autoplay, when = conversation.hub.autoplay, _when(conversation, "its intro (title, note, count-in)")
        if options:
            n, playing = len(options["options"]), (f"It sweeps through them on his phone {when}, one bar each."
                                                   if autoplay else "Autoplay is off: it waits.")
            return _ok(f"Options #{msg.seq}: {n} of them, in memory on his phone once it loads. {playing} He moves "
                       "between them himself; when he picks one, his next message says which.")
        playing = f"It plays on his phone {when}." if autoplay else "Autoplay is off: it waits in the chat."
        return _ok(f"Music #{msg.seq}, {msg.data['duration']:.1f} s. {playing}")

    @tool("play_music", "Play a music bubble again on Anthony's phone, `loops` times in a row (the last one unless "
          "you give `seq`), when your turn ends, after your reply and a short intro (\"Again: <title>. Three, two, "
          "one.\"). Use it for 'play again' (1) or 'loop that three times' (3).", PLAY)
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
        when = _when(conversation, "a short intro" if conversation.hub.autoplay else "")
        return _ok(f"Music #{msg.seq} ({msg.data.get('title')}) plays {loops} time(s) on his phone {when}.")

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
