"""Shared test setup: the arranger's folder on sys.path, a temporary data folder, and the server on a free port."""

from __future__ import annotations

import http.client
import json
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parents[1]
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # no system proxy lookup: fast and local
sys.path.insert(0, str(HERE))


@dataclass
class Reply:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body)


@dataclass
class Running:
    url: str
    data: Path
    worker_starts: list[int] = field(default_factory=list)

    def call(self, method: str, path: str, body: bytes | str | dict | list | None = None) -> Reply:
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        if isinstance(body, str):
            body = body.encode()
        req = urllib.request.Request(self.url + path, data=body, method=method)
        try:
            with OPENER.open(req, timeout=10) as r:
                return Reply(r.status, dict(r.headers), r.read())
        except urllib.error.HTTPError as e:
            return Reply(e.code, dict(e.headers), e.read())

    def claim_length(self, method: str, path: str, length: int) -> Reply:
        """Send only headers that claim a body of `length` bytes: what the server does before reading one."""
        host, port = self.url.removeprefix("http://").split(":")
        conn = http.client.HTTPConnection(host, int(port), timeout=10)
        conn.putrequest(method, path)
        conn.putheader("Content-Length", str(length))
        conn.endheaders()
        r = conn.getresponse()
        reply = Reply(r.status, dict(r.getheaders()), r.read())
        conn.close()
        return reply


@pytest.fixture
def server(tmp_path: Path):
    import server as arranger_server

    data = tmp_path / "arranger"
    data.mkdir()
    running = Running("", data)
    httpd = arranger_server.make_server(data, port=0, start_worker=lambda: running.worker_starts.append(1))
    running.url = f"http://127.0.0.1:{httpd.server_address[1]}"
    t = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    t.start()
    yield running
    httpd.shutdown()
    httpd.server_close()
