"""The command line of one Claude Code turn."""

from __future__ import annotations

import json
from pathlib import Path

from zpkt.app.ask.engines import CLAUDE_MODE, DEFAULT_MODE, MODES, ToolServer, claude_command

HOME = Path("/Users/someone")


def command(**kw):
    base = dict(
        prompt="-hello", mode="build", model="", resume=False, session_id="sid", claude_bin="claude",
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
        "dontAsk",
    ]
    assert c.args[c.args.index("--session-id") + 1] == "sid"


def test_a_started_session_resumes_and_options_are_added():
    c = command(resume=True, model="opus", system="guide")
    assert c.args[c.args.index("--resume") : c.args.index("--resume") + 2] == ["--resume", "sid"]
    assert "--session-id" not in c.args
    assert c.args[c.args.index("--model") + 1] == "opus"
    assert c.args[c.args.index("--append-system-prompt") + 1] == "guide"


def after(c, flag: str) -> list[str]:
    return c.args[c.args.index(flag) + 1].split(",")


def test_the_modes_map_to_claudes_and_unknown_is_the_default():
    assert set(MODES) == set(CLAUDE_MODE) and DEFAULT_MODE == "auto"
    assert command(mode="yolo").args[6] == "bypassPermissions"
    assert command(mode="auto_edit").args[6] == "acceptEdits"
    assert command(mode="build").args[6] == "dontAsk"
    # the default is full power (26 November 2026): Claude Code's own auto mode, with the shell and every tool
    full = command(mode="nonsense")
    assert full.args[6] == command(mode="auto").args[6] == "auto"
    assert "--disallowedTools" not in full.args and "--strict-mcp-config" not in full.args
    assert "plan" not in [command(mode=m).args[6] for m in MODES if m != "plan"]  # plan mode builds nothing


def test_the_default_mode_runs_the_apps_tools_and_reads_and_refuses_what_writes_or_runs():
    """`build`: Claude Code's `dontAsk` (what no rule allows is refused, with no question), the app's tool server and
    the reading tools allowed, and deny rules for everything that edits a file or runs a command."""
    tools = ToolServer("python", ("-m", "zpkt.app.ask.mcp"), {})
    for mode in ("build", "ask"):  # Claude has nobody to ask on the page: "ask" is "build" for it
        c = command(mode=mode, tools=tools)
        assert c.args[6] == "dontAsk"
        assert after(c, "--allowedTools") == ["mcp__zpkt", "Read", "Glob", "Grep"]
        assert {"Bash", "Edit", "Write", "NotebookEdit", "EnterPlanMode", "ExitPlanMode"} <= set(
            after(c, "--disallowedTools")
        )
        assert "--strict-mcp-config" in c.args  # only the app's server, not the Mac's others
    assert "mcp__zpkt" not in after(command(mode="build"), "--allowedTools")  # no tool server: reads only
    for mode in ("auto_edit", "yolo"):  # a developer's modes: the app's tools run there too, nothing is denied
        c = command(mode=mode, tools=tools)
        assert after(c, "--allowedTools") == ["mcp__zpkt"] and "--disallowedTools" not in c.args


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
    assert c.args[c.args.index("--allowedTools") + 1].split(",")[0] == "mcp__zpkt"
    assert "--mcp-config" not in command().args


def test_extra_folders_go_last_and_only_if_they_exist(tmp_path):
    c = command(extra_dirs=[tmp_path, tmp_path / "missing"])
    assert c.args[-2:] == ["--add-dir", str(tmp_path)]
