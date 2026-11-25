"""The command line of one Claude Code turn."""

from __future__ import annotations

import json
from pathlib import Path

from zpkt.app.ask.engines import CLAUDE_MODE, MODES, ToolServer, claude_command

HOME = Path("/Users/someone")


def command(**kw):
    base = dict(
        prompt="-hello", mode="plan", model="", resume=False, session_id="sid", claude_bin="claude",
        environ={"PATH": "/usr/bin", "KEEP": "1"}, home=HOME,
    )  # fmt: skip
    return claude_command(**{**base, **kw})


def test_the_prompt_goes_on_stdin_and_a_new_session_gets_an_id():
    c = command()
    assert c.stdin == "-hello" and "-hello" not in c.args
    assert c.args[:7] == [
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--permission-mode",
        "plan",
    ]
    assert c.args[-2:] == ["--session-id", "sid"]


def test_a_started_session_resumes_and_options_are_added():
    c = command(resume=True, model="opus", system="guide")
    assert c.args[c.args.index("--resume") : c.args.index("--resume") + 2] == ["--resume", "sid"]
    assert "--session-id" not in c.args
    assert c.args[c.args.index("--model") + 1] == "opus"
    assert c.args[c.args.index("--append-system-prompt") + 1] == "guide"


def test_the_modes_map_to_claudes_and_unknown_is_read_only():
    assert set(MODES) == set(CLAUDE_MODE)
    assert command(mode="yolo").args[6] == "bypassPermissions"
    assert command(mode="auto_edit").args[6] == "acceptEdits"
    assert command(mode="nonsense").args[6] == "plan"


def test_the_environment_drops_a_parent_sessions_variables_and_adds_the_token():
    env = {
        "PATH": "/usr/bin",
        "CLAUDECODE": "1",
        "CLAUDE_CODE_ENTRYPOINT": "x",
        "CLAUDE_AGENT_SDK_VERSION": "1",
        "CLAUDE_CODE_OAUTH_TOKEN": "old",
        "KEEP": "1",
    }
    c = command(environ=env, token="new")
    assert c.env["CLAUDE_CODE_OAUTH_TOKEN"] == "new" and c.env["KEEP"] == "1" and c.env["ZPKT_AGENT"] == "1"
    assert not any(k in c.env for k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_AGENT_SDK_VERSION"))
    assert c.env["PATH"].startswith(f"{HOME}/.local/bin:{HOME}/.cargo/bin:")
    assert command(environ=env).env["CLAUDE_CODE_OAUTH_TOKEN"] == "old"  # no new token: the CLI's own


def test_the_tool_server_is_given_as_an_mcp_config_and_nothing_else_of_it_is_allowed():
    tools = ToolServer("python", ("-m", "zpkt.app.ask.mcp"), {"ZPKT_APP_URL": "http://x"})
    c = command(tools=tools)
    config = json.loads(c.args[c.args.index("--mcp-config") + 1])
    assert config == {
        "mcpServers": {
            "zpkt": {"command": "python", "args": ["-m", "zpkt.app.ask.mcp"], "env": {"ZPKT_APP_URL": "http://x"}}
        }
    }
    assert c.args[c.args.index("--allowedTools") + 1] == "mcp__zpkt"
    assert "--mcp-config" not in command().args


def test_extra_folders_go_last_and_only_if_they_exist(tmp_path):
    c = command(extra_dirs=[tmp_path, tmp_path / "missing"])
    assert c.args[-2:] == ["--add-dir", str(tmp_path)]
