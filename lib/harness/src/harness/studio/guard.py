"""Commands the studio session never runs, whatever it is told: a PreToolUse check on every Bash call.

The session runs in auto mode, so a safety classifier already judges each action. These are the few hard rules
that hold regardless, because a misheard sentence must never cost data: no sudo, no force pushes and no pushes to
main (saving goes through pull requests), no secrets read out of the Keychain, no disk tools, and no recursive
delete of a top-level folder (the root, the home folder, or anything directly under them).
"""

from __future__ import annotations

import re
from typing import Any

_SEP = r"(?:^|[;&|(`]|\$\()\s*"          # the start of a command, also after ; && || | ( ` and $(

RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(_SEP + r"sudo\b"), "sudo"),
    (re.compile(r"\bgit\s+push\b[^;&|]*?\s(?:--force(?:-with-lease)?\b|-f\b|\+\S)"), "a force push"),
    (re.compile(r"\bgit\s+push\b[^;&|]*?\s(?:\S+:)?(?:refs/heads/)?(?:main|master)(?:\s|$|;|&|\|)"),
     "a push to main (save through a pull request)"),
    (re.compile(r"\bsecurity\s+(?:find-(?:generic|internet)-password\b[^;&|]*\s-w\b|dump-keychain\b)"),
     "reading secrets from the Keychain"),
    (re.compile(_SEP + r"(?:mkfs\S*|diskutil\s+(?:erase\w*|partition\w*|zero\w*)|dd\s+[^;&|]*\bof=/dev/)"),
     "a disk tool"),
    (re.compile(r"\brm\s+(?:-{1,2}\w[\w-]*\s+)*-\w*[rR]\w*\s+(?:-{1,2}\w[\w-]*\s+)*[\"']?"
                r"(?:/|~/?|\$HOME/?|\$\{HOME\}/?|\.\./?)(?:[^/\s\"';&|]+/?)?[\"']?(?:\s|$|;|&|\|)"),
     "a recursive delete of a top-level folder"),
]


def check(command: str) -> str | None:
    """Why `command` is refused, or None if it may run."""
    for pattern, what in RULES:
        if pattern.search(command):
            return what
    return None


async def bash_hook(data: dict[str, Any], _tool_use_id: str | None, _ctx: Any) -> dict[str, Any]:
    """Agent SDK PreToolUse hook (matcher "Bash")."""
    why = check(str((data.get("tool_input") or {}).get("command", "")))
    if why is None:
        return {}
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": f"studio never runs {why}. Ask Anthony to do it."}}
