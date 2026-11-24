"""The HW002 arranger's server: the pages, the files they play and the arrangement file they write.

    python3 contrib/arranger/server.py            # 127.0.0.1:8975 ($ARRANGER_PORT)

Pages: the arranger (/), transitions (/transitions/), mix 1 (/mix/), mix 2 (/mix2/, whose batches mixset.py renders
in Live: the server starts its worker when a batch is queued), the spectral A/B (/spectral/) and kick design
(/kick/). Each writes its structure into the arrangement file (arrangement.py says who owns which key).

Standard library only. The loops, renders and arrangements live outside the repo, in $ARRANGER_DATA (default
~/_agent_scratch/arranger). Put it on the tailnet with `tailscale serve --bg --https=8975 http://127.0.0.1:8975`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import arrangement as A

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
DEFAULT_PORT = 8975
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".flac": "audio/flac",
    ".svg": "image/svg+xml",
}
NO_STORE = "no-store"
HOUR = "public, max-age=3600"
FOREVER = "public, max-age=31536000, immutable"  # loops are named by their content
MAX_ARRANGEMENT = 2_000_000  # bytes in a body
MAX_TRANSITIONS_VIEW = 200_000
MAX_MIX2_REQUEST = 100_000


class Mix2Worker:
    """mixset.py's worker, at most one: it renders the queued mix-2 requests in Live, one after another, and stops at
    the first surprise (that request is marked failed with the reason)."""

    def __init__(self, data: Path) -> None:
        self.data = data
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return
            root = HERE.parents[1]
            uv = shutil.which("uv") or str(Path("~/.local/bin/uv").expanduser())
            (self.data / "mix2").mkdir(parents=True, exist_ok=True)
            with open(self.data / "mix2" / "worker.log", "a") as log:
                self._process = subprocess.Popen(
                    [uv, "run", "--project", str(root), "python", str(HERE / "mixset.py"), "worker"],
                    cwd=root,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    env={**os.environ, "ARRANGER_DATA": str(self.data)},
                )


@dataclass
class Reply:
    """What a route answers: a status, a body and its headers."""

    code: int
    body: bytes
    ctype: str = "application/json"
    cache: str = NO_STORE


def json_reply(obj: Any, code: int = 200) -> Reply:
    return Reply(code, json.dumps(obj).encode())


def error(message: str, code: int) -> Reply:
    return json_reply({"error": message}, code)


NOT_FOUND = "not found"


def file_reply(path: Path, cache: str = NO_STORE) -> Reply:
    if not path.is_file():
        return error(NOT_FOUND, 404)
    return Reply(200, path.read_bytes(), TYPES.get(path.suffix, "application/octet-stream"), cache)


def write_json(path: Path, obj: Any, indent: int | None = None) -> None:
    """Replace a JSON file in one step (a temporary file moved over it), so a reader never sees half of one."""
    tmp = path.with_name(f".{path.stem}.tmp")
    tmp.write_text(json.dumps(obj, indent=indent))
    tmp.replace(path)


@dataclass
class Request:
    method: str
    path: str
    match: re.Match[str]
    read_body: Callable[[int], bytes | None]  # the body if its length is within the limit given, else None


Route = Callable[["Arranger", Request], Reply]


@dataclass
class Arranger:
    """The server's state: where the data is and how a mix-2 render starts. One lock orders every write to the data
    folder, so two saves of one arrangement never interleave."""

    data: Path
    start_worker: Callable[[], None]
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def arrangements(self) -> Path:
        return self.data / "arrangements"


_SIZE_CHECKED = object()


def read_json(req: Request, limit: int, bad: str, empty: Any = _SIZE_CHECKED) -> Any:
    """The body as JSON, or Rejected(bad) if it is not JSON. A missing or empty body, or one of `limit` bytes or
    more, is Rejected("bad size"), unless `empty` is given: it then stands for such a body (the later pages' keys
    and mix-2 batches have always read it as null)."""
    raw = req.read_body(limit)
    if raw is None:
        if empty is _SIZE_CHECKED:
            raise A.Rejected("bad size")
        return empty
    try:
        return json.loads(raw)
    except ValueError:
        raise A.Rejected(bad) from None


# ---- static pages and data files -------------------------------------------------------------------------------------

PAGES = {"/": "index.html", "/index.html": "index.html"} | {
    f"/{p}{slash}": f"{p}.html" for p in ("transitions", "mix", "mix2", "spectral", "kick") for slash in ("", "/")
}

# url pattern -> (file under the data folder, with \1 for the match, and its cache header)
DATA_FILES: list[tuple[str, str, str]] = [
    (r"/loops\.json", "loops.json", NO_STORE),  # made by mine.py
    (r"/audio/([a-f0-9]{16}\.flac)", r"audio/\1", FOREVER),
    (r"/refs/refs\.json", "refs/refs.json", NO_STORE),  # made by refs.py
    (r"/refs/([a-z0-9-]{1,64}(?:\.flac|\.spec\.json))", r"refs/\1", HOUR),
    (r"/fx\.json", "fx/fx.json", NO_STORE),  # transition sounds, made by fxset.py
    (r"/fx/audio/([a-z0-9-]{1,64}\.flac)", r"fx/audio/\1", NO_STORE),
    (r"/mix2/catalog\.json", "mix2/catalog.json", NO_STORE),  # mix 2 (mixset.py)
    (r"/mix2/([a-z0-9-]{1,64})/([a-z0-9-]{1,32}\.flac)", r"mix2/\1/\2", NO_STORE),
    (r"/spectral/renders\.json", "spectral/renders.json", NO_STORE),  # spectral.py
    (r"/spectral/([a-z0-9-]{1,32}\.flac)", r"spectral/\1", NO_STORE),
    (r"/kickdesign/kicks\.json", "kickdesign/kicks.json", NO_STORE),  # kickdesign.py
    (r"/kickdesign/frames/([a-z0-9-]{1,64}\.json)", r"kickdesign/frames/\1", NO_STORE),
    (r"/kickdesign/(ref-[a-z0-9-]{1,64}\.flac)", r"kickdesign/\1", HOUR),
    (r"/kickfuzz/renders\.json", "kickfuzz/renders.json", NO_STORE),  # kickfuzz.py
    (r"/kickfuzz/([a-z0-9-]{1,32}\.flac)", r"kickfuzz/\1", NO_STORE),
]


def get_page(app: Arranger, req: Request) -> Reply:
    return file_reply(STATIC / PAGES[req.path])


def get_data_file(rel: str, cache: str) -> Route:
    def route(app: Arranger, req: Request) -> Reply:
        return file_reply(app.data / req.match.expand(rel), cache)

    return route


# ---- the arranger page: arrangements --------------------------------------------------------------------------------


def list_arrangements(app: Arranger, req: Request) -> Reply:
    rows = []
    for f in sorted(app.arrangements.glob("*.json")):
        try:
            rows.append(A.list_row(f.stem, json.loads(f.read_text())))
        except ValueError:
            continue
    return json_reply(sorted(rows, key=lambda r: -(r["saved"] or 0)))


def arrangement_id(req: Request) -> str:
    """The id in the path, or Rejected("bad id")."""
    if not req.match or not A.ID.match(req.match[1]):
        raise A.Rejected("bad id")
    return req.match[1]


def get_arrangement(app: Arranger, req: Request) -> Reply:
    return file_reply(app.arrangements / f"{arrangement_id(req)}.json")


def save_arrangement(app: Arranger, req: Request) -> Reply:
    """The arranger page's save. It keeps what the later steps wrote (arrangement.merge_page_save)."""
    aid = arrangement_id(req)
    new = A.parse_page_save(read_json(req, MAX_ARRANGEMENT, "bad arrangement"))
    app.arrangements.mkdir(parents=True, exist_ok=True)
    f = app.arrangements / f"{aid}.json"
    with app.lock:
        try:
            old = json.loads(f.read_text()) if f.is_file() else None
        except ValueError:
            old = None
        merged = A.merge_page_save(new, old if isinstance(old, dict) else None)
        write_json(f, merged)
    return json_reply({"ok": True, "saved": merged["saved"]})


def delete_arrangement(app: Arranger, req: Request) -> Reply:
    """Kept, out of the list: nothing he made is destroyed from a phone tap."""
    aid = arrangement_id(req)
    f = app.arrangements / f"{aid}.json"
    with app.lock:
        if f.exists():
            (app.arrangements / "deleted").mkdir(exist_ok=True)
            f.replace(app.arrangements / "deleted" / f"{aid}-{int(time.time())}.json")
    return json_reply({"ok": True})


# ---- later pages: their key in the arrangement ----------------------------------------------------------------------


def put_later_key(app: Arranger, req: Request) -> Reply:
    """A later page's structure (transitions, mix, mix2, spectral, kickFuzz) into its key of the arrangement."""
    aid, key = req.match[1], req.match[2]
    f = app.arrangements / f"{aid}.json"
    if not A.ID.match(aid) or not f.is_file():
        return error("no such arrangement", 404)
    value = A.parse_later_key(key, read_json(req, MAX_ARRANGEMENT, f"bad {key}", empty=None))
    with app.lock:
        a = json.loads(f.read_text())
        a[key] = value
        write_json(f, a)
    return json_reply({"ok": True})


# ---- the transitions page's own view --------------------------------------------------------------------------------


def get_transitions_view(app: Arranger, req: Request) -> Reply:
    f = app.data / "transitions.json"
    return file_reply(f) if f.exists() else json_reply({})


def put_transitions_view(app: Arranger, req: Request) -> Reply:
    """The change shown, hearts, stacks and faders, stamped `saved`."""
    view = A.parse_transitions_view(read_json(req, MAX_TRANSITIONS_VIEW, "bad picks"))
    view["saved"] = time.time()
    with app.lock:
        write_json(app.data / "transitions.json", view)
    return json_reply({"ok": True})


# ---- mix 2: batches rendered in Live --------------------------------------------------------------------------------


def list_mix2_requests(app: Arranger, req: Request) -> Reply:
    rows = []
    for f in (app.data / "mix2" / "requests").glob("*.json"):
        try:
            rows.append(json.loads(f.read_text()))
        except ValueError:
            continue
    return json_reply(sorted(rows, key=lambda r: -(r.get("made") or 0)))


def queue_mix2_request(app: Arranger, req: Request) -> Reply:
    """Queue a batch (a target, a device, one or two ranges, some bars) and start the worker."""
    batch = A.parse_mix2_request(read_json(req, MAX_MIX2_REQUEST, "bad request", empty=None))
    batch.update(id=time.strftime("b%m%d-%H%M%S"), status="queued", made=time.time())
    folder = app.data / "mix2" / "requests"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{batch['id']}.json").write_text(json.dumps(batch, indent=1))
    app.start_worker()
    return json_reply(batch)


# ---- the routing table ----------------------------------------------------------------------------------------------

ROUTES: dict[str, list[tuple[re.Pattern[str], Route]]] = {
    "GET": [
        *((re.compile(re.escape(p)), get_page) for p in PAGES),
        *((re.compile(pattern), get_data_file(rel, cache)) for pattern, rel, cache in DATA_FILES),
        (re.compile(r"/api/arrangements"), list_arrangements),
        (re.compile(r"/api/arrangements/([^/]+)"), get_arrangement),
        (re.compile(r"/api/transitions"), get_transitions_view),
        (re.compile(r"/api/mix2/requests"), list_mix2_requests),
    ],
    "PUT": [
        (re.compile(rf"/api/arrangements/([^/]+)/({'|'.join(A.LATER_KEYS)})"), put_later_key),
        (re.compile(r"/api/transitions"), put_transitions_view),
        (re.compile(r"/api/arrangements/([^/]+)"), save_arrangement),
    ],
    "POST": [(re.compile(r"/api/mix2/requests"), queue_mix2_request)],
    "DELETE": [(re.compile(r"/api/arrangements/([^/]+)"), delete_arrangement)],
}
# what an unmatched path gets: GET and POST a 404; PUT and DELETE have only arrangement paths, so a bad id
FALLBACK = {
    "GET": error(NOT_FOUND, 404),
    "POST": error(NOT_FOUND, 404),
    "PUT": error("bad id", 400),
    "DELETE": error("bad id", 400),
}


def dispatch(app: Arranger, method: str, path: str, read_body: Callable[[int], bytes | None]) -> Reply:
    """Find the route for a request and run it; a Rejected body is a 400 with its message."""
    if method in ("GET", "HEAD"):
        method, path = "GET", path.split("?")[0]
    for pattern, route in ROUTES.get(method, []):
        if m := pattern.fullmatch(path):
            try:
                return route(app, Request(method, path, m, read_body))
            except A.Rejected as e:
                return error(str(e), 400)
    return FALLBACK[method]


def make_handler(app: Arranger) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "arranger"

        def log_message(self, format: str, *args: Any) -> None:  # quiet
            pass

        def read_body(self, limit: int) -> bytes | None:
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n) if 0 < n < limit else None

        def answer(self) -> None:
            reply = dispatch(app, self.command, self.path, self.read_body)
            self.send_response(reply.code)
            self.send_header("Content-Type", reply.ctype)
            self.send_header("Content-Length", str(len(reply.body)))
            self.send_header("Cache-Control", reply.cache)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(reply.body)

        do_GET = do_HEAD = do_PUT = do_POST = do_DELETE = answer

    return Handler


def make_server(
    data: Path, host: str = "127.0.0.1", port: int = DEFAULT_PORT, start_worker: Callable[[], None] | None = None
) -> ThreadingHTTPServer:
    """The server for `data`, not yet serving. `start_worker` starts mix 2's renders (default: mixset.py's worker)."""
    app = Arranger(data, start_worker or Mix2Worker(data).start)
    return ThreadingHTTPServer((host, port), make_handler(app))


def main() -> None:
    data = Path(os.environ.get("ARRANGER_DATA", "~/_agent_scratch/arranger")).expanduser()
    port = int(os.environ.get("ARRANGER_PORT", str(DEFAULT_PORT)))
    httpd = make_server(data, port=port)
    print(f"arranger on http://127.0.0.1:{port} (data {data})", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
