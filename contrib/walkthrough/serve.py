"""The walkthrough journal page: every run and its journal as it is written (tailnet: tailscale serve --https=8996).

Stdlib only. Serves page.html, /api/runs (the runs, newest first) and the files of a run (journal.jsonl, run.json,
notes.md, shots/*.png) from the runs folder, and nothing else.
"""

from __future__ import annotations

import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

HERE = Path(__file__).resolve().parent
RUNS = Path(os.environ.get("WT_RUNS", "~/Music/zpkt/walkthrough/runs")).expanduser()
PORT = int(os.environ.get("WT_PORT", "8996"))
ALLOWED = {"journal.jsonl", "run.json", "notes.md"}


def runs() -> list[dict]:
    out = []
    for d in sorted(RUNS.iterdir(), reverse=True) if RUNS.exists() else []:
        if not (d / "run.json").exists():
            continue
        meta = json.loads((d / "run.json").read_text())
        j = d / "journal.jsonl"
        n = sum(1 for x in j.read_text().splitlines() if x.strip()) if j.exists() else 0
        cps = sorted(p.name for p in (d / "checkpoints").iterdir()) if (d / "checkpoints").exists() else []
        out.append(
            {"id": d.name, **meta, "entries": n, "checkpoints": cps, "updated": j.stat().st_mtime if j.exists() else 0}
        )
    return out


class H(BaseHTTPRequestHandler):
    def send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path in ("/", "/index.html"):
            return self.send(200, (HERE / "page.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/api/runs":
            return self.send(200, json.dumps(runs()).encode(), "application/json")
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 3 and parts[0] == "runs":
            run = (RUNS / parts[1]).resolve()
            f = (run / "/".join(parts[2:])).resolve()
            ok = run.parent == RUNS.resolve() and f.is_relative_to(run) and f.is_file()
            ok = ok and (f.name in ALLOWED or (f.parent.name == "shots" and f.suffix == ".png"))
            if ok:
                return self.send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "text/plain; charset=utf-8")
        self.send(404, b"not found", "text/plain")

    def log_message(self, *a: object) -> None:
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
