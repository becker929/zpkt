"""The CLI's help and error shapes: no doubled program name, plain help when piped, one error envelope."""

from __future__ import annotations

import json

import pytest
import typer
from typer.testing import CliRunner

from zpkt.app import agent_commands
from zpkt.app.web import error_body, error_response
from zpkt.cli import live_invocation, plain_help


def usage_of(args: list[str]) -> str:
    from zpkt.live.cli import app

    hands = typer.main.get_group(app)
    rest, prog = live_invocation(args, list(hands.commands), list(hands.commands["live"].commands))  # type: ignore[attr-defined]
    result = CliRunner().invoke(app, [*rest, "--help"], prog_name=prog)
    assert result.exit_code == 0, result.output
    return result.output


@pytest.mark.parametrize("word", ["state", "describe"])
def test_live_help_says_zpkt_live_once(word):
    out = usage_of([word])
    assert "Usage: zpkt live " + word in out


def test_hands_own_commands_keep_their_path():
    assert "Usage: zpkt live als" in usage_of(["als"])


def test_state_and_als_reads_take_json():
    for words in (
        ["state", "ls"],
        ["state", "diff"],
        ["state", "take"],
        ["als", "check"],
        ["als", "params"],
        ["als", "mix"],
    ):
        assert "--json" in usage_of(words), words


def test_audio_help_names_zpkt_audio_not_ears():
    from zpkt.audio import cli

    out = CliRunner().invoke(cli.app, ["--help"], prog_name="zpkt audio").output
    assert "zpkt audio" in out and "ears: measure" not in out
    assert cli.program() in ("zpkt audio", "ears")


def test_help_is_plain_when_piped_or_no_color():
    assert plain_help(False, {}) and plain_help(True, {"NO_COLOR": "1"})
    assert not plain_help(True, {})


def test_describe_brief_drops_stops():
    from zpkt.live.describe import brief

    d = {"key": "k", "stops": [{"shown": "1", "raw": 0}], "now": ["1", 0]}
    assert brief(d) == {"key": "k", "now": ["1", 0]}  # type: ignore[arg-type]


def test_every_web_error_has_ok_false_and_error():
    assert error_body("no") == {"ok": False, "error": "no"}
    r = error_response("no", 404)
    assert r.code == 404 and json.loads(r.body) == {"ok": False, "error": "no"}


def test_a_long_measurement_is_sent_as_a_summary():
    small = {"sources": {"a": 1}, "x": {"k": 1}}
    assert agent_commands.measurement_view(small) == {"analysis": small}
    big = {"sources": {"a": 1}, "x": {"k": "z" * agent_commands.MAX_MEASUREMENT_BYTES}}
    view = agent_commands.measurement_view(big)
    assert view["cut"] and view["sources"] == ["a"] and view["sections"]["x"] == ["k"]
    assert len(json.dumps(view)) < 500
