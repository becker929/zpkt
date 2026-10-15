"""The regions' state and renders (studio/regions.py, docs/rummage.md): an empty state at first, a valid state kept
whole and read back, anything the page could not have made refused, a broken file set aside, and the renders served
from their own folder by name only, cached for good."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from harness.studio import regions as R

sys.path.insert(0, str(Path(__file__).parent / "ui"))
from lab_server import app as lab_app  # noqa: E402

STATE = {
    "committed": {"bed": 2, "drums": None, "bass": 1},
    "carrying": "bass-1",
    "plinths": {"bed": "bed-2", "drums": None, "bass": None},
    "completions": [{"at": 1760400000.5, "combo": "2-3-1", "plate": "pl_abc"}, {"at": 1760400100, "combo": "1-1-1"}],
    "page": {"seen": ["bed", "bass"]},
}


@pytest.fixture
def store(tmp_path):
    return R.RegionStore(tmp_path / "regions")


def test_a_region_starts_empty(store):
    s = store.get("rummage")
    assert s == R.empty("rummage")
    assert s["committed"] == {"bed": None, "drums": None, "bass": None} and s["carrying"] is None
    assert s["plinths"] == {"bed": None, "drums": None, "bass": None} and s["completions"] == []
    with pytest.raises(KeyError):
        store.get("elsewhere")


def test_a_state_is_kept_whole_and_read_back(store, tmp_path):
    kept = store.put("rummage", STATE)
    assert kept["region"] == "rummage" and kept["updated"] > 0
    assert {k: kept[k] for k in STATE} == STATE
    assert store.get("rummage") == kept
    assert json.loads((tmp_path / "regions" / "rummage.json").read_text()) == kept
    again = store.put("rummage", {**kept, "carrying": None})        # what GET gave, changed and sent back
    assert again["carrying"] is None and again["committed"] == STATE["committed"] and again["updated"] >= kept["updated"]


def test_a_partial_state_is_filled_in(store):
    kept = store.put("rummage", {"committed": {"drums": 3}})
    assert kept["committed"] == {"bed": None, "drums": 3, "bass": None}
    assert kept["plinths"] == {"bed": None, "drums": None, "bass": None} and kept["completions"] == [] and kept["page"] == {}


@pytest.mark.parametrize("change, why", [
    (lambda s: s["committed"].update(bed=4), "option id"),
    (lambda s: s["committed"].update(bed="2"), "option id"),
    (lambda s: s["committed"].update(bed=True), "option id"),
    (lambda s: s["committed"].update(lead=1), "unknown"),
    (lambda s: s.update(committed=[1, 2, 3]), "expected an object"),
    (lambda s: s.update(carrying="bed-4"), "artifact id"),
    (lambda s: s.update(carrying="lead-1"), "artifact id"),
    (lambda s: s.update(carrying=3), "artifact id"),
    (lambda s: s["plinths"].update(drums="bed-1"), "not a drums artifact"),
    (lambda s: s["completions"].append({"at": 5, "combo": "1-2"}), "combo"),
    (lambda s: s["completions"].append({"at": -1, "combo": "1-2-3"}), "time"),
    (lambda s: s["completions"].append({"at": "now", "combo": "1-2-3"}), "time"),
    (lambda s: s["completions"].append({"at": 5, "combo": "1-2-3", "mood": "x"}), "unknown"),
    (lambda s: s["completions"].append({"at": 5, "combo": "1-2-3", "plate": ""}), "plate"),
    (lambda s: s.update(completions={"at": 5}), "list"),
    (lambda s: s.update(page={"blob": "x" * 5000}), "bytes"),
    (lambda s: s.update(page="hi"), "object"),
    (lambda s: s.update(hero={"x": 1}), "unknown"),
])
def test_what_the_page_could_not_have_made_is_refused(store, change, why):
    state = json.loads(json.dumps(STATE))
    change(state)
    with pytest.raises(R.Invalid, match=why):
        store.put("rummage", state)
    assert store.get("rummage") == R.empty("rummage")                     # nothing was written


def test_completions_keep_the_newest(store):
    many = [{"at": 1000 + i, "combo": "1-1-1"} for i in range(R.COMPLETIONS_MAX + 5)]
    kept = store.put("rummage", {"completions": many})
    assert len(kept["completions"]) == R.COMPLETIONS_MAX and kept["completions"][0]["at"] == 1005


def test_a_broken_file_is_set_aside_and_the_region_starts_again(store, tmp_path):
    root = tmp_path / "regions"
    root.mkdir()
    (root / "rummage.json").write_text("{not json")
    assert store.get("rummage") == R.empty("rummage")
    assert [p.name for p in root.iterdir() if p.name.startswith("rummage.bad-")]
    (root / "rummage.json").write_text(json.dumps({"committed": {"bed": 9}}))
    assert store.get("rummage") == R.empty("rummage")
    store.put("rummage", STATE)
    assert store.get("rummage")["carrying"] == "bass-1"


@pytest.fixture
async def client(tmp_path):
    c = TestClient(TestServer(lab_app(tmp_path)))
    await c.start_server()
    yield c
    await c.close()


async def test_the_api_starts_empty_keeps_a_state_and_refuses_nonsense(client, tmp_path):
    r = await client.get("/studio/api/regions/rummage/state")
    assert r.status == 200 and r.headers["Cache-Control"] == "no-store"
    assert await r.json() == R.empty("rummage")
    r = await client.post("/studio/api/regions/rummage/state", json=STATE)
    assert r.status == 200
    kept = await r.json()
    assert kept["region"] == "rummage" and {k: kept[k] for k in STATE} == STATE
    assert await (await client.get("/studio/api/regions/rummage/state")).json() == kept
    assert (tmp_path / "regions" / "rummage.json").is_file()
    bad = await client.post("/studio/api/regions/rummage/state", json={**STATE, "carrying": "bed-7"})
    assert bad.status == 400 and "carrying" in await bad.text()
    assert (await client.post("/studio/api/regions/rummage/state", data="not json")).status == 400
    assert (await client.post("/studio/api/regions/rummage/state", json=[1, 2])).status == 400
    assert (await client.get("/studio/api/regions/elsewhere/state")).status == 404
    assert (await client.post("/studio/api/regions/elsewhere/state", json=STATE)).status == 404
    assert await (await client.get("/studio/api/regions/rummage/state")).json() == kept       # the refusals wrote nothing


async def test_the_renders_are_served_by_name_and_cached_for_good(client, tmp_path):
    audio = tmp_path / "regions" / "rummage" / "audio"
    audio.mkdir(parents=True)
    (audio / "sh001-2-3-1-0a1b2c3d.m4a").write_bytes(b"\x00\x00\x00 ftypM4A fake")
    (audio / "sh001-1-1-1-0a1b2c3d.wav").write_bytes(b"RIFFfake")
    r = await client.get("/studio/regions/rummage/audio/sh001-2-3-1-0a1b2c3d.m4a")
    assert r.status == 200 and r.headers["Content-Type"] == "audio/mp4" and "immutable" in r.headers["Cache-Control"]
    assert await r.read() == b"\x00\x00\x00 ftypM4A fake"
    r = await client.get("/studio/regions/rummage/audio/sh001-1-1-1-0a1b2c3d.wav")
    assert r.status == 200 and r.headers["Content-Type"] == "audio/wav"


async def test_the_interface_sounds_are_served_by_name_too(client, tmp_path):
    audio = tmp_path / "regions" / "rummage" / "audio"
    audio.mkdir(parents=True)
    (audio / "ui-step-0a1b2c3d.m4a").write_bytes(b"\x00\x00\x00 ftypM4A step")
    r = await client.get("/studio/regions/rummage/audio/ui-step-0a1b2c3d.m4a")
    assert r.status == 200 and r.headers["Content-Type"] == "audio/mp4" and "immutable" in r.headers["Cache-Control"]
    assert await r.read() == b"\x00\x00\x00 ftypM4A step"
    assert (await client.get("/studio/regions/rummage/audio/ui-step-0a1b2c3e.m4a")).status == 404     # not there
    # there, but not names the route serves: the name is a-z only, the hash 8 lower-case hex, the file .m4a
    for name in ("ui-Step-0a1b2c3d.m4a", "ui-step2-0a1b2c3d.m4a", "ui-step-0a1b2c3.m4a", "ui-step-0A1B2C3D.m4a",
                 "ui-step-0a1b2c3d.wav", "ui--0a1b2c3d.m4a", "ux-step-0a1b2c3d.m4a"):
        (audio / name).write_bytes(b"fake")
        assert (await client.get(f"/studio/regions/rummage/audio/{name}")).status == 404, name


@pytest.mark.parametrize("path", [
    "rummage/audio/sh001-2-3-1-0a1b2c3e.m4a",            # not there
    "rummage/audio/sh001-4-3-1-0a1b2c3d.m4a",            # no option 4
    "rummage/audio/sh001-2-3-1-0A1B2C3D.m4a",            # the hash is lower-case hex
    "rummage/audio/sh001-2-3-1.m4a",
    "rummage/audio/sh001-2-3-1-0a1b2c3d.mp3",
    "rummage/audio/..%2F..%2Frummage.json",
    "rummage/audio/%2E%2E%2Fsecret-1-1-1-0a1b2c3d.m4a",
    "elsewhere/audio/sh001-2-3-1-0a1b2c3d.m4a",
])
async def test_the_renders_route_serves_nothing_else(client, tmp_path, path):
    audio = tmp_path / "regions" / "rummage" / "audio"
    audio.mkdir(parents=True)
    (audio / "sh001-2-3-1-0a1b2c3d.m4a").write_bytes(b"fake")
    (tmp_path / "regions" / "elsewhere" / "audio").mkdir(parents=True)
    (tmp_path / "regions" / "elsewhere" / "audio" / "sh001-2-3-1-0a1b2c3d.m4a").write_bytes(b"fake")
    r = await client.get(f"/studio/regions/{path}")
    assert r.status == 404
