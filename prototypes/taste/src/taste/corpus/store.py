"""SQLite-backed corpus store.

CorpusStore abstracts the storage layer. All queries go through this class.
Swapping to Postgres later is a store.py change, not an architecture change.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from taste.corpus.models import AnnotationEntry


_SCHEMA = """
CREATE TABLE IF NOT EXISTS annotations (
    clip_id       TEXT PRIMARY KEY,
    render_path   TEXT NOT NULL,
    profile_json  TEXT NOT NULL,
    verdict_json  TEXT NOT NULL,
    human_feedback TEXT DEFAULT '',
    score         INTEGER NOT NULL,
    tags          TEXT DEFAULT '[]',
    created_at    TEXT DEFAULT ''
);
"""


class CorpusStore:
    """Thin wrapper around SQLite for annotation storage and retrieval."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._con = sqlite3.connect(str(db_path), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._con.executescript(_SCHEMA)
        self._con.commit()

    def add(self, entry: AnnotationEntry) -> None:
        import json
        self._con.execute(
            """INSERT OR REPLACE INTO annotations
               (clip_id, render_path, profile_json, verdict_json,
                human_feedback, score, tags, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                entry.clip_id,
                entry.render_path,
                entry.profile_json,
                entry.verdict_json,
                entry.human_feedback,
                entry.score,
                json.dumps(entry.tags),
                entry.created_at,
            ),
        )
        self._con.commit()

    def get(self, clip_id: str) -> AnnotationEntry | None:
        import json
        row = self._con.execute(
            "SELECT * FROM annotations WHERE clip_id = ?", (clip_id,)
        ).fetchone()
        if row is None:
            return None
        return AnnotationEntry(
            clip_id=row["clip_id"],
            render_path=row["render_path"],
            profile_json=row["profile_json"],
            verdict_json=row["verdict_json"],
            human_feedback=row["human_feedback"],
            score=row["score"],
            tags=json.loads(row["tags"]),
            created_at=row["created_at"],
        )

    def count(self) -> int:
        return self._con.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]

    def all(self) -> list[AnnotationEntry]:
        import json
        rows = self._con.execute("SELECT * FROM annotations").fetchall()
        return [
            AnnotationEntry(
                clip_id=r["clip_id"],
                render_path=r["render_path"],
                profile_json=r["profile_json"],
                verdict_json=r["verdict_json"],
                human_feedback=r["human_feedback"],
                score=r["score"],
                tags=json.loads(r["tags"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def close(self) -> None:
        self._con.close()
