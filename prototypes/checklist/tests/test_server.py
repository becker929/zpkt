"""server.py through a real HTTP server on a free port, with the public site replaced by a local fake: the pages and
their redirect, the map's check sounds (copied from the site once, by name only), the harness routes the pages call,
and the artist's seed, which the harness keeps a copy of."""

from __future__ import annotations

import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from harness.config import Config
from harness.studio.artist import SEED

import server

SOUND = "anvil-hit-c242b349.m4a"


@pytest.fixture
async def site():
    hits: list[str] = []

    async def serve(request: web.Request) -> web.Response:
        hits.append(request.path)
        if request.path == f"/audio/zpkt/check-sounds/{SOUND}":
            return web.Response(body=b"\x00\x00\x00 ftypM4A", content_type="audio/mp4")
        return web.Response(status=404)

    app = web.Application()
    app.router.add_get("/{tail:.*}", serve)
    s = TestServer(app)
    await s.start_server()
    yield str(s.make_url("")).rstrip("/"), hits
    await s.close()


@pytest.fixture
async def client(tmp_path, site, monkeypatch):
    url, _ = site
    monkeypatch.setattr(
        server,
        "config",
        lambda data: (
            Config(site=url, studio_dir=data, site_audio=data / "site-audio", regions_audio=data / "regions"),
            data / "check-sounds",
        ),
    )
    c = TestClient(TestServer(server.app(tmp_path)))
    await c.start_server()
    yield c
    await c.close()


async def test_the_pages_are_served_where_they_were(client):
    r = await client.get("/studio/checklist", allow_redirects=False)
    assert r.status == 302 and r.headers["Location"] == "/studio/checklist/"
    r = await client.get("/studio/checklist/map", allow_redirects=False)
    assert r.status == 302 and r.headers["Location"] == "/studio/checklist/map/"
    assert (await client.get("/studio/checklist/")).status == 200
    assert (await client.get("/studio/checklist/map/")).status == 200
    for bad in ("/studio/checklist/..%2F..%2Fserver.py", "/studio/checklist/nope.js"):
        assert (await client.get(bad)).status == 404, bad


async def test_a_check_sound_is_copied_from_the_site_once(client, site, tmp_path):
    _, hits = site
    r = await client.get(f"/studio/checklist/map/sounds/{SOUND}")
    assert r.status == 200 and r.headers["Content-Type"] == "audio/mp4" and "immutable" in r.headers["Cache-Control"]
    await client.get(f"/studio/checklist/map/sounds/{SOUND}")
    assert hits == [f"/audio/zpkt/check-sounds/{SOUND}"]
    assert (tmp_path / "check-sounds" / SOUND).is_file()
    for name in ("anvil-hit.m4a", "anvil-hit-c242b349.mp3", "..%2Fsecret-hit-c242b349.m4a"):
        assert (await client.get(f"/studio/checklist/map/sounds/{name}")).status == 404, name
    assert len(hits) == 1


async def test_the_harness_routes_the_pages_call_are_there(client):
    assert (await (await client.get("/studio/api/artist/repertoire")).json())["works"]
    assert (await (await client.get("/studio/api/regions/rummage/state")).json())["region"] == "rummage"
    assert (await client.get("/studio/site-audio/elsewhere/x.mp3")).status == 404


def test_the_maps_works_are_the_artists_seed():
    page = json.loads((server.STATIC / "map" / "works.json").read_text())
    assert page == json.loads(SEED.read_text())
