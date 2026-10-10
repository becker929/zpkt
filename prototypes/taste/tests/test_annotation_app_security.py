"""The annotation app must not serve files outside its clips folder."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("flask")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import annotation_app  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    clips = tmp_path / "clips"
    clips.mkdir()
    (clips / "a.wav").write_bytes(b"RIFF")
    (tmp_path / "secret.txt").write_text("nope")
    monkeypatch.setattr(annotation_app, "_clips_dir", clips)
    return annotation_app.app.test_client()


def test_serves_a_clip(client) -> None:
    assert client.get("/audio/a.wav").status_code == 200


@pytest.mark.parametrize("path", ["/audio/..%2fsecret.txt", "/audio/../secret.txt",
                                  "/audio/..%2f..%2f..%2fetc%2fhosts"])
def test_refuses_traversal(client, path) -> None:
    r = client.get(path)
    assert r.status_code in (404, 400) and b"nope" not in r.data
