"""arrangement.py: the parse of each body and what a page save keeps; and the server as its own process."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time

import arrangement as A
import pytest
from conftest import HERE, OPENER


def test_page_save_keeps_every_key_it_does_not_own():
    old = {
        "name": "Old",
        "bars": 40,
        "regions": [],
        "mutes": ["kick"],
        "saved": 1.0,
        "desk": {"monitor": []},
        "automation": {"future": True},
        "mix": {"channels": {}},
    }
    new = {"name": "New", "bars": 32, "regions": [{"lane": "kick", "clip": "k", "start": 0, "len": 4}]}
    got = A.merge_page_save(new, old, now=5.0)
    assert got == {
        **new,
        "saved": 5.0,
        "desk": {"monitor": []},
        "automation": {"future": True},
        "mix": {"channels": {}},
    }
    assert "mutes" not in got  # the page owns mutes: not sending them is the page's choice


def test_page_save_without_an_old_file():
    assert A.merge_page_save({"regions": []}, None, now=2.0) == {"regions": [], "saved": 2.0}


def test_unknown_key_survives_a_save_over_http(server):
    f = server.data / "arrangements" / "short-x.json"
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps({"regions": [], "automation": [1, 2]}))
    server.call("PUT", "/api/arrangements/short-x", {"name": "x", "regions": [], "mutes": []})
    assert json.loads(f.read_text())["automation"] == [1, 2]


@pytest.mark.parametrize(("key", "body"), [("mix", {"channels": {}}), ("kickFuzz", None), ("transitions", [])])
def test_parse_later_key_accepts(key, body):
    assert A.parse_later_key(key, body) == body


def test_parse_later_key_message():
    with pytest.raises(A.Rejected, match=r"^bad spectral$"):
        A.parse_later_key("spectral", [{"id": "a"}])


def test_mix2_request_with_bars_that_are_not_numbers():
    with pytest.raises(A.Rejected, match="bad request"):
        A.parse_mix2_request({"target": "t", "device": "d", "params": [{}], "bars": ["a", "b"]})


def test_ids():
    assert A.ID.match("short-8d2a2") and not A.ID.match("-x") and not A.ID.match("A")


def test_worker_starts_once(tmp_path, monkeypatch):
    import server

    started = []

    class Running:
        def __init__(self, args, **kw):
            started.append((args, kw["env"]["ARRANGER_DATA"]))

        def poll(self):
            return None

    monkeypatch.setattr(server.subprocess, "Popen", Running)
    w = server.Mix2Worker(tmp_path)
    w.start()
    w.start()
    assert len(started) == 1
    args, data = started[0]
    assert args[-2:] == [str(HERE / "mixset.py"), "worker"] and args[1:3] == ["run", "--project"]
    assert data == str(tmp_path) and (tmp_path / "mix2" / "worker.log").exists()


def test_server_runs_as_a_script(tmp_path):
    """`python3 server.py` with ARRANGER_DATA and ARRANGER_PORT, as the restart recipe starts it."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "ARRANGER_DATA": str(tmp_path), "ARRANGER_PORT": str(port)}
    proc = subprocess.Popen([sys.executable, str(HERE / "server.py")], env=env, stdout=subprocess.PIPE, text=True)
    try:
        line = proc.stdout.readline()
        assert line.strip() == f"arranger on http://127.0.0.1:{port} (data {tmp_path})"
        for _ in range(50):
            try:
                with OPENER.open(f"http://127.0.0.1:{port}/api/arrangements", timeout=2) as r:
                    assert json.loads(r.read()) == []
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise AssertionError("the server did not answer")
    finally:
        proc.terminate()
        proc.wait(5)


# ---- the contract: lib/contracts/arrangement.schema.json agrees with the code ---------------------------------------

jsonschema = pytest.importorskip("jsonschema")
SCHEMA = json.loads((HERE.parents[1] / "lib" / "contracts" / "arrangement.schema.json").read_text())


def valid(doc) -> bool:
    return not list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(doc))


def test_schema_is_a_schema():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


def test_sample_and_server_files_match_the_schema(server):
    from samples import ARRANGEMENT

    assert valid(ARRANGEMENT)
    server.call(
        "PUT", "/api/arrangements/short-x", {"name": "x", "bars": 40, "regions": ARRANGEMENT["regions"], "mutes": []}
    )
    for key in A.LATER_KEYS:
        server.call("PUT", f"/api/arrangements/short-x/{key}", ARRANGEMENT[key])
    assert valid(json.loads((server.data / "arrangements" / "short-x.json").read_text()))


LATER_BODIES = [
    ("transitions", [{"id": "a", "seam": 17}], True),
    ("transitions", [{"id": "a"}], False),
    ("mix", {"channels": {}}, True),
    ("mix", {"channels": []}, False),
    ("mix2", [{"device": "d", "target": "t"}], True),
    ("mix2", [{"device": "d"}], False),
    ("spectral", [{"id": "a", "parts": []}], True),
    ("spectral", [{"parts": []}], False),
    ("kickFuzz", None, True),
    ("kickFuzz", {"loop": "a.flac", "kickTurnedDb": 1.5, "bells": [[40, 8, 0.7]]}, True),
    ("kickFuzz", {"loop": "A.flac", "kickTurnedDb": 1.5}, False),
    ("kickFuzz", {"loop": "a.flac", "kickTurnedDb": 1, "bells": [[1, 2]]}, False),
    ("kickFuzz", {"loop": "a.flac", "kickTurnedDb": 1, "bells": [[1, 2, 3]] * 7}, False),
]


@pytest.mark.parametrize(("key", "body", "ok"), LATER_BODIES)
def test_parse_and_schema_agree(key, body, ok):
    try:
        A.parse_later_key(key, body)
        parsed = True
    except A.Rejected:
        parsed = False
    assert parsed is ok
    assert valid({"regions": [], key: body}) is ok


# ---- the two halves: structure and sound, named in the type, side by side in the file ---------------------------------


def test_the_type_names_structure_and_sound_and_the_file_is_unchanged():
    from samples import ARRANGEMENT

    assert A.STRUCTURE_KEYS == ("name", "bars", "regions", "mutes", "transitions")
    assert A.SOUND_KEYS == ("mix", "mix2", "spectral", "kickFuzz", "desk")
    assert set(A.PAGE_KEYS) <= set(A.STRUCTURE_KEYS) and set(A.LATER_KEYS) <= {*A.STRUCTURE_KEYS, *A.SOUND_KEYS}
    assert set(SCHEMA["properties"]) == {*A.STRUCTURE_KEYS, *A.SOUND_KEYS, "saved"}  # the file's keys, flat
    halves = {**A.structure(ARRANGEMENT), **A.sound(ARRANGEMENT)}
    assert halves == {k: v for k, v in ARRANGEMENT.items() if k != "saved"}
    assert "mix" not in A.structure(ARRANGEMENT) and "regions" not in A.sound(ARRANGEMENT)
    assert A.sound({"regions": []}) == {} and A.structure({"regions": []}) == {"regions": []}
