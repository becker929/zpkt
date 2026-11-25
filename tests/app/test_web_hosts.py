"""The desk's port answers only for its own names: localhost, the tailnet proxy's name and names you add. A page
that points its own domain at 127.0.0.1 (DNS rebinding) sends that domain as Host, and is turned away.

And the origin rule as a request arrives through the tailnet proxy (`tailscale serve`): the headers are made up
here to be what the proxy sends; no proxy runs."""

from __future__ import annotations

import http.client
import json
from dataclasses import replace

import pytest

from zpkt.app import web
from zpkt.app.desk import Settings
from zpkt.app.web import cross_site, host_allowed

TAILNET = "studio.tail1234.ts.net"


def ask(rig, method: str, path: str, headers: dict[str, str], body: bytes | None = None) -> tuple[int, bytes]:
    """One request with exactly these headers (http.client adds no Host when one is given)."""
    port = int(rig.url.rsplit(":", 1)[1])
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request(method, path, body=body, headers=headers)
        r = conn.getresponse()
        return r.status, r.read(2000)
    finally:
        conn.close()


def own_host(rig) -> str:
    return rig.url.removeprefix("http://")


# ---- which Host names the desk answers for ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "extra", "expected"),
    [
        ("127.0.0.1:8985", (), True),
        ("127.0.0.1", (), True),
        ("localhost:8985", (), True),
        ("LOCALHOST:8985", (), True),
        ("[::1]:8985", (), True),
        ("[::1]", (), True),
        (TAILNET, (), True),  # tailscale serve on 443
        (f"{TAILNET}:8985", (), True),  # tailscale serve --https=8985
        ("Studio.Tail1234.TS.net", (), True),
        ("evil.example", (), False),
        ("evil.example:8985", (), False),
        ("ts.net.evil.example", (), False),
        ("evil-ts.net", (), False),  # not a name under ts.net
        ("127.0.0.1.evil.example", (), False),
        ("localhost.evil.example:8985", (), False),
        ("", (), False),
        (None, (), False),
        ("studio:8985", (), False),
        ("studio:8985", ("studio",), True),  # a name you add (ZPKT_APP_HOSTS)
        ("desk.example.org", ("studio", "Desk.Example.org"), True),
        ("127.0.0.1:8985:1", (), False),
        ("a b", (), False),
    ],
)
def test_host_allowed(host, extra, expected):
    assert host_allowed(host, extra) is expected


def test_the_settings_read_extra_names_from_the_environment(monkeypatch):
    monkeypatch.setenv("ZPKT_APP_HOSTS", "studio, desk.example.org ,")
    assert web.hosts_from_env() == ("studio", "desk.example.org")
    monkeypatch.delenv("ZPKT_APP_HOSTS")
    assert web.hosts_from_env() == ()
    assert Settings.__dataclass_fields__["hosts"].default == ()


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/"),
        ("GET", "/app/"),
        ("GET", "/api/state"),
        ("GET", "/events"),
        ("HEAD", "/app/song/"),
        ("POST", "/api/command"),
        ("POST", "/api/agent/command"),
        ("POST", "/api/undo"),
        ("PUT", "/app/ask/api/sessions/x"),
        ("PATCH", "/app/ask/api/sessions/x"),
        ("DELETE", "/app/ask/api/sessions/x"),
    ],
)
def test_a_rebound_name_is_turned_away_whatever_it_asks(rig, method, path):
    """The attacker's page is same-origin with its own name, so Origin and Host agree: only the Host check stops
    it. Reads count too: the state and the event stream are what it would read."""
    port = own_host(rig).rsplit(":", 1)[1]
    headers = {"Host": f"evil.example:{port}", "Origin": f"http://evil.example:{port}"}
    before = len(rig.desk.bus.log)
    code, body = ask(rig, method, path, headers, b"{}" if method != "GET" and method != "HEAD" else None)
    assert code == 403, (method, path)
    if method != "HEAD":
        assert "answers for its own names" in json.loads(body)["error"]
    assert len(rig.desk.bus.log) == before


def test_a_request_with_no_host_is_turned_away(rig):
    port = int(own_host(rig).rsplit(":", 1)[1])
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.putrequest("GET", "/api/state", skip_host=True)
    conn.endheaders()
    assert conn.getresponse().status == 403
    conn.close()


def test_its_own_names_still_get_the_pages_and_the_state(rig):
    port = own_host(rig).rsplit(":", 1)[1]
    for host in (own_host(rig), f"localhost:{port}", TAILNET, f"{TAILNET}:{port}"):
        assert ask(rig, "GET", "/api/state", {"Host": host})[0] == 200, host
        assert ask(rig, "GET", "/app/", {"Host": host})[0] == 200, host
    assert rig.get("/api/state")[0] == 200  # what every other test sends


def test_a_name_from_the_settings_is_answered(rig):
    assert ask(rig, "GET", "/api/state", {"Host": "studio:8985"})[0] == 403
    rig.desk.settings = replace(rig.desk.settings, hosts=("studio",))
    assert ask(rig, "GET", "/api/state", {"Host": "studio:8985"})[0] == 200


# ---- the origin rule behind the tailnet proxy ------------------------------------------------------------------------


def through_proxy(origin: str | None, host: str = TAILNET, **more: str) -> dict[str, str]:
    """The headers of a request as `tailscale serve` hands it on: the Host the phone asked for, who it is for and
    from, and the browser's own Origin."""
    headers = {
        "Host": host,
        "X-Forwarded-For": "100.101.102.103",
        "X-Forwarded-Proto": "https",
        "X-Forwarded-Host": host,
        "Tailscale-User-Login": "someone@example.com",
        "Content-Type": "application/json",
        **more,
    }
    if origin is not None:
        headers["Origin"] = origin
    return headers


PIN = json.dumps({"kind": "history.checkpoint", "args": {"name": "from-the-phone"}}).encode()


def test_a_write_from_the_desks_own_page_on_the_phone_gets_through_the_proxy(rig):
    code, body = ask(rig, "POST", "/api/command", through_proxy(f"https://{TAILNET}"), PIN)
    assert code == 200 and json.loads(body)["ok"]
    assert rig.desk.bus.log[-1]["kind"] == "history.checkpoint" and rig.desk.bus.log[-1]["who"] == "you"


def test_the_proxy_on_its_own_port_gets_through_too(rig):
    host = f"{TAILNET}:8985"
    assert ask(rig, "POST", "/api/command", through_proxy(f"https://{host}", host), PIN)[0] == 200
    assert ask(rig, "POST", "/api/command", through_proxy(f"https://{TAILNET}:443"), PIN)[0] == 200  # 443 said aloud


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "null",
        f"https://{TAILNET}:8975",  # another of the tailnet's sites on this Mac (the arranger)
        f"http://{TAILNET}",  # not the https page
        "https://other.tail1234.ts.net",  # another machine of the tailnet
        "https://studio.tail9999.ts.net",
        "http://127.0.0.1:8985",
    ],
)
def test_a_write_from_another_site_is_refused_behind_the_proxy(rig, origin):
    before = len(rig.desk.bus.log)
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        code, body = ask(rig, method, "/api/command", through_proxy(origin), PIN)
        assert code == 403 and "its own pages only" in json.loads(body)["error"], (method, origin)
    assert len(rig.desk.bus.log) == before


def test_a_proxy_that_rewrites_host_is_judged_by_the_forwarded_host(rig):
    """Should the proxy hand on Host: 127.0.0.1:8985 and the asked name only as X-Forwarded-Host, the page's Origin
    is compared with that name."""
    local = own_host(rig)
    ok = through_proxy(f"https://{TAILNET}", local, **{"X-Forwarded-Host": TAILNET})
    assert ask(rig, "POST", "/api/command", ok, PIN)[0] == 200
    other = through_proxy("https://evil.example", local, **{"X-Forwarded-Host": TAILNET})
    assert ask(rig, "POST", "/api/command", other, PIN)[0] == 403
    lying = through_proxy("https://evil.example", local, **{"X-Forwarded-Host": "evil.example"})
    assert ask(rig, "POST", "/api/command", lying, PIN)[0] == 403  # a forwarded name the desk does not answer for


def test_reads_and_the_event_stream_come_through_the_proxy(rig):
    assert ask(rig, "GET", "/api/state", through_proxy(None))[0] == 200
    assert ask(rig, "GET", "/app/", through_proxy(None))[0] == 200
    port = int(own_host(rig).rsplit(":", 1)[1])
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/events?app=1", headers=through_proxy(None))
    r = conn.getresponse()
    assert r.status == 200 and r.getheader("Content-Type") == "text/event-stream"
    assert r.readline().startswith(b"data: ")
    conn.close()


@pytest.mark.parametrize(
    ("origin", "host", "forwarded_host", "proto", "expected"),
    [
        (f"https://{TAILNET}", TAILNET, TAILNET, "https", False),
        (f"https://{TAILNET}:443", TAILNET, TAILNET, "https", False),
        (f"https://{TAILNET}", f"{TAILNET}:443", None, "https", False),
        (f"https://{TAILNET}:8985", f"{TAILNET}:8985", None, "https", False),
        (f"https://{TAILNET}", f"{TAILNET}:8985", None, "https", True),
        (f"https://{TAILNET}:8975", TAILNET, TAILNET, "https", True),
        (f"http://{TAILNET}", TAILNET, TAILNET, "https", True),
        (f"https://{TAILNET}", "127.0.0.1:8985", TAILNET, "https", False),
        ("https://evil.example", "127.0.0.1:8985", TAILNET, "https", True),
        ("http://127.0.0.1:8985", "127.0.0.1:8985", None, None, False),
        ("http://localhost:8985", "127.0.0.1:8985", None, None, True),
    ],
)
def test_cross_site_with_what_the_proxy_forwards(origin, host, forwarded_host, proto, expected):
    assert cross_site(origin, host, forwarded_host, proto) is expected
