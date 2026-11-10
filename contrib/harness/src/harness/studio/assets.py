"""The page's own files, served so a phone on a slow link fetches each of them once.

The page links its scripts and styles under a version, `/studio/static/<version>/...`, that changes whenever any
file in static/ does: those URLs are cached for good, and the page (never cached) names the version to use, so a
deploy is picked up on the next load. The page also lists every module up front (modulepreload: one round trip
instead of one per level of imports) and carries the newest page of history, so the chat shows before the socket
is up. Each file is read and gzipped once per version.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import mimetypes
import re
import time
from pathlib import Path
from typing import Any

STATIC = Path(__file__).parent / "static"
PREFIX = "/studio/static/"
VERSION = re.compile(r"^[0-9a-f]{12}$")
NOT_MODULES = {"mic-worklet.js"}          # loaded by the audio worklet, not by the page
CHECK_S = 1.0                             # how often the files are looked at for changes


class Assets:
    def __init__(self, root: Path = STATIC):
        self.root = root.resolve()
        self._version = ""
        self._checked = -CHECK_S
        self._files: dict[str, tuple[bytes, bytes, str]] = {}

    def version(self) -> str:
        """A hash of every file's name, size and modification time, looked at no more than once a second."""
        now = time.monotonic()
        if now - self._checked >= CHECK_S:
            self._checked = now
            files = sorted((str(p.relative_to(self.root)), st.st_size, st.st_mtime_ns)
                           for p in self.root.rglob("*") if p.is_file() and (st := p.stat()))
            version = hashlib.sha256(repr(files).encode()).hexdigest()[:12]
            if version != self._version:
                self._version, self._files = version, {}
        return self._version

    def split(self, path: str) -> tuple[str | None, str]:
        """`<version>/js/main.js` -> (version, 'js/main.js'); an unversioned path has None."""
        head, _, rest = path.partition("/")
        return (head, rest) if VERSION.match(head) and rest else (None, path)

    def file(self, rel: str) -> tuple[bytes, bytes, str] | None:
        """(the file, gzipped, its content type), or None outside static/ or missing."""
        self.version()
        if rel in self._files:
            return self._files[rel]
        path = (self.root / rel).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            return None
        data = path.read_bytes()
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith(("javascript", "json")):
            ctype += "; charset=utf-8"
        entry = (data, gzip.compress(data, 9, mtime=0), ctype)
        self._files[rel] = entry
        return entry

    def page(self, boot: dict[str, Any] | None = None) -> str:
        """index.html with versioned links, a modulepreload for every module, and `boot` (the newest page of
        history) for the page to show before its socket is up."""
        version = self.version()
        index = self.file("index.html")
        if index is None:
            raise FileNotFoundError(self.root / "index.html")
        html = index[0].decode().replace(f'"{PREFIX}', f'"{PREFIX}{version}/')
        modules = sorted(p.name for p in (self.root / "js").glob("*.js") if p.name not in NOT_MODULES)
        head = [f'<link rel="modulepreload" href="{PREFIX}{version}/js/{name}">' for name in modules]
        if boot is not None:
            data = json.dumps(boot, separators=(",", ":")).replace("<", "\\u003c")
            head.append(f'<script type="application/json" id="boot">{data}</script>')
        return html.replace("</head>", "  " + "\n  ".join(head) + "\n</head>", 1)


def accepts_gzip(accept_encoding: str) -> bool:
    """Whether an Accept-Encoding header takes gzip (and does not refuse it with q=0)."""
    for part in accept_encoding.lower().split(","):
        name, _, params = part.partition(";")
        if name.strip() == "gzip":
            return not re.fullmatch(r"q=0(\.0*)?", params.replace(" ", ""))
    return False
