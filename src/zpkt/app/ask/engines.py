"""The command line of one Claude Code turn, and the permission modes. Pure: arguments in, a command out.

Three permission levels hold for both engines: read-only (`plan`), edit files without a shell (`auto_edit`) and full
(`yolo`). `ask` is for Gemini: every edit and command waits for a yes from the page.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

MODES = ("plan", "auto_edit", "yolo", "ask")
CLAUDE_MODE = {"plan": "plan", "auto_edit": "acceptEdits", "yolo": "bypassPermissions", "ask": "default"}
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
        return json.dumps({"mcpServers": {"zpkt": server}})


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
        CLAUDE_MODE.get(mode, "plan"),
    ]
    if model:
        args += ["--model", model]
    args += ["--resume", session_id] if resume else ["--session-id", session_id]
    if system:
        args += ["--append-system-prompt", system]
    if tools is not None:
        args += ["--mcp-config", tools.claude_config(), "--allowedTools", "mcp__zpkt"]
    dirs = [str(d) for d in extra_dirs or [] if d and Path(d).exists()]
    if dirs:
        args += ["--add-dir", *dirs]  # variadic, so it goes last
    return CliCommand(claude_bin, args, prompt, claude_env(environ, home, token))
