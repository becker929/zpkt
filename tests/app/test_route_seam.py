"""One seam puts an adapter's pages on the web server: the mount table. Ask and the Song both use it, and a new
adapter's routes need no change to the server."""

from __future__ import annotations

import http.client
import json

from zpkt.app import web
from zpkt.app.mounts import MountReply, Request

from .test_song import song_rig  # noqa: F401  (the Song adapter on the rig)


class Notes:
    """A made-up adapter's routes: it answers with what it was asked, and streams on /stream."""

    def handle(self, request: Request) -> MountReply | None:
        if request.rest == "/stream":  # a mount that answers as it goes writes on the connection and returns None
            h = request.connection
            h.send_response(200)
            h.send_header("Content-Type", "text/event-stream")
            h.end_headers()
            h.wfile.write(b"data: one\n\n")
            return None
        body = request.read_body(1000) or b""
        seen = {
            "method": request.method,
            "path": request.path,
            "rest": request.rest,
            "query": request.query,
            "body": body.decode(),
            "agent": request.connection.headers.get("User-Agent"),
        }
        return MountReply(201, json.dumps(seen).encode())


def ask(rig, method: str, path: str, body: bytes | None = None) -> tuple[int, bytes, str]:
    conn = http.client.HTTPConnection("127.0.0.1", int(rig.url.rsplit(":", 1)[1]), timeout=10)
    try:
        conn.request(method, path, body=body, headers={"User-Agent": "seam-test"})
        r = conn.getresponse()
        return r.status, r.read(), r.getheader("Content-Type", "")
    finally:
        conn.close()


def test_there_is_one_seam(rig):
    assert not hasattr(rig.desk, "extensions")
    assert not hasattr(web.Handler, "extension")
    assert rig.desk.mounts.find("/app/anything") is None


def test_ask_and_the_song_are_both_mounts(asked, song_rig):  # noqa: F811
    mounts = asked.rig.desk.mounts
    assert mounts.prefixes() == ["/app/ask", "/app/song"]
    assert mounts.find("/app/ask/api/engines")[1] is asked.adapter.routes
    assert mounts.find("/app/song/api/arrangements")[2] == "/api/arrangements"
    rig = asked.rig
    assert ask(rig, "GET", "/app/ask/api/engines")[0] == 200
    assert ask(rig, "GET", "/app/song/api/arrangements")[0] == 200
    asked.adapter.stop()
    assert mounts.prefixes() == ["/app/song"]
    assert ask(rig, "GET", "/app/ask/api/engines")[0] == 404


def test_a_new_mount_gets_every_method_with_the_path_the_query_and_the_body(rig):
    rig.desk.mounts.add("/app/notes", Notes())
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        body = None if method == "GET" else b"hello"
        code, raw, ctype = ask(rig, method, "/app/notes/a/b?x=1&y=two", body)
        assert code == 201 and ctype == "application/json", method
        assert json.loads(raw) == {
            "method": method,
            "path": "/app/notes/a/b",
            "rest": "/a/b",
            "query": {"x": "1", "y": "two"},
            "body": "" if method == "GET" else "hello",
            "agent": "seam-test",
        }
    code, raw, _ = ask(rig, "HEAD", "/app/notes/a")
    assert code == 201 and raw == b""
    assert json.loads(ask(rig, "GET", "/app/notes")[1])["rest"] == "/"
    rig.desk.mounts.remove("/app/notes")
    assert ask(rig, "GET", "/app/notes/a")[0] == 404
    assert ask(rig, "PUT", "/app/notes/a", b"x")[0] == 404


def test_a_mount_may_answer_as_it_goes(rig):
    rig.desk.mounts.add("/app/notes", Notes())
    code, raw, ctype = ask(rig, "GET", "/app/notes/stream")
    assert code == 200 and ctype == "text/event-stream" and raw == b"data: one\n\n"


def test_a_mount_does_not_get_a_write_from_another_site_or_a_name_that_is_not_ours(rig):
    rig.desk.mounts.add("/app/notes", Notes())
    conn = http.client.HTTPConnection("127.0.0.1", int(rig.url.rsplit(":", 1)[1]), timeout=10)
    conn.request("POST", "/app/notes/a", body=b"x", headers={"Origin": "https://evil.example"})
    assert conn.getresponse().status == 403
    conn.close()
    conn = http.client.HTTPConnection("127.0.0.1", int(rig.url.rsplit(":", 1)[1]), timeout=10)
    conn.request("GET", "/app/notes/a", headers={"Host": "evil.example"})
    assert conn.getresponse().status == 403
    conn.close()
