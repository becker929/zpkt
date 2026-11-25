"""The old desk's whole surface, pinned before the server moved into zpkt.app: routes, pages, ports, event shapes.

If one of these has to change, a capability changed: stop and say so.
"""

from __future__ import annotations

import json
import urllib.request

import server


def test_the_routes_and_pages_are_the_ones_the_old_desk_had():
    assert sorted(server.POST_ROUTES) == [
        "/api/checkpoint",
        "/api/monitor",
        "/api/page",
        "/api/redo",
        "/api/restart",
        "/api/revert",
        "/api/surface/make",
        "/api/surface/remove",
        "/api/surface/save",
        "/api/toggle",
        "/api/transport",
        "/api/undo",
    ]
    assert sorted(server.GET_ROUTES) == [
        "/api/analysis",
        "/api/checkpoint",
        "/api/compare",
        "/api/desk",
        "/api/history",
        "/api/state",
    ]
    assert sorted(server.PAGES) == ["/desk", "/desk/", "/index.html"]
    assert sorted(server.Handler.STREAMS) == ["/events"]


def test_the_default_ports_are_8985_8986_8987(monkeypatch):
    monkeypatch.delenv("MIXDESK_PORT", raising=False)
    settings = server.Settings.from_env()
    assert (settings.http_port, settings.udp_port, settings.meter_port) == (8985, 8986, 8987)


def test_the_event_stream_starts_with_a_full_state_and_the_history_has_its_shape(rig):
    with urllib.request.urlopen(rig.url + "/events", timeout=10) as r:
        assert r.headers["Content-Type"] == "text/event-stream"
        first = r.readline().decode()
    msg = json.loads(first.removeprefix("data: "))
    assert msg["t"] == "full"
    assert {"page", "values", "monitor", "match", "pos", "playing", "loop", "live", "gains"} <= set(msg["state"])
    view = rig.get("/api/history")[1]
    assert {"t", "entries", "pos", "can_undo", "can_redo", "checkpoints"} == set(view)


def test_the_meter_message_is_db_per_band():
    hz = [20.0, 25.2]
    assert server.meter_message([1.0, 0.1], hz) == {"t": "meter", "hz": hz, "db": [0.0, -20.0]}
    assert server.meter_message([0.0, 1e-9], hz) == {"t": "meter", "hz": hz, "db": [-140.0, -140.0]}
    assert server.meter_message([1.0], hz) is None
