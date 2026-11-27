"""Ask over HTTP: the page, the API and the stream, on the real server started in this process (fakes behind it)."""

from __future__ import annotations

import base64
import json
import os
import re
import stat
import sys
import urllib.error
import urllib.request
from pathlib import Path

import jsonschema

from zpkt.app.ask.claude import ClaudeProvider
from zpkt.app.ask.testing import Call, Permit, ScriptedProvider, Wait

API = "/app/ask/api"
CONTRACTS = Path(__file__).resolve().parents[2] / "lib" / "contracts"
FAKE_CLAUDE = Path(__file__).parent / "fakes" / "fake_claude.py"


def text(t: str) -> dict:
    return {"type": "message", "role": "assistant", "content": t, "delta": True}


def script(asked, engine: str, *steps) -> ScriptedProvider:
    asked.providers[engine].script = list(steps)
    return asked.providers[engine]


def start(asked, prompt="hello", **extra) -> dict:
    code, body = asked.rig.post(f"{API}/sessions", {"workspace": "work", "prompt": prompt, "engine": "claude", **extra})
    assert code == 200, body
    return body["session"]


def raw(asked, method: str, path: str, headers: dict | None = None, body: bytes | None = None):
    req = urllib.request.Request(asked.rig.url + path, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def test_the_page_and_its_assets_are_served_and_point_at_the_apps_api(asked):
    code, body, headers = raw(asked, "GET", "/app/ask/")
    assert code == 200 and headers["Content-Type"].startswith("text/html")
    html = body.decode()
    assert "/app/ask/api" in html and "/app/ask/zpkt/index.js" in html and 'src="/api/' not in html
    assert raw(asked, "GET", "/app/ask")[0] == 200
    code, _js, headers = raw(asked, "GET", "/app/ask/zpkt/index.js")
    assert code == 200 and "javascript" in headers["Content-Type"]
    assert raw(asked, "GET", "/app/ask/zpkt/missing.js")[0] == 404
    assert raw(asked, "GET", "/app/ask/zpkt/..%2f..%2fapp.html")[0] == 404
    assert raw(asked, "GET", "/app/ask/nothing")[0] == 404


def test_every_api_path_the_page_calls_is_served(asked):
    """The page's own fetches: nothing it calls may be a surprise 404, and the widget routes are gone."""
    root = Path(__file__).resolve().parents[2] / "src" / "zpkt" / "app" / "static" / "ask"
    source = (root / "index.html").read_text() + "".join(p.read_text() for p in (root / "zpkt").glob("*.js"))
    paths = set(re.findall(r"/app/ask/api/([a-z]+)", source)) | set(re.findall(r"\$\{API\}/([a-z]+)", source))
    served = {"engines", "workspaces", "sessions", "attachments", "main", "archive", "abilities"}
    assert paths == served, paths ^ served
    assert asked.rig.get(f"{API}/abilities")[0] == 200
    for gone in ("surfaces", "library"):
        assert asked.rig.get(f"{API}/{gone}")[0] == 404
    assert not re.search(r"requestMIDIAccess|zpkt-surface-state|AudioContext|createOscillator", source)
    s = asked.ask.main()
    assert asked.rig.post(f"{API}/sessions/{s['id']}/surface", {"spec": {"controls": []}})[0] == 404


def test_a_session_runs_streams_and_replays(asked):
    script(
        asked,
        "claude",
        {"type": "init"},
        text("Hi "),
        text("there"),
        {"type": "result", "status": "success", "stats": {}},
    )
    s = start(asked)
    events = asked.stream(s["id"], lambda e: e["type"] == "run_end")
    assert [e["type"] for e in events][:1] == ["prompt"] and events[-1]["type"] == "run_end"
    asked.ask.wait_idle()
    again = asked.stream(s["id"], lambda e: e["type"] == "__state")
    assert [e["type"] for e in again] == ["prompt", "init", "message", "message", "result", "run_end", "__state"]
    assert again[-1]["running"] is False
    later = asked.stream(s["id"], lambda e: e["type"] == "__state", start=4)
    assert [e["seq"] for e in later if "seq" in e] == [4, 5]
    req = urllib.request.Request(f"{asked.rig.url}{API}/sessions/{s['id']}/stream", headers={"Last-Event-ID": "3"})
    with urllib.request.urlopen(req, timeout=10) as r:
        assert r.readline().decode().strip() == "id: 4"
    schema = json.loads((CONTRACTS / "ask-event.schema.json").read_text())
    for e in events:
        if e["type"] != "__state":  # the stream's own marker (a late reader gets it after the replay), not an event
            jsonschema.validate(e, schema)
    jsonschema.validate(asked.ask.store.get(s["id"]), json.loads((CONTRACTS / "ask-session.schema.json").read_text()))


def test_messages_stop_rename_delete_and_restore(asked):
    script(asked, "claude", Wait())
    s = start(asked, "long job")
    sid = s["id"]
    listed = asked.rig.get(f"{API}/sessions")[1]["sessions"]
    assert listed[0]["id"] == sid and listed[0]["running"] is True
    assert asked.rig.post(f"{API}/sessions/{sid}/messages", {"prompt": "x", "engine": "claude"})[0] == 409
    assert asked.rig.request("DELETE", f"{API}/sessions/{sid}")[0] == 409
    assert asked.rig.post(f"{API}/sessions/{sid}/stop")[1] == {"stopped": True}
    asked.ask.wait_idle()
    assert asked.rig.request("PATCH", f"{API}/sessions/{sid}", {"title": "Renamed"})[1]["session"]["title"] == "Renamed"
    assert asked.rig.request("PATCH", f"{API}/sessions/{sid}", {"title": " "})[0] == 400
    script(asked, "claude", text("again"))
    assert (
        asked.rig.post(f"{API}/sessions/{sid}/messages", {"prompt": "more", "engine": "claude", "mode": "auto_edit"})[0]
        == 200
    )
    asked.ask.wait_idle()
    assert asked.rig.request("DELETE", f"{API}/sessions/{sid}")[0] == 200
    assert asked.rig.get(f"{API}/sessions")[1]["sessions"] == []
    assert asked.rig.get(f"{API}/sessions/{sid}/stream")[0] == 404
    assert asked.rig.post(f"{API}/sessions/{sid}/restore")[1]["session"]["id"] == sid
    assert asked.rig.post(f"{API}/sessions/{'0' * 8}-0000-0000-0000-{'0' * 12}/restore")[0] == 404


def test_bad_requests_get_a_status_and_a_sentence(asked):
    bad = [
        ({"workspace": "nope", "prompt": "x"}, "Unknown workspace"),
        ({"workspace": "work", "prompt": " "}, "Empty prompt"),
        ({"workspace": "work", "prompt": "x", "engine": "nope"}, "Invalid engine"),
        ({"workspace": "work", "prompt": "x", "mode": "root"}, "Invalid mode"),
    ]
    for body, why in bad:
        code, reply = asked.rig.post(f"{API}/sessions", body)
        assert code == 400 and reply["error"] == why
    assert raw(asked, "POST", f"{API}/sessions", {"Content-Type": "application/json"}, b"{nope")[0] == 400
    assert raw(asked, "POST", f"{API}/sessions", {}, b"[1]")[0] == 400
    assert asked.rig.get(f"{API}/sessions")[1]["sessions"] == []


def test_a_request_another_site_makes_is_refused(asked):
    code, body, _ = raw(asked, "POST", f"{API}/sessions", {"Sec-Fetch-Site": "cross-site"}, b"{}")
    assert code == 403 and b"Cross-site" in body
    assert raw(asked, "GET", f"{API}/engines", {"Sec-Fetch-Site": "same-origin"})[0] == 200
    assert raw(asked, "GET", f"{API}/engines", {"Sec-Fetch-Site": "none"})[0] == 200


def test_old_surface_blocks_and_surface_events_still_replay(asked):
    """An old transcript keeps its control-panel block and its `surface` event; the page draws both as a stub."""
    s = asked.ask.store.create("Old", "work", str(asked.ask.workspaces.get("work")["path"]))
    block = '```zpkt-surface\n{"title": "Kick", "controls": [{"kind": "knob", "id": "a", "label": "A", "min": 0, "max": 1, "value": 0.5}]}\n```'
    asked.ask.store.emit(s["id"], {"type": "message", "role": "assistant", "content": block, "delta": True})
    asked.ask.store.emit(s["id"], {"type": "surface", "spec": {"title": "Kick", "controls": []}, "values": {"a": 0.7}})
    events = asked.stream(s["id"], lambda e: e["type"] == "__state")
    assert events[0]["content"] == block and events[1]["type"] == "surface" and events[1]["values"] == {"a": 0.7}


def test_attachments_and_media_files_with_ranges(asked, tmp_path):
    png = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()
    code, made = asked.rig.post(f"{API}/attachments", {"dataUrl": f"data:image/png;base64,{png}", "name": "shot.png"})
    name = made["attachment"]["file"]
    assert code == 200 and name.endswith("-shot.png")
    assert raw(asked, "GET", f"{API}/attachments/{name}")[1].startswith(b"\x89PNG")
    assert asked.rig.post(f"{API}/attachments", {"dataUrl": "data:text/html;base64,AAAA"})[0] == 400
    assert raw(asked, "GET", f"{API}/attachments/..%2fsessions.json")[0] in (404, 400)
    s = start(asked, "x")
    asked.ask.wait_idle()
    work = Path(asked.ask.workspaces.get("work")["path"])
    (work / "kick.wav").write_bytes(bytes(range(100)))
    (work / "notes.txt").write_text("secret")
    url = f"{API}/sessions/{s['id']}/file?path="
    code, body, headers = raw(asked, "GET", url + "kick.wav")
    assert code == 200 and len(body) == 100 and headers["Content-Type"] == "audio/wav"
    code, body, headers = raw(asked, "GET", url + "kick.wav", {"Range": "bytes=10-19"})
    assert code == 206 and body == bytes(range(10, 20)) and headers["Content-Range"] == "bytes 10-19/100"
    assert raw(asked, "GET", url + "kick.wav", {"Range": "bytes=200-300"})[0] == 416
    assert raw(asked, "GET", url + "notes.txt")[0] == 415
    assert raw(asked, "GET", url + "..%2f..%2f..%2f..%2fetc%2fpasswd")[0] in (403, 404, 415)
    assert raw(asked, "GET", url)[0] == 400


def test_workspaces_are_added_inside_home_only(asked, tmp_path):
    home = asked.ask.workspaces.home
    folder = home / "music"
    folder.mkdir(exist_ok=True)
    code, made = asked.rig.post(f"{API}/workspaces", {"path": str(folder), "name": "Music"})
    assert code == 200 and made["workspace"]["path"] == str(folder.resolve())
    assert asked.rig.post(f"{API}/workspaces", {"path": "/etc"})[0] == 400
    assert asked.rig.post(f"{API}/workspaces", {"path": str(home / "missing")})[0] == 400
    assert asked.rig.request("DELETE", f"{API}/workspaces/{made['workspace']['id']}")[0] == 200


def test_an_answer_for_nothing_waiting_is_a_409_and_a_real_one_goes_through(asked):
    s = start(asked, "x")
    asked.ask.wait_idle()
    assert asked.rig.post(f"{API}/sessions/{s['id']}/permission", {"id": "nope", "option": "yes"})[0] == 409
    script(asked, "claude", Permit("Edit a.txt"), text("ok"))
    t = start(asked, "edit", mode="ask")
    events = asked.stream(t["id"], lambda e: e["type"] == "permission")
    pid = events[-1]["id"]
    assert asked.rig.post(f"{API}/sessions/{t['id']}/permission", {"id": pid, "option": "maybe"})[0] == 400
    assert asked.rig.post(f"{API}/sessions/{t['id']}/permission", {"id": pid, "option": "yes"})[0] == 200
    asked.ask.wait_idle()
    assert asked.providers["claude"].answers == ["yes"]


def test_the_tool_route_runs_a_command_as_agent_and_refuses_the_rest(asked):
    gate = asked.ask.gate
    body = {"session": "s9", "token": gate.token("s9"), "tool": "read_state", "args": {}}
    code, reply = asked.rig.post(f"{API}/tool", body)
    assert code == 200 and reply["set"] == "HW002_121_pp_finish"
    assert asked.rig.post(f"{API}/tool", {**body, "tool": "mix.set"})[0] == 404
    assert asked.rig.post(f"{API}/tool", {**body, "token": "x"})[0] == 403
    code, tools = asked.rig.get(f"{API}/tools")
    assert [t["name"] for t in tools["tools"]] == [
        "make_page",
        "read_state",
        "read_measurement",
        "bounce_audio",
        "measure_audio",
        "change_live",
        "propose_live",
    ]
    schema = json.loads((CONTRACTS / "ask-tool.schema.json").read_text())
    jsonschema.validate(body, {"$ref": "#/$defs/request", **schema})


def test_a_scripted_agent_makes_a_page_through_the_bus_and_the_set_is_unmoved(asked):
    page = {"title": "Kick: level", "groups": [{"name": "Level", "controls": [{"target": "Kick bus/volume"}]}]}
    p = script(asked, "claude", Call("make_page", {"page": page}), Call("read_state"), text("made it"))
    before = asked.rig.desk.history.entries[:]
    s = start(asked, "make me a page")
    asked.ask.wait_idle()
    assert [code for code, _ in p.replies] == [200, 200]
    assert asked.rig.desk.history.entries == before
    log = [row for row in asked.rig.desk.bus.log if row["who"] == "agent"]
    assert [row["kind"] for row in log] == ["page.draft", "desk.state"] and {row["group"] for row in log} == {
        f"ask-{s['id']}"
    }


def test_the_old_desk_still_answers_beside_ask(asked):
    assert asked.rig.get("/api/state")[0] == 200
    assert raw(asked, "GET", "/desk/")[0] == 200 and raw(asked, "GET", "/app/")[0] == 200
    assert "page.draft" in asked.rig.get("/api/commands")[1]["commands"]
    code, _ = asked.rig.command("page.draft", {"spec": {}})  # the web is "you": the same command works for it too
    assert code == 400


def test_a_real_claude_process_reaches_the_tools_through_the_mcp_server_and_the_app(asked, tmp_path):
    """The whole path with only the model faked: process, MCP server, HTTP, gate, bus, the desk's state."""
    script_file = tmp_path / "claude"
    script_file.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_CLAUDE}" "$@"\n')
    script_file.chmod(script_file.stat().st_mode | stat.S_IEXEC)
    asked.ask.providers["claude"] = ClaudeProvider(
        lambda name: None, claude_bin=str(script_file), environ={"PATH": os.environ["PATH"]}, home=tmp_path
    )
    s = start(asked, "mcp please")
    asked.ask.wait_idle()
    events = asked.ask.store.replay(s["id"])
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["status"] == "success"
    inner = json.loads(json.loads(result["output"])["content"][0]["text"])
    assert inner["set"] == "HW002_121_pp_finish"
    assert "tools: make_page,read_state,read_measurement,bounce_audio,measure_audio,change_live" in "".join(
        e.get("content", "") for e in events if e["type"] == "message"
    )
    assert [r["who"] for r in asked.rig.desk.bus.log if r["kind"] == "desk.state"] == ["agent"]
