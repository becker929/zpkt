"""Sessions and their events, kept in files, as Zpkt web kept them.

    <dir>/sessions.json         the index: one object per session (id, title, workspace, cwd, kind, engines, ...)
    <dir>/sessions/<id>.jsonl   the session's events, one per line, each numbered with `seq` and stamped `t` (ms)

Every event is appended as it happens, so a run survives the page closing and any device can replay it and follow
on. Deleting a session hides it for a week (restore brings it back), then its file goes. A damaged index entry is
skipped and the file is kept aside, never quietly overwritten. Old Zpkt web files read as they are.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from zpkt.app.ask.events import Event

Record = dict[str, Any]
ID = re.compile(r"^[0-9a-f-]{36}$")
KEEP_DELETED_S = 7 * 86400
MAIN_TITLE = "Ask"


log = logging.getLogger(__name__)


class NoSuchSession(KeyError):
    pass


class Refused(ValueError):
    """The store will not do that; `code` is the HTTP-style status and the message says why."""

    def __init__(self, message: str, code: int = 400) -> None:
        super().__init__(message)
        self.code = code


def write_json(path: Path, value: Any) -> None:
    """Atomic: a crash never leaves half a file."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=1))
    tmp.replace(path)


def load_list(path: Path, sound: Callable[[Any], bool]) -> list[Any]:
    """A list the app keeps in a file. Entries that fail `sound` are skipped; the file is kept aside as it was."""
    try:
        text = path.read_text()
    except OSError:
        return []
    try:
        data = json.loads(text)
        good = [x for x in data if sound(x)] if isinstance(data, list) else None
    except ValueError:
        good = None
    if good is None or (data and not good) or len(good) < len(data):
        aside = path.with_name(f"{path.name}.damaged-{int(path.stat().st_mtime * 1000)}")
        if text.strip() and not aside.exists():
            aside.write_text(text)
    return good or []


def _sound(entry: Any) -> bool:
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("id"), str)
        and bool(ID.match(entry["id"]))
        and isinstance(entry.get("cwd"), str)
        and isinstance(entry.get("title"), str)
    )


class SessionStore:
    """The index and the event files. One lock; subscribers are called under it and must not block (queue.put)."""

    def __init__(self, data_dir: Path, clock: Callable[[], float] = time.time) -> None:
        self.dir = Path(data_dir)
        self.sessions_dir = self.dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.dir / "sessions.json"
        self.clock = clock
        self.lock = threading.RLock()
        self.subs: dict[str, set[Callable[[Event], None]]] = {}
        self.taps: list[Callable[[str, Event], None]] = []
        self.seqs: dict[str, int] = {}
        self.index: list[Record] = load_list(self.index_file, _sound)
        for s in self.index:
            s.setdefault("updated", 0)
            if not isinstance(s.get("engines"), dict):
                s.pop("engines", None)
        self._purge()
        self._fresh_mains()

    # ---- time and files ----------------------------------------------------------------------------------------
    def now_ms(self) -> int:
        return int(self.clock() * 1000)

    def file(self, sid: str) -> Path:
        if not ID.match(sid):
            raise NoSuchSession(sid)
        return self.sessions_dir / f"{sid}.jsonl"

    def save(self) -> None:
        with self.lock:
            try:
                write_json(self.index_file, self.index)
            except OSError as exc:  # a full disk must not take the app down
                log.warning(f"ask: sessions.json not saved: {exc}")

    def _purge(self) -> None:
        cut = self.now_ms() - KEEP_DELETED_S * 1000
        gone = [s for s in self.index if s.get("deleted") and s["deleted"] < cut]
        for s in gone:
            with contextlib.suppress(OSError):
                self.file(s["id"]).unlink()
        self.index = [s for s in self.index if s not in gone]

    def _fresh_mains(self) -> None:
        """Once, for folders from before 2026-11-26: a main conversation used to be the most recent old session
        (someone's old chat, under its old title). Such a one goes back to the earlier chats, and `main` then
        makes a clean one. A main conversation that was made as one is marked `fresh` and is never touched again,
        so this does nothing the second time."""
        changed = False
        for s in self.index:
            if not s.get("main") or s.get("fresh"):
                continue
            if s.get("title") == MAIN_TITLE:  # made as the main conversation, before the mark existed
                s["fresh"] = True
            else:
                del s["main"]
            changed = True
        if changed:
            self.save()

    # ---- sessions ----------------------------------------------------------------------------------------------
    def get(self, sid: str) -> Record:
        with self.lock:
            for s in self.index:
                if s["id"] == sid and not s.get("deleted"):
                    return s
        raise NoSuchSession(sid)

    def all_sessions(self, running: Callable[[str], bool] = lambda sid: False) -> list[Record]:
        with self.lock:
            live = [{**s, "running": running(s["id"])} for s in self.index if not s.get("deleted")]
        return sorted(live, key=lambda s: s.get("updated", 0), reverse=True)

    def create(self, title: str, workspace: str, cwd: str, kind: str = "normal") -> Record:
        now = self.now_ms()
        s: Record = {
            "id": str(uuid.uuid4()),
            "title": title,
            "workspace": workspace,
            "cwd": cwd,
            "kind": kind,
            "started": False,
            "created": now,
            "updated": now,
        }
        with self.lock:
            self.index.append(s)
            self.save()
        return s

    def touch(self, s: Record) -> None:
        s["updated"] = self.now_ms()
        self.save()

    def rename(self, sid: str, title: str) -> Record:
        s = self.get(sid)
        t = " ".join(str(title or "").split())[:80]
        if not t:
            raise Refused("A title cannot be empty")
        s["title"] = t
        self.save()
        return s

    def remove(self, sid: str, running: bool = False) -> None:
        if running:
            raise Refused("Session is running", 409)
        s = self.get(sid)
        if s.get("main"):
            raise Refused("The main conversation cannot be deleted", 409)
        s["deleted"] = self.now_ms()
        self.save()

    def restore(self, sid: str) -> Record:
        with self.lock:
            for s in self.index:
                if s["id"] == sid and s.get("deleted"):
                    del s["deleted"]
                    self.save()
                    return s
        raise Refused("Nothing to restore", 404)

    def discard(self, sid: str) -> None:
        """Forget a session nothing ever happened in (its first turn was refused)."""
        with self.lock:
            if self.seqs.get(sid) or self.file(sid).exists():
                return
            self.index = [s for s in self.index if s["id"] != sid]
            self.save()

    def main(self, workspace: str, cwd: str, song: str = "") -> Record:
        """The workspace's one conversation for a song: the session marked `main` for that song, else a new, empty one
        titled "Ask". `song` "" is the desk's own sets (HW002) and every main session from before songs. Older
        sessions are never taken for it; they are the archive."""
        with self.lock:
            mine = [s for s in self.index if not s.get("deleted") and self._in(s, workspace, cwd)]
            found = next((s for s in mine if s.get("main") and s.get("song", "") == song), None)
            if found is None:
                found = self.create(MAIN_TITLE, workspace, cwd)
                found["main"] = found["fresh"] = True
                if song:
                    found["song"] = song
                self.save()
            return found

    def archive(self, workspace: str, cwd: str, running: Callable[[str], bool] = lambda sid: False) -> list[Record]:
        """The workspace's sessions that are not its main conversation, newest first."""
        return [s for s in self.all_sessions(running) if not s.get("main") and self._in(s, workspace, cwd)]

    @staticmethod
    def _in(s: Record, workspace: str, cwd: str) -> bool:
        return s.get("workspace") == workspace or (not s.get("workspace") and s.get("cwd") == cwd)

    def engine_state(self, s: Record) -> dict[str, Any]:
        """Which engines have a conversation going here (older sessions only knew Gemini)."""
        engines: dict[str, Any] = s.setdefault("engines", {"gemini": {"started": bool(s.get("started"))}})
        return engines

    # ---- events ------------------------------------------------------------------------------------------------
    def _next_seq(self, sid: str) -> int:
        if sid not in self.seqs:
            n = 0
            f = self.file(sid)
            try:
                text = f.read_text()
                n = len([ln for ln in text.split("\n") if ln])
                if text and not text.endswith("\n"):  # the last event was cut off mid-write: end its line
                    with f.open("a") as fh:
                        fh.write("\n")
            except OSError:
                pass
            self.seqs[sid] = n
        n = self.seqs[sid]
        self.seqs[sid] = n + 1
        return n

    def emit(self, sid: str, event: Event) -> Event:
        with self.lock:
            e = {**event, "seq": self._next_seq(sid), "t": self.now_ms()}
            try:
                with self.file(sid).open("a") as fh:
                    fh.write(json.dumps(e) + "\n")
            except OSError as exc:  # the event still reaches the page; it is logged as lost
                log.warning(f"ask: session {sid}: event {e['seq']} not saved: {exc}")
            for fn in list(self.subs.get(sid, ())):
                with contextlib.suppress(Exception):
                    fn(e)
            for tap in self.taps:
                try:
                    tap(sid, e)
                except Exception as exc:  # a tap must not break the run
                    log.warning(f"ask: tap failed: {exc}")
        return e

    def replay(self, sid: str, start: int = 0) -> list[Event]:
        try:
            lines = self.file(sid).read_text().split("\n")
        except OSError:
            return []
        out: list[Event] = []
        for line in [ln for ln in lines if ln][start:]:  # a bad line keeps its place, so seq stays the line number
            with contextlib.suppress(ValueError):
                e = json.loads(line)
                if isinstance(e, dict):
                    out.append(e)
        return out

    def page(self, sid: str, turns: int = 20, before: int | None = None) -> dict[str, Any]:
        """A page of a long transcript, in whole turns: the last `turns` turns, or the `turns` before the seq
        `before`. `first` is the seq of the first event given (pass it as `before` for the older page), `next` the
        seq to follow the stream from, `more` whether older events exist."""
        events = self.replay(sid)
        end = len(events) if before is None else sum(1 for e in events if e.get("seq", 0) < before)
        starts = [i for i, e in enumerate(events[:end]) if e.get("type") == "prompt"]
        begin = starts[-turns] if len(starts) > max(turns, 0) > 0 else 0
        shown = events[begin:end]
        first = shown[0].get("seq", begin) if shown else (before or 0)
        return {
            "events": shown,
            "first": first,
            "next": (events[-1].get("seq", len(events) - 1) + 1) if events else 0,
            "more": begin > 0,
        }

    def follow(self, sid: str, start: int, fn: Callable[[Event], None]) -> Callable[[], None]:
        """Replay from `start`, then call `fn` for each new event. Done under one lock, so none slips between."""
        with self.lock:
            for e in self.replay(sid, start):
                fn(e)
            self.subs.setdefault(sid, set()).add(fn)

        def stop() -> None:
            with self.lock:
                self.subs.get(sid, set()).discard(fn)

        return stop
