"""The one render queue: one request file per batch (a job) in a folder.

A job is filed with `add`; whoever renders it takes the queued ones oldest first (`queued`) and writes progress into
its file (`update`); readers list the jobs (`rows`) and ask where the queue stands (`status`). A job's status is
queued, rendering, ready or failed. Moved here from contrib/arranger on 24 Nov 2026 (the app owns the queue now):
mix 2's folder (<data>/mix2/requests) and the app's own jobs (zpkt.app.options) both use it, and the arranger's
`renderqueue` module is an alias for this one. Standard library only.
"""

from __future__ import annotations

import json
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

STATUSES = ("queued", "rendering", "ready", "failed")


def _file_whole(path: Path, row: dict[str, Any]) -> None:
    """Write a job's file so that a reader (the worker is another process) never sees half of it."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(row, indent=1))
    tmp.replace(path)


class RenderQueue:
    """The request files in `folder` (<data>/mix2/requests)."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self._write = threading.Lock()  # one writer at a time inside this process

    def add(self, batch: dict[str, Any], prefix: str = "b") -> dict[str, Any]:
        """Queue a checked batch: it gets its id, status and time, and its file. Returns the batch as filed. Two
        batches in one second get different ids (-2, -3, ...)."""
        self.folder.mkdir(parents=True, exist_ok=True)
        with self._write:
            base = time.strftime(f"{prefix}%m%d-%H%M%S")
            job_id, n = base, 1
            while (self.folder / f"{job_id}.json").exists():
                n += 1
                job_id = f"{base}-{n}"
            batch.update(id=job_id, status="queued", made=time.time())
            _file_whole(self.folder / f"{job_id}.json", batch)
        return batch

    def path_of(self, job_id: str) -> Path:
        """Where a job's file is (a job id is a plain name; anything with a slash is refused)."""
        if not job_id or "/" in job_id or job_id.startswith("."):
            raise ValueError(f"{job_id!r} is not a job id")
        return self.folder / f"{job_id}.json"

    def get(self, job_id: str) -> dict[str, Any] | None:
        """One job, or None when there is none (or its file is not JSON)."""
        try:
            return json.loads(self.path_of(job_id).read_text())
        except (OSError, ValueError):
            return None

    def update(self, job_id: str, **fields: Any) -> dict[str, Any]:
        """Change fields of a job and file it again whole (a reader never sees half a file). Returns the job."""
        with self._write:
            path = self.path_of(job_id)
            row = json.loads(path.read_text())
            row.update(fields)
            _file_whole(path, row)
            return row

    def _read(self, strict: bool) -> list[tuple[Path, dict[str, Any]]]:
        out = []
        for path in self.folder.glob("*.json"):
            try:
                out.append((path, json.loads(path.read_text())))
            except ValueError:
                if strict:
                    raise
        return out

    def rows(self) -> list[dict[str, Any]]:
        """Every batch, newest first; a file that is not JSON is passed over."""
        return sorted((row for _, row in self._read(strict=False)), key=lambda r: -(r.get("made") or 0))

    def queued(self, strict: bool = False) -> list[Path]:
        """The files of the batches waiting to render, oldest first. `strict`: a file that is not JSON raises (the
        worker stops at it) instead of being passed over."""
        rows = sorted(self._read(strict), key=lambda pr: pr[1].get("made", 0))
        return [path for path, row in rows if row.get("status") == "queued"]

    def fail(self, path: Path, reason: str) -> None:
        """Mark a batch failed, with the reason the page shows."""
        with self._write:
            row = json.loads(path.read_text())
            row.update(status="failed", error=reason)
            _file_whole(path, row)

    def status(self, worker_running: bool | None) -> dict[str, Any]:
        """Where the queue stands: whether the worker runs (None: not known), the batches rendering and waiting
        (oldest first), and how many batches are in each status."""
        rows = sorted(self.rows(), key=lambda r: r.get("made") or 0)
        counts = Counter(r.get("status") for r in rows)
        return {
            "worker": "unknown" if worker_running is None else "running" if worker_running else "idle",
            "rendering": [r.get("id") for r in rows if r.get("status") == "rendering"],
            "queued": [r.get("id") for r in rows if r.get("status") == "queued"],
            "counts": {s: counts.get(s, 0) for s in STATUSES},
        }
