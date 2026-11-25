"""The app's connections: one lock over Live, the meter's socket handed in, and no ports in the tests."""

from __future__ import annotations

import threading
import time

import pytest

from tests.app.conftest import FakeMeter, free_port, osc_spec
from zpkt.app.connections import LiveConnections, MeterSocket, open_connections
from zpkt.live import state as S
from zpkt.live.testing import FakeLive, hw002_like


def test_connections_are_a_transport_so_zpkt_live_takes_them():
    with FakeLive(hw002_like()) as live:
        conn = LiveConnections(live)
        mix = S.take(conn)
        assert "Main" in mix["tracks"] and len(live.calls) >= 1


def test_calls_from_two_threads_never_overlap():
    class Slow:
        def __init__(self):
            self.inside = 0
            self.most = 0

        def execute(self, code):
            raise NotImplementedError

        def run(self, code):
            self.inside += 1
            self.most = max(self.most, self.inside)
            time.sleep(0.01)
            self.inside -= 1
            return "ok"

    slow = Slow()
    conn = LiveConnections(slow)  # type: ignore[arg-type]
    threads = [threading.Thread(target=lambda: [conn.run("1") for _ in range(5)]) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert slow.most == 1


def test_exclusive_holds_live_across_calls():
    with FakeLive(hw002_like()) as live:
        conn = LiveConnections(live)
        got = []

        def other():
            got.append(conn.run("result = 1"))

        with conn.exclusive():
            t = threading.Thread(target=other)
            t.start()
            time.sleep(0.05)
            assert got == []  # the other thread waits
        t.join(5)
        assert got == [1]


def test_the_meter_is_read_from_the_handed_in_socket():
    meter = FakeMeter()
    conn = LiveConnections(FakeLive(hw002_like()), meter)
    meter.send(osc_spec([0.5, 0.25]))
    meter.send(b"not osc")
    assert conn.read_meter() == [0.5, 0.25]
    assert conn.read_meter() is None


def test_no_meter_is_a_clear_error():
    with pytest.raises(RuntimeError, match="no meter socket"):
        LiveConnections(FakeLive(hw002_like())).read_meter()


def test_the_real_meter_socket_binds_when_first_read_and_not_before():
    import socket

    port = free_port(socket.SOCK_DGRAM)
    conn = open_connections(live_port=9, meter_port=port)
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", port))  # still free: nothing bound it yet
    probe.close()
    assert isinstance(conn.meter, MeterSocket) and conn.meter.fileno() == 0
    conn.close()
    assert conn.meter.fileno() == -1
    with pytest.raises(OSError, match="closed"):
        conn.meter.recvfrom(10)
