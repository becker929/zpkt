"""Reading and writing the ``span`` and ``segment_run`` tables.

A method's spans for a sound are replaced as a unit. Re-running a classifier
over a file deletes that method's old rows first, so a re-run never leaves two
generations of spans layered on top of each other. Other methods are untouched,
which is the whole point of keeping ``method`` on the row.

``segment_run`` is the bookkeeping beside it: one row per sound per method,
holding whether the run worked, how long it took and how much audio it saw. It
exists for two reasons. A run over the whole collection takes hours and has to
be restartable, and a file that legitimately produces no spans must not look
like a file that was never tried. It is also where the report's timing numbers
come from.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ..db import now_iso
from .spans import Span

STATUS_OK = "ok"
STATUS_FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Candidate:
    """One sound to classify, and the readable path to reach it."""

    hash: str
    path: str
    duration_s: float


@dataclass(frozen=True, slots=True)
class RunRecord:
    """The outcome of classifying one sound with one method."""

    hash: str
    method: str
    status: str
    spans: int
    audio_s: float
    elapsed_s: float
    peak_rss_b: int | None
    error: str | None


def candidates(
    conn: sqlite3.Connection,
    *,
    include_discarded: bool = False,
    limit: int | None = None,
    max_duration_s: float | None = None,
) -> list[Candidate]:
    """Every sound worth classifying, longest first.

    A sound qualifies when it still has a readable alias on disk and it has not
    been discarded. Discarded sounds are skipped because the user already
    rejected them; classifying them would spend hours on material no interface
    will ever show.

    Longest first is deliberate. It puts the slowest files at the front, so a
    run that is going to be too slow says so in the first minutes rather than
    the last hour.
    """
    where = [
        "EXISTS (SELECT 1 FROM alias a WHERE a.hash = b.hash)",
        "b.duration_s IS NOT NULL",
        "b.duration_s > 0",
    ]
    params: list[object] = []
    if not include_discarded:
        where.append("b.hash NOT IN (SELECT hash FROM soft_delete)")
    if max_duration_s is not None:
        where.append("b.duration_s <= ?")
        params.append(max_duration_s)

    sql = (
        "SELECT b.hash AS hash, b.duration_s AS duration_s, "
        "(SELECT a.path FROM alias a WHERE a.hash = b.hash ORDER BY a.id LIMIT 1) "
        "AS path FROM blob b WHERE " + " AND ".join(where) + " ORDER BY b.duration_s DESC"
    )
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    return [
        Candidate(
            hash=str(row["hash"]),
            path=str(row["path"]),
            duration_s=float(row["duration_s"]),
        )
        for row in conn.execute(sql, params)
    ]


def done_hashes(conn: sqlite3.Connection, method: str) -> set[str]:
    """Hashes this method has already been run over, successfully or not.

    A failure counts as done. A file ffmpeg cannot decode will not decode on the
    second pass either, and retrying it every restart would stall the run.
    Force a retry by deleting its ``segment_run`` row.
    """
    return {
        str(row["hash"])
        for row in conn.execute(
            "SELECT hash FROM segment_run WHERE method = ?", (method,)
        )
    }


def replace_spans(
    conn: sqlite3.Connection, file_hash: str, method: str, spans: Sequence[Span]
) -> None:
    """Swap in one method's spans for one sound. Does not commit."""
    conn.execute("DELETE FROM span WHERE hash = ? AND method = ?", (file_hash, method))
    conn.executemany(
        "INSERT INTO span (hash, method, start_s, end_s, label, confidence, detail) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                file_hash,
                method,
                float(s.start_s),
                float(s.end_s),
                s.label,
                None if s.confidence is None else float(s.confidence),
                s.detail,
            )
            for s in spans
        ],
    )


def record_run(conn: sqlite3.Connection, record: RunRecord) -> None:
    """Save the outcome of one classification. Does not commit."""
    conn.execute(
        "INSERT INTO segment_run "
        "(hash, method, status, spans, audio_s, elapsed_s, peak_rss_b, error, ran_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(hash, method) DO UPDATE SET "
        "status=excluded.status, spans=excluded.spans, audio_s=excluded.audio_s, "
        "elapsed_s=excluded.elapsed_s, peak_rss_b=excluded.peak_rss_b, "
        "error=excluded.error, ran_at=excluded.ran_at",
        (
            record.hash,
            record.method,
            record.status,
            record.spans,
            record.audio_s,
            record.elapsed_s,
            record.peak_rss_b,
            record.error,
            now_iso(),
        ),
    )


def load_spans(
    conn: sqlite3.Connection, file_hash: str, method: str
) -> list[Span]:
    """Read one method's spans for one sound, in time order."""
    return [
        Span(
            start_s=float(row["start_s"]),
            end_s=float(row["end_s"]),
            label=str(row["label"]),
            confidence=None if row["confidence"] is None else float(row["confidence"]),
            detail=None if row["detail"] is None else str(row["detail"]),
        )
        for row in conn.execute(
            "SELECT start_s, end_s, label, confidence, detail FROM span "
            "WHERE hash = ? AND method = ? ORDER BY start_s, id",
            (file_hash, method),
        )
    ]


def methods_present(conn: sqlite3.Connection) -> list[str]:
    """Every method name that has written at least one span."""
    return [
        str(row["method"])
        for row in conn.execute(
            "SELECT DISTINCT method FROM span ORDER BY method"
        )
    ]


def run_totals(conn: sqlite3.Connection, method: str) -> dict[str, float]:
    """Counters for one method's run: files, audio seconds, wall seconds."""
    row = conn.execute(
        "SELECT COUNT(*) AS files, "
        "SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) AS ok, "
        "COALESCE(SUM(audio_s), 0) AS audio_s, "
        "COALESCE(SUM(elapsed_s), 0) AS elapsed_s, "
        "COALESCE(MAX(peak_rss_b), 0) AS peak_rss_b, "
        "COALESCE(SUM(spans), 0) AS spans "
        "FROM segment_run WHERE method = ?",
        (STATUS_OK, method),
    ).fetchone()
    return {
        "files": float(row["files"]),
        "ok": float(row["ok"] or 0),
        "audio_s": float(row["audio_s"]),
        "elapsed_s": float(row["elapsed_s"]),
        "peak_rss_b": float(row["peak_rss_b"]),
        "spans": float(row["spans"]),
    }


def commit_all(conn: sqlite3.Connection, records: Iterable[RunRecord]) -> int:
    """Write a batch of run records and commit. Returns how many were written."""
    count = 0
    for record in records:
        record_run(conn, record)
        count += 1
    conn.commit()
    return count
