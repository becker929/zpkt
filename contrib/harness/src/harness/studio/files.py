"""Serving files and JSON to a phone on a slow link: a folder of static pages, gzip where the browser takes it, and the
cache headers every route under /studio/ uses."""

from __future__ import annotations

import re
from pathlib import Path

from aiohttp import web

FOREVER = "private, max-age=31536000, immutable"     # for files named by their content, or never reused
NO_STORE = {"Cache-Control": "no-store"}
GZIP_FROM = 1024                                      # bytes: a JSON answer longer than this goes gzipped
TEXT_SUFFIXES = (".html", ".js", ".css", ".json", ".svg")


def accepts_gzip(accept_encoding: str) -> bool:
    """Whether an Accept-Encoding header takes gzip (and does not refuse it with q=0)."""
    for part in accept_encoding.lower().split(","):
        name, _, params = part.partition(";")
        if name.strip() == "gzip":
            return not re.fullmatch(r"q=0(\.0*)?", params.replace(" ", ""))
    return False


def gzipped(request: web.Request, resp: web.Response) -> web.Response:
    """Text over GZIP_FROM bytes goes gzipped to a browser that takes it."""
    if resp.body is not None and len(resp.body) > GZIP_FROM and accepts_gzip(request.headers.get("Accept-Encoding", "")):
        resp.enable_compression(web.ContentCoding.gzip)
    return resp


def static_file(request: web.Request, root: Path, rel: str) -> web.StreamResponse:
    """A file of a static page under `root`, by relative path (so the same files run from any static server in
    tests), revalidated each load: these pages change often. A folder is its index.html, reached with a trailing
    slash so the page's relative links resolve inside it. Anything outside `root` is not found."""
    root = root.resolve()
    path = (root / (rel or "index.html")).resolve()
    if path.is_dir() and path.is_relative_to(root):
        if not request.path.endswith("/"):
            raise web.HTTPFound(request.path + "/")
        path = path / "index.html"
    if not path.is_relative_to(root) or not path.is_file():
        raise web.HTTPNotFound()
    resp = web.FileResponse(path, headers={"Cache-Control": "no-cache"})
    if path.suffix in TEXT_SUFFIXES and accepts_gzip(request.headers.get("Accept-Encoding", "")):
        resp.enable_compression(web.ContentCoding.gzip)
    return resp
