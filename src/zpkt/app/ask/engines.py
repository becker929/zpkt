"""The command line of one Claude Code turn, and the permission modes. Pure: arguments in, a command out.

The modes, for both engines:

    auto       the default (Anthony, 26 November 2026: "full power again with shell and auto mode and everything"): the
               agent has every tool, the shell and file edits included, and the app's tools. Claude Code runs in its own
               `auto` permission mode, where it decides for itself what is safe to do; Gemini CLI runs in `yolo`.
    build      the careful one: the agent advises and uses the app's five tools (make or
               change a page, read the state, read the measurement, change Live, propose a change to Live). It reads
               files. It cannot edit a file or run a command, and no mode's question is asked.
    ask        the same, and with Gemini every edit and command waits for a yes from the page. Claude Code has nobody
               to ask on this page, so there it is `build`.
    auto_edit  developer: edits files without asking, no shell.
    yolo       developer: everything.
    plan       read-only with no tools: the summary of a compaction is written in it. The page never sends it; a turn
               that names it runs as `build` (service.py).

The app's tools run in every mode without a question from the mode. Three of them never move Live. The fourth,
`change_live`, does (Anthony, 26 November 2026: values and devices are act, then undo, no question asked): the app
checks each batch whole and keeps it as one History row that one undo takes back (zpkt.app.change). The fifth,
`propose_live`, is the other half of that decision: structure and code are ask first. It carries its own question,
in every mode and for both engines: the app shows the batch as a card in the chat and runs it only after the
person's tap (zpkt.app.propose, tools.py). That question is the app's, not the engine's permission prompt.
An ability (`ability_<name>`: code the person answered with "Always" on such a card, zpkt.app.abilities) is one
more tool each. It runs in every mode with no question at all: that tap was the standing yes.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

MODES = ("auto", "build", "ask", "auto_edit", "yolo", "plan")
DEFAULT_MODE = "auto"
CLAUDE_DEFAULT_MODEL = "claude-opus-5-5"  # CLAUDE_AGENT_MODEL overrides it
# `dontAsk`: what is not allowed by a rule is refused without a question (`claude -p` has nobody to ask).
CLAUDE_MODE = {
    "auto": "auto",
    "build": "dontAsk",
    "ask": "dontAsk",
    "auto_edit": "acceptEdits",
    "yolo": "bypassPermissions",
    "plan": "plan",
}
TOOL_SERVER = "zpkt"
CLAUDE_TOOLS = f"mcp__{TOOL_SERVER}"  # every tool of the app's server
CLAUDE_READS = ("Read", "Glob", "Grep")
# Refused in `build` whatever the Mac's own Claude settings allow: a deny rule wins over an allow rule. The plan
# tools are here so the agent never puts itself in plan mode, where it would only describe what it would do.
CLAUDE_NEVER = ("Bash", "Edit", "Write", "NotebookEdit", "EnterPlanMode", "ExitPlanMode")
MODEL_NAME = re.compile(r"^[\w.\-]+$")
# Variables of a parent Claude Code session that must never leak into the child.
PARENT_VARS = re.compile(r"^CLAUDE_CODE_(?!OAUTH_TOKEN$)|^CLAUDECODE$|^CLAUDE_AGENT_SDK")


@dataclass(frozen=True)
class ToolServer:
    """The stdio MCP server that gives an agent the app's tools (mcp.py), and what it needs to reach the app."""

    command: str  # the Python that runs it
    args: tuple[str, ...]
    env: Mapping[str, str]  # ZPKT_DESK_URL, ZPKT_APP_SESSION, ZPKT_APP_TOKEN

    def claude_config(self) -> str:
        server = {"command": self.command, "args": list(self.args), "env": dict(self.env)}
        return json.dumps({"mcpServers": {TOOL_SERVER: server}})


@dataclass(frozen=True)
class CliCommand:
    """What to run: the program, its arguments, what to write to its stdin and its environment."""

    bin: str
    args: list[str]
    stdin: str | None = None
    env: dict[str, str] = field(default_factory=dict)


def agent_path(home: Path, path: str = "") -> str:
    """PATH for agents: uv and cargo tools in front."""
    return ":".join(p for p in (str(home / ".local" / "bin"), str(home / ".cargo" / "bin"), path) if p)


def claude_env(environ: Mapping[str, str], home: Path, token: str = "") -> dict[str, str]:
    env = {**environ, "NO_COLOR": "1", "PATH": agent_path(home, environ.get("PATH", "")), "ZPKT_AGENT": "1"}
    for key in [k for k in env if PARENT_VARS.search(k)]:
        del env[key]
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    return env


def claude_command(
    *,
    prompt: str,
    mode: str,
    model: str,
    resume: bool,
    session_id: str,
    claude_bin: str,
    environ: Mapping[str, str],
    home: Path,
    token: str = "",
    system: str = "",
    extra_dirs: list[Path] | None = None,
    tools: ToolServer | None = None,
) -> CliCommand:
    """One headless turn of Claude Code. The prompt goes on stdin: no argv limit, and a prompt starting with "-" is
    never read as a flag. With `tools`, the agent has the app's tools and no others of this server."""
    args = [
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--permission-mode",
        CLAUDE_MODE.get(mode, CLAUDE_MODE[DEFAULT_MODE]),
    ]
    guarded = CLAUDE_MODE.get(mode, CLAUDE_MODE[DEFAULT_MODE]) == "dontAsk"
    if model:
        args += ["--model", model]
    args += ["--resume", session_id] if resume else ["--session-id", session_id]
    if system:
        args += ["--append-system-prompt", system]
    if tools is not None:
        args += ["--mcp-config", tools.claude_config()]
    allowed = ([CLAUDE_TOOLS] if tools is not None else []) + (list(CLAUDE_READS) if guarded else [])
    if allowed:
        args += ["--allowedTools", ",".join(allowed)]
    if guarded:
        # Only the app's server: the Mac's other MCP servers (mail, documents) are not this chat's business.
        args += ["--disallowedTools", ",".join(CLAUDE_NEVER), "--strict-mcp-config"]
    dirs = [str(d) for d in extra_dirs or [] if d and Path(d).exists()]
    if dirs:
        args += ["--add-dir", *dirs]  # variadic, so it goes last
    return CliCommand(claude_bin, args, prompt, claude_env(environ, home, token))
