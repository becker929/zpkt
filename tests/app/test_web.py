"""The Web adapter through real HTTP against FakeLive: the old desk page and the new shell from one state, and the
bus's door (POST /api/command)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from tests.app.conftest import wait_for
from zpkt.app.bus import Command


def first_control(rig, prefix="k"):
    """(slot, key) of the first control of the armed page that has a state key."""
    for slot, v in rig.state()["values"].items():
        page, name = slot.split(":")
        if v.get("key") and name.startswith(prefix) and int(page) == rig.state()["page"]:
            return name, v["key"], v
    raise AssertionError("no control with a key")


def test_the_front_door_is_the_app_and_the_old_page_is_at_desk(rig):
    req = urllib.request.Request(rig.url + "/")
    opener = urllib.request.build_opener(NoRedirect)
    with pytest.raises(urllib.error.HTTPError) as e:
        opener.open(req, timeout=10)
    assert e.value.code == 302 and e.value.headers["Location"] == "/app/"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def test_the_old_page_and_the_new_shell_are_served_from_one_app(rig):
    old, shell = rig.get("/desk/"), rig.get("/app/")
    assert old[0] == 200 and b"<script>" in old[1]
    assert shell[0] == 200 and b'id="htop"' in shell[1] and b"/events?app=1" in shell[1]
    assert rig.get("/app")[0] == 200
    assert old[1] != shell[1]


def test_the_shell_event_stream_starts_with_the_state_the_monitor_and_the_history(rig):
    with urllib.request.urlopen(rig.url + "/events?app=1", timeout=10) as r:
        kinds = []
        for _ in range(3):
            line = r.readline().decode()
            kinds.append(json.loads(line.removeprefix("data: "))["t"])
            r.readline()
    assert kinds == ["full", "hear", "hist"]


def test_the_old_event_stream_does_not_get_the_shells_messages(rig):
    with urllib.request.urlopen(rig.url + "/events", timeout=10) as r:
        assert json.loads(r.readline().decode().removeprefix("data: "))["t"] == "full"
    rig.desk.push_app({"t": "hear"})  # only app clients have it
    assert all("hear" not in str(q.queue) for q in rig.desk.clients)


def test_a_drag_moves_live_and_is_one_history_entry_by_you(rig):
    _, key, _ = first_control(rig, "f")
    code, reply = rig.command("mix.set", {"norms": [[key, 0.25]]})
    assert code == 200 and reply["missing"] == []
    assert wait_for(lambda: rig.desk.history.entries)
    entry = rig.desk.history.entries[0]
    assert entry["who"] == "you" and entry["moves"][0]["key"] == key
    assert wait_for(lambda: rig.get("/api/hear")[1]["changed"] == 1)
    assert key in rig.get("/api/hear")[1]["keys"]


def test_the_web_is_always_you_even_if_the_body_says_agent(rig):
    _, key, _ = first_control(rig, "f")
    code, _ = rig.command("mix.set", {"norms": [[key, 0.3]]}, who="agent")
    assert code == 200
    assert rig.desk.history.entries[0]["who"] == "you"


def test_every_old_post_goes_through_the_bus_with_who(rig):
    assert rig.post("/api/page", {"page": 1}) == (200, {"ok": True})
    assert rig.post("/api/transport", {"action": "play"})[0] == 200
    kinds = [(e["kind"], e["who"], e["status"]) for e in rig.desk.bus.log]
    assert ("page.arm", "you", 200) in kinds and ("transport", "you", 200) in kinds


def test_a_bad_command_is_a_clear_400_and_an_unknown_one_a_404(rig):
    assert rig.post("/api/command", {})[0] == 400
    assert rig.post("/api/command", {"kind": "mix.set", "args": {"writes": "no"}})[0] == 400
    code, body = rig.command("nope")
    assert code == 404 and "mix.set" in body["error"]
    assert rig.get("/api/commands")[1]["commands"][0] == "ability.list"  # the kinds, sorted


def test_the_change_stream_has_what_the_agent_did_in_one_group(rig):
    _, key, _ = first_control(rig, "f")
    reply = rig.desk.bus.submit(
        Command("mix.set", "agent", {"norms": [[key, 0.2]]}, approval="user", group="make the kick sit back")
    )
    assert reply[0] == 200
    code, body = rig.get("/api/changes?who=agent")
    assert code == 200 and body["changes"][0]["key"] == key
    assert body["changes"][0]["group"] == "make the kick sit back" and body["changes"][0]["who"] == "agent"
    assert rig.get("/api/changes?since=x")[0] == 400
