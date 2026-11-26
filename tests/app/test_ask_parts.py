"""Ask's smaller parts: Gemini's updates as events, media paths, workspaces, notes' rules, and the boundary."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import jsonschema
import pytest

from zpkt.app.ask.gemini import Running, tool_output, tool_view, update_events
from zpkt.app.ask.media import byte_range, resolve_media, save_attachment
from zpkt.app.ask.notes import check_notes, named
from zpkt.app.ask.store import Refused
from zpkt.app.ask.workspaces import Workspaces

SRC = Path(__file__).resolve().parents[2] / "src" / "zpkt"
EVENT_SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "lib" / "contracts" / "ask-event.schema.json").read_text()
)


def running() -> Running:
    return Running(lambda e: None, lambda tool, options: None)


def test_gemini_updates_become_the_pages_events_and_pass_the_schema():
    r = running()
    got = [
        *update_events({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "Hi"}}, r),
        *update_events(
            {
                "sessionUpdate": "tool_call",
                "toolCallId": "t",
                "title": "Edit a.txt",
                "kind": "edit",
                "locations": [{"path": "/a.txt"}],
            },
            r,
        ),
        *update_events({"sessionUpdate": "tool_call_update", "toolCallId": "t", "status": "in_progress"}, r),
        *update_events(
            {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "t",
                "status": "completed",
                "content": [{"type": "diff", "path": "/a.txt", "oldText": "a", "newText": "b"}],
            },
            r,
        ),
        *update_events({"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": "hmm"}}, r),
        *update_events({"sessionUpdate": "plan", "entries": []}, r),
    ]
    assert [e["type"] for e in got] == ["message", "tool_use", "tool_result"]
    assert got[1]["parameters"] == {"kind": "edit", "paths": ["/a.txt"]} and got[2]["output"] == "edited /a.txt"
    for e in got:
        jsonschema.validate(e, EVENT_SCHEMA)


def test_a_mode_change_said_as_text_is_not_shown_and_an_unknown_tool_update_is_ignored():
    r = running()
    assert (
        update_events(
            {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "[MODE_UPDATE] autoEdit"}}, r
        )
        == []
    )
    assert r.mode_seen == "autoEdit"
    assert (
        update_events({"sessionUpdate": "tool_call_update", "toolCallId": "never-seen", "status": "completed"}, r) == []
    )


def test_tool_view_bounds_what_it_shows():
    view = tool_view(
        {
            "title": "T",
            "content": [{"type": "content", "content": {"type": "text", "text": "x" * 9000}}],
            "locations": [{"path": f"/{i}"} for i in range(30)],
        }
    )
    assert len(view["content"][0]["text"]) == 6000 and len(view["paths"]) == 20
    assert tool_output(view).startswith("x")


def test_media_paths_stay_inside_home_and_out_of_hidden_folders(tmp_path):
    home = tmp_path / "home"
    (home / "work" / ".git").mkdir(parents=True)
    (home / "work" / "a.wav").write_bytes(b"x" * 10)
    (home / "work" / ".git" / "b.wav").write_bytes(b"x")
    (home / "work" / "c.txt").write_text("t")
    outside = tmp_path / "o.wav"
    outside.write_bytes(b"x")
    cwd = home / "work"
    assert resolve_media("a.wav", cwd, home).type == "audio/wav"
    assert resolve_media(str(cwd / "a.wav"), cwd, home).size == 10
    for path, code in (
        (".git/b.wav", 403),
        (str(outside), 403),
        ("c.txt", 415),
        ("nope.wav", 404),
        ("", 400),
        (None, 400),
        (".", 415),
    ):
        with pytest.raises(Refused) as why:
            resolve_media(path, cwd, home)
        assert why.value.code == code, path


def test_byte_ranges():
    assert byte_range("", 100) is None and byte_range("bytes=-", 100) is None
    assert byte_range("bytes=10-19", 100) == (10, 19) and byte_range("bytes=90-", 100) == (90, 99)
    assert byte_range("bytes=-10", 100) == (90, 99) and byte_range("bytes=50-500", 100) == (50, 99)
    with pytest.raises(Refused):
        byte_range("bytes=200-300", 100)


def test_attachments_are_images_of_bounded_size(tmp_path):
    name, size = save_attachment(tmp_path / "a", "data:image/jpeg;base64,AAAA", "My shot!.JPG")
    assert name.endswith("-My-shot-.jpg") and size == 3 and (tmp_path / "a" / name).exists()
    for bad in ("data:image/svg+xml;base64,AAAA", "data:image/png;base64,@@@@", None):
        with pytest.raises(Refused):
            save_attachment(tmp_path, bad)


def test_workspaces_start_with_scratch_and_desktop_and_stay_in_home(tmp_path):
    ws = Workspaces(tmp_path / "d", home=tmp_path)
    assert [w["id"] for w in ws.all()] == ["scratch", "desktop"]
    assert [w["id"] for w in Workspaces(tmp_path / "d", home=tmp_path).all()] == ["scratch", "desktop"]  # read back
    ws.ensure(ws.get("scratch") or {})
    assert (tmp_path / "gemini-scratch").is_dir()
    with pytest.raises(Refused, match="Folder is gone"):
        ws.ensure(ws.get("desktop") or {})
    (tmp_path / "x").mkdir()
    a, b = ws.add("", "~/x"), ws.add("", "x")
    assert a["path"] == b["path"] == str((tmp_path / "x").resolve()) and a["id"] != b["id"]
    with pytest.raises(Refused, match="inside your home"):
        ws.add("", "/")


def test_notes_name_a_project_by_a_known_name_or_a_set_shaped_word_not_gear():
    assert named("how is HW002 doing", []) == "HW002"
    assert named("the TR808 and the SM57", []) is None
    assert named("mix hw002 and SH999", ["hw002"]) == "hw002"  # a known project wins
    assert named("nothing here", []) is None


def test_notes_lines_are_checked_before_they_are_written():
    assert check_notes('{"notes": ["- Kick at 60 Hz.", "<b>no</b>", "ok", "A second real line."]}') == [
        "Kick at 60 Hz.",
        "A second real line.",
    ]
    assert check_notes("not json") == [] and check_notes('{"notes": "x"}') == [] and check_notes("") == []


def test_ask_modules_import_nothing_from_zpkt_live():
    """An agent's way in is the app's commands. The ask package and the tool table never touch zpkt.live;
    agent_commands.py is the one place that does, as the app's own service, through the app's connection."""
    for path in (SRC / "app" / "ask").glob("*.py"):
        imported = {
            n.module for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.ImportFrom) and n.module
        }
        imported |= {
            a.name for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.Import) for a in n.names
        }
        live = {m for m in imported if m.startswith("zpkt.live") or m.startswith("hands")}
        assert not live, f"{path.name} imports {live}"


def test_no_ask_module_reads_a_key_itself():
    """Keys come only through the secret lookup the app is given: no module of Ask reads a key, token or secret from
    the environment, runs `security`, or opens a .env file. (A key is only put into a child's own environment.)"""
    for path in (SRC / "app" / "ask").glob("*.py"):
        if path.name == "mcp.py":  # it reads ZPKT_APP_TOKEN: the session's token the app itself put in its environment
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("get", "getenv", "pop")
            ):
                first = node.args[0] if node.args else None
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    is_variable = first.value.isupper() and any(w in first.value for w in ("KEY", "TOKEN", "SECRET"))
                    assert not is_variable, f"{path.name}:{node.lineno} reads {first.value}"
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in ("security", ".env"), f"{path.name}:{node.lineno}"


def test_the_app_starts_web_and_agents_by_name_and_ask_data_goes_where_the_environment_says(tmp_path, monkeypatch):
    import urllib.request

    from tests.app.conftest import FakeMeter, make_settings
    from zpkt.app import adapters, parse_args
    from zpkt.app.adapters import AppContext
    from zpkt.app.connections import LiveConnections
    from zpkt.app.desk import Desk
    from zpkt.live.testing import FakeLive, hw002_like

    assert parse_args([]).adapters == "web,api,agents,listen"
    monkeypatch.setenv("ZPKT_ASK_DIR", str(tmp_path / "ask-data"))
    desk = Desk(make_settings(tmp_path), connections=LiveConnections(FakeLive(hw002_like()), FakeMeter()))
    web, agents = adapters.create(["web", "agents"], AppContext(desk.bus, desk, desk.settings))
    web.supervise = False
    web.start()
    agents.start()
    try:
        assert (tmp_path / "ask-data" / "workspaces.json").exists()
        with urllib.request.urlopen(f"http://127.0.0.1:{web.port}/app/ask/api/engines", timeout=10) as r:
            assert [e["id"] for e in json.loads(r.read())["engines"]] == ["claude", "gemini"]
        assert {"page.draft", "desk.state", "measurement.read"} <= set(desk.bus.kinds())
    finally:
        agents.stop()
        web.stop()
    assert desk.mounts.find("/app/ask") is None  # the adapter took its routes off the one seam
