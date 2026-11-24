"""The harness's own routes through the real server, signed in, with the public site replaced by a local fake: the
redirects, the /skrng proxy and its cache, the site-audio copy, and the pages under /studio/ that stay."""

from __future__ import annotations

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from harness.config import Config
from harness.studio import routes
from harness.studio.artist import SEED, Artist
from harness.studio.regions import RegionStore
from harness.web import App

PW = "correct horse battery"


class Site:
    """The public site: a page, the stylesheet, a missing page, and published audio, counting what is asked for."""

    def __init__(self):
        self.hits: list[str] = []
        self.app = web.Application()
        self.app.router.add_get("/{tail:.*}", self.serve)

    async def serve(self, request: web.Request) -> web.Response:
        self.hits.append(request.path_qs)
        if request.path == "/skrng/talk/":
            return web.Response(text="<h1>talk</h1>", content_type="text/html")
        if request.path == "/style.css":
            return web.Response(text="body{}", content_type="text/css")
        if request.path == "/audio/skrng/b9.mp3":
            return web.Response(body=b"ID3site", content_type="audio/mpeg")
        return web.Response(status=404, text="gone")


class StandIn:
    """What the routes under /studio/ need of the harness: its config, the artist's store, the regions."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.artist = Artist(cfg.studio_dir / "artist", SEED)
        self.artist_model = None
        self.regions = RegionStore(cfg.studio_dir / "regions")

    def app(self) -> web.Application:
        return routes.app(self)


@pytest.fixture
async def site():
    s = Site()
    server = TestServer(s.app)
    await server.start_server()
    s.url = str(server.make_url("")).rstrip("/")
    yield s
    await server.close()


@pytest.fixture
async def client(tmp_path, site):
    cfg = Config(
        site=site.url,
        skrng_dir=tmp_path / "skrng",
        studio_dir=tmp_path / "studio",
        lab_audio=tmp_path / "lab",
        site_audio=tmp_path / "site-audio",
        regions_audio=tmp_path / "regions",
        images_dir=tmp_path / "images",
    )
    app = App(cfg, cfg.skrng_dir, secure_cookie=False, studio=StandIn(cfg))
    c = TestClient(TestServer(app.build()))
    await c.start_server()
    yield c
    await c.close()


async def sign_in(client):
    r = await client.post("/login", data={"password": PW, "confirm": PW, "next": "/"}, allow_redirects=False)
    assert r.status == 302


async def test_pages_redirect_to_the_sign_in_and_apis_answer_401(client):
    for path in ("/studio/lab/", "/studio/gemini/", "/skrng/talk/"):
        r = await client.get(path, allow_redirects=False)
        assert r.status == 302 and r.headers["Location"] == f"/login?next={path}", path
    r = await client.get("/studio/api/regions/rummage/state")
    assert r.status == 401 and await r.json() == {"error": "Sign in first."}


async def test_the_root_redirects_to_studio(client):
    await sign_in(client)
    r = await client.get("/", allow_redirects=False)
    assert r.status == 302 and r.headers["Location"] == "/studio/"


async def test_the_site_pages_are_proxied_and_cached(client, site):
    await sign_in(client)
    r = await client.get("/skrng/talk/")
    assert r.status == 200 and await r.text() == "<h1>talk</h1>" and r.content_type == "text/html"
    await client.get("/skrng/talk/")
    assert site.hits.count("/skrng/talk/") == 1  # the second came from the 30 s cache
    r = await client.get("/style.css")
    assert r.status == 200 and r.content_type == "text/css"
    r = await client.get("/skrng/missing/")
    assert r.status == 404 and await r.text() == "gone"
    assert (await client.get("/elsewhere/")).status == 404 and "/elsewhere/" not in site.hits


async def test_site_audio_is_copied_from_the_site_once(client, site, tmp_path):
    await sign_in(client)
    r = await client.get("/studio/site-audio/skrng/b9.mp3")
    assert r.status == 200 and await r.read() == b"ID3site" and r.headers["Content-Type"] == "audio/mpeg"
    assert (tmp_path / "site-audio" / "skrng" / "b9.mp3").read_bytes() == b"ID3site"
    await client.get("/studio/site-audio/skrng/b9.mp3")
    assert site.hits.count("/audio/skrng/b9.mp3") == 1
    assert (await client.get("/studio/site-audio/skrng/b10.mp3")).status == 404


async def test_the_pages_that_stay_are_served(client):
    await sign_in(client)
    r = await client.get("/studio/lab", allow_redirects=False)
    assert r.status == 302 and r.headers["Location"] == "/studio/lab/"
    assert "HW002 lab" in await (await client.get("/studio/lab/")).text()
    r = await client.get("/studio/gemini", allow_redirects=False)
    assert r.status == 302 and r.headers["Location"] == "/studio/gemini/"
    r = await client.get("/studio/gemini/")
    assert r.status == 200 and r.content_type == "text/html"
    assert (await client.get("/studio/gemini/..%2F..%2Fgemini.py")).status == 404
    r = await client.get("/studio/api/artist/repertoire")
    assert r.status == 200 and (await r.json())["works"]
    r = await client.get("/studio/api/regions/rummage/state")
    assert r.status == 200 and (await r.json())["region"] == "rummage"


async def test_studio_opens_the_home_page_that_links_what_is_here(client):
    await sign_in(client)
    r = await client.get("/studio", allow_redirects=False)
    assert r.status == 302 and r.headers["Location"] == "/studio/"
    page = await (await client.get("/studio/")).text()
    for link in ("/studio/gemini/", "/studio/lab/", "/skrng/"):
        assert f'href="{link}"' in page, link


async def test_gemini_counts_the_image_walls_images_in_the_months_spend(client, tmp_path):
    from datetime import UTC, datetime

    await sign_in(client)
    (tmp_path / "images").mkdir()
    now = datetime.now(UTC).isoformat()
    (tmp_path / "images" / "images.jsonl").write_text(
        f'{{"created": "{now}", "model": "gemini-3-pro-image", "tokens": {{}}}}\n'
    )
    usage = (await (await client.get("/studio/gemini/api/state")).json())["usage"]
    assert usage["image_count"] == 1 and usage["images"] == 0.134
