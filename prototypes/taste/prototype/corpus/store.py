"""
SQLite-backed append-only corpus store.
Stores AnnotationEntry rows and cached AudioProfile JSON blobs.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

from .models import AnnotationEntry

_DEFAULT_DB = Path(__file__).parent.parent.parent / "taste_corpus.db"

_CREATE_ANNOTATIONS = """
CREATE TABLE IF NOT EXISTS annotations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    clip_id     TEXT NOT NULL,
    source_track TEXT NOT NULL,
    time_start  REAL NOT NULL,
    time_end    REAL NOT NULL,
    decomposition TEXT NOT NULL DEFAULT 'full_mix',
    evaluation_lens TEXT NOT NULL DEFAULT 'overall',
    verdict     INTEGER NOT NULL,
    what_works  TEXT NOT NULL DEFAULT '',
    what_fails  TEXT NOT NULL DEFAULT '',
    comparison_anchors TEXT NOT NULL DEFAULT '',
    notes       TEXT NOT NULL DEFAULT '',
    embedding   BLOB,
    timestamp   REAL NOT NULL,
    source_tag  TEXT NOT NULL DEFAULT 'manual',
    corrects    TEXT
);
"""

_CREATE_PROFILES = """
CREATE TABLE IF NOT EXISTS audio_profiles (
    clip_id     TEXT PRIMARY KEY,
    profile_json TEXT NOT NULL,
    cached_at   REAL NOT NULL
);
"""

_CREATE_IDX_CLIP = "CREATE INDEX IF NOT EXISTS idx_clip_id ON annotations(clip_id);"
_CREATE_IDX_VERDICT = "CREATE INDEX IF NOT EXISTS idx_verdict ON annotations(verdict);"


class CorpusStore:
    def __init__(self, db_path: Path = _DEFAULT_DB):
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self):
        c = self._conn
        c.execute(_CREATE_ANNOTATIONS)
        c.execute(_CREATE_PROFILES)
        c.execute(_CREATE_IDX_CLIP)
        c.execute(_CREATE_IDX_VERDICT)
        c.commit()

    def add_annotation(self, entry: AnnotationEntry) -> int:
        import struct
        emb_blob = (
            struct.pack(f"{len(entry.embedding)}f", *entry.embedding)
            if entry.embedding else None
        )
        cur = self._conn.execute(
            """INSERT INTO annotations
               (clip_id, source_track, time_start, time_end, decomposition,
                evaluation_lens, verdict, what_works, what_fails,
                comparison_anchors, notes, embedding, timestamp, source_tag, corrects)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                entry.clip_id,
                entry.source_track,
                entry.time_range[0],
                entry.time_range[1],
                entry.decomposition,
                entry.evaluation_lens,
                entry.verdict,
                entry.what_works,
                entry.what_fails,
                entry.comparison_anchors,
                entry.notes,
                emb_blob,
                entry.timestamp,
                entry.source_tag,
                entry.corrects,
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_all_annotations(self) -> list[AnnotationEntry]:
        rows = self._conn.execute(
            "SELECT * FROM annotations ORDER BY timestamp ASC"
        ).fetchall()
        return [_row_to_entry(row) for row in rows]

    def get_by_clip_id(self, clip_id: str) -> list[AnnotationEntry]:
        rows = self._conn.execute(
            "SELECT * FROM annotations WHERE clip_id = ? ORDER BY timestamp ASC",
            (clip_id,),
        ).fetchall()
        return [_row_to_entry(row) for row in rows]

    def get_by_decomposition(self, decomposition: str) -> list[AnnotationEntry]:
        rows = self._conn.execute(
            "SELECT * FROM annotations WHERE decomposition = ? ORDER BY timestamp ASC",
            (decomposition,),
        ).fetchall()
        return [_row_to_entry(row) for row in rows]

    def search_text(self, query: str) -> list[AnnotationEntry]:
        like = f"%{query}%"
        rows = self._conn.execute(
            """SELECT * FROM annotations WHERE
               what_works LIKE ? OR what_fails LIKE ? OR
               comparison_anchors LIKE ? OR notes LIKE ?
               ORDER BY timestamp DESC""",
            (like, like, like, like),
        ).fetchall()
        return [_row_to_entry(row) for row in rows]

    def stats(self) -> dict:
        total = self._conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]
        by_verdict: dict[int, int] = {}
        for row in self._conn.execute(
            "SELECT verdict, COUNT(*) FROM annotations GROUP BY verdict"
        ).fetchall():
            by_verdict[int(row[0])] = int(row[1])
        by_tag: dict[str, int] = {}
        for row in self._conn.execute(
            "SELECT source_tag, COUNT(*) FROM annotations GROUP BY source_tag"
        ).fetchall():
            by_tag[str(row[0])] = int(row[1])
        by_lens: dict[str, int] = {}
        for row in self._conn.execute(
            "SELECT evaluation_lens, COUNT(*) FROM annotations GROUP BY evaluation_lens"
        ).fetchall():
            by_lens[str(row[0])] = int(row[1])
        return {
            "total": total,
            "by_verdict": by_verdict,
            "by_source_tag": by_tag,
            "by_evaluation_lens": by_lens,
        }

    def cache_profile(self, clip_id: str, profile_json: str):
        self._conn.execute(
            """INSERT OR REPLACE INTO audio_profiles (clip_id, profile_json, cached_at)
               VALUES (?, ?, ?)""",
            (clip_id, profile_json, time.time()),
        )
        self._conn.commit()

    def get_cached_profile(self, clip_id: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT profile_json FROM audio_profiles WHERE clip_id = ?",
            (clip_id,),
        ).fetchone()
        return row[0] if row else None

    def close(self):
        self._conn.close()


def _row_to_entry(row: sqlite3.Row) -> AnnotationEntry:
    import struct
    emb_blob = row["embedding"]
    embedding = []
    if emb_blob:
        n = len(emb_blob) // 4
        embedding = list(struct.unpack(f"{n}f", emb_blob))

    return AnnotationEntry(
        clip_id=row["clip_id"],
        source_track=row["source_track"],
        time_range=(row["time_start"], row["time_end"]),
        decomposition=row["decomposition"],
        evaluation_lens=row["evaluation_lens"],
        verdict=row["verdict"],
        what_works=row["what_works"] or "",
        what_fails=row["what_fails"] or "",
        comparison_anchors=row["comparison_anchors"] or "",
        notes=row["notes"] or "",
        embedding=embedding,
        timestamp=row["timestamp"],
        source_tag=row["source_tag"],
        corrects=row["corrects"],
    )
