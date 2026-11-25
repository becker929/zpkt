"""Folders an agent may work in. Kept in workspaces.json, as Zpkt web kept them: {id, name, path}."""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Any

from zpkt.app.ask.store import Refused, load_list, write_json


def _sound(w: Any) -> bool:
    return isinstance(w, dict) and all(isinstance(w.get(k), str) for k in ("id", "path", "name"))


class Workspaces:
    def __init__(self, data_dir: Path, home: Path | None = None) -> None:
        self.file = Path(data_dir) / "workspaces.json"
        self.home = (home or Path.home()).resolve()
        self.lock = threading.Lock()
        found = load_list(self.file, _sound)
        if found or self.file.exists():
            self.list: list[dict[str, str]] = found
        else:
            self.list = [
                {"id": "scratch", "name": "Scratch", "path": str(self.home / "gemini-scratch")},
                {"id": "desktop", "name": "Desktop", "path": str(self.home / "Desktop")},
            ]
            self.file.parent.mkdir(parents=True, exist_ok=True)
            write_json(self.file, self.list)

    def all(self) -> list[dict[str, str]]:
        return list(self.list)

    def get(self, wid: str) -> dict[str, str] | None:
        return next((w for w in self.list if w["id"] == wid), None)

    def add(self, name: str, path: str) -> dict[str, str]:
        if not path.strip():
            raise Refused("Folder path required")
        p = Path(path.strip().replace("~", str(self.home), 1) if path.strip().startswith("~") else path.strip())
        if not p.is_absolute():
            p = self.home / p
        try:
            real = p.resolve(strict=True)
        except OSError:
            raise Refused(f"No such folder: {p}") from None
        if not real.is_dir():
            raise Refused("Not a folder")
        if real != self.home and self.home not in real.parents:
            raise Refused("Folder must be inside your home folder")
        slug = re.sub(r"[^a-z0-9]+", "-", real.name.lower())[:30] + "-" + format(int(time.time() * 1000), "x")[-4:]
        with self.lock:
            while self.get(slug):
                slug += "x"
            w = {"id": slug, "name": (name or real.name)[:60], "path": str(real)}
            self.list.append(w)
            write_json(self.file, self.list)
        return w

    def remove(self, wid: str) -> None:
        with self.lock:
            self.list = [w for w in self.list if w["id"] != wid]
            write_json(self.file, self.list)

    def ensure(self, w: dict[str, str]) -> None:
        """Make sure the folder exists before an agent runs in it (scratch is made on first use)."""
        p = Path(w["path"])
        if p.exists():
            return
        if w["id"] == "scratch":
            p.mkdir(parents=True, exist_ok=True)
        else:
            raise Refused(f"Folder is gone: {p}")
