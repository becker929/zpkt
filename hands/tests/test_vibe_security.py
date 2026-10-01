"""The vibe server must not be a remote shell.

It once had an unauthenticated POST /shell, listened on every interface and
sent CORS "*", so any web page the user visited could run commands on the
Mac. These tests pin the fixes against the real handler on a loopback port.
"""
from __future__ import annotations

import inspect
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from hands.vibe import server as vibe


@pytest.fixture()
def base_url(tmp_path, monkeypatch):
    restarts: list[int] = []
    monkeypatch.setattr(vibe.VibeServer, "handle_restart", lambda self: restarts.append(1) or {"status": "restarting"})
    srv = vibe.VibeServer(output_dir=str(tmp_path))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv._make_handler())
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", restarts
    httpd.shutdown()


def _post(url: str, headers: dict | None = None) -> tuple[int, dict, dict]:
    req = urllib.request.Request(url, data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read()), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read()), dict(e.headers)


def test_shell_endpoint_is_gone(base_url) -> None:
    url, _ = base_url
    status, body, _ = _post(url + "/shell")
    assert status == 404
    assert not hasattr(vibe.VibeServer, "handle_shell")


def test_restart_refused_without_token(base_url, monkeypatch) -> None:
    url, restarts = base_url
    monkeypatch.delenv("VIBE_TOKEN", raising=False)
    assert _post(url + "/restart")[0] == 403
    monkeypatch.setenv("VIBE_TOKEN", "s3cret")
    assert _post(url + "/restart", {"Authorization": "Bearer wrong"})[0] == 403
    assert restarts == []


def test_restart_allowed_with_token(base_url, monkeypatch) -> None:
    url, restarts = base_url
    monkeypatch.setenv("VIBE_TOKEN", "s3cret")
    assert _post(url + "/restart", {"Authorization": "Bearer s3cret"})[0] == 200
    assert restarts == [1]


def test_self_improve_refused_without_token(base_url, monkeypatch) -> None:
    url, _ = base_url
    monkeypatch.delenv("VIBE_TOKEN", raising=False)
    assert _post(url + "/self-improve")[0] == 403


def test_cors_is_not_wildcard(base_url) -> None:
    url, _ = base_url
    _, _, headers = _post(url + "/feedback")
    assert headers.get("Access-Control-Allow-Origin") != "*"


def test_binds_loopback_by_default() -> None:
    default = inspect.signature(vibe.VibeServer.serve).parameters["host"].default
    assert default == "127.0.0.1"


def _raw(url: str, method: str = "POST", headers: dict | None = None, data: bytes = b"{}") -> int:
    req = urllib.request.Request(url, data=data if method != "GET" else None, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_rejects_rebinding_host(base_url) -> None:
    url, _ = base_url
    assert _raw(url + "/session", "GET", {"Host": "evil.example"}) == 403


def test_rejects_foreign_origin(base_url) -> None:
    url, _ = base_url
    h = {"Content-Type": "application/json", "Origin": "https://evil.example"}
    assert _raw(url + "/feedback", headers=h) == 403


def test_rejects_cross_site_simple_post(base_url) -> None:
    """text/plain POSTs skip CORS preflight, so a web page could send them."""
    url, _ = base_url
    assert _raw(url + "/feedback", headers={"Content-Type": "text/plain"}) == 415


def test_tunnel_mode_requires_token_everywhere(base_url, monkeypatch) -> None:
    url, _ = base_url
    monkeypatch.setenv("VIBE_TUNNEL", "1")
    monkeypatch.setenv("VIBE_TOKEN", "s3cret")
    assert _raw(url + "/session", "GET") == 403
    assert _raw(url + "/session", "GET", {"Authorization": "Bearer s3cret"}) == 200
