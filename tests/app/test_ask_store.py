"""Ask's store: sessions and events in files, numbered, replayed and followed; Zpkt web's files read as they are."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from zpkt.app.ask.store import NoSuchSession, Refused, SessionStore

OLD_SESSION = "11111111-2222-3333-4444-555555555555"


def make(tmp_path: Path, clock=lambda: 1000.0) -> SessionStore:
    return SessionStore(tmp_path / "ask", clock=clock)


def test_create_emit_replay_and_numbering(tmp_path):
    store = make(tmp_path)
    s = store.create("Bass", "scratch", str(tmp_path))
    a = store.emit(s["id"], {"type": "prompt", "text": "hi"})
    b = store.emit(s["id"], {"type": "message", "content": "yo"})
    assert (a["seq"], b["seq"], a["t"]) == (0, 1, 1_000_000)
    assert [e["seq"] for e in store.replay(s["id"], 1)] == [1]
    again = make(tmp_path)  # a restart: the numbering carries on from the file
    assert again.emit(s["id"], {"type": "x"})["seq"] == 2
    assert again.get(s["id"])["title"] == "Bass"


def test_a_cut_off_last_line_is_ended_so_the_next_event_is_not_lost(tmp_path):
    store = make(tmp_path)
    s = store.create("t", "w", str(tmp_path))
    store.emit(s["id"], {"type": "a"})
    with store.file(s["id"]).open("a") as f:
        f.write('{"type": "cut')
    fresh = make(tmp_path)
    fresh.emit(s["id"], {"type": "b"})
    types = [e["type"] for e in fresh.replay(s["id"])]
    assert types == ["a", "b"]


def test_follow_replays_then_follows_with_nothing_between(tmp_path):
    store = make(tmp_path)
    s = store.create("t", "w", str(tmp_path))
    for i in range(3):
        store.emit(s["id"], {"type": "e", "i": i})
    seen: list[int] = []
    off = store.follow(s["id"], 1, lambda e: seen.append(e["seq"]))
    store.emit(s["id"], {"type": "e", "i": 3})
    off()
    store.emit(s["id"], {"type": "e", "i": 4})
    assert seen == [1, 2, 3]


def test_concurrent_emits_get_distinct_numbers(tmp_path):
    store = make(tmp_path)
    s = store.create("t", "w", str(tmp_path))
    threads = [
        threading.Thread(target=lambda: [store.emit(s["id"], {"type": "e"}) for _ in range(25)]) for _ in range(4)
    ]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(e["seq"] for e in store.replay(s["id"])) == list(range(100))


def test_delete_hides_for_a_week_restore_brings_back_then_it_goes(tmp_path):
    now = [1000.0]
    store = make(tmp_path, clock=lambda: now[0])
    s = store.create("t", "w", str(tmp_path))
    store.emit(s["id"], {"type": "e"})
    store.remove(s["id"])
    assert store.all_sessions() == []
    with pytest.raises(NoSuchSession):
        store.get(s["id"])
    assert store.restore(s["id"])["id"] == s["id"]
    store.remove(s["id"])
    now[0] += 8 * 86400
    gone = make(tmp_path, clock=lambda: now[0])
    assert gone.index == [] and not store.file(s["id"]).exists()
    with pytest.raises(Refused):
        gone.restore(s["id"])


def test_a_running_session_cannot_be_deleted_and_titles_are_checked(tmp_path):
    store = make(tmp_path)
    s = store.create("t", "w", str(tmp_path))
    with pytest.raises(Refused) as why:
        store.remove(s["id"], running=True)
    assert why.value.code == 409
    assert store.rename(s["id"], "  new   name ")["title"] == "new name"
    with pytest.raises(Refused):
        store.rename(s["id"], "   ")


def test_discard_forgets_a_session_nothing_happened_in(tmp_path):
    store = make(tmp_path)
    empty = store.create("t", "w", str(tmp_path))
    used = store.create("u", "w", str(tmp_path))
    store.emit(used["id"], {"type": "e"})
    store.discard(empty["id"])
    store.discard(used["id"])
    assert [s["id"] for s in store.index] == [used["id"]]


def test_an_old_zpkt_web_session_reads_as_it_is(tmp_path):
    """Files at rest keep their forms: Zpkt web's index entry and its events (a zpkt-surface block included)."""
    folder = tmp_path / "ask"
    (folder / "sessions").mkdir(parents=True)
    (folder / "sessions.json").write_text(
        json.dumps(
            [
                {
                    "id": OLD_SESSION,
                    "title": "Old bass",
                    "workspace": "scratch",
                    "cwd": "/tmp",
                    "kind": "normal",
                    "started": True,
                    "created": 1,
                    "updated": 5,
                    "unseen": ["x"],
                }
            ]
        )
    )
    block = '```zpkt-surface\n{"title": "Kick", "controls": [{"kind": "knob", "id": "a", "label": "A", "min": 0, "max": 1, "value": 0.5}]}\n```'
    lines = [
        {"type": "prompt", "text": "a kick", "mode": "plan", "engine": "gemini", "seq": 0, "t": 1},
        {"type": "message", "role": "assistant", "content": block, "delta": True, "seq": 1, "t": 2},
        {"type": "surface", "spec": {"controls": [{"kind": "knob", "id": "a"}]}, "seq": 2, "t": 3},
    ]
    (folder / "sessions" / f"{OLD_SESSION}.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    store = SessionStore(folder)
    (s,) = store.all_sessions()
    assert s["title"] == "Old bass" and s["unseen"] == ["x"]
    assert store.engine_state(s) == {"gemini": {"started": True}}  # an older session only knew Gemini
    replayed = store.replay(OLD_SESSION)
    assert [e["type"] for e in replayed] == ["prompt", "message", "surface"]
    assert "zpkt-surface" in replayed[1]["content"]
    assert store.emit(OLD_SESSION, {"type": "message", "content": "more"})["seq"] == 3


def test_a_damaged_index_is_kept_aside_not_overwritten(tmp_path):
    folder = tmp_path / "ask"
    folder.mkdir()
    (folder / "sessions.json").write_text("{not json")
    store = SessionStore(folder)
    assert store.index == []
    assert list(folder.glob("sessions.json.damaged-*"))
    (folder / "sessions.json").write_text(json.dumps([{"id": "bad"}, {"id": OLD_SESSION, "cwd": "/", "title": "ok"}]))
    kept = SessionStore(folder)
    assert [s["id"] for s in kept.index] == [OLD_SESSION]
