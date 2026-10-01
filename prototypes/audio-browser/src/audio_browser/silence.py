"""Dead air: measuring it, storing it, and reading it back.

A quarter of the collection is silence — 11.5 hours of 45.8 — nearly all of it
leading and trailing silence on stems and long empty stretches inside project
bounces. Two things follow: the player should not make anyone sit through it,
and the statistics should stop counting it as listening time.

Every gap down to 0.4 seconds is measured once and stored. **The floor is
applied at read time**, so the 2 second minimum is a setting rather than a
property of the data, and turning it down needs no re-measurement.

Nothing here writes to an audio file. ``ffmpeg`` is run with ``-f null -``,
which decodes and discards; the only output is what it prints to stderr.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
import sqlite3

MIN_GAP_S = 2.0
"""The shortest gap worth skipping.

A 2 second floor recovers 10.4 of the 11.5 available hours. Going down to 0.4
buys 1.1 hours more and jumps over musical rests and the gap between two drum
hits, so the player would jitter. Two seconds never lands inside a phrase.
"""

NOISE_DB = -50.0
"""What counts as silent. Below this is dead air, not a quiet passage."""

MEASURE_GAP_S = 0.4
"""The shortest gap that is stored. Below the floor on purpose: see the module
docstring. Storing more than is skipped is what keeps the floor adjustable.
"""

TIMEOUT_S = 600.0
"""Give up on one file after ten minutes. The longest sound here is under one."""

_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_END = re.compile(r"silence_end:\s*(-?[\d.]+)")
_MAX_DB = re.compile(r"max_volume:\s*(-?[\d.]+) dB")
_MEAN_DB = re.compile(r"mean_volume:\s*(-?[\d.]+) dB")
_DURATION = re.compile(r"time=(\d+):(\d\d):(\d\d(?:\.\d+)?)")


class SilenceError(Exception):
    """ffmpeg could not read this file."""


@dataclass(frozen=True, slots=True)
class Interval:
    """One gap, in seconds from the start of the sound."""

    start_s: float
    end_s: float

    @property
    def length_s(self) -> float:
        return max(0.0, self.end_s - self.start_s)


@dataclass(frozen=True, slots=True)
class Measurement:
    """What one pass of ffmpeg found."""

    max_db: float | None
    mean_db: float | None
    duration_s: float | None
    intervals: tuple[Interval, ...]

    @property
    def silent_s(self) -> float:
        return sum(interval.length_s for interval in self.intervals)

    @property
    def silent_frac(self) -> float:
        if not self.duration_s:
            return 0.0
        return min(1.0, self.silent_s / self.duration_s)


def measure(path: Path, *, noise_db: float = NOISE_DB, min_gap_s: float = MEASURE_GAP_S) -> Measurement:
    """Run one decode and read the gaps and the levels off its log.

    ``silencedetect`` and ``volumedetect`` are chained into one pass, because
    two passes over 46 hours of audio is twice the work for the same answer.

    The file is opened read-only by ffmpeg and the decoded audio goes to the
    null muxer. Nothing is written anywhere.
    """
    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-af",
        f"silencedetect=n={noise_db}dB:d={min_gap_s},volumedetect",
        "-f",
        "null",
        "-",
    ]
    try:
        done = subprocess.run(
            command, capture_output=True, text=True, timeout=TIMEOUT_S, check=False
        )
    except FileNotFoundError as exc:  # pragma: no cover - ffmpeg is a hard dependency
        raise SilenceError("ffmpeg is not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise SilenceError(f"ffmpeg timed out after {TIMEOUT_S:.0f}s") from exc
    if done.returncode != 0:
        tail = (done.stderr or "").strip().splitlines()[-1:] or ["no output"]
        raise SilenceError(f"ffmpeg failed: {tail[0]}")
    return parse(done.stderr or "")


def parse(log: str) -> Measurement:
    """Read one ffmpeg log. Pure, so the parsing is testable without ffmpeg.

    A ``silence_start`` with no matching ``silence_end`` means the file ended
    inside the gap. It is closed at the last time ffmpeg reported, which is the
    end of the sound, so trailing silence is not lost.
    """
    starts = [float(value) for value in _START.findall(log)]
    ends = [float(value) for value in _END.findall(log)]

    duration: float | None = None
    stamps = _DURATION.findall(log)
    if stamps:
        hours, minutes, seconds = stamps[-1]
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    intervals: list[Interval] = []
    for index, start in enumerate(starts):
        if index < len(ends):
            end = ends[index]
        elif duration is not None:
            end = duration
        else:
            continue
        if end > start:
            intervals.append(Interval(start_s=max(0.0, start), end_s=end))

    max_db = _MAX_DB.findall(log)
    mean_db = _MEAN_DB.findall(log)
    return Measurement(
        max_db=float(max_db[-1]) if max_db else None,
        mean_db=float(mean_db[-1]) if mean_db else None,
        duration_s=duration,
        intervals=tuple(intervals),
    )


# ------------------------------------------------------------------- reading


def merged(
    intervals: Iterable[Interval],
    *,
    min_gap_s: float = MIN_GAP_S,
    duration_s: float | None = None,
) -> list[Interval]:
    """Sorted, clamped, non-overlapping, and longer than the floor.

    The twin of ``skippable`` in ``frontend/lib/silence.ts``. ffmpeg reports
    gaps in order and apart, but a re-measurement or a hand-written row could
    overlap, and merging keeps the arithmetic honest.
    """
    limit = duration_s if duration_s and duration_s > 0 else None
    clamped: list[Interval] = []
    for interval in intervals:
        start = max(0.0, interval.start_s)
        end = interval.end_s if limit is None else min(interval.end_s, limit)
        if end - start >= min_gap_s:
            clamped.append(Interval(start_s=start, end_s=end))
    clamped.sort(key=lambda i: i.start_s)

    out: list[Interval] = []
    for interval in clamped:
        if out and interval.start_s <= out[-1].end_s:
            if interval.end_s > out[-1].end_s:
                out[-1] = Interval(start_s=out[-1].start_s, end_s=interval.end_s)
            continue
        out.append(interval)
    return out


def silent_seconds(intervals: Sequence[Interval]) -> float:
    """Total seconds inside the given gaps. Assumes :func:`merged` has run."""
    return sum(interval.length_s for interval in intervals)


def sounding_seconds(
    duration_s: float | None, intervals: Sequence[Interval]
) -> float | None:
    """Wall duration minus the given gaps.

    ``None`` when the wall duration is unknown, because a sounding duration
    derived from nothing is worse than no number at all.
    """
    if duration_s is None:
        return None
    return max(0.0, duration_s - silent_seconds(intervals))


def read_intervals(
    conn: sqlite3.Connection,
    file_hash: str,
    *,
    min_gap_s: float = MIN_GAP_S,
    duration_s: float | None = None,
) -> list[Interval]:
    """Every stored gap of this sound, filtered to the asked-for floor."""
    rows = conn.execute(
        "SELECT start_s, end_s FROM silence_interval WHERE hash = ? ORDER BY start_s",
        (file_hash,),
    ).fetchall()
    raw = [Interval(start_s=float(r["start_s"]), end_s=float(r["end_s"])) for r in rows]
    return merged(raw, min_gap_s=min_gap_s, duration_s=duration_s)


def measured_at(conn: sqlite3.Connection, file_hash: str) -> sqlite3.Row | None:
    """The summary row, or ``None`` when this sound has never been measured.

    A sound with no gaps at all still has a row here, which is how "measured and
    silent nowhere" is told apart from "never measured".
    """
    row: sqlite3.Row | None = conn.execute(
        "SELECT hash, max_db, mean_db, silent_s, duration_s, silent_frac, measured_at"
        " FROM silence WHERE hash = ?",
        (file_hash,),
    ).fetchone()
    return row


# SQL for sounding duration, in one expression over ``blob b``.
#
# It is the same arithmetic as :func:`sounding_seconds`, done in SQLite so a page
# of a hundred rows is one query rather than a hundred. The floor is the module
# constant, written into the statement as a float literal so the many callers
# that share ``_SUMMARY_COLUMNS`` need not each bind a parameter.
#
# Unlike :func:`merged` this does not merge overlapping gaps. The measurement
# writes them in order and apart, so there is nothing to merge; the route that
# serves one sound's intervals does merge, and that is where an overlapping
# hand-written row would show up.
# Null has one meaning here and it is "nobody has measured this sound". A sound
# that was measured and found to hold no silence answers its wall duration, and a
# sound that has never been measured answers nothing at all. Letting the second
# borrow the first's answer would print a sounding length for 2,495 sounds nobody
# has listened to a single sample of.
SOUNDING_S_SQL = f"""
    CASE WHEN b.duration_s IS NULL
           OR NOT EXISTS (SELECT 1 FROM silence sm WHERE sm.hash = b.hash)
    THEN NULL ELSE MAX(0.0, b.duration_s - COALESCE((
      SELECT SUM(MIN(si.end_s, b.duration_s) - MAX(0.0, si.start_s))
      FROM silence_interval si
      WHERE si.hash = b.hash
        AND MIN(si.end_s, b.duration_s) - MAX(0.0, si.start_s) >= {MIN_GAP_S}
    ), 0.0)) END
"""


def write(
    conn: sqlite3.Connection,
    file_hash: str,
    measurement: Measurement,
    *,
    at: str,
    duration_s: float | None = None,
) -> int:
    """Store one measurement, replacing any earlier one for this sound.

    ``duration_s`` from the index is preferred when it is known: ffprobe already
    measured it exactly, and the value ffmpeg prints while decoding is rounded
    to the last progress line.

    Returns the number of intervals written.
    """
    wall = duration_s if duration_s is not None else measurement.duration_s
    silent = measurement.silent_s
    conn.execute(
        "INSERT INTO silence (hash, max_db, mean_db, silent_s, duration_s,"
        " silent_frac, measured_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(hash) DO UPDATE SET max_db = excluded.max_db,"
        " mean_db = excluded.mean_db, silent_s = excluded.silent_s,"
        " duration_s = excluded.duration_s, silent_frac = excluded.silent_frac,"
        " measured_at = excluded.measured_at",
        (
            file_hash,
            measurement.max_db,
            measurement.mean_db,
            silent,
            wall,
            min(1.0, silent / wall) if wall else 0.0,
            at,
        ),
    )
    conn.execute("DELETE FROM silence_interval WHERE hash = ?", (file_hash,))
    conn.executemany(
        "INSERT OR REPLACE INTO silence_interval (hash, start_s, end_s) VALUES (?, ?, ?)",
        [(file_hash, i.start_s, i.end_s) for i in measurement.intervals],
    )
    conn.commit()
    return len(measurement.intervals)


def unmeasured(
    conn: sqlite3.Connection, *, limit: int = 0, include_discarded: bool = False
) -> list[tuple[str, str, float | None]]:
    """Sounds with no ``silence`` row, as ``(hash, path, duration_s)``.

    This is what makes the measurement reproducible rather than a one-off: a
    fresh index, or 500 newly scanned sounds, are caught up by running the
    command again. Sounds that already have a row are skipped, so it is
    restartable.
    """
    where = ["NOT EXISTS (SELECT 1 FROM silence s WHERE s.hash = b.hash)"]
    if not include_discarded:
        where.append("NOT EXISTS (SELECT 1 FROM soft_delete d WHERE d.hash = b.hash)")
    sql = (
        "SELECT b.hash AS hash, b.duration_s AS duration_s,"
        " (SELECT a.path FROM alias a WHERE a.hash = b.hash ORDER BY a.id LIMIT 1) AS path"
        f" FROM blob b WHERE {' AND '.join(where)}"
        " AND EXISTS (SELECT 1 FROM alias a WHERE a.hash = b.hash)"
        " ORDER BY b.hash"
    )
    if limit > 0:
        sql += f" LIMIT {int(limit)}"
    return [
        (str(row["hash"]), str(row["path"]), row["duration_s"])
        for row in conn.execute(sql)
    ]
