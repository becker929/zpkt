"""The Gemini chat (harness/gemini.py, studio/gemini_routes.py, contrib/docs/gemini.md): a turn runs the model and its
tools until it answers, the repo tools see tracked files only, images go through harness.images onto the wall, chats
and usage are kept on the Mac, attachments past the harness's 64 KB body cap arrive, and a retry answers again."""

from __future__ import annotations

import base64
import io
import json
import subprocess

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from harness import gemini as G
from harness import images as I
from harness.studio.gemini_routes import add_gemini_routes
from harness.studio.routes import IMAGES_KEY


def png(w=32, h=32) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "zpkt"
    (r / "docs").mkdir(parents=True)
    (r / "README.md").write_text("# zpkt\nhands drives Live\nears measures renders\n")
    (r / "docs" / "workflow.md").write_text("step one\nthe kick stays out until the drop\n")
    (r / ".env").write_text("SECRET=1\n")
    (r / "notes.txt").write_text("untracked\n")
    git = lambda *a: subprocess.run(["git", "-C", str(r), *a], check=True, capture_output=True)
    git("init", "-q", "-b", "main")
    git("add", "README.md", "docs/workflow.md", ".env")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "first")
    return r


def fake_stream(*rounds):
    """Each round is a list of SSE events; records every request body."""
    sent, it = [], iter(rounds)

    async def stream(url, body, headers):
        sent.append({"url": url, "body": json.loads(json.dumps(body)), "headers": headers})
        for ev in next(it):
            yield ev
    return stream, sent


def text_events(*chunks, usage=None):
    evs = [{"candidates": [{"content": {"role": "model", "parts": [{"text": c}]}}]} for c in chunks]
    evs[-1]["candidates"][0]["finishReason"] = "STOP"
    evs[-1]["usageMetadata"] = usage or {"promptTokenCount": 1000, "candidatesTokenCount": 200, "thoughtsTokenCount": 100}
    return evs


def call_event(name, args, sig="c2lnbmF0dXJl"):
    return [{"candidates": [{"content": {"role": "model", "parts": [
        {"functionCall": {"name": name, "args": args}, "thoughtSignature": sig}]}}],
        "usageMetadata": {"promptTokenCount": 800, "candidatesTokenCount": 20}}]


async def client(tmp_path, repo, stream, image_post=None) -> TestClient:
    sub = web.Application()
    sub[IMAGES_KEY] = I.Store(tmp_path / "images")
    add_gemini_routes(sub, root=tmp_path / "gemini", repo=repo, key="k", stream=stream, image_post=image_post)
    app = web.Application(client_max_size=64 * 1024)          # the harness's own cap, which /send reads past
    app.add_subapp("/studio", sub)
    c = TestClient(TestServer(app))
    await c.start_server()
    return c


async def events(resp) -> list[dict]:
    return [json.loads(line) for line in (await resp.text()).splitlines() if line.strip()]


async def test_a_turn_reads_the_repo_then_answers(tmp_path, repo):
    stream, sent = fake_stream(call_event("zpkt_read", {"path": "docs/workflow.md"}), text_events("The kick ", "waits."))
    c = await client(tmp_path, repo, stream)
    try:
        r = await c.post("/studio/gemini/api/chats/new/send", json={"text": "When does the kick come in?"})
        evs = await events(r)
        types = [e["type"] for e in evs]
        assert types[0] == "chat" and types[-1] == "done" and "tool" in types
        assert "".join(e["text"] for e in evs if e["type"] == "text") == "The kick waits."
        cid = evs[0]["id"]
        assert evs[0]["title"] == "When does the kick come in?"

        first, second = sent
        assert first["headers"]["x-goog-api-key"] == "k" and ":streamGenerateContent?alt=sse" in first["url"]
        assert first["body"]["tools"] == G.TOOLS
        assert "zpkt" in first["body"]["systemInstruction"]["parts"][0]["text"]
        # the call goes back with its signature, then the tool's answer
        call, reply = second["body"]["contents"][1:]
        assert call["parts"][0]["thoughtSignature"] == "c2lnbmF0dXJl"
        got = reply["parts"][0]["functionResponse"]
        assert got["name"] == "zpkt_read" and "the kick stays out until the drop" in got["response"]["text"]
        assert not any(k.startswith("_") for msg in second["body"]["contents"] for k in msg)

        chat = await (await c.get(f"/studio/gemini/api/chats/{cid}")).json()
        assert [x["role"] for x in chat["contents"]] == ["user", "model", "user", "model"]
        assert chat["dollars"] > 0
        state = await (await c.get("/studio/gemini/api/state")).json()
        assert state["chats"][0]["id"] == cid and state["usage"]["chat"] >= 0
        rows = (tmp_path / "gemini" / "usage.jsonl").read_text().splitlines()
        assert len(rows) == 2 and json.loads(rows[0])["chat"] == cid
    finally:
        await c.close()


async def test_images_go_through_harness_images(tmp_path, repo):
    def post(url, body, headers, timeout):
        return {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": base64.b64encode(png()).decode()}}]}}],
                "usageMetadata": {"totalTokenCount": 1300}}
    stream, sent = fake_stream(call_event("make_image", {"prompt": "a gold obelisk", "title": "obelisk", "aspect": "9:16"}),
                               text_events("Here it is."))
    c = await client(tmp_path, repo, stream, image_post=post)
    try:
        evs = await events(await c.post("/studio/gemini/api/chats/new/send", json={"text": "make me an obelisk"}))
        made = next(e for e in evs if e["type"] == "images")["images"]
        cid = evs[0]["id"]
        rec = I.Store(tmp_path / "images").all()[0]
        assert made[0]["id"] == rec.id and rec.batch == f"gemini-{cid}" and rec.prompt == "a gold obelisk"
        assert "make me an obelisk" in rec.context and rec.settings["imageConfig"]["aspectRatio"] == "9:16"
        resp = sent[1]["body"]["contents"][2]["parts"][0]["functionResponse"]["response"]
        assert resp["wall"] == f"/studio/images/?batch=gemini-{cid}"
        chat = await (await c.get(f"/studio/gemini/api/chats/{cid}")).json()
        assert chat["contents"][2]["parts"][0]["_images"][0]["thumb"] == rec.thumb     # the page shows it again later
    finally:
        await c.close()


def test_the_repo_tools_see_tracked_files_only(repo):
    r = G.Repo(repo)
    assert r.list("")["entries"] == ["docs/", "README.md"]                # no .env, no untracked notes
    with pytest.raises(ValueError):
        r.read("notes.txt")
    with pytest.raises(ValueError):
        r.read(".env")
    with pytest.raises(ValueError):
        r.read("../zpkt/README.md")
    assert r.read("README.md", 2, 1)["text"] == "2\thands drives Live"
    hits = r.search("measures|kick")["hits"]
    assert hits == ["README.md:3: ears measures renders", "docs/workflow.md:2: the kick stays out until the drop"]
    assert r.search("kick", glob="*.md", path="docs")["files"] == 1
    assert r.log()["commits"][0].endswith("first")


async def test_attachments_past_64k_are_kept_and_sent_inline(tmp_path, repo):
    stream, sent = fake_stream(text_events("A red square."))
    c = await client(tmp_path, repo, stream)
    big = base64.b64encode(png(700, 700) + b"\0" * 90_000).decode()          # well past 64 KB
    try:
        evs = await events(await c.post("/studio/gemini/api/chats/new/send",
                                        json={"text": "what is this", "images": [{"mime": "image/png", "data": big}],
                                              "settings": {"zpkt": False, "model": "gemini-flash-latest"}}))
        assert evs[-1]["type"] == "done"
        body = sent[0]["body"]
        assert "tools" not in body and "systemInstruction" not in body and "gemini-flash-latest" in sent[0]["url"]
        assert body["contents"][0]["parts"][0]["inlineData"]["data"] == big
        chat = await (await c.get(f"/studio/gemini/api/chats/{evs[0]['id']}")).json()
        name = chat["contents"][0]["parts"][0]["file"]
        f = await c.get(f"/studio/gemini/files/{chat['id']}/{name}")
        assert f.status == 200 and len(await f.read()) == len(base64.b64decode(big))
    finally:
        await c.close()


async def test_retry_answers_the_last_message_again(tmp_path, repo):
    stream, sent = fake_stream(text_events("one"), text_events("two"))
    c = await client(tmp_path, repo, stream)
    try:
        cid = (await events(await c.post("/studio/gemini/api/chats/new/send", json={"text": "count"})))[0]["id"]
        evs = await events(await c.post(f"/studio/gemini/api/chats/{cid}/retry"))
        assert [e["text"] for e in evs if e["type"] == "text"] == ["two"]
        chat = await (await c.get(f"/studio/gemini/api/chats/{cid}")).json()
        assert len(chat["contents"]) == 2 and chat["contents"][1]["parts"][0]["text"] == "two"
        assert len(sent[1]["body"]["contents"]) == 1
        assert (await c.delete(f"/studio/gemini/api/chats/{cid}")).status == 200
        assert (await c.get(f"/studio/gemini/api/chats/{cid}")).status == 404
    finally:
        await c.close()


async def test_an_error_is_shown_in_the_chat(tmp_path, repo):
    async def stream(url, body, headers):
        raise RuntimeError("quota exceeded")
        yield  # never reached: it makes this an async generator
    c = await client(tmp_path, repo, stream)
    try:
        evs = await events(await c.post("/studio/gemini/api/chats/new/send", json={"text": "hi"}))
        assert evs[-1] == {"type": "error", "error": "quota exceeded"}
    finally:
        await c.close()


def test_the_estimate():
    assert G.cost("gemini-flash-latest", {"promptTokenCount": 1_000_000}) == pytest.approx(0.5)
    assert G.cost("gemini-pro-latest", {"candidatesTokenCount": 500_000, "thoughtsTokenCount": 500_000}) == pytest.approx(12)
    img = {"promptTokenCount": 100, "candidatesTokenCount": 1240, "thoughtsTokenCount": 200,
           "candidatesTokensDetails": [{"modality": "IMAGE", "tokenCount": 1120}]}
    assert G.cost("gemini-3-pro-image", img) == pytest.approx((100 * 2 + 320 * 12 + 1120 * 120) / 1e6)
