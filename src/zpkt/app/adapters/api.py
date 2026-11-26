"""The API adapter: other programs ask the app to do things over HTTP and JSON, under /api/v1/.

Callers are the `zpkt` command, music-bot's booth, zpkt-demo and agents. Each call is one Command on the bus, stamped
with who its token says it is (cli, booth, demo or agent): each caller has its own token file in ~/.config/zpkt/
(zpkt.app.token), sent as `Authorization: Bearer <token>`. A request may say `who`, but only its own name: a token
cannot ask as someone else, and `you` and `minilab` are never accepted here. Access is for this Mac only: the server
listens on 127.0.0.1 and turns away a request whose Host is not local. Only /health is open. A token is never logged.

    GET  /api/v1/health            is the app up (no token)
    GET  /api/v1/commands          every command kind, its effect and who may ask
    POST /api/v1/command           {"kind", "args", "approval", "group"} ("who" may be sent; it must be the token's)
    POST /api/v1/live/run          the same, with the kind from the path: live/run, live/read, live/open-set,
    ...                            live/render-loop, live/tempo, live/transport, state/take, state/put,
                                   page/apply, describe

An agent cannot claim your word: approval "user" from who "agent" is refused here, so no call of an agent moves
Live. It makes pages (page.draft), with compare states for a change it suggests; the press is yours.
The shapes are in lib/contracts/app-api.schema.json.
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

from zpkt.app import token as tokens
from zpkt.app.adapters import AdapterSpec, AppContext
from zpkt.app.bus import APPROVED_BY_USER, BadRequest, Bus, Command, Refused, Who
from zpkt.app.jobs import API_CALLERS

DEFAULT_PORT = 8984  # beside the desk's 8985-8987; not the one the tailnet serves
PREFIX = "/api/v1"
MAX_BODY = 16 * 1024 * 1024
# the path sugar: POST /api/v1/<path> is the command of that kind
ROUTES: dict[str, str] = {
    "/live/run": "live.run",
    "/live/read": "live.read",
    "/live/open-set": "live.open_set",
    "/live/render-loop": "live.render_loop",
    "/live/tempo": "live.set_tempo",
    "/live/transport": "live.transport",
    "/state/take": "state.take",
    "/state/put": "state.put",
    "/panel/apply": "panel.apply",
    "/page/apply": "panel.apply",  # the older path
    "/describe": "describe",
}


def parse_request(body: Any, kind: str | None = None, who: str | None = None) -> Command:
    """The request body as a Command. `who` is whose token came with it: the Command is stamped with that, and a
    body that claims another name is Refused. (None: no token is known, as when only the body is parsed; then the
    body's own `who` stands, default cli.) BadRequest for a body that cannot be used, with what to change."""
    if not isinstance(body, dict):
        raise BadRequest("the body must be a JSON object")
    kind = kind or body.get("kind")
    if not isinstance(kind, str) or not kind:
        raise BadRequest("the body needs 'kind', the command's name")
    claimed = body.get("who")
    if claimed is not None and claimed not in API_CALLERS:
        raise BadRequest(f"'who' is one of {', '.join(API_CALLERS)}, not {claimed!r}")
    if who is not None and claimed is not None and claimed != who:
        raise Refused(
            f"this token is {who}'s: it cannot ask as {claimed}. Send {claimed}'s own token, or leave 'who' out."
        )
    stamp = cast(Who, who or claimed or "cli")  # the bus checks it is one of WHO
    args = body.get("args", {})
    if not isinstance(args, dict):
        raise BadRequest("'args' must be a JSON object")
    approval, group = body.get("approval"), body.get("group")
    for name, value in (("approval", approval), ("group", group)):
        if value is not None and not isinstance(value, str):
            raise BadRequest(f"{name!r} must be text")
    if stamp == "agent" and approval == APPROVED_BY_USER:
        raise BadRequest(
            "an agent cannot say the user approved. Make a page with the change as a compare state (page.draft): "
            "the user's press on its pad makes the change"
        )
    return Command(kind, stamp, args, approval, group or None)


def listing(bus: Bus) -> list[dict[str, Any]]:
    return [
        {"kind": k, "effect": s.effect, "touches_live": s.touches_live, "callers": list(s.callers or [])}
        for k, s in sorted(bus.table.items())
    ]


class ApiServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128  # as the desk's: a burst of requests waits instead of being refused

    def __init__(self, address: tuple[str, int], bus: Bus, tokens_by_who: dict[str, str]) -> None:
        """`tokens_by_who` is {who: token}: the token a request carries says who is asking."""
        super().__init__(address, ApiHandler)
        self.bus, self.tokens = bus, dict(tokens_by_who)

    def local_hosts(self) -> set[str]:
        port = self.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}", "127.0.0.1", "localhost"}


class ApiHandler(BaseHTTPRequestHandler):
    server: ApiServer

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _json(self, body: dict[str, Any], code: int = 200) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _caller(self) -> str | None:
        """Who is asking, by the token sent; "" for /health, which needs none. None when the request was turned
        away (not a local host, or no token of ours) and already answered."""
        if self.headers.get("Host", "") not in self.server.local_hosts():
            self._json({"error": "this API answers on localhost only"}, 403)
            return None
        if self.path == f"{PREFIX}/health":
            return ""
        scheme, _, sent = self.headers.get("Authorization", "").partition(" ")
        who = tokens.who_holds(self.server.tokens, sent) if scheme == "Bearer" else None
        if who is None:
            self._json(
                {
                    "error": "send your token from ~/.config/zpkt/ (app-token for the cli) as 'Authorization: Bearer ...'"
                },
                401,
            )
        return who

    def do_GET(self) -> None:
        if self._caller() is None:
            return
        if self.path == f"{PREFIX}/health":
            self._json({"ok": True, "app": "zpkt", "api": 1})
        elif self.path == f"{PREFIX}/commands":
            self._json({"commands": listing(self.server.bus)})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        who = self._caller()
        if who is None:
            return
        path = self.path.split("?")[0]
        if not path.startswith(PREFIX + "/"):
            return self._json({"error": "not found"}, 404)
        route = path[len(PREFIX) :]
        kind = None if route == "/command" else ROUTES.get(route)
        if route != "/command" and kind is None:
            return self._json({"error": f"no route {route}; see GET {PREFIX}/commands"}, 404)
        try:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise BadRequest("Content-Length is not a number") from None
            if length < 0:
                raise BadRequest("Content-Length is below zero")
            if length > MAX_BODY:
                return self._json({"error": f"the body is over {MAX_BODY // 2**20} MB"}, 413)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                raise BadRequest("the body is not JSON") from None
            code, reply = self.server.bus.submit(parse_request(body, kind, who or None))
        except BadRequest as exc:
            code, reply = 400, {"error": str(exc)}
        except Refused as exc:
            code, reply = exc.code, {"error": str(exc)}
        self._json(reply, code)


class ApiAdapter:
    """Serves /api/v1/ on 127.0.0.1. The port is ZPKT_API_PORT (default 8984); 0 picks a free one."""

    name = "api"

    def __init__(self, context: AppContext, port: int | None = None, config_dir: Path | None = None) -> None:
        self.context = context
        self.wanted_port = int(os.environ.get("ZPKT_API_PORT", DEFAULT_PORT)) if port is None else port
        self.config_dir = config_dir
        self.server: ApiServer | None = None
        self.thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        if self.server is None:
            raise RuntimeError("the api adapter has not started")
        return int(self.server.server_address[1])

    def start(self) -> None:
        by_who = tokens.ensure_tokens(self.config_dir)
        self.server = ApiServer(("127.0.0.1", self.wanted_port), self.context.bus, by_who)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name="api")
        self.thread.start()

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None


def make(context: AppContext) -> ApiAdapter:
    return ApiAdapter(context)


ADAPTER = AdapterSpec("api", make)
