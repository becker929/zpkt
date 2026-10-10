"""Tool calls in a few words, for the chat, the narrator and screenshot captions."""

from __future__ import annotations

import json
import os
from typing import Any


def describe(tool: str, args: dict[str, Any]) -> str:
    """A tool call in a few words, for the chat and the narrator."""
    def base(p: Any) -> str:
        return os.path.basename(str(p or "")) or "a file"

    short = tool.removeprefix("mcp__studio__")
    if tool == "Bash":
        return str(args.get("description") or args.get("command", ""))[:90] or "Run a command"
    if tool in ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit"):
        verb = {"Read": "Read", "Write": "Write", "NotebookEdit": "Edit"}.get(tool, "Edit")
        return f"{verb} {base(args.get('file_path') or args.get('notebook_path'))}"
    if tool in ("Glob", "Grep"):
        return f"Search for {str(args.get('pattern', ''))[:60]}"
    if tool == "Skill":
        return f"Use the {args.get('skill') or args.get('name') or 'a'} skill"
    if tool in ("Task", "Agent"):
        return str(args.get("description") or "Start a helper")[:90]
    if tool == "WebSearch":
        return f"Search the web for {str(args.get('query', ''))[:60]}"
    if tool == "WebFetch":
        return f"Read {str(args.get('url', ''))[:60]}"
    if tool == "TodoWrite":
        return "Update the plan"
    if short == "present_music":
        return f"Present {args.get('title', 'music')}"
    if short == "play_music":
        return f"Play it {args.get('loops', 1)}×"
    if short == "screenshot":
        return f"Screenshot: {str(args.get('caption', ''))[:60]}"
    return short.replace("_", " ")


def detail(args: dict[str, Any]) -> str:
    if "command" in args:
        return str(args["command"])[:2000]
    return json.dumps(args, ensure_ascii=False)[:2000]
