"""The app's page watcher: it registers a page's keys with Live and gets Live's changes as pushes (FakeLive only)."""

from __future__ import annotations

import threading

import pytest

from tests.app.conftest import FakeMeter, wait_for
from zpkt.app.connections import LiveConnections
from zpkt.app.watching import PageWatcher
from zpkt.live.testing import FakeLive, hw002_like
from zpkt.live.transport import LiveClient

KICK, HATS = "Kick bus/volume", "Hats bus/volume"


def set_volume(live, track, value):
    with live.main_thread():
        next(t for t in live.song.tracks if t.name == track).mixer_device.volume.value = value


def test_in_process_a_changed_value_reaches_the_callback_with_its_key_and_raw_value():
    live, seen = FakeLive(hw002_like()), []
    with live:
        watcher = PageWatcher(LiveConnections(live, FakeMeter()), lambda key, raw: seen.append((key, raw)))
        assert watcher.watch([KICK, HATS]).ids == (HATS, KICK)
        set_volume(live, "Kick bus", 0.3)
        assert seen == [(KICK, pytest.approx(0.3))]
        watcher.watch([HATS])  # the next page: the kick is no longer watched
        set_volume(live, "Kick bus", 0.6)
        assert len(seen) == 1
        watcher.watch([])
        set_volume(live, "Hats bus", 0.2)
        assert len(seen) == 1


def test_a_key_live_cannot_watch_is_kept_with_its_reason():
    with FakeLive(hw002_like()) as live:
        watcher = PageWatcher(LiveConnections(live, FakeMeter()), lambda k, v: None)
        watcher.watch([KICK, "Nobody/volume"])
        assert list(watcher.failed) == ["Nobody/volume"]


def test_over_the_socket_the_watcher_serves_pushes_from_its_own_thread_and_asks_again_after_a_reconnect():
    seen = []
    with FakeLive(hw002_like()) as live:
        port = live.serve()
        client = LiveClient(port=port, keep=True, retries=0)
        conn = LiveConnections(client, FakeMeter(), closers=(client,))
        watcher = PageWatcher(conn, lambda key, raw: seen.append((key, raw)))
        stop = threading.Event()
        thread = threading.Thread(target=watcher.serve, args=(stop,), daemon=True)
        try:
            watcher.watch([KICK])
            thread.start()
            set_volume(live, "Kick bus", 0.25)
            assert wait_for(lambda: seen) and seen[0] == (KICK, pytest.approx(0.25))
            assert conn.run("1 + 1") == 2  # a call while the thread listens
            with conn.exclusive():
                client.close()  # the connection drops: Live's side forgets the watch
            assert conn.run("1 + 1") == 2  # a new connection
            assert wait_for(lambda: conn.connections == 2 and watcher._made == 2)  # the thread asked again
            seen.clear()
            set_volume(live, "Kick bus", 0.75)
            assert wait_for(lambda: seen) and seen[-1] == (KICK, pytest.approx(0.75))
        finally:
            stop.set()
            thread.join(2)
            client.close()


def test_a_stray_push_line_is_ignored():
    seen = []
    with FakeLive(hw002_like()) as live:
        conn = LiveConnections(live, FakeMeter())
        PageWatcher(conn, lambda k, v: seen.append(k))
        live.on_push({"push": "other"})
        live.on_push({"hello": 1})
    assert seen == []


def test_a_transport_without_pushes_pumps_nothing():
    class Plain:
        def execute(self, code):
            raise AssertionError("no call expected")

        def run(self, code):
            raise AssertionError("no call expected")

    conn = LiveConnections(Plain())
    assert conn.pump_pushes(0.0) == 0 and conn.connections == 0
    conn.on_push(lambda m: None)  # ignored, not an error


def test_the_real_connections_hold_one_connection_for_pushes_only_when_asked():
    from zpkt.app.connections import open_connections

    plain, pushing = open_connections(9, None), open_connections(9, None, pushes=True)
    assert plain.live.keep is False and plain.live.on_push is None  # type: ignore[attr-defined]
    assert pushing.live.keep is True and pushing.live.on_push is not None  # type: ignore[attr-defined]
    assert plain.live._sock is None and pushing.live._sock is None  # type: ignore[attr-defined]  # nothing opened yet
