"""The arranger server's routes, through real HTTP requests to the server on a free port, against a temporary data
folder. These pin what the pages and scripts rely on: paths, status codes, content types, cache headers, and what is
written to the arrangement file."""

from __future__ import annotations

import json
import re
import time

import pytest

PAGES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/transitions": "transitions.html",
    "/transitions/": "transitions.html",
    "/mix": "mix.html",
    "/mix/": "mix.html",
    "/mix2": "mix2.html",
    "/mix2/": "mix2.html",
    "/spectral": "spectral.html",
    "/spectral/": "spectral.html",
    "/kick": "kick.html",
    "/kick/": "kick.html",
}


@pytest.mark.parametrize(("path", "page"), sorted(PAGES.items()))
def test_pages(server, path, page):
    r = server.call("GET", path + "?v=1")
    assert r.status == 200
    assert r.headers["Content-Type"] == "text/html; charset=utf-8"
    assert r.headers["Cache-Control"] == "no-store"
    from conftest import HERE

    assert r.body == (HERE / "static" / page).read_bytes()


def test_head_has_headers_and_no_body(server):
    r = server.call("HEAD", "/")
    assert r.status == 200
    assert int(r.headers["Content-Length"]) > 0
    assert r.body == b""


# (url path, file under the data folder, content type, cache header)
DATA_FILES = [
    ("/loops.json", "loops.json", "application/json", "no-store"),
    ("/refs/refs.json", "refs/refs.json", "application/json", "no-store"),
    ("/refs/ksms-roses.flac", "refs/ksms-roses.flac", "audio/flac", "public, max-age=3600"),
    ("/refs/ksms-roses.spec.json", "refs/ksms-roses.spec.json", "application/json", "public, max-age=3600"),
    ("/mix2/catalog.json", "mix2/catalog.json", "application/json", "no-store"),
    ("/mix2/b1114-101010/p00-m.flac", "mix2/b1114-101010/p00-m.flac", "audio/flac", "no-store"),
    ("/spectral/renders.json", "spectral/renders.json", "application/json", "no-store"),
    ("/spectral/fix-a.flac", "spectral/fix-a.flac", "audio/flac", "no-store"),
    ("/kickdesign/kicks.json", "kickdesign/kicks.json", "application/json", "no-store"),
    ("/kickdesign/frames/t-f1.json", "kickdesign/frames/t-f1.json", "application/json", "no-store"),
    ("/kickdesign/ref-ksms.flac", "kickdesign/ref-ksms.flac", "audio/flac", "public, max-age=3600"),
    ("/kickfuzz/renders.json", "kickfuzz/renders.json", "application/json", "no-store"),
    ("/kickfuzz/mix-b6.flac", "kickfuzz/mix-b6.flac", "audio/flac", "no-store"),
    ("/fx.json", "fx/fx.json", "application/json", "no-store"),
    ("/fx/audio/nr-lp-2.flac", "fx/audio/nr-lp-2.flac", "audio/flac", "no-store"),
    (
        "/audio/0123456789abcdef.flac",
        "audio/0123456789abcdef.flac",
        "audio/flac",
        "public, max-age=31536000, immutable",
    ),
]


@pytest.mark.parametrize(("url", "rel", "ctype", "cache"), DATA_FILES)
def test_data_files(server, url, rel, ctype, cache):
    assert server.call("GET", url).status == 404  # not there yet
    f = server.data / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"content of " + rel.encode())
    r = server.call("GET", url)
    assert (r.status, r.headers["Content-Type"], r.headers["Cache-Control"]) == (200, ctype, cache)
    assert r.body == b"content of " + rel.encode()


@pytest.mark.parametrize(
    "url",
    [
        "/audio/0123456789ABCDEF.flac",  # names are lower-case hex
        "/audio/0123.flac",
        "/refs/Upper.flac",
        "/refs/x.wav",
        "/fx/audio/../loops.json",
        "/kickdesign/x.flac",  # only ref- files
        "/mix2/a/b/c.flac",
        "/spectral/x.wav",
        "/nothing",
        "/api/nothing",
    ],
)
def test_unknown_paths_are_404(server, url):
    r = server.call("GET", url)
    assert r.status == 404
    assert r.json() == {"error": "not found"}


def test_missing_file_is_404_json(server):
    r = server.call("GET", "/loops.json")
    assert (r.status, r.headers["Content-Type"], r.json()) == (404, "application/json", {"error": "not found"})


# ---- arrangements ---------------------------------------------------------------------------------------------------


def arrangement(**more):
    return {
        "name": "Try",
        "bars": 40,
        "regions": [{"lane": "kick", "clip": "kick-rumble-a", "start": 16, "len": 24, "off": 0}],
        "mutes": [],
        **more,
    }


def test_save_then_read(server):
    t0 = time.time()
    r = server.call("PUT", "/api/arrangements/short-x", arrangement())
    assert r.status == 200
    body = r.json()
    assert body["ok"] is True and t0 - 1 <= body["saved"] <= time.time() + 1
    stored = json.loads((server.data / "arrangements" / "short-x.json").read_text())
    assert stored == {**arrangement(), "saved": body["saved"]}
    got = server.call("GET", "/api/arrangements/short-x")
    assert got.status == 200 and got.json() == stored


def test_list_newest_first_and_skips_broken_files(server):
    server.call("PUT", "/api/arrangements/a-one", arrangement(name="One"))
    time.sleep(0.01)
    server.call("PUT", "/api/arrangements/b-two", arrangement(name="Two", bars=32))
    (server.data / "arrangements" / "broken.json").write_text("{not json")
    (server.data / "arrangements" / "no-name.json").write_text(json.dumps({"regions": []}))
    rows = server.call("GET", "/api/arrangements").json()
    assert [r["id"] for r in rows[:2]] == ["b-two", "a-one"]
    assert rows[0] == {"id": "b-two", "name": "Two", "bars": 32, "saved": rows[0]["saved"]}
    assert rows[2] == {"id": "no-name", "name": "no-name", "bars": None, "saved": None}
    assert len(rows) == 3


def test_list_when_folder_missing(server):
    assert server.call("GET", "/api/arrangements").json() == []


@pytest.mark.parametrize("bad", ["Upper", "-dash", "a" * 65, "a.b", "a_b"])
def test_bad_ids(server, bad):
    assert server.call("GET", f"/api/arrangements/{bad}").json() == {"error": "bad id"}
    assert server.call("GET", f"/api/arrangements/{bad}").status == 400
    assert server.call("PUT", f"/api/arrangements/{bad}", arrangement()).status == 400
    assert server.call("DELETE", f"/api/arrangements/{bad}").status == 400


def test_read_missing_arrangement(server):
    assert server.call("GET", "/api/arrangements/none-here").status == 404


@pytest.mark.parametrize(
    "body", ["", "not json", json.dumps([1]), json.dumps({"name": "x"}), json.dumps({"regions": {}})]
)
def test_save_rejects_bad_bodies(server, body):
    r = server.call("PUT", "/api/arrangements/short-x", body)
    assert r.status == 400
    assert r.json()["error"] in ("bad size", "bad arrangement")
    assert not (server.data / "arrangements" / "short-x.json").exists()


def test_save_rejects_too_large(server):
    r = server.claim_length("PUT", "/api/arrangements/short-x", 2_000_000)
    assert (r.status, r.json()) == (400, {"error": "bad size"})
    assert server.claim_length("PUT", "/api/transitions", 200_000).json() == {"error": "bad size"}
    assert server.claim_length("POST", "/api/mix2/requests", 100_000).json() == {"error": "bad request"}


LATER_KEYS = {
    "transitions": [{"id": "nr-lp-2", "seam": 17}],
    "mix": {"channels": {"kick": {"gainDb": -1.0}}},
    "mix2": [{"device": "Saturator", "target": "kick", "values": {}}],
    "spectral": [{"id": "a", "parts": []}],
    "kickFuzz": {"loop": "t-f1.flac", "kickTurnedDb": -1.2},
    "desk": {"monitor": ["mon C1"], "values": {"Kick bus/desk EQ/1 Gain A": ["1.0 dB", 0.5]}},
}


def test_page_save_keeps_the_later_steps(server):
    """The arranger page sends only name, bars, regions and mutes; what the later pages and the mix desk wrote
    stays (contrib/mixdesk/recipe.py writes `desk`)."""
    f = server.data / "arrangements" / "short-8d2a2.json"
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps({**arrangement(), "saved": 1.0, **LATER_KEYS}))
    r = server.call("PUT", "/api/arrangements/short-8d2a2", arrangement(name="Renamed"))
    stored = json.loads(f.read_text())
    assert stored == {**arrangement(name="Renamed"), "saved": r.json()["saved"], **LATER_KEYS}


def test_page_save_body_wins_over_old_keys(server):
    f = server.data / "arrangements" / "short-x.json"
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps({**arrangement(), "mix": {"channels": {"old": {}}}}))
    server.call("PUT", "/api/arrangements/short-x", arrangement(mix={"channels": {"new": {}}}))
    assert json.loads(f.read_text())["mix"] == {"channels": {"new": {}}}


def test_page_save_over_broken_file(server):
    f = server.data / "arrangements" / "short-x.json"
    f.parent.mkdir(parents=True)
    f.write_text("{broken")
    assert server.call("PUT", "/api/arrangements/short-x", arrangement()).status == 200
    assert json.loads(f.read_text())["name"] == "Try"


def test_delete_moves_aside(server):
    server.call("PUT", "/api/arrangements/short-x", arrangement())
    r = server.call("DELETE", "/api/arrangements/short-x")
    assert (r.status, r.json()) == (200, {"ok": True})
    assert not (server.data / "arrangements" / "short-x.json").exists()
    kept = list((server.data / "arrangements" / "deleted").glob("short-x-*.json"))
    assert len(kept) == 1 and re.fullmatch(r"short-x-\d+\.json", kept[0].name)
    assert json.loads(kept[0].read_text())["name"] == "Try"
    assert server.call("DELETE", "/api/arrangements/short-x").json() == {"ok": True}  # already gone: still ok


def test_delete_other_paths(server):
    assert server.call("DELETE", "/api/other").status == 400


# ---- a later page's structure ---------------------------------------------------------------------------------------


@pytest.fixture
def saved(server):
    server.call("PUT", "/api/arrangements/short-8d2a2", arrangement())
    return server.data / "arrangements" / "short-8d2a2.json"


@pytest.mark.parametrize("key", sorted(k for k in LATER_KEYS if k != "desk"))
def test_put_later_key(server, saved, key):
    before = json.loads(saved.read_text())
    r = server.call("PUT", f"/api/arrangements/short-8d2a2/{key}", LATER_KEYS[key])
    assert (r.status, r.json()) == (200, {"ok": True})
    after = json.loads(saved.read_text())
    assert after == {**before, key: LATER_KEYS[key]}  # `saved` is not touched


def test_put_kick_fuzz_null(server, saved):
    server.call("PUT", "/api/arrangements/short-8d2a2/kickFuzz", LATER_KEYS["kickFuzz"])
    assert server.call("PUT", "/api/arrangements/short-8d2a2/kickFuzz", "null").status == 200
    assert json.loads(saved.read_text())["kickFuzz"] is None
    assert server.call("PUT", "/api/arrangements/short-8d2a2/kickFuzz", "").status == 200  # an empty body is null too
    assert json.loads(saved.read_text())["kickFuzz"] is None


def test_put_kick_fuzz_with_bells(server, saved):
    body = {"loop": "solo-mf1.flac", "kickTurnedDb": 0.5, "bells": [[40.0, 8.0, 0.7], [2500, 4, 1]], "id": "mf1"}
    assert server.call("PUT", "/api/arrangements/short-8d2a2/kickFuzz", body).status == 200
    assert json.loads(saved.read_text())["kickFuzz"] == body


BAD_LATER = [
    ("transitions", {"id": "x"}),
    ("transitions", [{"id": "x"}]),
    ("transitions", [3]),
    ("mix", []),
    ("mix", {"channels": []}),
    ("mix2", [{"device": "Saturator"}]),
    ("mix2", {}),
    ("spectral", [{"id": "a"}]),
    ("kickFuzz", {"loop": "Bad.flac", "kickTurnedDb": 0}),
    ("kickFuzz", {"loop": "a.flac"}),
    ("kickFuzz", {"loop": "a.flac", "kickTurnedDb": "1"}),
    ("kickFuzz", {"loop": "a.flac", "kickTurnedDb": 1, "bells": [[1, 2]]}),
    ("kickFuzz", {"loop": "a.flac", "kickTurnedDb": 1, "bells": [[1, 2, 3]] * 7}),
    ("kickFuzz", []),
    ("mix", "not json"),
]


@pytest.mark.parametrize(("key", "body"), BAD_LATER)
def test_put_later_key_rejects(server, saved, key, body):
    before = saved.read_text()
    r = server.call("PUT", f"/api/arrangements/short-8d2a2/{key}", body if isinstance(body, str) else json.dumps(body))
    assert (r.status, r.json()) == (400, {"error": f"bad {key}"})
    assert saved.read_text() == before


def test_put_later_key_needs_the_arrangement(server):
    r = server.call("PUT", "/api/arrangements/none-here/mix", {"channels": {}})
    assert (r.status, r.json()) == (404, {"error": "no such arrangement"})
    assert server.call("PUT", "/api/arrangements/Bad/mix", {"channels": {}}).status == 404


def test_put_unknown_later_key_is_a_bad_id(server, saved):
    assert server.call("PUT", "/api/arrangements/short-8d2a2/desk", {"monitor": []}).json() == {"error": "bad id"}


# ---- the transitions page's view ------------------------------------------------------------------------------------


def test_transitions_view(server):
    assert server.call("GET", "/api/transitions").json() == {}
    view = {"seam": 17, "picks": {"17": ["nr-lp-2"]}, "hearts": ["nr-lp-2"]}
    r = server.call("PUT", "/api/transitions", view)
    assert (r.status, r.json()) == (200, {"ok": True})
    got = server.call("GET", "/api/transitions").json()
    assert {k: v for k, v in got.items() if k != "saved"} == view
    assert isinstance(got["saved"], float)


@pytest.mark.parametrize("body", ["", "x", json.dumps({"picks": []}), json.dumps([1])])
def test_transitions_view_rejects(server, body):
    r = server.call("PUT", "/api/transitions", body)
    assert r.status == 400 and r.json()["error"] in ("bad size", "bad picks")
    assert not (server.data / "transitions.json").exists()


# ---- mix 2 batches --------------------------------------------------------------------------------------------------

BATCH = {
    "target": "bus-kick",
    "device": "Saturator",
    "params": [{"name": "Drive", "min": 0, "max": 12, "steps": 3, "unit": "dB"}],
    "bars": [17, 24],
}


def test_queue_a_batch(server):
    r = server.call("POST", "/api/mix2/requests", BATCH)
    assert r.status == 200
    got = r.json()
    assert re.fullmatch(r"b\d{4}-\d{6}", got["id"])
    assert got["status"] == "queued" and isinstance(got["made"], float)
    assert {k: got[k] for k in BATCH} == BATCH
    f = server.data / "mix2" / "requests" / f"{got['id']}.json"
    assert json.loads(f.read_text()) == got
    assert f.read_text() == json.dumps(got, indent=1)
    assert server.worker_starts == [1]
    listed = server.call("GET", "/api/mix2/requests").json()
    assert listed == [got]


def test_batches_newest_first(server):
    folder = server.data / "mix2" / "requests"
    folder.mkdir(parents=True)
    (folder / "a.json").write_text(json.dumps({"id": "a", "made": 1}))
    (folder / "b.json").write_text(json.dumps({"id": "b", "made": 3}))
    (folder / "c.json").write_text(json.dumps({"id": "c"}))
    (folder / "d.json").write_text("{broken")
    assert [r["id"] for r in server.call("GET", "/api/mix2/requests").json()] == ["b", "a", "c"]


def test_no_batches_yet(server):
    assert server.call("GET", "/api/mix2/requests").json() == []


BAD_BATCHES = [
    {**BATCH, "target": 3},
    {**BATCH, "device": None},
    {**BATCH, "params": []},
    {**BATCH, "params": [{}, {}, {}]},
    {**BATCH, "bars": [0, 4]},
    {**BATCH, "bars": [9, 8]},
    {**BATCH, "bars": [1, 41]},
    {**BATCH, "bars": [1]},
    [1],
]


@pytest.mark.parametrize("body", BAD_BATCHES)
def test_bad_batches(server, body):
    r = server.call("POST", "/api/mix2/requests", body)
    assert (r.status, r.json()) == (400, {"error": "bad request"})
    assert server.worker_starts == []


def test_post_elsewhere(server):
    assert server.call("POST", "/api/arrangements/x", {}).status == 404
