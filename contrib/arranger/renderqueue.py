"""The queue of small render batches (mix 2): one request file per batch in <data>/mix2/requests.

The page queues a batch through the server (`add`); mixset.py's worker renders the queued ones oldest first
(`queued`) and writes each one's progress into its file; the server lists them (`rows`) and says where the queue
stands (`status`). A batch's status is queued, rendering, ready or failed. Standard library only: the server and
mixset.py both import it.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

STATUSES = ("queued", "rendering", "ready", "failed")


class RenderQueue:
    """The request files in `folder` (<data>/mix2/requests)."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def add(self, batch: dict[str, Any]) -> dict[str, Any]:
        """Queue a checked batch: it gets its id, status and time, and its file. Returns the batch as filed."""
        batch.update(id=time.strftime("b%m%d-%H%M%S"), status="queued", made=time.time())
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / f"{batch['id']}.json").write_text(json.dumps(batch, indent=1))
        return batch

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
        row = json.loads(path.read_text())
        row.update(status="failed", error=reason)
        path.write_text(json.dumps(row, indent=1))

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
