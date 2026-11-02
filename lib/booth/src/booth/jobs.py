"""The booth's jobs, in SQLite under BOOTH_HOME: one row per job, its files in jobs/<id>/.

A job moves queued -> building -> rendering -> measuring -> done, or to failed (the score's fault or a passing one)
or held (the booth stopped itself on a surprise; it runs again from the start once Anthony reopens the booth). The
bot's key is unique: submitting the same key again answers the same job, so a bot that crashed mid-request never
renders twice.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from pathlib import Path

STATES = ("queued", "building", "rendering", "measuring", "done", "failed", "held")
RUNNING = ("building", "rendering", "measuring")
FILES = ("render.m4a", "video.mp4", "still.jpg", "score.json", "measure.json")


def new_id() -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(12))


class Jobs:
    def __init__(self, home: Path) -> None:
        self.home = home
        self.dir = home / "jobs"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(home / "booth.db", check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, key TEXT UNIQUE, parent TEXT, state TEXT, stage TEXT, score TEXT, want TEXT,
            created REAL, started REAL, finished REAL, timings TEXT, measure TEXT, error TEXT, attempts INTEGER DEFAULT 0)""")
        self.db.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")

    # ---- rows ----------------------------------------------------------------------------------------------------
    def add(self, key: str, score: dict, want: dict, parent: str | None = None) -> tuple[dict, bool]:
        """(job, created): an existing key answers its job."""
        old = self.by_key(key)
        if old:
            return old, False
        jid = new_id()
        self.db.execute("INSERT INTO jobs (id, key, parent, state, stage, score, want, created) VALUES (?, ?, ?, 'queued', '', ?, ?, ?)",
                        (jid, key, parent, json.dumps(score), json.dumps(want), time.time()))
        (self.dir / jid).mkdir(exist_ok=True)
        (self.dir / jid / "score.json").write_text(json.dumps(score, indent=2) + "\n")
        return self.get(jid), True

    def get(self, jid: str) -> dict | None:
        row = self.db.execute("SELECT * FROM jobs WHERE id = ?", (jid,)).fetchone()
        return self._row(row) if row else None

    def by_key(self, key: str) -> dict | None:
        row = self.db.execute("SELECT * FROM jobs WHERE key = ?", (key,)).fetchone()
        return self._row(row) if row else None

    def _row(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        for k in ("score", "want", "timings", "measure", "error"):
            d[k] = json.loads(d[k]) if d[k] else None
        return d

    def update(self, jid: str, **fields) -> None:
        for k in ("timings", "measure", "error"):
            if k in fields and fields[k] is not None:
                fields[k] = json.dumps(fields[k])
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), jid))

    def queue(self) -> list[dict]:
        return [self._row(r) for r in self.db.execute("SELECT * FROM jobs WHERE state = 'queued' ORDER BY created, id")]

    def position(self, jid: str) -> int | None:
        ids = [j["id"] for j in self.queue()]
        return ids.index(jid) + 1 if jid in ids else None

    def next(self) -> dict | None:
        q = self.queue()
        return q[0] if q else None

    def today(self) -> dict:
        start = time.time() - time.time() % 86400
        rows = self.db.execute("SELECT started, finished FROM jobs WHERE started >= ?", (start,)).fetchall()
        return {"jobs": len(rows), "live_s": round(sum((f or time.time()) - s for s, f in rows))}

    def recover(self) -> None:
        """A job a crash left running is held: Live may be in any state, so a person looks first."""
        self.db.execute("UPDATE jobs SET state = 'held', error = ? WHERE state IN ('building', 'rendering', 'measuring')",
                        (json.dumps({"stage": "restart", "code": "booth_restarted", "message": "the booth restarted mid-job", "retryable": True}),))

    def requeue_held(self) -> int:
        return self.db.execute("UPDATE jobs SET state = 'queued', stage = '', error = NULL WHERE state = 'held'").rowcount

    def cancel(self, jid: str) -> bool:
        return self.db.execute("UPDATE jobs SET state = 'failed', error = ? WHERE id = ? AND state = 'queued'",
                               (json.dumps({"stage": "queue", "code": "cancelled", "message": "cancelled", "retryable": False}), jid)).rowcount > 0

    def files(self, jid: str) -> list[str]:
        d = self.dir / jid
        return [f for f in FILES if (d / f).is_file()]

    # ---- the booth's own switches ---------------------------------------------------------------------------------
    def kv(self, k: str, default: str | None = None) -> str | None:
        row = self.db.execute("SELECT v FROM kv WHERE k = ?", (k,)).fetchone()
        return row[0] if row else default

    def set_kv(self, k: str, v: str) -> None:
        self.db.execute("INSERT INTO kv (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v", (k, v))

    def public(self, job: dict) -> dict:
        """What GET /v1/jobs/{id} answers."""
        return {"job": job["id"], "key": job["key"], "state": job["state"], "stage": job["stage"], "parent": job["parent"],
                "position": self.position(job["id"]), "timings": job["timings"] or {}, "measure": job["measure"],
                "files": self.files(job["id"]) if job["state"] == "done" else [], "error": job["error"]}
