"""LiveClient against a fake Remote Script on a free loopback port (never Live's own 16619)."""
from __future__ import annotations

import json
import socket
import socketserver
import threading

import pytest
from typer.testing import CliRunner

from hands.cli import app
from hands.live import transport as T
from hands.live.transport import UNREACHABLE, LiveClient, LiveError, McpResult, MockTransport

HANG = object()  # answer: read the request, never reply


class FakeRemoteScript:
    """Speaks the AbletonLiveMCP protocol; `answer(message)` gives each reply (None: hang up)."""

    def __init__(self, answer):
        self.answer, self.seen, self.release = answer, [], threading.Event()
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                for line in self.rfile:
                    message = json.loads(line)
                    outer.seen.append(message)
                    reply = outer.answer(message)
                    if reply is HANG:
                        outer.release.wait(5)
                        return
                    if reply is None:
                        return
                    self.wfile.write(json.dumps(reply).encode() + b"\n")

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, args=(0.05,), daemon=True).start()

    def client(self, **kw) -> LiveClient:
        return LiveClient("127.0.0.1", self.port, **{"timeout": 2.0, "backoff": 0.0, **kw})

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def remote():
    servers = []

    def start(answer):
        servers.append(FakeRemoteScript(answer))
        return servers[-1]
    yield start
    for s in servers:
        s.close()


def test_ok_reply_keeps_result_and_elapsed(remote):
    live = remote(lambda m: {"status": "ok", "result": {"tempo": 160.0}, "elapsed": 0.004})
    client = live.client()
    res = client.execute("result = {'tempo': song.tempo}")
    assert (res.status, res.result, res.elapsed) == ("ok", {"tempo": 160.0}, 0.004)
    assert client.run("song.tempo") == {"tempo": 160.0}
    assert [m["id"] for m in live.seen] == ["cmd-1", "cmd-2"]
    assert live.seen[0]["code"] == "result = {'tempo': song.tempo}"


def test_error_reply_keeps_traceback_and_warning(remote):
    live = remote(lambda m: {"status": "error", "error": "boom", "traceback": "Traceback ...",
                             "warning": "Multi-line code may have partially executed."})
    res = live.client().execute("a = 1\nraise ValueError('boom')")
    assert (res.status, res.error, res.traceback) == ("error", "boom", "Traceback ...")
    with pytest.raises(LiveError, match=r"boom \(Multi-line code may have partially executed\.\) \[in 'a = 1'\]") as exc:
        live.client().run("a = 1\nraise ValueError('boom')")
    assert exc.value.result.traceback == "Traceback ..."


def test_loading_hint_becomes_the_warning(remote):
    live = remote(lambda m: {"status": "error", "error": "Scope unavailable: x", "hint": "Ableton may still be loading."})
    assert live.client().execute("song.tempo").warning == "Ableton may still be loading."


def test_ping(remote):
    live = remote(lambda m: {"status": "ok", "pong": True} if m.get("ping") else {"status": "error"})
    assert live.client().ping() >= 0.0
    assert live.seen == [{"ping": True}]
    silent = remote(lambda m: {"status": "ok"})
    with pytest.raises(LiveError, match="no pong"):
        silent.client().ping()


def test_unreachable_retries_the_connection_only(monkeypatch):
    attempts = []

    def refuse(address, timeout):
        attempts.append(address)
        raise ConnectionRefusedError("refused")
    monkeypatch.setattr(T.socket, "create_connection", refuse)
    client = LiveClient("127.0.0.1", 9, retries=2, backoff=0.0)
    res = client.execute("song.tempo")
    assert res.status == "error" and res.error.startswith(f"{UNREACHABLE}: refused")
    assert len(attempts) == 3
    with pytest.raises(LiveError, match=UNREACHABLE):
        client.run("song.tempo")


def test_a_failed_connect_is_retried_until_it_works(remote, monkeypatch):
    live = remote(lambda m: {"status": "ok", "result": 2})
    real, calls = socket.create_connection, []

    def flaky(address, timeout):
        calls.append(address)
        if len(calls) == 1:
            raise TimeoutError("timed out")
        return real(address, timeout)
    monkeypatch.setattr(T.socket, "create_connection", flaky)
    assert live.client(retries=1).run("1 + 1") == 2
    assert len(calls) == 2 and len(live.seen) == 1


def test_a_sent_request_is_never_resent(remote):
    live = remote(lambda m: None)
    res = live.client(retries=2).execute("song.create_audio_track(-1)")
    assert res.status == "error" and "without a reply" in res.error
    assert len(live.seen) == 1


def test_no_reply_in_time_says_the_code_may_still_run(remote):
    live = remote(lambda m: HANG)
    res = live.client(timeout=0.2, retries=2).execute("song.tempo = 140")
    assert res.error == f"{UNREACHABLE}: no reply in 0.2 s; the code may still run"
    assert len(live.seen) == 1


def test_mock_transport_runs_and_raises():
    mock = MockTransport([McpResult(status="ok", result=3), McpResult(status="error", error="nope")])
    assert mock.run("1 + 2") == 3
    with pytest.raises(LiveError, match="nope"):
        mock.run("x")
    assert mock.calls == ["1 + 2", "x"]


def test_cli_exec_and_ping(remote):
    live = remote(lambda m: {"status": "ok", "pong": True} if m.get("ping")
                  else {"status": "ok", "result": [1, 2]} if m["code"] == "[1, 2]"
                  else {"status": "error", "error": "NameError", "traceback": "tb"})
    port = ["--port", str(live.port)]
    out = CliRunner().invoke(app, ["live", "exec", "--json", "[1, 2]", *port])
    assert out.exit_code == 0 and out.stdout.strip() == "[1, 2]"
    bad = CliRunner().invoke(app, ["live", "exec", "nope", *port])
    assert bad.exit_code == 1 and "ERROR: NameError" in bad.stderr
    pong = CliRunner().invoke(app, ["live", "ping", *port])
    assert pong.exit_code == 0 and pong.stdout.startswith("pong in")
