"""Controller cards' live values, and the preset library (starred cards). Files as Zpkt web kept them:
surface-state.json (id -> {values, peaks, side}) and library.json (a list of presets)."""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from zpkt.app.ask.store import Refused, load_list, write_json

SURFACE_ID = re.compile(r"^[\w:.\/\-]{1,160}$")
MAX_STATE = 64 * 1024
MAX_STATES = 5000
MAX_PRESETS = 500


def clean(value: Any) -> Any:
    text = json.dumps(value if value is not None else {})
    if len(text) > MAX_STATE:
        raise Refused("Surface state too large", 413)
    return json.loads(text)


def _preset(p: Any) -> bool:
    return (
        isinstance(p, dict)
        and isinstance(p.get("id"), str)
        and isinstance(p.get("spec"), dict)
        and isinstance(p["spec"].get("controls"), list)
    )


class Library:
    def __init__(self, data_dir: Path) -> None:
        self.state_file = Path(data_dir) / "surface-state.json"
        self.lib_file = Path(data_dir) / "library.json"
        self.lock = threading.Lock()
        try:
            raw = json.loads(self.state_file.read_text())
        except (OSError, ValueError):
            raw = {}
        self.state: dict[str, dict[str, Any]] = (
            {k: v for k, v in raw.items() if isinstance(v, dict)} if isinstance(raw, dict) else {}
        )
        self.presets: list[dict[str, Any]] = load_list(self.lib_file, _preset)

    def set_state(self, sid: str, body: dict[str, Any]) -> dict[str, Any]:
        if not SURFACE_ID.match(sid):
            raise Refused("Bad surface id")
        with self.lock:
            cur = self.state.setdefault(sid, {})
            if isinstance(body.get("values"), dict):
                cur["values"] = clean(body["values"])
            if isinstance(body.get("peaks"), dict):
                cur["peaks"] = clean(body["peaks"])
            if body.get("side") in ("a", "b"):
                cur["side"] = body["side"]
            cur["updated"] = int(time.time() * 1000)
            if len(self.state) > MAX_STATES:
                for k in sorted(self.state, key=lambda k: self.state[k].get("updated", 0))[
                    : len(self.state) - MAX_STATES
                ]:
                    del self.state[k]
            write_json(self.state_file, self.state)
            return cur

    def states(self, prefix: str = "") -> dict[str, Any]:
        with self.lock:
            return {k: v for k, v in self.state.items() if not prefix or k.startswith(prefix)}

    def library(self) -> list[dict[str, Any]]:
        return sorted(self.presets, key=lambda p: p.get("updated", 0), reverse=True)

    def star(self, spec: Any, values: Any, name: str = "", session: str = "", source: str = "") -> dict[str, Any]:
        if not isinstance(spec, dict) or not isinstance(spec.get("controls"), list) or not spec["controls"]:
            raise Refused("A preset needs a spec with controls")
        now = int(time.time() * 1000)
        with self.lock:
            existing = next((p for p in self.presets if source and p.get("source") == source), None)
            if existing is not None:
                existing.update(values=clean(values), updated=now, **({"name": name[:80]} if name else {}))
                write_json(self.lib_file, self.presets)
                return existing
            if len(self.presets) >= MAX_PRESETS:
                raise Refused(f"The library is full ({MAX_PRESETS} presets); delete some first")
            p = {
                "id": uuid.uuid4().hex[:8],
                "name": (name or spec.get("title") or "Surface")[:80],
                "spec": clean(spec),
                "values": clean(values),
                "session": session[:40] or None,
                "source": source[:120] or None,
                "created": now,
                "updated": now,
            }
            self.presets.append(p)
            write_json(self.lib_file, self.presets)
            return p

    def update(self, pid: str, name: Any, values: Any) -> dict[str, Any]:
        with self.lock:
            p = next((x for x in self.presets if x["id"] == pid), None)
            if p is None:
                raise Refused("No such preset", 404)
            if isinstance(name, str) and name.strip():
                p["name"] = name.strip()[:80]
            if isinstance(values, dict):
                p["values"] = clean(values)
            p["updated"] = int(time.time() * 1000)
            write_json(self.lib_file, self.presets)
            return p

    def remove(self, pid: str) -> None:
        with self.lock:
            self.presets = [p for p in self.presets if p["id"] != pid]
            write_json(self.lib_file, self.presets)
