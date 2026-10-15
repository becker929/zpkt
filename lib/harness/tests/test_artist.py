"""The artist agent's store and API (studio/artist.py, docs/artist-agent.md): a press is kept before any question;
answers, plates and repertoire versions; works outside the page's primitives are refused; the quick question falls
back to rules; site audio is served from an allowlist only."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from harness.studio import artist as A

sys.path.insert(0, str(Path(__file__).parent / "ui"))
from lab_server import app as lab_app  # noqa: E402

SEED = json.loads(A.SEED.read_text())


@pytest.fixture
def store(tmp_path):
    s = A.Artist(tmp_path / "artist", A.SEED)
    yield s
    s.close()


def test_a_press_is_kept_before_any_question_and_answers_join_it(store):
    made = store.add_feedback("down", "splash", {"work": {"id": "heavy"}, "item": "kick.drive"}, 123.0)
    fb = store.feedback()
    assert fb[0]["id"] == made["id"] and fb[0]["vote"] == "down" and fb[0]["question"] is None
    assert fb[0]["context"]["work"]["id"] == "heavy" and fb[0]["client_ts"] == 123.0
    store.set_question(made["id"], "What was off?", ["The shake", "Something else"], "rules")
    store.add_answer(made["id"], "", "The shake")
    store.add_answer(made["id"], "too long", None)
    fb = store.feedback()[0]
    assert fb["question"] == {"question": "What was off?", "choices": ["The shake", "Something else"], "by": "rules"}
    assert [a["choice"] or a["text"] for a in fb["answers"]] == ["The shake", "too long"]
    with pytest.raises(ValueError):
        store.add_feedback("meh", "splash", {})
    with pytest.raises(KeyError):
        store.add_answer("fb_nope", "x")


def test_a_big_context_is_cut_not_refused(store):
    made = store.add_feedback("up", "ledger", {"blob": "x" * 20000})
    assert "truncated" in store.event(made["id"])["context"]


def test_plates_number_up_and_list_by_track(store):
    a = store.add_plate({"track": "hw002", "item": "drive", "work": {"id": "ledger"}})
    b = store.add_plate({"track": "other", "item": "x"})
    c = store.add_plate({"track": "hw002", "item": "eq"})
    assert [a[1], b[1], c[1]] == [1, 2, 3]
    assert [p["item"] for p in store.plates("hw002")] == ["drive", "eq"]
    assert [p["n"] for p in store.plates()] == [1, 2, 3]
    with pytest.raises(ValueError):
        store.add_plate({"item": "no track"})


def test_the_repertoire_starts_from_the_seed_and_versions(store):
    rep = store.repertoire()
    assert rep["version"] == 1 and rep["parent"] is None
    assert [w["id"] for w in rep["works"]] == [w["id"] for w in SEED["works"]]
    works = copy.deepcopy(rep["works"])
    works[0]["weight"] = 7
    assert store.set_repertoire(works, "more ledger") == 2
    rep = store.repertoire()
    assert rep["version"] == 2 and rep["parent"] == 1 and rep["works"][0]["weight"] == 7 and rep["notes"] == "more ledger"


@pytest.mark.parametrize("change, why", [
    (lambda w: w["params"].update(shake=2.0), "outside"),
    (lambda w: w["params"]["particles"].update(palette="neon"), "not one of"),
    (lambda w: w["params"].update(glitter=True), "unknown"),
    (lambda w: w.update(sparkle=1), "unknown"),
    (lambda w: w["params"].pop("sky"), "missing"),
    (lambda w: w.update(id="Bad Id"), "id"),
    (lambda w: w.update(title="x" * 41), "title"),
    (lambda w: w.update(rarity=0), "outside"),
    (lambda w: w.update(when={"night": "yes"}), "true or false"),
    (lambda w: w["params"].update(lamp=1), "true or false"),
])
def test_works_outside_the_primitives_are_refused(change, why):
    works = copy.deepcopy(SEED["works"])
    change(works[0])
    with pytest.raises(A.Invalid, match=why):
        A.validate(works)


def test_two_works_with_one_id_are_refused():
    works = copy.deepcopy(SEED["works"])
    works[1]["id"] = works[0]["id"]
    with pytest.raises(A.Invalid, match="twice"):
        A.validate(works)


async def test_the_quick_question_falls_back_to_rules():
    event = {"vote": "down", "view": "splash", "context": {"work": {"id": "wax", "params": {"seal": "wax"}}}}
    q = await A.ask(event)
    assert q["by"] == "rules" and q["question"] == "What was off?" and "The wax seal" in q["choices"]
    assert q["choices"][-1] == "Something else" and len(q["choices"]) <= 4

    async def broken(_prompt):
        raise RuntimeError("no model")

    async def chatty(_prompt):
        return 'Sure! {"question": "The seal, or the shake?", "choices": ["The seal", "The shake"]}'

    async def nonsense(_prompt):
        return "I think it was nice"

    assert (await A.ask(event, broken))["by"] == "rules"
    assert (await A.ask(event, nonsense))["by"] == "rules"
    assert await A.ask(event, chatty) == {"question": "The seal, or the shake?", "choices": ["The seal", "The shake"],
                                          "by": "model"}
    up = await A.ask({"vote": "up", "view": "explore", "context": {}})
    assert up["question"] == "What landed?" and "The finds" in up["choices"]


def test_the_brief_attributes_presses_to_the_work_that_just_played(store):
    store.add_plate({"track": "hw002", "work": {"id": "wax"}})
    made = store.add_feedback("up", "splash", {})
    store.set_question(made["id"], "What landed?", ["The wax seal"], "rules")
    store.add_answer(made["id"], "", "The wax seal")
    b = A.brief(store)
    assert b["works"]["wax"] == {"played": 1, "up": 1, "down": 0}
    assert b["said"] == [{"vote": "up", "view": "splash", "question": "What landed?", "answers": ["The wax seal"]}]
    assert "wax" in A.show(store)


@pytest.fixture
async def client(tmp_path):
    c = TestClient(TestServer(lab_app(tmp_path)))
    await c.start_server()
    yield c
    await c.close()


async def test_the_api_keeps_a_press_asks_and_takes_an_answer(client):
    r = await client.post("/studio/api/artist/feedback", json={"vote": "up", "view": "ledger",
                                                              "context": {"item": "kick.drive"}, "client_ts": 1.5})
    assert r.status == 201
    fid = (await r.json())["id"]
    items = (await (await client.get("/studio/api/artist/feedback")).json())["items"]
    assert items[0]["id"] == fid and items[0]["question"] is None              # stored before any question
    q = await (await client.post(f"/studio/api/artist/feedback/{fid}/question")).json()
    assert q["by"] == "rules" and q["question"] == "What landed?"
    r = await client.post(f"/studio/api/artist/feedback/{fid}/answer", json={"text": "", "choice": q["choices"][0]})
    assert (await r.json()) == {"ok": True}
    item = (await (await client.get("/studio/api/artist/feedback?limit=5")).json())["items"][0]
    assert item["question"]["question"] == "What landed?" and item["answers"][0]["choice"] == q["choices"][0]
    assert (await client.post("/studio/api/artist/feedback", json={"vote": "sideways"})).status == 400
    assert (await client.post("/studio/api/artist/feedback", data="not json")).status == 400
    assert (await client.post("/studio/api/artist/feedback/fb_nope/question")).status == 404
    assert (await client.post("/studio/api/artist/feedback/fb_nope/answer", json={"text": "x"})).status == 404


async def test_the_api_keeps_plates_and_serves_the_repertoire(client):
    plate = {"track": "hw002", "step": "kick", "item": "drive", "title": "Distortion", "step_name": "Kick",
             "work": {"id": "ledger", "version": 1, "title": "The ledger", "params": SEED["works"][0]["params"]},
             "sound": "anvil", "done": ["kick.scoop", "kick.drive"], "unlocked": ["kick.drive"],
             "render": {"label": "Batch 8.1, drive 37%", "path": "skrng/x.mp3"}, "client_ts": 2}
    r = await client.post("/studio/api/artist/plates", json=plate)
    assert r.status == 201 and (await r.json())["n"] == 1
    r = await client.post("/studio/api/artist/plates", json={**plate, "track": "other"})
    assert (await r.json())["n"] == 2
    items = (await (await client.get("/studio/api/artist/plates?track=hw002")).json())["items"]
    assert len(items) == 1 and items[0]["work"]["id"] == "ledger" and items[0]["render"]["path"] == "skrng/x.mp3"
    assert len((await (await client.get("/studio/api/artist/plates")).json())["items"]) == 2
    assert (await client.post("/studio/api/artist/plates", json={"item": "no track"})).status == 400
    rep = await (await client.get("/studio/api/artist/repertoire")).json()
    assert rep["version"] == 1 and {w["id"] for w in rep["works"]} >= {"ledger", "wax"}


@pytest.mark.parametrize("path", [
    "skrng/../../etc/passwd", "skrng/x.wav", "elsewhere/x.mp3", "zpkt/check-sounds/anvil-hit.m4a",
    "skrng/a b.mp3", "zpkt/check-sounds/anvil-hit-c242b349.mp3",
])
async def test_site_audio_serves_only_its_allowlist(client, path, monkeypatch):
    def no_fetch(*_a, **_k):
        raise AssertionError("fetched a path outside the allowlist")
    monkeypatch.setattr("harness.studio.routes.ClientSession", no_fetch)
    r = await client.get(f"/studio/site-audio/{path}")
    assert r.status == 404


async def test_site_audio_serves_its_local_copy(client, tmp_path):
    copy_ = tmp_path / "site-audio" / "skrng" / "b8.mp3"
    copy_.parent.mkdir(parents=True)
    copy_.write_bytes(b"ID3fake")
    r = await client.get("/studio/site-audio/skrng/b8.mp3")
    assert r.status == 200 and r.headers["Content-Type"] == "audio/mpeg" and "immutable" in r.headers["Cache-Control"]
    assert await r.read() == b"ID3fake"
