import pytest
from aiohttp.test_utils import TestClient, TestServer

from booth.server import app
from conftest import example
from test_runner import Rig

TOKEN = "zb1_test"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
async def client(tmp_path, fake):
    rig = Rig(tmp_path, fake)
    rig.runner.close("tests drive the worker themselves")
    a = app(rig.jobs, rig.runner, rig.settings, TOKEN)
    a.cleanup_ctx.clear()                       # no background worker: tests call tick()
    async with TestClient(TestServer(a)) as c:
        c.rig = rig
        yield c


async def test_token_is_required(client):
    assert (await client.get("/v1/guide")).status == 401
    assert (await client.get("/v1/guide", headers={"Authorization": "Bearer zb1_wrong"})).status == 401


async def test_guide(client):
    g = await (await client.get("/v1/guide", headers=AUTH)).json()
    assert g["palette"] == "2026-11" and g["schema"]["title"] == "Score" and len(g["examples"]) == 2
    assert all("load" not in i for i in g["instruments"])       # the booth's load paths never leave it
    assert {"room", "echo"} == set(g["returns"])


async def test_guide_for_another_palette(client):
    g = await (await client.get("/v1/guide?palette=2026-12", headers=AUTH)).json()
    assert g["palette"] == "2026-12" and len(g["instruments"]) > 40
    assert all(e["palette"] == "2026-12" for e in g["examples"]) and len(g["examples"]) == 2   # old examples, new version
    kit = [i for i in g["instruments"] if i["id"] == "drums.909"][0]
    assert kit["pads"][0] == {"note": 36, "name": "Bass Drum"} and len(kit["pads"]) == 16
    res = await client.get("/v1/guide?palette=2027-01", headers=AUTH)
    assert res.status == 404 and (await res.json())["error"] == "unknown_palette"


async def test_config_pins_the_served_palette(tmp_path, fake):
    rig = Rig(tmp_path, fake)
    rig.settings.palette = "2026-12"
    a = app(rig.jobs, rig.runner, rig.settings, TOKEN)
    a.cleanup_ctx.clear()
    async with TestClient(TestServer(a)) as c:
        assert (await (await c.get("/v1/guide", headers=AUTH)).json())["palette"] == "2026-12"


async def test_check(client):
    ok = await (await client.post("/v1/check", json={"score": example()}, headers=AUTH)).json()
    assert ok["ok"] and ok["estimate"]["notes"] > 0
    bad = example()
    bad["bpm"] = 400
    res = await (await client.post("/v1/check", json={"score": bad}, headers=AUTH)).json()
    assert not res["ok"] and res["errors"][0]["path"] == "bpm"
    assert (await client.post("/v1/check", data="nope", headers=AUTH)).status == 400


async def test_jobs_flow(client):
    rig = client.rig
    r = await client.post("/v1/jobs", json={"key": "at://x#v1", "score": example()}, headers=AUTH)
    assert r.status == 503 and (await r.json())["error"] == "closed"
    rig.runner.open()
    r = await client.post("/v1/jobs", json={"key": "at://x#v1", "score": example(), "parent": "at://p"}, headers=AUTH)
    assert r.status == 202
    job = await r.json()
    assert job["state"] == "queued" and job["position"] == 1 and job["eta_s"] > 0
    again = await client.post("/v1/jobs", json={"key": "at://x#v1", "score": example("lullaby")}, headers=AUTH)
    assert again.status == 200 and (await again.json())["job"] == job["job"]
    assert (await client.get(f"/v1/jobs/{job['job']}/files/video.mp4", headers=AUTH)).status == 404
    rig.runner.tick()
    done = await (await client.get(f"/v1/jobs/{job['job']}", headers=AUTH)).json()
    assert done["state"] == "done" and "video.mp4" in done["files"] and done["parent"] == "at://p"
    f = await client.get(f"/v1/jobs/{job['job']}/files/video.mp4", headers=AUTH)
    assert f.status == 200 and await f.read() == b"x"
    assert (await client.get(f"/v1/jobs/{job['job']}/files/..%2Fbooth.db", headers=AUTH)).status == 404


async def test_invalid_scores_and_queue_full(client):
    rig = client.rig
    rig.runner.open()
    bad = example()
    bad["parts"][0]["instrument"] = "nope.nope"
    r = await client.post("/v1/jobs", json={"key": "k0", "score": bad}, headers=AUTH)
    assert r.status == 400 and (await r.json())["errors"][0]["code"] == "unknown_instrument"
    rig.settings.queue_max = 2
    for k in range(2):
        assert (await client.post("/v1/jobs", json={"key": f"k{k + 1}", "score": example()}, headers=AUTH)).status == 202
    r = await client.post("/v1/jobs", json={"key": "k9", "score": example()}, headers=AUTH)
    assert r.status == 429 and (await r.json())["error"] == "queue_full"


async def test_cancel_and_status(client):
    rig = client.rig
    rig.runner.open()
    job = await (await client.post("/v1/jobs", json={"key": "k", "score": example()}, headers=AUTH)).json()
    st = await (await client.get("/v1/status", headers=AUTH)).json()
    assert st["open"] and st["queue"] == 1 and st["live"]["front"] == "booth_template"
    assert (await (await client.delete(f"/v1/jobs/{job['job']}", headers=AUTH)).json())["cancelled"]
    assert (await (await client.get(f"/v1/jobs/{job['job']}", headers=AUTH)).json())["state"] == "failed"
