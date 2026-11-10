import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

from harness.config import Config
from harness.web import App

PW = "correct horse battery"


class FakeMethods:
    async def call(self, method, params):
        if method == "ping":
            return {"ok": True}
        raise ValueError(f"unknown method {method!r}")


@pytest.fixture
async def client(tmp_path):
    cfg = Config(jobs_dir=tmp_path / "jobs", workdir=tmp_path, skrng_dir=tmp_path / "skrng")
    app = App(cfg, FakeMethods(), cfg.skrng_dir, secure_cookie=False)   # the test server is plain http
    c = TestClient(TestServer(app.build()))
    await c.start_server()
    c.app_state = app
    yield c
    await c.close()


async def sign_in(client, pw=PW, confirm=PW):
    return await client.post("/login", data={"password": pw, "confirm": confirm, "next": "/skrng/talk/"},
                             allow_redirects=False)


async def test_everything_needs_a_session(client):
    r = await client.get("/skrng/talk/", allow_redirects=False)
    assert r.status == 302 and r.headers["Location"].startswith("/login?next=/skrng/talk/")
    assert (await client.post("/api/rpc", json={"method": "ping"})).status == 401
    assert (await client.get("/api/skrng/feedback")).status == 401


async def test_first_visit_sets_the_password_and_only_a_hash_is_kept(client, tmp_path):
    assert "Choose a password" in await (await client.get("/login")).text()
    assert (await sign_in(client, PW, "different")).status == 401
    r = await sign_in(client)
    assert r.status == 302 and r.headers["Location"] == "/skrng/talk/"
    stored = (tmp_path / "skrng" / "auth.json").read_text()
    assert PW not in stored and r.cookies["skrng_session"].value not in stored
    assert (await client.post("/api/rpc", json={"method": "ping"})).status == 200


async def test_later_visits_need_the_same_password(client):
    await sign_in(client)
    client.session.cookie_jar.clear()
    assert "Sign in." in await (await client.get("/login")).text()
    assert (await sign_in(client, "wrong password!", "")).status == 401
    assert (await client.post("/api/rpc", json={"method": "ping"})).status == 401
    assert (await sign_in(client, PW, "")).status == 302
    assert (await client.post("/api/rpc", json={"method": "ping"})).status == 200


async def test_feedback_is_kept_on_the_mac_and_rpc_errors_are_reported(client, tmp_path):
    await sign_in(client)
    assert (await client.post("/api/skrng/feedback", json={"batch": 0, "transcript": "darker"})).status == 200
    await client.post("/api/skrng/feedback", json={"batch": 8.7, "transcript": "brighter"})
    rows = await (await client.get("/api/skrng/feedback?batch=0")).json()
    assert [r["transcript"] for r in rows] == ["darker"]
    assert len((tmp_path / "skrng" / "feedback.jsonl").read_text().splitlines()) == 2
    r = await client.post("/api/rpc", json={"method": "rm_rf"})
    assert r.status == 400 and "unknown method" in (await r.json())["error"]


async def test_only_skrng_pages_are_proxied_and_audio_redirects(client):
    await sign_in(client)
    assert (await client.get("/private/x", allow_redirects=False)).status == 404
    r = await client.get("/audio/skrng/a.mp3", allow_redirects=False)
    assert r.status == 302 and r.headers["Location"] == "https://anthonybecker.me/audio/skrng/a.mp3"
    assert (await client.get("/login?next=//evil.example", allow_redirects=False)).status == 200
