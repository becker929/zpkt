"""The one render queue (zpkt.app.renderqueue): the arranger's old module is an alias, and jobs update whole."""

from __future__ import annotations

import json
import sys

import pytest

from zpkt.app.renderqueue import RenderQueue


def test_the_arrangers_renderqueue_module_is_this_one():
    sys.path.insert(0, "contrib/arranger")
    try:
        import renderqueue  # the old name

        assert renderqueue.RenderQueue is RenderQueue
    finally:
        sys.path.remove("contrib/arranger")
        sys.modules.pop("renderqueue", None)


def test_two_jobs_in_one_second_get_two_ids(tmp_path):
    q = RenderQueue(tmp_path / "jobs")
    ids = {q.add({"title": str(k)}, prefix="o")["id"] for k in range(5)}
    assert len(ids) == 5 and all(i.startswith("o") for i in ids)
    assert len(list((tmp_path / "jobs").glob("*.json"))) == 5


def test_update_changes_fields_and_leaves_the_rest(tmp_path):
    q = RenderQueue(tmp_path)
    job = q.add({"title": "t", "versions": [1, 2]})
    row = q.update(job["id"], status="rendering", done=1)
    assert row["status"] == "rendering" and row["versions"] == [1, 2]
    assert q.get(job["id"]) == row
    assert not list(tmp_path.glob("*.tmp"))


def test_get_is_none_for_a_missing_or_broken_job_and_ids_are_plain_names(tmp_path):
    q = RenderQueue(tmp_path)
    assert q.get("nope") is None
    (tmp_path / "bad.json").write_text("{broken")
    assert q.get("bad") is None
    for bad in ("", "../x", "a/b", ".hidden"):
        with pytest.raises(ValueError):
            q.path_of(bad)


def test_the_old_status_shape_is_unchanged(tmp_path):
    q = RenderQueue(tmp_path)
    q.add({"x": 1})
    assert json.loads(json.dumps(q.status(None))) == {
        "worker": "unknown",
        "rendering": [],
        "queued": [q.rows()[0]["id"]],
        "counts": {"queued": 1, "rendering": 0, "ready": 0, "failed": 0},
    }
