"""The Web adapter's server: the mix desk's HTTP server, moved into the app.

It answers only for its own names (localhost, the tailnet proxy's name, the names in ZPKT_APP_HOSTS), and takes
writes only from its own pages (`host_allowed`, `cross_site`). It serves the old desk page at / (same routes, same server-sent events, same ports: 8985, 8986 for the pager's
datagrams, 8987 for the meter) and the new shell at /app/ (the Hear bar and the Desk), both from the same state. Every
POST is a Command on the bus (zpkt.app.bus), stamped who="you": the old paths are the commands under their old names,
and POST /api/command takes any kind. The server holds no state of its own; the Desk does.

    uv run python contrib/mixdesk/server.py      # as before; or `zpkt app`
"""

from __future__ import annotations

import contextlib
import json
import queue
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlparse

from zpkt.app import deskstate as D  # noqa: F401  (kept importable as server.D)
from zpkt.app import pages
from zpkt.app import protocol as P  # noqa: F401
from zpkt.app.bus import BadRequest, Command, Reply
from zpkt.app.commands import POST_PATHS
from zpkt.app.desk import HOSTS_ENV, Desk, Settings, hosts_from_env, meter_message, mixdesk_dir, start_threads
from zpkt.app.options import BadOption
from zpkt.live import desk_pager
from zpkt.live.changes import Who
from zpkt.live.transport import LiveError

__all__ = [
    "GET_ROUTES",
    "HERE",
    "PAGES",
    "POST_ROUTES",
    "BadRequest",
    "Desk",
    "DeskHTTPServer",
    "Handler",
    "Response",
    "Settings",
    "hosts_from_env",
    "main",
    "meter_message",
    "pager_start_code",
    "start",
]

HERE = mixdesk_dir()  # the desk's own files (the old page, desk.json, sources.json, pager.py)
AUDIO_TYPES = {".wav": "audio/wav", ".flac": "audio/flac", ".mp3": "audio/mpeg"}
SHELL_DIR = Path(__file__).resolve().parent / "static"


def pager_start_code(cfg: dict[str, Any], udp_port: int) -> str:
    """The code that (re)loads pager.py into Live and starts it, handing the old desk's monitor and page over."""
    return desk_pager.start_code(HERE / "pager.py", cfg, udp_port)


# ---- POST routes: path -> the command kind it is; the bus runs it ------------------------------------------------------

POST_ROUTES: dict[str, str] = dict(POST_PATHS)


# ---- GET routes: each takes the desk and the query, and returns a Response ------------------------------------------


@dataclass(frozen=True)
class Response:
    """What a GET route answers: a status, a body and its type."""

    code: int
    body: bytes
    ctype: str = "application/json"


def json_response(obj: Any, code: int = 200) -> Response:
    return Response(code, json.dumps(obj).encode())


def get_analysis(desk: Desk, query: dict[str, str]) -> Response:
    f = desk.settings.viz_dir / "analysis.json"
    return Response(200, f.read_bytes()) if f.exists() else json_response({"error": "run analyze.py first"}, 404)


def get_desk(desk: Desk, query: dict[str, str]) -> Response:
    return json_response(desk.cfg())


def get_history(desk: Desk, query: dict[str, str]) -> Response:
    return json_response(desk.history.view())


def get_checkpoint(desk: Desk, query: dict[str, str]) -> Response:
    try:
        vals = desk.history.load(query.get("name", ""))
    except (ValueError, FileNotFoundError) as exc:
        return json_response({"error": str(exc)}, 404)
    return json_response({k: vals[k] for k in desk.history.cur if k in vals})


def get_compare(desk: Desk, query: dict[str, str]) -> Response:
    try:
        return json_response(desk.history.compare(query.get("a", ""), query.get("b", "now")))
    except (ValueError, FileNotFoundError) as exc:
        return json_response({"error": str(exc)}, 404)


def get_state(desk: Desk, query: dict[str, str]) -> Response:
    return json_response(desk.page_state())


GET_ROUTES: dict[str, Callable[[Desk, dict[str, str]], Response]] = {
    "/api/analysis": get_analysis,
    "/api/desk": get_desk,
    "/api/history": get_history,
    "/api/checkpoint": get_checkpoint,
    "/api/compare": get_compare,
    "/api/state": get_state,
}


# ---- what only the shell and the API use ------------------------------------------------------------------------------


def get_hear(desk: Desk, query: dict[str, str]) -> Response:
    return json_response(desk.monitor.message())


def get_commands(desk: Desk, query: dict[str, str]) -> Response:
    return json_response({"commands": desk.bus.kinds("you")})


def get_changes(desk: Desk, query: dict[str, str]) -> Response:
    """The set's change stream (zpkt.live.changes): ?since=N for what came after, ?who=agent for one mover."""
    stream = desk.history.changes
    if stream is None:
        return json_response({"changes": [], "last": 0})
    desk.history.flush_changes(force=True)
    try:
        since = int(query.get("since", "0"))
    except ValueError:
        return json_response({"error": "since is a whole number"}, 400)
    who = query.get("who")
    found = stream.read(since, who)  # type: ignore[arg-type]
    return json_response({"changes": found, "last": stream.last(), "skipped": stream.skipped})


def get_options(desk: Desk, query: dict[str, str]) -> Response:
    """Every Option; ?option=ID for one."""
    if "option" in query:
        try:
            return json_response(desk.options.get(query["option"]))
        except BadOption as exc:
            return json_response({"error": str(exc)}, 404)
    return json_response(desk.options.message())


def get_pages(desk: Desk, query: dict[str, str]) -> Response:
    return json_response({"pages": pages.listing(desk)})


APP_GET_ROUTES: dict[str, Callable[[Desk, dict[str, str]], Response]] = {
    "/api/pages": get_pages,
    "/api/hear": get_hear,
    "/api/commands": get_commands,
    "/api/changes": get_changes,
    "/api/options": get_options,
}


def post_command(desk: Desk, body: dict[str, Any], who: Who = "you") -> Reply:
    """Any command by kind: {"kind": "mix.set", "args": {...}, "group": "..."}. The web is "you"; the agents' route
    (POST /api/agent/command) is "agent". The body can never say who, and never carries an approval."""
    kind = body.get("kind")
    if not isinstance(kind, str):
        raise BadRequest("the body needs 'kind', the command's name")
    args = body.get("args", {})
    if not isinstance(args, dict):
        raise BadRequest("'args' must be a JSON object")
    group = body.get("group")
    return desk.bus.submit(Command(kind, who, args, group=str(group) if group else None))


# The HTML pages served, by path. The routes above serve any page; a second page is one more entry here.
PAGES: dict[str, Path] = {"/": HERE / "static" / "index.html", "/index.html": HERE / "static" / "index.html"}
SHELL_PAGES: dict[str, Path] = {"/app/": SHELL_DIR / "app.html", "/app": SHELL_DIR / "app.html"}


LOOPBACK_NAMES = ("127.0.0.1", "localhost", "::1")
TAILNET_SUFFIX = ".ts.net"  # a `tailscale serve` name; only Tailscale answers DNS for it, never with 127.0.0.1
DEFAULT_PORTS = {"http": 80, "https": 443}


def split_host(host: str | None) -> tuple[str, int | None] | None:
    """A Host header as (name in lower case, port or None); None when it is not one name and one port."""
    try:
        parsed = urlparse(f"//{host or ''}")
        name, port = parsed.hostname, parsed.port
    except ValueError:
        return None
    if not name or parsed.path or parsed.username is not None or " " in (host or ""):
        return None
    return name.lower(), port


def host_allowed(host: str | None, extra: Sequence[str] = ()) -> bool:
    """Is `host` (a Host header) a name this server answers for: this Mac's loopback names, a tailnet name (the
    `tailscale serve` proxy keeps the name the phone asked for), or one of `extra`. The port is not judged.

    This is the check against DNS rebinding. A page on evil.example that points its name at 127.0.0.1 is the same
    site as this server to the browser, so its Origin agrees with its Host; but the Host is still evil.example."""
    found = split_host(host)
    if found is None:
        return False
    name = found[0]
    return name in LOOPBACK_NAMES or name.endswith(TAILNET_SUFFIX) or name in {e.lower() for e in extra}


def _site(name: str, port: int | None, scheme: str | None) -> tuple[str, int | None]:
    return name, port if port is not None else DEFAULT_PORTS.get(scheme or "")


def cross_site(
    origin: str | None, host: str | None, forwarded_host: str | None = None, forwarded_proto: str | None = None
) -> bool:
    """True when a browser says the request comes from a page on another site (its Origin names another host than
    the one asked). Any web page could otherwise post to this server on 127.0.0.1 as a "simple" request. A caller
    that sends no Origin (curl, the CLI, the tests) is not a browser page and passes.

    Behind the tailnet proxy the name asked is the proxy's. The proxy hands it on as Host, and as X-Forwarded-Host
    with X-Forwarded-Proto; the Origin may agree with either. A port left out is the scheme's own (443 for https),
    so `https://name` and `name:443` are one site, and `https://name` and `name:8985` are two."""
    if not origin:
        return False
    if origin == "null":
        return True
    try:
        page = urlparse(origin)
        page_site = _site((page.hostname or "").lower(), page.port, page.scheme)
    except ValueError:
        return True
    if page.netloc.lower() == (host or "").lower() and not forwarded_proto:
        return False  # the same text on both sides: the desk's own page, asked directly
    scheme = (forwarded_proto or "http").split(",")[0].strip().lower()
    if page.scheme != scheme:
        return True
    for asked in (host, forwarded_host):
        found = split_host(asked)
        if found is not None and _site(*found, scheme) == page_site:
            return False
    return True


def parse_body(raw: bytes) -> dict[str, Any]:
    """A POST body: a JSON object, or nothing (an empty object)."""
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        raise BadRequest("the body is not JSON") from None
    if not isinstance(body, dict):
        raise BadRequest("the body must be a JSON object")
    return body


class Handler(BaseHTTPRequestHandler):
    server: DeskHTTPServer

    def log_message(self, format: str, *args: Any) -> None:
        pass

    @property
    def desk(self) -> Desk:
        return self.server.desk

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: Any, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _media(self, name: str) -> None:
        """Serve one analysed WAV (with Range, so the browser can seek). Only files analyze.py wrote."""
        f = self.desk.settings.viz_dir / name
        if "/" in name or not name.endswith(".wav") or not f.is_file():
            return self._send(404, b"not found", "text/plain")
        self._ranged(f, "audio/wav")

    def _version_file(self, query: dict[str, str]) -> None:
        """Serve the audio of one Version of an Option (only a file an Option names), with Range."""
        try:
            f = self.desk.options.file_of(query.get("option", ""), query.get("version", ""))
        except BadOption as exc:
            return self._send(404, str(exc).encode(), "text/plain")
        if f is None or not f.is_file():
            return self._send(404, b"that Version has no audio file (it may have been swept)", "text/plain")
        self._ranged(f, AUDIO_TYPES.get(f.suffix.lower(), "application/octet-stream"))

    def _ranged(self, f: Path, ctype: str) -> None:
        size = f.stat().st_size
        a, b, code = 0, size - 1, 200
        rng = self.headers.get("Range", "")
        if rng.startswith("bytes="):
            lo, _, hi = rng[6:].partition("-")
            try:
                a = int(lo) if lo else 0
                b = min(int(hi), size - 1) if hi else size - 1
            except ValueError:
                return self._send(416, b"bad range", "text/plain")
            code = 206
        with f.open("rb") as fh:
            fh.seek(a)
            body = fh.read(b - a + 1)
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(len(body)))
        if code == 206:
            self.send_header("Content-Range", f"bytes {a}-{b}/{size}")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    # ---- mounted routes (the Song at /app/song): the mount answers, whatever the method ----------------------------
    def _read_limited(self, limit: int) -> bytes | None:
        """The request body if its length is above 0 and below `limit`, else None (what a mount's routes expect)."""
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if 0 < n < limit else None

    def _mounted(self, path: str) -> bool:
        """Hand the request to the mount whose prefix starts `path`; True when one answered."""
        found = self.desk.mounts.find(path)
        if found is None:
            return False
        _, mount, rest = found
        try:
            reply = mount.handle(self.command, rest, self._read_limited)
        except (LiveError, OSError) as exc:
            self._json({"error": str(exc)}, 503)
            return True
        self.send_response(reply.code)
        self.send_header("Content-Type", reply.ctype)
        self.send_header("Content-Length", str(len(reply.body)))
        self.send_header("Cache-Control", reply.cache)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(reply.body)
        return True

    # ---- GET -----------------------------------------------------------------------------------------------------
    def get_events(self, query: dict[str, str]) -> None:
        """Server-sent events. The shell asks with ?app=1 and also gets the monitor's and the history's state."""
        app = query.get("app") == "1"
        q: queue.Queue[dict[str, Any]] = self.desk.subscribe(app)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            first = [{"t": "full", "state": self.desk.page_state()}]
            if app:
                first += [self.desk.monitor.message(), self.desk.history.view(), self.desk.options.message()]
            for msg in first:
                self.wfile.write(f"data: {json.dumps(msg)}\n\n".encode())
            self.wfile.flush()
            while True:
                try:
                    msg = q.get(timeout=15)
                    self.wfile.write(f"data: {json.dumps(msg)}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except OSError:  # the page went away (BrokenPipeError, ConnectionResetError)
            pass
        finally:
            self.desk.unsubscribe(q)

    # routes that write as they go (server-sent events), so they need the connection itself
    STREAMS: ClassVar[dict[str, Callable[[Handler, dict[str, str]], None]]] = {"/events": get_events}

    def extension(self, method: str) -> bool:
        """Give the request to the first extension that wants its path (an adapter's routes, e.g. Ask). True if one did."""
        url = urlparse(self.path)
        for ext in list(self.desk.extensions):
            if ext.handles(url.path):
                query = {k: v[0] for k, v in parse_qs(url.query).items()}
                with contextlib.suppress(OSError):  # the page went away mid-answer
                    ext.serve(self, method, url.path, query)
                return True
        return False

    def do_GET(self) -> None:
        if self._refuse_host():
            return
        url = urlparse(self.path)
        if self.extension("GET") or self._mounted(url.path):
            return
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        page = self.server.pages.get(url.path) or SHELL_PAGES.get(url.path)
        if page is not None:
            return self._send(200, page.read_bytes(), "text/html; charset=utf-8")
        if url.path == "/api/options/file":
            return self._version_file(query)
        if url.path.startswith("/media/"):
            return self._media(url.path[len("/media/") :])
        stream = self.STREAMS.get(url.path)
        if stream is not None:
            return stream(self, query)
        route = GET_ROUTES.get(url.path) or APP_GET_ROUTES.get(url.path)
        if route is None:
            return self._send(404, b"not found", "text/plain")
        answer = route(self.desk, query)
        self._send(answer.code, answer.body, answer.ctype)

    # ---- POST ----------------------------------------------------------------------------------------------------
    def do_HEAD(self) -> None:
        if self._refuse_host():
            return
        if not self._mounted(urlparse(self.path).path):
            self._send(404, b"", "text/plain")

    def _other(self, method: str) -> None:
        """PUT, PATCH and DELETE belong to an extension (Ask) or a mount (the Song); the old routes have none."""
        if not (self.extension(method) or self._mounted(urlparse(self.path).path)):
            self._json({"error": "not found"}, 404)

    def _refuse_host(self) -> bool:
        """Answer 403 to a request for a name this server does not answer for (DNS rebinding); True when it did."""
        if host_allowed(self.headers.get("Host"), self.desk.settings.hosts):
            return False
        self._json(
            {
                "error": "this server answers for its own names only: localhost, its tailnet name, "
                f"and the names in {HOSTS_ENV}"
            },
            403,
        )
        return True

    def _refuse_cross_site(self) -> bool:
        """Answer 403 to a request for a name that is not ours, or to a write that a page on another site sent;
        True when it did."""
        if self._refuse_host():
            return True
        forwarded = self.headers.get("X-Forwarded-Host")
        if forwarded is not None and not host_allowed(forwarded, self.desk.settings.hosts):
            forwarded = None  # a forwarded name we do not answer for counts for nothing
        if not cross_site(
            self.headers.get("Origin"), self.headers.get("Host"), forwarded, self.headers.get("X-Forwarded-Proto")
        ):
            return False
        self._json({"error": "this server takes writes from its own pages only"}, 403)
        return True

    def do_PUT(self) -> None:
        if not self._refuse_cross_site():
            self._other("PUT")

    def do_PATCH(self) -> None:
        if not self._refuse_cross_site():
            self._other("PATCH")

    def do_DELETE(self) -> None:
        if not self._refuse_cross_site():
            self._other("DELETE")

    def do_POST(self) -> None:
        if self._refuse_cross_site():
            return
        if self.extension("POST") or self._mounted(urlparse(self.path).path):
            return
        kind = POST_ROUTES.get(self.path)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = parse_body(self.rfile.read(n))
            if self.path == "/api/command":
                code, reply = post_command(self.desk, body)
            elif self.path == "/api/agent/command":
                code, reply = post_command(self.desk, body, "agent")
            elif kind is None:
                return self._json({"error": "not found"}, 404)
            else:
                code, reply = self.desk.bus.submit(Command(kind, "you", body))
        except BadRequest as exc:
            code, reply = 400, {"error": str(exc)}
        except (LiveError, OSError) as exc:
            code, reply = 503, {"error": str(exc)}
        self._json(reply, code)


class DeskHTTPServer(ThreadingHTTPServer):
    """The desk's HTTP server: the routes above for `desk`, and the HTML `pages` (path -> file; default PAGES)."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], desk: Desk, pages: Mapping[str, Path] | None = None) -> None:
        super().__init__(address, Handler)
        self.desk = desk
        self.pages = dict(PAGES if pages is None else pages)


def start(desk: Desk, supervise: bool = True, pages: Mapping[str, Path] | None = None) -> DeskHTTPServer:
    """The desk's threads (pager datagrams, meter, supervisor) and its HTTP server for `pages`, not yet serving."""
    start_threads(desk, supervise)
    return DeskHTTPServer(("127.0.0.1", desk.settings.http_port), desk, pages)


def serve_in_thread(server: DeskHTTPServer) -> threading.Thread:
    t = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True, name="http")
    t.start()
    return t


def main() -> None:
    srv = start(Desk(Settings.from_env()))
    print(f"mix desk on http://127.0.0.1:{srv.server_address[1]}  (the new shell: /app/)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
