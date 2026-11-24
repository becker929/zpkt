"""Every answer of the booth's HTTP API, through a real request to the server in-process, against the schemas in
lib/contracts/booth-*.schema.json: what the bot's fake booth is tested against too."""

import json
from pathlib import Path

import jsonschema
import pytest
from aiohttp.test_utils import TestClient, TestServer

from booth.contract import BadRequest, parse_job_request
from booth.server import app
from conftest import example
from test_runner import Rig

CONTRACTS = Path(__file__).resolve().parents[3] / "lib" / "contracts"
TOKEN = "zb1_test"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def valid(name: str, data) -> None:
    jsonschema.validate(data, json.loads((CONTRACTS / f"booth-{name}.schema.json").read_text()))


def invalid(name: str, data) -> bool:
    try:
        valid(name, data)
    except jsonschema.ValidationError:
        return True
    return False


@pytest.fixture
async def client(tmp_path, fake):
    rig = Rig(tmp_path, fake)
    a = app(rig.jobs, rig.runner, rig.settings, TOKEN)
    a.cleanup_ctx.clear()
    async with TestClient(TestServer(a)) as c:
        c.rig = rig
        yield c


# what the bot sends (contrib/bot/booth.mjs submit)
BOT_SUBMIT = {"key": "at://did:plc:x/app.bsky.feed.post/3k#v1", "want": {"video": {"size": [1080, 1920]}, "stems": False}}


async def test_a_job_from_submit_to_done_matches_the_schemas(client):
    body = {**BOT_SUBMIT, "score": example(), "parent": "abcdefghijkl"}
    valid("job-request", body)
    r = await client.post("/v1/jobs", json=body, headers=AUTH)
    queued = await r.json()
    assert r.status == 202 and queued["eta_s"] > 0
    valid("job", queued)
    again = await client.post("/v1/jobs", json=body, headers=AUTH)
    assert again.status == 200 and "eta_s" not in (await again.json())
    valid("job", await again.json())
    client.rig.runner.tick()
    done = await (await client.get(f"/v1/jobs/{queued['job']}", headers=AUTH)).json()
    assert done["state"] == "done" and done["position"] is None
    valid("job", done)
    valid("measure", done["measure"])
    on_disk = client.rig.jobs.dir / queued["job"] / "measure.json"
    valid("measure", json.loads(on_disk.read_text()))


async def test_held_and_cancelled_jobs_match_the_schema(client):
    rig = client.rig
    rig.ops.export_silent = True                         # a silent render holds the job
    held = await (await client.post("/v1/jobs", json={"key": "h", "score": example()}, headers=AUTH)).json()
    rig.runner.tick()
    view = await (await client.get(f"/v1/jobs/{held['job']}", headers=AUTH)).json()
    assert view["state"] == "held" and view["error"]["code"] == "held" and view["error"]["retryable"]
    valid("job", view)
    rig.runner.open()
    queued = await (await client.post("/v1/jobs", json={"key": "c", "score": example()}, headers=AUTH)).json()
    assert (await (await client.delete(f"/v1/jobs/{queued['job']}", headers=AUTH)).json()) == {"cancelled": True}
    view = await (await client.get(f"/v1/jobs/{queued['job']}", headers=AUTH)).json()
    assert view["state"] == "failed" and view["error"]["code"] == "cancelled"
    valid("job", view)


async def test_status_check_and_errors_match_the_schemas(client):
    valid("status", await (await client.get("/v1/status", headers=AUTH)).json())
    valid("check", await (await client.post("/v1/check", json={"score": example()}, headers=AUTH)).json())
    bad = example()
    bad["bpm"] = 400
    valid("check", await (await client.post("/v1/check", json={"score": bad}, headers=AUTH)).json())
    answers = [
        await client.get("/v1/status"),
        await client.post("/v1/check", data="nope", headers=AUTH),
        await client.post("/v1/jobs", json={"key": "", "score": example()}, headers=AUTH),
        await client.post("/v1/jobs", json={"key": "k", "score": bad}, headers=AUTH),
        await client.get("/v1/jobs/aaaaaaaaaaaa", headers=AUTH),
        await client.get("/v1/jobs/aaaaaaaaaaaa/files/video.mp4", headers=AUTH),
        await client.delete("/v1/jobs/aaaaaaaaaaaa", headers=AUTH),
    ]
    assert [a.status for a in answers] == [401, 400, 400, 400, 404, 404, 404]
    for a in answers:
        valid("error", await a.json())
    client.rig.runner.close("tests")
    closed = await client.post("/v1/jobs", json={"key": "k2", "score": example()}, headers=AUTH)
    body = await closed.json()
    assert closed.status == 503 and body["retry_in_s"] == 600 and body["reason"] == "tests"
    valid("error", body)


def test_the_schemas_refuse_what_the_bot_must_not_rely_on():
    assert invalid("job-request", {"score": {}})                                   # no key
    assert invalid("job", {"job": "x", "state": "building"})                       # fields missing
    assert invalid("measure", {"seconds": 1, "sample_rate": 44100, "lufs": -14, "true_peak_db": -1, "phone_db": -3,
                               "sections": [], "flags": ["bass_inaudible_on_phone"], "notes": []})   # not a flag
    assert invalid("status", {"open": True, "reason": None, "running": None, "queue": 0, "live": {"front": None},
                              "today": {"jobs": 0, "live_s": 0}})                  # reason is "" when open


def test_parse_job_request_is_as_lenient_as_the_booth_was():
    key, score, parent, want = parse_job_request({"key": "k", "score": {"a": 1}, "parent": 7, "want": "loop"})
    assert (key, score, parent, want) == ("k", {"a": 1}, None, {})
    assert parse_job_request({"key": "k", "parent": "p" * 400, "want": {"loop": True}})[2:] == ("p" * 300, {"loop": True})
    for bad in ({}, {"key": ""}, {"key": 3}, {"key": "k" * 301}):
        with pytest.raises(BadRequest) as exc:
            parse_job_request(bad)
        assert exc.value.code == "bad_key"
