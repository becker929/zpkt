"""server.py's UDP thread and what it queues for the page: offline, on a free port, never the running desk's 8986.

    hands/.venv/bin/python -m pytest contrib/mixdesk/tests
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import history  # noqa: E402
import server  # noqa: E402


def free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_for(check, seconds: float = 2.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if check():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture()
def udp_server(tmp_path, monkeypatch):
    """server.udp() on a free port, with a history in tmp_path; yields a function that sends one datagram."""
    port = free_udp_port()
    monkeypatch.setattr(server, "UDP_PORT", port)
    monkeypatch.setattr(server, "HIST", history.History("SET", server.LABELS, directory=tmp_path / "hist"))
    monkeypatch.setattr(server.history.S, "folder", lambda set_name: tmp_path / "state" / set_name)
    threading.Thread(target=server.udp, daemon=True).start()
    out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    time.sleep(0.05)  # the thread binds its socket
    yield lambda data: out.sendto(data if isinstance(data, bytes) else json.dumps(data).encode(), ("127.0.0.1", port))
    out.close()


def test_a_bad_datagram_is_dropped_and_the_udp_thread_keeps_serving(udp_server):
    for bad in (b"[1, 2]", b'"text"', b"{}", b'{"t": "pos"}', b'{"t": "v", "n": 0.5}', b"not json"):
        udp_server(bad)
    udp_server({"t": "pos", "b": 12.5, "p": True})
    assert wait_for(lambda: server.STATE["pos"] == 12.5 and server.STATE["playing"] is True)


def test_a_queued_full_state_does_not_change_when_a_later_datagram_arrives(udp_server):
    q: server.queue.Queue = server.queue.Queue()
    server.CLIENTS.append(q)
    try:
        with server.LOCK:
            server.STATE["pos"] = 0.0
        server.set_state(None, "attached")
        udp_server({"t": "pos", "b": 32.0, "p": False})
        assert wait_for(lambda: server.STATE["pos"] == 32.0)
        queued = q.get_nowait()
        assert queued["t"] == "full" and queued["state"]["pos"] == 0.0
        assert queued["state"] is not server.STATE
    finally:
        server.CLIENTS.remove(q)
