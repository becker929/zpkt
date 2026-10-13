"""What the page played and did over a whole run, gathered in pieces as it goes (phone.Phone drains the page)."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "ui"))
from heard import Ear  # noqa: E402


class Recording:
    def __init__(self) -> None:
        self._ears: dict[int, dict[str, Any]] = {}
        self.engine: list[dict[str, Any]] = []
        self._seen: set[str] = set()

    def add_ears(self, raw: list[dict[str, Any]]) -> None:
        for r in raw:
            if r.get("error"):
                raise RuntimeError(f"the ear did not start: {r['error']}")
            e = self._ears.setdefault(r["id"], {"rate": int(r["rate"]), "times": [], "sizes": [], "chunks": [],
                                                "heardAt": [], "now": [], "outputLatency": r["outputLatency"]})
            e["times"] += r["times"]
            e["sizes"] += r["sizes"]
            e["chunks"].append(np.frombuffer(base64.b64decode(r["samples"]), dtype="<f4"))
            e["heardAt"] += r["heardAt"]
            e["now"] += r["now"]

    def add_engine(self, log: list[dict[str, Any]], now: float) -> None:
        """New items of the engine's log, each with `seenAt`: the page's clock (ms) when it was first taken. After an
        app switch the page has a new audio context whose clock starts again, and seenAt tells the two apart."""
        for item in log:
            key = json.dumps(item, sort_keys=True)
            if key not in self._seen:
                self._seen.add(key)
                self.engine.append({**item, "seenAt": now})

    def ears(self) -> list[Ear]:
        """One Ear per audio context, each chunk at its own time (as heard.heard builds them)."""
        out = []
        for id_, e in sorted(self._ears.items()):
            rate, times, sizes = e["rate"], e["times"], e["sizes"]
            if not times:
                continue
            chunk = np.concatenate(e["chunks"]) if e["chunks"] else np.zeros(0, np.float32)
            t0 = times[0]
            samples = np.zeros(int(round((times[-1] - t0) * rate)) + sizes[-1], np.float32)
            at, expected, gaps = 0, 0, []
            for i, (t, n) in enumerate(zip(times, sizes)):
                pos = int(round((t - t0) * rate))
                if i and pos != expected:
                    gaps.append((t, pos - expected))
                samples[pos:pos + n] = chunk[at:at + n]
                at += n
                expected = pos + n
            clock = np.array(e["heardAt"]) if e["heardAt"] else np.array(e["now"]) + [0.0, e["outputLatency"]]
            out.append(Ear(id_, rate, t0, samples, clock, "", gaps))
        return out
