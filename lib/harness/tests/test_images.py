"""Images made with Gemini (harness/images.py, docs/images.md): every image a call returns is kept with its record
(context, batch, the full prompt, the model, the settings sent, timings), failures are recorded too, a call without
its context is refused, and the wall's API pages them newest first and serves their files."""

from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from harness import images as I

sys.path.insert(0, str(Path(__file__).parent / "ui"))
from lab_server import app as lab_app  # noqa: E402


def png(w=64, h=96, color=(255, 255, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def fake(images=1, text="Here it is."):
    calls = []

    def post(url, body, headers, timeout):
        calls.append({"url": url, "body": body, "headers": headers})
        parts = [{"text": text}] + [{"inlineData": {"mimeType": "image/png", "data": base64.b64encode(png(1200, 1800)).decode()}}] * images
        return {"candidates": [{"content": {"parts": parts}}], "usageMetadata": {"totalTokenCount": 1700}}
    return post, calls


def test_every_image_is_kept_with_its_record(tmp_path):
    store = I.Store(tmp_path)
    post, calls = fake(images=2)
    recs = I.generate(store, "a giant eurorack obelisk", key="k", context="to try the look", batch="b1", title="euro",
                      model="gemini-3-pro-image", aspect="9:16", size="2K", post=post)
    assert len(recs) == 2 and [r.title for r in recs] == ["euro (1)", "euro (2)"]
    sent = calls[0]
    assert sent["url"].endswith("/models/gemini-3-pro-image:generateContent") and sent["headers"]["X-goog-api-key"] == "k"
    assert sent["body"]["generationConfig"] == {"responseModalities": ["TEXT", "IMAGE"], "imageConfig": {"aspectRatio": "9:16", "imageSize": "2K"}}
    kept = store.all()
    assert [r.id for r in kept] == [r.id for r in recs]
    r = kept[0]
    assert (r.prompt, r.context, r.batch, r.model, r.text) == ("a giant eurorack obelisk", "to try the look", "b1", "gemini-3-pro-image", "Here it is.")
    assert r.settings["imageConfig"]["aspectRatio"] == "9:16" and r.tokens["totalTokenCount"] == 1700
    assert (r.width, r.height) == (1200, 1800)
    assert (tmp_path / "files" / r.file).read_bytes()[:4] == b"\x89PNG"
    assert Image.open(tmp_path / "files" / r.thumb).size == (900, 1350)            # the wall's copy


def test_reference_images_go_before_the_prompt(tmp_path):
    ref = tmp_path / "ref.png"
    ref.write_bytes(png())
    post, calls = fake()
    [r] = I.generate(I.Store(tmp_path / "s"), "in this style", key="k", context="c", batch="b", inputs=[ref], post=post)
    parts = calls[0]["body"]["contents"][0]["parts"]
    assert parts[0]["inlineData"]["mimeType"] == "image/png" and parts[1] == {"text": "in this style"}
    assert r.inputs == [str(ref)]


def test_no_context_no_call_and_failures_are_recorded(tmp_path):
    store = I.Store(tmp_path)
    post, calls = fake()
    with pytest.raises(ValueError):
        I.generate(store, "p", key="k", context=" ", batch="b", post=post)
    with pytest.raises(ValueError):
        I.generate(store, "p", key="k", context="c", batch="b", aspect="7:3", post=post)
    assert not calls

    def refuse(*_a):
        raise RuntimeError("HTTP 429: quota")
    with pytest.raises(RuntimeError):
        I.generate(store, "p", key="k", context="c", batch="b", post=refuse)
    I.generate(store, "p2", key="k", context="c", batch="b", post=fake(images=0)[0])   # a reply with no image
    errors = [json.loads(x) for x in (tmp_path / "errors.jsonl").read_text().splitlines()]
    assert [e["error"][:8] for e in errors] == ["HTTP 429", "no image"] and errors[0]["prompt"] == "p"
    assert store.all() == []


def test_a_batch_runs_together_and_keeps_going_past_a_failure(tmp_path):
    store = I.Store(tmp_path)
    good, _ = fake()

    def post(url, body, headers, timeout):
        if body["contents"][0]["parts"][-1]["text"] == "bad":
            raise RuntimeError("HTTP 500")
        return good(url, body, headers, timeout)
    recs, errors = I.run_batch(store, [{"prompt": "a", "title": "A", "aspect": "3:4"}, {"prompt": "bad"}, {"prompt": "c"}],
                               key="k", context="ctx", batch="bb", post=post)
    assert sorted(r.prompt for r in recs) == ["a", "c"] and len(errors) == 1
    assert {r.batch for r in store.all()} == {"bb"}


async def test_the_wall_pages_newest_first_and_serves_files(tmp_path):
    client = TestClient(TestServer(lab_app(tmp_path)))
    await client.start_server()
    try:
        store = I.Store(tmp_path / "images")
        for k in range(5):
            I.import_image(store, _write(tmp_path / f"{k}.png"), prompt=f"p{k}", model="m", context="ctx",
                           batch="old" if k < 2 else "new", title=f"t{k}", created=f"2026-10-1{k}T00:00:00+00:00")
        r = await client.get("/studio/images/api/list?limit=3")
        d = await r.json()
        assert d["total"] == 5 and [x["title"] for x in d["items"]] == ["t4", "t3", "t2"]
        assert [b["batch"] for b in d["batches"]] == ["new", "old"] and d["batches"][0]["count"] == 3
        d = await (await client.get("/studio/images/api/list?batch=old")).json()
        assert [x["title"] for x in d["items"]] == ["t1", "t0"] and d["items"][0]["imported"] is True
        f = await client.get(f"/studio/images/files/{d['items'][0]['thumb']}")
        assert f.status == 200 and "immutable" in f.headers["Cache-Control"]
        assert (await client.get("/studio/images/files/..%2Fimages.jsonl")).status == 404
        assert (await client.get("/studio/images/")).status == 200
    finally:
        await client.close()


def _write(p: Path) -> Path:
    p.write_bytes(png())
    return p
