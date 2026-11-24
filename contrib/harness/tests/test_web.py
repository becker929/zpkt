import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

from harness.config import Config
from harness.web import App

PW = "correct horse battery"


@pytest.fixture
async def client(tmp_path):
    cfg = Config(skrng_dir=tmp_path / "skrng")
    app = App(cfg, cfg.skrng_dir, secure_cookie=False)   # the test server is plain http
    c = TestClient(TestServer(app.build()))
    await c.start_server()
    c.app_state = app
    yield c
    await c.close()


async def signed_in(client) -> bool:
    """Whether the browser's cookie opens the pages: / goes to /skrng/ (no studio here), not to the sign-in."""
    r = await client.get("/", allow_redirects=False)
    return r.headers["Location"] == "/skrng/"


async def sign_in(client, pw=PW, confirm=PW):
    return await client.post("/login", data={"password": pw, "confirm": confirm, "next": "/skrng/talk/"},
                             allow_redirects=False)


async def test_everything_needs_a_session(client):
    r = await client.get("/skrng/talk/", allow_redirects=False)
    assert r.status == 302 and r.headers["Location"].startswith("/login?next=/skrng/talk/")
    assert (await client.post("/api/anything", json={})).status == 401
    assert not await signed_in(client)


async def test_first_visit_sets_the_password_and_only_a_hash_is_kept(client, tmp_path):
    assert "Choose a password" in await (await client.get("/login")).text()
    assert (await sign_in(client, PW, "different")).status == 401
    r = await sign_in(client)
    assert r.status == 302 and r.headers["Location"] == "/skrng/talk/"
    stored = (tmp_path / "skrng" / "auth.json").read_text()
    assert PW not in stored and r.cookies["skrng_session"].value not in stored
    assert await signed_in(client)


async def test_later_visits_need_the_same_password(client):
    await sign_in(client)
    client.session.cookie_jar.clear()
    assert "Sign in." in await (await client.get("/login")).text()
    assert (await sign_in(client, "wrong password!", "")).status == 401
    assert not await signed_in(client)
    assert (await sign_in(client, PW, "")).status == 302
    assert await signed_in(client)


async def test_only_skrng_pages_are_proxied_and_audio_redirects(client):
    await sign_in(client)
    assert (await client.get("/private/x", allow_redirects=False)).status == 404
    r = await client.get("/audio/skrng/a.mp3", allow_redirects=False)
    assert r.status == 302 and r.headers["Location"] == "https://anthonybecker.me/audio/skrng/a.mp3"
    assert (await client.get("/login?next=//evil.example", allow_redirects=False)).status == 200
