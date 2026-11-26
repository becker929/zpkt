"""One long conversation: the workspace's main session, the archive of older ones, and a transcript read in pages."""

from __future__ import annotations

from pathlib import Path

import pytest

from zpkt.app.ask.service import Ask
from zpkt.app.ask.store import Refused, SessionStore
from zpkt.app.ask.testing import ScriptedProvider
from zpkt.app.ask.tools import ToolGate
from zpkt.app.bus import Bus

API = "/app/ask/api"


def make(tmp_path: Path) -> Ask:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    said = {"type": "message", "role": "assistant", "content": "ok", "delta": True}
    ask = Ask(tmp_path / "ask", {"claude": ScriptedProvider("claude", [said])}, ToolGate(Bus()), home=tmp_path)
    ask.workspaces.list.insert(0, {"id": "work", "name": "Work", "path": str(work)})
    return ask


def test_the_main_session_is_made_on_first_use_and_is_the_same_ever_after(tmp_path):
    ask = make(tmp_path)
    main = ask.main("work")
    assert main["main"] is True and main["workspace"] == "work" and main["running"] is False
    assert ask.main("work")["id"] == main["id"] == ask.main()["id"]  # no workspace named: the first one
    assert ask.archive("work") == []
    again = Ask(tmp_path / "ask", {}, ToolGate(Bus()), home=tmp_path)  # after a restart
    again.workspaces.list.insert(0, {"id": "work", "name": "Work", "path": str(tmp_path / "work")})
    assert again.main("work")["id"] == main["id"]
    with pytest.raises(Refused, match="Unknown workspace"):
        ask.main("nope")


def test_the_most_recent_old_session_becomes_main_and_the_rest_are_the_archive(tmp_path):
    ask = make(tmp_path)
    old = ask.create("work", "first", engine="claude")
    ask.wait_idle()
    new = ask.create("work", "second", engine="claude")
    ask.wait_idle()
    new["updated"] = old["updated"] + 5
    other = ask.store.create("elsewhere", "desktop", str(tmp_path))
    main = ask.main("work")
    assert main["id"] == new["id"] and main["title"] == "second"
    assert [s["id"] for s in ask.archive("work")] == [old["id"]]
    assert [e["text"] for e in ask.store.replay(old["id"]) if e["type"] == "prompt"] == ["first"]  # still on disk
    assert other["id"] not in {s["id"] for s in ask.archive("work")} and not other.get("main")
    with pytest.raises(Refused, match="cannot be deleted"):
        ask.remove(new["id"])
    ask.remove(old["id"])
    assert ask.archive("work") == []
    ask.send(ask.store.get(main["id"]), "third", engine="claude")  # the main session takes turns like any other
    ask.wait_idle()
    assert [e["text"] for e in ask.store.replay(main["id"]) if e["type"] == "prompt"] == ["second", "third"]


def test_a_long_transcript_is_read_a_page_of_whole_turns_at_a_time(tmp_path):
    store = SessionStore(tmp_path)
    s = store.create("t", "w", str(tmp_path))
    for n in range(5):
        store.emit(s["id"], {"type": "prompt", "text": f"q{n}"})
        store.emit(s["id"], {"type": "message", "content": f"a{n}"})
        store.emit(s["id"], {"type": "run_end"})
    last = store.page(s["id"], turns=2)
    assert [e["seq"] for e in last["events"]] == list(range(9, 15))
    assert last["first"] == 9 and last["next"] == 15 and last["more"] is True
    older = store.page(s["id"], turns=2, before=last["first"])
    assert [e["seq"] for e in older["events"]] == list(range(3, 9)) and older["more"] is True
    oldest = store.page(s["id"], turns=2, before=older["first"])
    assert [e["seq"] for e in oldest["events"]] == [0, 1, 2] and oldest["more"] is False and oldest["next"] == 15
    assert store.page(s["id"], turns=50)["first"] == 0 and len(store.page(s["id"], turns=50)["events"]) == 15
    empty = store.create("e", "w", str(tmp_path))
    assert store.page(empty["id"]) == {"events": [], "first": 0, "next": 0, "more": False}


def test_main_archive_and_pages_over_http(asked):
    asked.providers["claude"].script = [{"type": "message", "role": "assistant", "content": "hi", "delta": True}]
    code, old = asked.rig.post(f"{API}/sessions", {"workspace": "work", "prompt": "old one", "engine": "claude"})
    assert code == 200 and asked.ask.wait_idle()
    code, body = asked.rig.get(f"{API}/main?workspace=work")
    assert code == 200 and body["session"]["id"] == old["session"]["id"] and body["session"]["main"] is True
    assert body["archive"] == []
    sid = body["session"]["id"]
    assert asked.rig.post(f"{API}/sessions/{sid}/messages", {"prompt": "again", "engine": "claude"})[0] == 200
    assert asked.ask.wait_idle()
    code, page = asked.rig.get(f"{API}/sessions/{sid}/events?turns=1")
    assert code == 200 and page["events"][0]["text"] == "again" and page["more"] is True and page["running"] is False
    code, older = asked.rig.get(f"{API}/sessions/{sid}/events?turns=1&before={page['first']}")
    assert older["events"][0]["text"] == "old one" and older["more"] is False
    tail = asked.stream(sid, lambda e: e["type"] == "__state", start=page["next"])
    assert [e["type"] for e in tail] == ["__state"]  # nothing is sent twice
    assert asked.rig.request("DELETE", f"{API}/sessions/{sid}")[0] == 409
    assert asked.rig.get(f"{API}/main?workspace=nope")[0] == 400
    code, sessions = asked.rig.get(f"{API}/archive?workspace=work")
    assert code == 200 and sessions == {"sessions": []}
    fresh = asked.rig.get(f"{API}/main?workspace=scratch")[1]["session"]  # no session there yet: one is made
    assert fresh["main"] is True and fresh["id"] != sid and fresh["workspace"] == "scratch"
