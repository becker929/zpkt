"""Where the chat is kept: messages in SQLite, media as content-addressed files, and turn timings.

    <root>/studio.sqlite3        conversations, messages, timings
    <root>/media/ab/<sha256>.ext speech replays, music, screenshots (served immutable)

Everything runs on the event loop's thread; the writes are tiny. Media files may be written from worker threads
(they never touch the database).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .model import Kind, MediaRef, Message

MEDIA_URL = "/studio/media/"
MEDIA_NAME = re.compile(r"^[0-9a-f]{64}\.[a-z0-9]{1,5}$")
MIME = {"flac": "audio/flac", "mp3": "audio/mpeg", "m4a": "audio/mp4", "wav": "audio/wav",
        "webp": "image/webp", "png": "image/png", "jpg": "image/jpeg"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY, created REAL NOT NULL, title TEXT NOT NULL DEFAULT '', claude_session TEXT);
CREATE TABLE IF NOT EXISTS messages (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, conversation TEXT NOT NULL, kind TEXT NOT NULL,
    created REAL NOT NULL, turn TEXT, rev INTEGER NOT NULL DEFAULT 0, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS messages_by_conversation ON messages (conversation, seq);
CREATE TABLE IF NOT EXISTS timings (
    id INTEGER PRIMARY KEY AUTOINCREMENT, conversation TEXT NOT NULL, turn TEXT NOT NULL, name TEXT NOT NULL,
    ms REAL, source TEXT NOT NULL, at REAL NOT NULL, extra TEXT);
CREATE INDEX IF NOT EXISTS timings_by_turn ON timings (turn);
"""


@dataclass
class Conversation:
    id: str
    created: float
    title: str = ""
    claude_session: str | None = None

    def wire(self) -> dict[str, Any]:
        return {"id": self.id, "created": self.created, "title": self.title}


def new_id(prefix: str) -> str:
    return prefix + time.strftime("%Y%m%d%H%M%S") + secrets.token_hex(2)


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.media_dir = root / "media"
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(root / "studio.sqlite3", isolation_level=None, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    # --- conversations -------------------------------------------------------
    def conversation(self) -> Conversation:
        """The current conversation (the newest), made on first use."""
        row = self.db.execute("SELECT id, created, title, claude_session FROM conversations "
                              "ORDER BY created DESC, rowid DESC LIMIT 1").fetchone()
        return Conversation(*row) if row else self.new_conversation()

    def new_conversation(self, title: str = "") -> Conversation:
        conv = Conversation(id=new_id("c"), created=time.time(), title=title)
        self.db.execute("INSERT INTO conversations (id, created, title) VALUES (?, ?, ?)",
                        (conv.id, conv.created, conv.title))
        return conv

    def set_claude_session(self, conversation: str, session_id: str | None) -> None:
        self.db.execute("UPDATE conversations SET claude_session = ? WHERE id = ?", (session_id, conversation))

    # --- messages ------------------------------------------------------------
    def add(self, msg: Message) -> Message:
        cur = self.db.execute(
            "INSERT INTO messages (conversation, kind, created, turn, rev, data) VALUES (?, ?, ?, ?, 0, ?)",
            (msg.conversation, msg.kind.value, msg.created, msg.turn, json.dumps(msg.data)))
        msg.seq, msg.rev = int(cur.lastrowid), 0
        return msg

    def update(self, msg: Message) -> Message:
        msg.rev += 1
        self.db.execute("UPDATE messages SET data = ?, rev = ? WHERE seq = ?", (json.dumps(msg.data), msg.rev, msg.seq))
        return msg

    def get(self, seq: int) -> Message | None:
        row = self.db.execute("SELECT seq, conversation, kind, created, turn, rev, data FROM messages WHERE seq = ?",
                              (seq,)).fetchone()
        return _message(row) if row else None

    def page(self, conversation: str, before: int | None = None, limit: int = 30) -> tuple[list[Message], bool]:
        """Up to `limit` messages before `before` (or the newest), oldest first, and whether older ones exist."""
        limit = max(1, min(limit, 200))
        rows = self.db.execute(
            "SELECT seq, conversation, kind, created, turn, rev, data FROM messages "
            "WHERE conversation = ? AND seq < ? ORDER BY seq DESC LIMIT ?",
            (conversation, before if before is not None else 2**62, limit + 1)).fetchall()
        has_more = len(rows) > limit
        return [_message(r) for r in reversed(rows[:limit])], has_more

    def last(self, conversation: str, kind: Kind) -> Message | None:
        row = self.db.execute(
            "SELECT seq, conversation, kind, created, turn, rev, data FROM messages "
            "WHERE conversation = ? AND kind = ? ORDER BY seq DESC LIMIT 1", (conversation, kind.value)).fetchone()
        return _message(row) if row else None

    # --- media ---------------------------------------------------------------
    def put_media(self, data: bytes, ext: str, **extra: Any) -> MediaRef:
        name = f"{hashlib.sha256(data).hexdigest()}.{ext}"
        path = self.media_dir / name[:2] / name
        if not path.exists():
            path.parent.mkdir(exist_ok=True)
            tmp = path.with_suffix(f".{os.getpid()}.{secrets.token_hex(3)}.tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        return MediaRef(url=MEDIA_URL + name, type=MIME.get(ext, "application/octet-stream"), bytes=len(data),
                        extra=tuple(sorted(extra.items())))

    def media_file(self, name: str) -> Path | None:
        if not MEDIA_NAME.match(name):
            return None
        path = self.media_dir / name[:2] / name
        return path if path.is_file() else None

    # --- timings -------------------------------------------------------------
    def mark(self, conversation: str, turn: str, name: str, ms: float | None, source: str = "mac",
             extra: dict[str, Any] | None = None) -> None:
        self.db.execute("INSERT INTO timings (conversation, turn, name, ms, source, at, extra) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (conversation, turn, name, ms, source, time.time(), json.dumps(extra) if extra else None))

    def timings(self, turns: int = 10) -> list[dict[str, Any]]:
        """The last `turns` turns, newest first, each with its marks in the order they were taken."""
        ids = [r[0] for r in self.db.execute(
            "SELECT turn FROM timings GROUP BY turn ORDER BY MAX(id) DESC LIMIT ?", (max(1, min(turns, 100)),))]
        out = []
        for turn in ids:
            marks = [{"name": n, "ms": ms, "source": s, "at": at, **(json.loads(x) if x else {})}
                     for n, ms, s, at, x in self.db.execute(
                         "SELECT name, ms, source, at, extra FROM timings WHERE turn = ? ORDER BY id", (turn,))]
            out.append({"turn": turn, "at": marks[0]["at"] if marks else None, "marks": marks})
        return out


def _message(row: tuple) -> Message:
    seq, conversation, kind, created, turn, rev, data = row
    return Message(kind=Kind(kind), data=json.loads(data), turn=turn, conversation=conversation, seq=seq,
                   created=created, rev=rev)
