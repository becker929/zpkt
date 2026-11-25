"""The server's UDP side: bad datagrams are dropped, and what is queued for the page is a copy (conftest.py's rig)."""

from __future__ import annotations

import queue

from conftest import wait_for


def test_a_bad_datagram_is_dropped_and_the_udp_thread_keeps_serving(rig):
    for bad in (b"[1, 2]", b'"text"', b"{}", b'{"t": "pos"}', b'{"t": "v", "n": 0.5}', b"not json"):
        rig.send(bad)
    rig.send({"t": "pos", "b": 12.5, "p": True})
    assert wait_for(lambda: (st := rig.state())["pos"] == 12.5 and st["playing"] is True)


def test_a_queued_full_state_does_not_change_when_a_later_datagram_arrives(rig):
    q: queue.Queue = queue.Queue()
    rig.desk.clients.append(q)
    try:
        rig.desk.set_state(None, "attached")
        rig.send({"t": "pos", "b": 32.0, "p": False})
        assert wait_for(lambda: rig.state()["pos"] == 32.0)
        queued = next(m for m in iter(q.get_nowait, None) if m["t"] == "full")
        assert queued["state"]["pos"] == 0.0
    finally:
        rig.desk.clients.remove(q)


def test_a_moved_value_enters_the_history_with_who_moved_it(rig):
    value = rig.state()["values"]["0:f1"]
    move = {"t": "v", "page": 0, "slot": "f1", "n": 0.1, "s": "-30 dB", "key": value["key"]}
    rig.send({**move, "r": 0.11, "sys": True})  # the desk's own move (a monitor switch): no entry
    rig.send({**move, "r": 0.12, "who": "minilab"})
    assert wait_for(lambda: len(rig.desk.history.entries) == 1)
    assert rig.desk.history.entries[0]["who"] == "minilab"
    assert rig.desk.history.entries[0]["moves"][0]["to"] == ["-30 dB", 0.12]
