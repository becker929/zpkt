"""The Remote Script's watch: parameters pushed back on the same socket. All on FakeLive, in process and over a free
loopback port (never Live's own 16619)."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import jsonschema
import pytest

from zpkt.live import watch as W
from zpkt.live.testing import FakeLive, hw002_like
from zpkt.live.testing import fakelive as fakelive_module
from zpkt.live.transport import LiveClient, LiveError

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "lib" / "contracts" / "live-watch.schema.json").read_text())
KEY = "Kick bus/volume"
SET_VOLUME = "result = (find_track('Kick bus').mixer_device.volume.__setattr__('value', {v!r}), 'ok')[1]"
OLD_SCRIPT = Path(__file__).with_name("data") / "remote_script_before_watch.py"


def set_volume(live, value):
    live.run(SET_VOLUME.format(v=value))


def wait_for(check, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        got = check()
        if got:
            return got
        time.sleep(0.01)
    return check()


def valid(message, definition):
    jsonschema.validate(message, {**SCHEMA, "oneOf": [{"$ref": f"#/$defs/{definition}"}]})


@pytest.fixture()
def live():
    with FakeLive(hw002_like()) as fake:
        yield fake


# ---- the wire shapes ------------------------------------------------------------------------------------------------


def test_the_messages_the_library_builds_and_the_script_sends_agree_with_the_schema(live):
    valid(W.watch_message({"k1": KEY, "k2": "Hats bus/volume"}), "watch_request")
    valid(W.unwatch_message(), "unwatch_request")
    reply = live.send(W.watch_message({"k1": KEY, "gone": "Nobody/volume"}))
    valid(reply, "reply")
    set_volume(live, 0.25)
    valid(live.pushes[-1], "push")
    valid(live.send(W.unwatch_message()), "reply")
    with pytest.raises(jsonschema.ValidationError):
        valid({"watch": [{"id": "k1"}]}, "watch_request")  # no code
    with pytest.raises(jsonschema.ValidationError):
        valid({"push": "watch", "changes": [], "at": 1}, "push")  # a push has at least one change


def test_a_push_is_read_as_data_and_a_stray_line_is_ignored():
    push = W.parse_push({"push": "watch", "changes": [{"id": "k1", "value": 0.5}], "at": 12.5})
    assert push == W.Push((W.Change("k1", 0.5),), 12.5)
    assert W.parse_push({"status": "ok"}) is None and W.parse_push("x") is None
    assert W.parse_push({"push": "other", "changes": []}) is None
    assert W.parse_push({"push": "watch", "changes": [{"nope": 1}, {"id": "a", "value": 1}], "at": "bad"}) == W.Push(
        (W.Change("a", 1),), 0.0
    )


# ---- watching, in process -----------------------------------------------------------------------------------------------


def test_a_watched_parameter_is_pushed_when_it_changes_and_not_otherwise(live):
    got = W.watch(live, {"k1": KEY})
    assert got == W.Watching(("k1",), {}) and live.pushes == []
    set_volume(live, 0.4)
    assert len(live.pushes) == 1
    push = W.parse_push(live.pushes[0])
    assert push is not None and push.changes[0].id == "k1" and push.changes[0].value == pytest.approx(0.4)
    set_volume(live, 0.4)  # the same value: Live does not notify
    assert len(live.pushes) == 1


def test_a_burst_of_changes_is_one_push_with_the_latest_value_of_each(live):
    W.watch(live, {"a": KEY, "b": "Hats bus/volume"})
    with live.deferring():
        for v in (0.1, 0.2, 0.3, 0.35):
            set_volume(live, v)
        live.run("result = (find_track('Hats bus').mixer_device.volume.__setattr__('value', 0.6), 'ok')[1]")
        assert live.pushes == []  # nothing goes until Live's next tick
        assert live.run_scheduled() == 1
    assert len(live.pushes) == 1
    values = {c.id: c.value for c in W.parse_push(live.pushes[0]).changes}
    assert values == {"a": pytest.approx(0.35), "b": pytest.approx(0.6)}


def test_a_switch_is_watched_by_its_attribute(live):
    W.watch(live, {"mute": "Kick bus/mute"})
    live.run("result = (setattr(find_track('Kick bus'), 'mute', True), 'ok')[1]")
    assert [c.value for p in live.pushes for c in W.parse_push(p).changes] == [True]


def test_watching_again_replaces_the_old_watches_and_unwatch_stops_them(live):
    W.watch(live, {"a": KEY})
    W.watch(live, {"b": "Hats bus/volume"})
    set_volume(live, 0.3)
    assert live.pushes == []  # the first watch is gone
    live.run("result = (find_track('Hats bus').mixer_device.volume.__setattr__('value', 0.3), 'ok')[1]")
    assert len(live.pushes) == 1
    assert W.unwatch(live) == W.Watching((), {})
    set_volume(live, 0.9)
    assert len(live.pushes) == 1


def test_a_key_the_set_lacks_is_reported_and_the_rest_are_still_watched(live):
    got = W.watch(live, {"ok": KEY, "bad": "Nobody/volume"})
    assert got.ids == ("ok",) and "bad" in got.failed and got.failed["bad"]


def test_a_bad_request_is_an_error_not_a_crash(live):
    reply = live.send({"watch": "k1"})
    assert reply["status"] == "error" and "list of {id, code}" in reply["error"]
    with pytest.raises(LiveError, match="would not watch"):
        W.parse_watching(reply)
    assert live.send({"watch": [{"id": "x", "code": 5}]})["status"] == "error"


def test_a_watch_is_one_call_to_live_and_is_kept_among_the_calls(live):
    before = len(live.calls)
    W.watch(live, {"k1": KEY})
    assert len(live.calls) == before + 1 and live.calls[-1].code == "watch" and live.calls[-1].status == "ok"


# ---- the old protocol, byte for byte ---------------------------------------------------------------------------------------


def old_fake(monkeypatch):
    """A FakeLive running the Remote Script as it was before watch, to compare replies with."""
    monkeypatch.setattr(fakelive_module, "REMOTE_SCRIPT", OLD_SCRIPT)
    return FakeLive(hw002_like())


def test_requests_and_replies_are_what_they_were_before_watch(monkeypatch, live):
    messages = [
        {"ping": True},
        {"id": "cmd-1", "code": "1 + 1"},
        {"id": "cmd-2", "code": "result = [t.name for t in tracks][:3]"},
        {"id": "cmd-3", "code": "raise ValueError('no')"},
        {"id": "cmd-4", "code": "   "},
        {"id": "cmd-5"},
        {"code": "song.tempo"},
        {"code": "undefined_name"},
    ]
    raws = [json.dumps(m).encode() for m in messages] + [b"not json", b"\xff\xfe"]
    with old_fake(monkeypatch) as old:
        expected = [json.dumps(_stable(old._bridge._dispatch(r)), default=str) for r in raws]
    got = [json.dumps(_stable(live._bridge._dispatch(r)), default=str) for r in raws]
    assert got == expected


def _stable(reply):
    """A reply without the parts that differ run to run (seconds taken, the traceback's line numbers)."""
    return {k: v for k, v in reply.items() if k not in ("elapsed", "traceback")}


def test_a_client_that_never_watches_gets_the_same_lines_over_tcp(live):
    port = live.serve()
    client = LiveClient(port=port, keep=True, on_push=lambda m: pytest.fail(f"unasked push {m}"))
    try:
        assert client.run("1 + 1") == 2
        client.run(SET_VOLUME.format(v=0.7))
        assert client.pump(0.05) == 0
    finally:
        client.close()


# ---- over TCP, as the app holds it ----------------------------------------------------------------------------------------------


def test_over_the_socket_a_push_made_by_a_call_comes_before_its_reply_and_the_call_still_answers(live):
    pushes = []
    port = live.serve()
    client = LiveClient(port=port, keep=True, on_push=pushes.append)
    try:
        assert W.watch(client, {"k1": KEY}).ids == ("k1",)
        assert client.run(SET_VOLUME.format(v=0.2)) == "ok"  # the reply is not mistaken for the push
        assert wait_for(lambda: pushes or client.pump(0.1))
        values = [c.value for p in pushes for c in W.parse_push(p).changes]
        assert values == [pytest.approx(0.2)]
        assert client.run("1 + 1") == 2  # ordinary calls are not disturbed
    finally:
        client.close()


def test_a_push_made_by_someone_else_arrives_while_nobody_waits(live):
    pushes = []
    port = live.serve()
    client = LiveClient(port=port, keep=True, on_push=pushes.append)
    try:
        W.watch(client, {"k1": KEY})
        with live.main_thread():
            volume = next(t for t in live.song.tracks if t.name == "Kick bus").mixer_device.volume
            volume.value = 0.33  # as a hand on Live's own screen
        assert client.pump(2.0) == 1
        assert W.parse_push(pushes[0]).changes == (W.Change("k1", pytest.approx(0.33)),)
        assert client.pump(0.05) == 0
    finally:
        client.close()


def test_when_the_client_goes_its_watches_are_taken_off(live):
    port = live.serve()
    client = LiveClient(port=port, keep=True, on_push=lambda m: None)
    W.watch(client, {"k1": KEY})
    assert wait_for(lambda: live._bridge._watches)
    client.close()
    assert wait_for(lambda: not live._bridge._watches)
    with live.main_thread():
        next(t for t in live.song.tracks if t.name == "Kick bus").mixer_device.volume.value = 0.11
    assert live.listener_errors == []


def test_pushes_and_replies_never_interleave_on_the_socket(live):
    pushes, stop = [], threading.Event()
    port = live.serve()
    client = LiveClient(port=port, keep=True, on_push=pushes.append)
    W.watch(client, {"k1": KEY})

    def hand():
        v = 0.0
        while not stop.is_set():
            v = 0.9 if v < 0.5 else 0.1
            with live.main_thread():
                next(t for t in live.song.tracks if t.name == "Kick bus").mixer_device.volume.value = v
            time.sleep(0.001)

    thread = threading.Thread(target=hand, daemon=True)
    thread.start()
    try:
        for i in range(60):
            assert client.run(f"{i} + 1") == i + 1
    finally:
        stop.set()
        thread.join(2)
        client.close()
    assert pushes and all(W.parse_push(p) for p in pushes)


def test_the_client_counts_its_connections_so_a_new_one_means_asking_again(live):
    port = live.serve()
    client = LiveClient(port=port, keep=True, on_push=lambda m: None)
    try:
        client.run("1")
        assert client.connections == 1
        client.close()
        client.run("1")
        assert client.connections == 2
    finally:
        client.close()
