"""The HW002 arranger's server: the page, the bounced loops and the saved arrangements; the transitions page
(/transitions/) with the transition sounds made by fxset.py; the first mix page (/mix/); and the second (/mix2/), whose
batches mixset.py renders in Live (the server starts its worker when a batch is queued). Each page writes its
structure into the arrangement file (`regions`, `transitions`, `mix`, `mix2`).

    python3 contrib/arranger/server.py            # 127.0.0.1:8975

Standard library only. The loops and their index (`loops.json`, made by mine.py) and the arrangements live outside
the repo, in $ARRANGER_DATA (default ~/_agent_scratch/arranger). Put it on the tailnet with
`tailscale serve --bg --https=8975 http://127.0.0.1:8975`.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("ARRANGER_DATA", "~/_agent_scratch/arranger")).expanduser()
PORT = int(os.environ.get("ARRANGER_PORT", "8975"))
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
         ".flac": "audio/flac", ".svg": "image/svg+xml"}
ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
MIX2 = DATA / "mix2"
UV = shutil.which("uv") or str(Path("~/.local/bin/uv").expanduser())
_worker = None   # the mix-2 render worker (mixset.py worker), at most one


def start_worker() -> None:
    """Start mixset.py's worker if it is not running: it renders the queued mix-2 requests in Live, one after another,
    and stops at the first surprise (that request is marked failed with the reason)."""
    global _worker
    if _worker is not None and _worker.poll() is None:
        return
    root = HERE.parents[1]
    log = open(MIX2 / "worker.log", "a")
    _worker = subprocess.Popen([UV, "run", "--project", str(root / "hands"), "python", str(HERE / "mixset.py"), "worker"],
                               cwd=root, stdout=log, stderr=subprocess.STDOUT, env={**os.environ, "ARRANGER_DATA": str(DATA)})


class Handler(BaseHTTPRequestHandler):
    server_version = "arranger"

    def log_message(self, *args):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json", cache: str = "no-store") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode())

    def _file(self, path: Path, cache: str = "no-store") -> None:
        if not path.is_file():
            return self._json({"error": "not found"}, 404)
        self._send(200, path.read_bytes(), TYPES.get(path.suffix, "application/octet-stream"), cache)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            return self._file(HERE / "static" / "index.html")
        if path == "/loops.json":
            return self._file(DATA / "loops.json")
        if path in ("/transitions", "/transitions/"):
            return self._file(HERE / "static" / "transitions.html")
        if path in ("/mix", "/mix/"):
            return self._file(HERE / "static" / "mix.html")
        if path in ("/mix2", "/mix2/"):
            return self._file(HERE / "static" / "mix2.html")
        if path == "/mix2/catalog.json":
            return self._file(MIX2 / "catalog.json")
        if m := re.fullmatch(r"/mix2/([a-z0-9-]{1,64})/([a-z0-9-]{1,32}\.flac)", path):
            return self._file(MIX2 / m[1] / m[2])
        if path == "/api/mix2/requests":
            rows = []
            for f in (MIX2 / "requests").glob("*.json"):
                try:
                    rows.append(json.loads(f.read_text()))
                except ValueError:
                    continue
            return self._json(sorted(rows, key=lambda r: -(r.get("made") or 0)))
        if path == "/fx.json":
            return self._file(DATA / "fx" / "fx.json")
        if m := re.fullmatch(r"/fx/audio/([a-z0-9-]{1,64}\.flac)", path):
            return self._file(DATA / "fx" / "audio" / m[1])
        if path == "/api/transitions":
            f = DATA / "transitions.json"
            return self._file(f) if f.exists() else self._json({})
        if m := re.fullmatch(r"/audio/([a-f0-9]{16}\.flac)", path):   # named by content: cache for good
            return self._file(DATA / "audio" / m[1], "public, max-age=31536000, immutable")
        if path == "/api/arrangements":
            rows = []
            for f in sorted((DATA / "arrangements").glob("*.json")):
                try:
                    a = json.loads(f.read_text())
                    rows.append({"id": f.stem, "name": a.get("name", f.stem), "bars": a.get("bars"), "saved": a.get("saved")})
                except ValueError:
                    continue
            return self._json(sorted(rows, key=lambda r: -(r["saved"] or 0)))
        if m := re.fullmatch(r"/api/arrangements/([^/]+)", path):
            if not ID.match(m[1]):
                return self._json({"error": "bad id"}, 400)
            return self._file(DATA / "arrangements" / f"{m[1]}.json")
        self._json({"error": "not found"}, 404)

    do_HEAD = do_GET

    def do_PUT(self) -> None:
        if m := re.fullmatch(r"/api/arrangements/([^/]+)/(transitions|mix|mix2)", self.path):   # a later page's structure
            f = DATA / "arrangements" / f"{m[1]}.json"
            if not ID.match(m[1]) or not f.is_file():
                return self._json({"error": "no such arrangement"}, 404)
            n = int(self.headers.get("Content-Length") or 0)
            try:
                t = json.loads(self.rfile.read(n)) if 0 < n < 2_000_000 else None
                if m[2] == "transitions":
                    assert isinstance(t, list) and all(isinstance(x, dict) and "id" in x and "seam" in x for x in t)
                elif m[2] == "mix2":
                    assert isinstance(t, list) and all(isinstance(x, dict) and "device" in x and "target" in x for x in t)
                else:
                    assert isinstance(t, dict) and isinstance(t.get("channels"), dict)
            except (ValueError, AssertionError):
                return self._json({"error": f"bad {m[2]}"}, 400)
            a = json.loads(f.read_text())
            a[m[2]] = t
            tmp = f.with_name(f".{m[1]}.tmp")
            tmp.write_text(json.dumps(a))
            tmp.replace(f)
            return self._json({"ok": True})
        if self.path == "/api/transitions":   # the transitions page's view: the change shown, hearts, stacks
            n = int(self.headers.get("Content-Length") or 0)
            if not 0 < n < 200_000:
                return self._json({"error": "bad size"}, 400)
            try:
                t = json.loads(self.rfile.read(n))
                assert isinstance(t, dict) and isinstance(t.get("picks"), dict)
            except (ValueError, AssertionError):
                return self._json({"error": "bad picks"}, 400)
            t["saved"] = time.time()
            tmp = DATA / ".transitions.tmp"
            tmp.write_text(json.dumps(t))
            tmp.replace(DATA / "transitions.json")
            return self._json({"ok": True})
        m = re.fullmatch(r"/api/arrangements/([^/]+)", self.path)
        if not m or not ID.match(m[1]):
            return self._json({"error": "bad id"}, 400)
        n = int(self.headers.get("Content-Length") or 0)
        if not 0 < n < 2_000_000:
            return self._json({"error": "bad size"}, 400)
        try:
            a = json.loads(self.rfile.read(n))
            assert isinstance(a, dict) and isinstance(a.get("regions"), list)
        except (ValueError, AssertionError):
            return self._json({"error": "bad arrangement"}, 400)
        a["saved"] = time.time()
        folder = DATA / "arrangements"
        folder.mkdir(parents=True, exist_ok=True)
        old = folder / f"{m[1]}.json"
        if old.is_file():   # the arranger page does not know the later steps' structure: keep what is there
            try:
                prev = json.loads(old.read_text())
                for key in ("transitions", "mix", "mix2"):
                    if key not in a and key in prev:
                        a[key] = prev[key]
            except ValueError:
                pass
        tmp = folder / f".{m[1]}.tmp"
        tmp.write_text(json.dumps(a))
        tmp.replace(folder / f"{m[1]}.json")
        self._json({"ok": True, "saved": a["saved"]})

    def do_POST(self) -> None:
        if self.path != "/api/mix2/requests":   # a batch to render: a target, a device, one or two ranges, some bars
            return self._json({"error": "not found"}, 404)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            r = json.loads(self.rfile.read(n)) if 0 < n < 100_000 else None
            assert isinstance(r, dict) and isinstance(r.get("target"), str) and isinstance(r.get("device"), str)
            assert isinstance(r.get("params"), list) and 1 <= len(r["params"]) <= 2
            assert isinstance(r.get("bars"), list) and len(r["bars"]) == 2 and 1 <= r["bars"][0] <= r["bars"][1] <= 40
        except (ValueError, AssertionError):
            return self._json({"error": "bad request"}, 400)
        r.update(id=time.strftime("b%m%d-%H%M%S"), status="queued", made=time.time())
        (MIX2 / "requests").mkdir(parents=True, exist_ok=True)
        (MIX2 / "requests" / f"{r['id']}.json").write_text(json.dumps(r, indent=1))
        start_worker()
        self._json(r)

    def do_DELETE(self) -> None:
        m = re.fullmatch(r"/api/arrangements/([^/]+)", self.path)
        if not m or not ID.match(m[1]):
            return self._json({"error": "bad id"}, 400)
        f = DATA / "arrangements" / f"{m[1]}.json"
        if f.exists():   # kept, out of the list: nothing he made is destroyed from a phone tap
            (DATA / "arrangements" / "deleted").mkdir(exist_ok=True)
            f.replace(DATA / "arrangements" / "deleted" / f"{m[1]}-{int(time.time())}.json")
        self._json({"ok": True})


if __name__ == "__main__":
    print(f"arranger on http://127.0.0.1:{PORT} (data {DATA})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
