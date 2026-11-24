"""renderqueue.py: the mix-2 batches on disk, and where the queue stands; the server's read-only queue route."""

from __future__ import annotations

import json

import pytest
from renderqueue import RenderQueue


def write(folder, name, row):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(row if isinstance(row, str) else json.dumps(row))


def test_queued_batches_oldest_first_and_where_the_queue_stands(tmp_path):
    q = RenderQueue(tmp_path / "requests")
    assert q.rows() == [] and q.queued() == []
    write(q.folder, "b2", {"id": "b2", "status": "queued", "made": 2})
    write(q.folder, "b1", {"id": "b1", "status": "queued", "made": 1})
    write(q.folder, "b0", {"id": "b0", "status": "rendering", "made": 0.5})
    write(q.folder, "a", {"id": "a", "status": "ready", "made": 0.1})
    write(q.folder, "x", "{broken")
    assert [p.stem for p in q.queued()] == ["b1", "b2"]
    assert [r["id"] for r in q.rows()] == ["b2", "b1", "b0", "a"]
    assert q.status(True) == {
        "worker": "running",
        "rendering": ["b0"],
        "queued": ["b1", "b2"],
        "counts": {"queued": 2, "rendering": 1, "ready": 1, "failed": 0},
    }
    assert q.status(False)["worker"] == "idle" and q.status(None)["worker"] == "unknown"
    with pytest.raises(ValueError):
        q.queued(strict=True)  # the worker stops at a file it cannot read, as it always did


def test_add_files_a_batch_and_fail_marks_one(tmp_path):
    q = RenderQueue(tmp_path / "requests")
    batch = q.add({"target": "bus-kick"})
    path = q.folder / f"{batch['id']}.json"
    assert path.read_text() == json.dumps(batch, indent=1) and batch["status"] == "queued"
    q.fail(path, "Live said no")
    assert json.loads(path.read_text()) == {**batch, "status": "failed", "error": "Live said no"}
    assert q.queued() == []


def test_the_server_says_where_the_queue_stands(server):
    assert server.call("GET", "/api/mix2/queue").json() == {
        "worker": "unknown",  # the test's worker cannot be asked
        "rendering": [],
        "queued": [],
        "counts": {"queued": 0, "rendering": 0, "ready": 0, "failed": 0},
    }
    batch = server.call(
        "POST",
        "/api/mix2/requests",
        {"target": "bus-kick", "device": "Saturator", "params": [{"name": "Drive"}], "bars": [17, 24]},
    ).json()
    assert server.call("GET", "/api/mix2/queue").json()["queued"] == [batch["id"]]
    assert server.call("POST", "/api/mix2/queue").status == 404  # read-only


def test_the_worker_says_whether_it_runs(tmp_path, monkeypatch):
    import server

    class Process:
        def __init__(self, args, **kw):
            self.done = None

        def poll(self):
            return self.done

    monkeypatch.setattr(server.subprocess, "Popen", Process)
    w = server.Mix2Worker(tmp_path)
    assert not w.running()
    w.start()
    assert w.running()
    w._process.done = 0
    assert not w.running()
    import threading
    import urllib.request

    httpd = server.make_server(tmp_path, port=0)  # its own worker, which it can ask
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{httpd.server_address[1]}/api/mix2/queue", timeout=10) as r:
            assert json.loads(r.read())["worker"] == "idle"
    finally:
        httpd.shutdown()
        httpd.server_close()
