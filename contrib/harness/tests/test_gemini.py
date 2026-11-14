"""Gemini CLI in zpkt (harness/gemini.py, studio/gemini_routes.py, contrib/docs/gemini.md), against a stand-in for
`gemini --acp` (fake_gemini_acp.py): a turn streams to the page and goes on without it, a question waits for the
phone's answer, a session survives a harness restart (session/load, its replay not shown twice), the mode reaches
Gemini CLI, a turn can be stopped, images past the harness's 64 KB body cap arrive, and each turn's cost is kept."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from harness import gemini as G
from harness.studio.gemini_routes import add_gemini_routes

FAKE = [sys.executable, str(Path(__file__).parent / "fake_gemini_acp.py")]


@pytest.fixture
def acp_log(tmp_path, monkeypatch):
    path = tmp_path / "acp.jsonl"
    monkeypatch.setenv("FAKE_ACP_LOG", str(path))
    return path


def sent(path: Path, method: str) -> list[dict]:
    if not path.is_file():
        return []
    return [m for m in map(json.loads, path.read_text().splitlines()) if m.get("method") == method]


def make(tmp_path, notes=None) -> G.Gemini:
    notify = (lambda title, body, sid: notes.append((title, body, sid))) if notes is not None else None
    return G.Gemini(tmp_path / "gemini", tmp_path, lambda: "k", cmd=FAKE, notify=notify)


async def client(g: G.Gemini) -> TestClient:
    sub = web.Application()
    add_gemini_routes(sub, gemini=g)
    app = web.Application(client_max_size=64 * 1024)          # the harness's own cap, which /prompt reads past
    app.add_subapp("/studio", sub)
    c = TestClient(TestServer(app))
    await c.start_server()
    return c


async def follow(c: TestClient, sid: str, after: int = -1, on=None) -> list[dict]:
    """Reads the events stream to its end (the session idle), calling on(ev) for each."""
    r = await c.get(f"/studio/gemini/api/sessions/{sid}/events?after={after}")
    out = []
    async for line in r.content:
        if line.strip():
            ev = json.loads(line)
            out.append(ev)
            if on:
                await on(ev)
    return out


async def test_a_turn_streams_and_is_kept(tmp_path, acp_log):
    g = make(tmp_path)
    c = await client(g)
    try:
        s = await (await c.post("/studio/gemini/api/sessions", json={})).json()
        assert s["model"] == "gemini-flash-latest" and s["mode"] == "default" and s["cwd"] == str(tmp_path)
        r = await c.post(f"/studio/gemini/api/sessions/{s['id']}/prompt", json={"text": "hello zpkt"})
        assert (await r.json())["after"] == -1
        evs = await follow(c, s["id"])
        types = [e["type"] for e in evs]
        assert types[0] == "user" and types[-2:] == ["done", "idle"] and "thought" in types
        assert "".join(e["text"] for e in evs if e["type"] == "text") == "echo: hello zpkt (0 images)"
        assert [e["n"] for e in evs] == list(range(len(evs)))

        init = sent(acp_log, "initialize")[0]["params"]
        assert init["clientCapabilities"]["fs"] == {"readTextFile": False, "writeTextFile": False}
        assert sent(acp_log, "session/new")[0]["params"]["cwd"] == str(tmp_path)

        state = await (await c.get("/studio/gemini/api/state")).json()
        row = state["sessions"][0]
        assert row["title"] == "hello zpkt" and row["dollars"] > 0 and not row["running"]
        assert state["offers"]["models"] == ["gemini-flash-latest", "gemini-3.1-pro-preview"]
        done = next(e for e in evs if e["type"] == "done")
        # 600 fresh + 400 cached at a tenth, at flash input; 150 out at flash output
        assert done["dollars"] == pytest.approx((600 * 0.5 + 40 * 0.5 + 150 * 3.0) / 1e6)
        # the page can come back later and get it all
        again = await (await c.get(f"/studio/gemini/api/sessions/{s['id']}")).json()
        assert again["events"] == evs
    finally:
        await c.close()
        await g.close()


async def test_a_question_waits_for_the_phone(tmp_path, acp_log):
    notes = []
    g = make(tmp_path, notes)
    c = await client(g)
    try:
        s = await (await c.post("/studio/gemini/api/sessions", json={})).json()
        await c.post(f"/studio/gemini/api/sessions/{s['id']}/prompt", json={"text": "edit the readme"})

        async def answer(ev):
            if ev["type"] == "permission" and "answered" not in ev:
                assert [o["kind"] for o in ev["options"]] == ["allow_once", "allow_always", "reject_once"]
                assert ev["tool"]["content"][0]["diff"] == "/repo/README.md"
                listed = await (await c.get("/studio/gemini/api/state")).json()
                assert listed["sessions"][0]["asking"] is True
                bad = await c.post(f"/studio/gemini/api/permissions/{ev['id']}", json={"option": "nope"})
                assert bad.status == 400
                ok = await c.post(f"/studio/gemini/api/permissions/{ev['id']}", json={"option": "proceed_once"})
                assert ok.status == 200
        evs = await follow(c, s["id"], on=answer)
        tools = [e for e in evs if e["type"] == "tool"]
        assert tools[0]["status"] == "pending" and tools[-1]["status"] == "completed" and tools[-1]["of"] == tools[0]["n"]
        assert tools[-1]["content"][0]["diff"] == "/repo/README.md"      # an update keeps what came before
        asked = [e for e in evs if e["type"] == "permission"]
        assert asked[-1]["answered"] == "proceed_once" and asked[-1]["of"] == asked[0]["n"]
        assert "Done." in "".join(e["text"] for e in evs if e["type"] == "text")
        reply = [m for m in map(json.loads, acp_log.read_text().splitlines())
                 if "outcome" in (m.get("result") or {})]
        assert reply[0]["result"]["outcome"] == {"outcome": "selected", "optionId": "proceed_once"}
        await asyncio.sleep(0.2)
        assert notes == [("Gemini asks", "Edit README.md", s["id"])]
    finally:
        await c.close()
        await g.close()


async def test_allow_always_changes_the_mode(tmp_path, acp_log):
    g = make(tmp_path)
    c = await client(g)
    try:
        s = await (await c.post("/studio/gemini/api/sessions", json={})).json()
        await c.post(f"/studio/gemini/api/sessions/{s['id']}/prompt", json={"text": "edit it"})

        async def always(ev):
            if ev["type"] == "permission" and "answered" not in ev:
                await c.post(f"/studio/gemini/api/permissions/{ev['id']}", json={"option": "proceed_always"})
        evs = await follow(c, s["id"], on=always)
        assert "".join(e["text"] for e in evs if e["type"] == "text") == "Done."     # no [MODE_UPDATE] in the answer
        assert [e["mode"] for e in evs if e["type"] == "note"] == ["autoEdit"]
        assert (await (await c.get(f"/studio/gemini/api/sessions/{s['id']}")).json())["mode"] == "autoEdit"
    finally:
        await c.close()
        await g.close()


async def test_yolo_mode_reaches_gemini_cli(tmp_path, acp_log):
    g = make(tmp_path)
    c = await client(g)
    try:
        s = await (await c.post("/studio/gemini/api/sessions", json={"mode": "yolo"})).json()
        assert s["mode"] == "yolo"
        assert sent(acp_log, "session/set_mode")[0]["params"] == {"sessionId": s["id"], "modeId": "yolo"}
        await c.post(f"/studio/gemini/api/sessions/{s['id']}/prompt", json={"text": "edit it"})
        evs = await follow(c, s["id"])
        assert not [e for e in evs if e["type"] == "permission"]
        assert "Done." in "".join(e["text"] for e in evs if e["type"] == "text")
        bad = await c.patch(f"/studio/gemini/api/sessions/{s['id']}", json={"mode": "anything"})
        assert bad.status == 400
    finally:
        await c.close()
        await g.close()


async def test_a_session_survives_a_restart(tmp_path, acp_log):
    g = make(tmp_path)
    c = await client(g)
    s = await (await c.post("/studio/gemini/api/sessions", json={})).json()
    await c.post(f"/studio/gemini/api/sessions/{s['id']}/prompt", json={"text": "one"})
    await follow(c, s["id"])
    await c.close()
    await g.close()

    g2 = make(tmp_path)                                        # the harness restarted: a new process
    c2 = await client(g2)
    try:
        before = len(g2.session(s["id"]).events)
        await c2.post(f"/studio/gemini/api/sessions/{s['id']}/prompt", json={"text": "two"})
        evs = await follow(c2, s["id"], after=before - 1)
        loads = sent(acp_log, "session/load")
        assert loads and loads[0]["params"]["sessionId"] == s["id"]
        said = "".join(e["text"] for e in evs if e["type"] == "text")
        assert said == "echo: two (0 images)"                  # the replayed history is not shown again
        assert sent(acp_log, "session/set_model")[-1]["params"]["modelId"] == "gemini-flash-latest"
    finally:
        await c2.close()
        await g2.close()


async def test_a_turn_can_be_stopped(tmp_path, acp_log):
    g = make(tmp_path)
    c = await client(g)
    try:
        s = await (await c.post("/studio/gemini/api/sessions", json={})).json()
        await c.post(f"/studio/gemini/api/sessions/{s['id']}/prompt", json={"text": "slow please"})
        busy = await c.post(f"/studio/gemini/api/sessions/{s['id']}/prompt", json={"text": "again"})
        assert busy.status == 409

        async def stop(ev):
            if ev["type"] == "text" and ev["text"] == "3 ":
                await c.post(f"/studio/gemini/api/sessions/{s['id']}/cancel")
        evs = await follow(c, s["id"], on=stop)
        assert evs[-2]["type"] == "done" and evs[-2]["stop"] == "cancelled"
        assert len([e for e in evs if e["type"] == "text"]) < 50
    finally:
        await c.close()
        await g.close()


async def test_images_past_64k_reach_gemini_cli(tmp_path, acp_log):
    g = make(tmp_path)
    c = await client(g)
    big = base64.b64encode(b"\x89PNG" + b"\0" * 120_000).decode()
    try:
        s = await (await c.post("/studio/gemini/api/sessions", json={})).json()
        r = await c.post(f"/studio/gemini/api/sessions/{s['id']}/prompt",
                         json={"text": "what is this", "images": [{"mime": "image/png", "data": big}]})
        assert r.status == 200
        evs = await follow(c, s["id"])
        assert "(1 images)" in "".join(e["text"] for e in evs if e["type"] == "text")
        block = sent(acp_log, "session/prompt")[0]["params"]["prompt"][0]
        assert block == {"type": "image", "mimeType": "image/png", "data": big}
        name = evs[0]["files"][0]
        f = await c.get(f"/studio/gemini/files/{s['id']}/{name}")
        assert f.status == 200 and len(await f.read()) == 120_004
        assert (await c.delete(f"/studio/gemini/api/sessions/{s['id']}")).status == 200
        assert (await c.get(f"/studio/gemini/api/sessions/{s['id']}")).status == 404
    finally:
        await c.close()
        await g.close()


def test_the_estimates():
    assert G.turn_cost("gemini-3.1-pro-preview", {"inputTokens": 1_000_000}) == pytest.approx(2.0)
    assert G.turn_cost("gemini-flash-latest", {"outputTokens": 500_000, "thoughtTokens": 500_000}) == pytest.approx(3.0)
    img = {"promptTokenCount": 100, "candidatesTokenCount": 1240, "thoughtsTokenCount": 200,
           "candidatesTokensDetails": [{"modality": "IMAGE", "tokenCount": 1120}]}
    assert G.cost("gemini-3-pro-image", img) == pytest.approx((100 * 2 + 320 * 12 + 1120 * 120) / 1e6)
