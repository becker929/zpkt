"""The MCP bridge forwards arbitrary Python to Live; it must not be open.

It used to bind 0.0.0.0 with no authentication, so anyone on the network
could run code on the Mac through Live. Pins: loopback bind, bearer token,
DNS-rebinding host checks, and a refusal to start without a token.
"""
from __future__ import annotations

import pytest

pytest.importorskip("mcp.server.fastmcp")
pytest.importorskip("starlette")
from starlette.testclient import TestClient  # noqa: E402

from hands import mcp_server  # noqa: E402

TOKEN = "t0ken"
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                   "clientInfo": {"name": "test", "version": "0"}}}
ACCEPT = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture(autouse=True)
def fresh_session_manager():
    # A session manager can only run once; each TestClient starts the app anew.
    mcp_server.mcp._session_manager = None
    yield
    mcp_server.mcp._session_manager = None


def _client():
    return TestClient(mcp_server.build_app(TOKEN), base_url="http://127.0.0.1:9010")


def test_binds_loopback_by_default() -> None:
    assert mcp_server.mcp.settings.host == "127.0.0.1"


def test_rejects_missing_or_wrong_token() -> None:
    with _client() as c:
        assert c.post("/mcp", json=INIT, headers=ACCEPT).status_code == 401
        bad = {**ACCEPT, "Authorization": "Bearer nope"}
        assert c.post("/mcp", json=INIT, headers=bad).status_code == 401


def test_rejects_foreign_host_even_with_token() -> None:
    with TestClient(mcp_server.build_app(TOKEN), base_url="http://evil.example:9010") as c:
        r = c.post("/mcp", json=INIT, headers={**ACCEPT, "Authorization": f"Bearer {TOKEN}"})
        assert r.status_code in (403, 421)


def test_accepts_token_from_docker_host() -> None:
    with TestClient(mcp_server.build_app(TOKEN), base_url="http://host.docker.internal:9010") as c:
        r = c.post("/mcp", json=INIT, headers={**ACCEPT, "Authorization": f"Bearer {TOKEN}"})
        assert r.status_code == 200


def test_refuses_to_start_without_token(monkeypatch) -> None:
    monkeypatch.delenv("MCP_BRIDGE_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="MCP_BRIDGE_TOKEN"):
        mcp_server.serve()
