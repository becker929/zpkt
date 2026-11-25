"""The two bugs the audit found, fixed: a shared dict used without a lock, and a UDP thread that dies on a message."""

from __future__ import annotations

import threading

from tests.app.conftest import osc_spec, wait_for
from zpkt.app import history as H


def test_a_datagram_that_fails_inside_does_not_end_the_udp_thread(rig, monkeypatch, capsys):
    real = rig.desk.history.seen
    calls = []

    def breaks_once(*args, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("disk full")
        return real(*args, **kw)

    monkeypatch.setattr(rig.desk.history, "seen", breaks_once)
    value = rig.state()["values"]["0:f1"]
    move = {"t": "v", "page": 0, "slot": "f1", "n": 0.1, "s": "-30 dB", "key": value["key"]}
    rig.send({**move, "r": 0.11})  # this one hits the failure
    assert wait_for(lambda: "disk full" in capsys.readouterr().out)
    rig.send({"t": "pos", "b": 7.5, "p": True})
    assert wait_for(lambda: rig.state()["pos"] == 7.5)  # the thread is still serving


def test_the_meter_thread_survives_garbage_and_reports_db(rig):
    got: list[dict] = []
    rig.desk.clients.append(q := __import__("queue").Queue())
    rig.meter.send(b"garbage")
    rig.meter.send(osc_spec([0.5] * 5))  # wrong band count: dropped, not fatal
    rig.meter.send(osc_spec([1.0] + [0.1] * 30))
    import threading

    threading.Thread(target=rig.desk.serve_meter, daemon=True).start()
    assert wait_for(lambda: any(m["t"] == "meter" for m in list(q.queue)))
    msg = next(m for m in list(q.queue) if m["t"] == "meter")
    assert len(msg["hz"]) == 31 and msg["db"][:2] == [0.0, -20.0]
    assert rig.desk.monitor.last_meter == msg
    got.append(msg)


def test_a_closed_pager_socket_ends_the_udp_thread_quietly():
    import socket

    from zpkt.app.desk import Desk

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.close()
    desk = Desk.__new__(Desk)  # serve_udp needs only the socket and receive
    done = threading.Thread(target=desk.serve_udp, args=(sock,), daemon=True)
    done.start()
    done.join(2)
    assert not done.is_alive()


def test_the_label_table_is_filled_under_the_historys_lock(tmp_path):
    labels: dict[str, str] = {}
    h = H.History("S", labels, tmp_path / "h", tmp_path / "cp", clock=lambda: 1.0)
    errors: list[Exception] = []

    def teach(i: int) -> None:
        try:
            for j in range(300):
                h.add_labels({f"k{i}-{j}": "x"})
                h.view()
        except Exception as exc:  # a dict that changed size during iteration
            errors.append(exc)

    threads = [threading.Thread(target=teach, args=(i,)) for i in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == [] and len(labels) == 1200
    h.add_labels({"k0-0": "other"})
    assert labels["k0-0"] == "x"  # the first name stays
