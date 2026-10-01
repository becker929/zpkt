"""Running one classifier over the collection.

The run is restartable. Every sound gets a ``segment_run`` row as soon as it
finishes, success or failure, and a restart skips whatever already has one. A
run over 46 hours of audio takes long enough that losing it to a closed laptop
would be a real cost.

Failures do not stop the run. A file ffmpeg cannot open is recorded with its
error and the run moves on, because one unreadable sound is not a reason to
abandon the other nine hundred.

Peak resident memory is read from the process itself after each file, so the
bakeoff report quotes a measurement rather than a guess. It is the peak for the
whole process since it started, which is the number that matters when the
question is "will this fit on this machine".
"""

from __future__ import annotations

import resource
import sqlite3
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .spans import Span
from .store import (
    STATUS_FAILED,
    STATUS_OK,
    Candidate,
    RunRecord,
    candidates,
    done_hashes,
    record_run,
    replace_spans,
)

COMMIT_EVERY = 10
# A file that took longer than this is committed on its own rather than waiting
# for the batch. The longest recording in the collection is nearly twelve hours
# and takes half an hour to classify; batching that behind nine short files
# would put half an hour of work at risk of a crash for no gain.
COMMIT_AFTER_S = 30.0


class Segmenter(Protocol):
    """What the runner needs from a classifier.

    Three members, and none of them knows about the database. A classifier is
    handed a path and gives back spans.
    """

    method: str

    def describe(self) -> str: ...

    def segment(self, path: Path, duration_s: float | None = None) -> list[Span]: ...


@dataclass(slots=True)
class RunSummary:
    """How a whole run went."""

    method: str
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    spans_written: int = 0
    audio_s: float = 0.0
    elapsed_s: float = 0.0
    peak_rss_b: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def seconds_per_audio_minute(self) -> float:
        """Wall seconds spent per minute of audio. Lower is faster."""
        if self.audio_s <= 0:
            return 0.0
        return self.elapsed_s / (self.audio_s / 60.0)

    @property
    def realtime_factor(self) -> float:
        """How many times faster than real time the classifier ran."""
        if self.elapsed_s <= 0:
            return 0.0
        return self.audio_s / self.elapsed_s

    def as_lines(self) -> list[str]:
        return [
            f"method            {self.method}",
            f"attempted         {self.attempted}",
            f"succeeded         {self.succeeded}",
            f"failed            {self.failed}",
            f"already done      {self.skipped}",
            f"spans written     {self.spans_written}",
            f"audio seconds     {self.audio_s:.1f}",
            f"wall seconds      {self.elapsed_s:.1f}",
            f"s per audio-min   {self.seconds_per_audio_minute:.2f}",
            f"realtime factor   {self.realtime_factor:.1f}x",
            f"peak rss          {self.peak_rss_b / (1 << 20):.0f} MiB",
        ]


def peak_rss_bytes() -> int:
    """Peak resident memory of this process, in bytes.

    ``ru_maxrss`` is bytes on macOS and kilobytes on Linux. The platform check
    keeps the number comparable across both.
    """
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def run_method(
    conn: sqlite3.Connection,
    segmenter: Segmenter,
    *,
    include_discarded: bool = False,
    limit: int | None = None,
    max_duration_s: float | None = None,
    force: bool = False,
    log: Callable[[str], None] = lambda _m: None,
) -> RunSummary:
    """Classify every eligible sound with one segmenter and store the spans."""
    todo = candidates(
        conn,
        include_discarded=include_discarded,
        limit=None,
        max_duration_s=max_duration_s,
    )
    already = set() if force else done_hashes(conn, segmenter.method)
    summary = RunSummary(method=segmenter.method)
    pending = [c for c in todo if c.hash not in already]
    summary.skipped = len(todo) - len(pending)
    if limit is not None:
        pending = pending[:limit]

    total_audio = sum(c.duration_s for c in pending)
    log(
        f"{segmenter.method}: {len(pending)} sounds, "
        f"{total_audio / 3600:.1f} h of audio, {summary.skipped} already done"
    )
    log(f"{segmenter.method}: {segmenter.describe()}")

    started = time.monotonic()
    for index, candidate in enumerate(pending, start=1):
        summary.attempted += 1
        record = _one(conn, segmenter, candidate, summary)
        record_run(conn, record)
        if index % COMMIT_EVERY == 0 or record.elapsed_s >= COMMIT_AFTER_S:
            conn.commit()
        done_audio = summary.audio_s
        rate = done_audio / max(time.monotonic() - started, 1e-6)
        remaining = (total_audio - done_audio) / max(rate, 1e-6)
        log(
            f"{segmenter.method} [{index}/{len(pending)}] "
            f"{candidate.duration_s:7.1f}s {record.status:<6} "
            f"{record.spans:4d} spans  {record.elapsed_s:6.1f}s  "
            f"eta {remaining / 60:.0f} min  {Path(candidate.path).name[:48]}"
        )
    conn.commit()
    summary.elapsed_s = time.monotonic() - started
    summary.peak_rss_b = peak_rss_bytes()
    return summary


def _one(
    conn: sqlite3.Connection,
    segmenter: Segmenter,
    candidate: Candidate,
    summary: RunSummary,
) -> RunRecord:
    started = time.monotonic()
    try:
        spans = segmenter.segment(Path(candidate.path), candidate.duration_s)
    except Exception as exc:  # noqa: BLE001 - one bad file must not end the run
        elapsed = time.monotonic() - started
        summary.failed += 1
        message = f"{type(exc).__name__}: {exc}"[:500]
        summary.errors.append((candidate.hash, message))
        return RunRecord(
            hash=candidate.hash,
            method=segmenter.method,
            status=STATUS_FAILED,
            spans=0,
            audio_s=candidate.duration_s,
            elapsed_s=elapsed,
            peak_rss_b=peak_rss_bytes(),
            error=message,
        )
    elapsed = time.monotonic() - started
    replace_spans(conn, candidate.hash, segmenter.method, spans)
    summary.succeeded += 1
    summary.spans_written += len(spans)
    summary.audio_s += candidate.duration_s
    return RunRecord(
        hash=candidate.hash,
        method=segmenter.method,
        status=STATUS_OK,
        spans=len(spans),
        audio_s=candidate.duration_s,
        elapsed_s=elapsed,
        peak_rss_b=peak_rss_bytes(),
        error=None,
    )


def build_segmenter(method: str) -> Segmenter:
    """Construct a classifier by name. Imports only the one that is asked for."""
    if method == "yamnet":
        from .yamnet import YamnetSegmenter  # noqa: PLC0415

        return YamnetSegmenter()
    if method == "vad":
        from .vad import VadMusicSegmenter  # noqa: PLC0415

        return VadMusicSegmenter()
    if method == "clap":
        from .clap import ClapSegmenter  # noqa: PLC0415

        return ClapSegmenter()
    raise ValueError(f"unknown method {method!r}; known: {', '.join(METHODS)}")


METHODS: Sequence[str] = ("yamnet", "vad", "clap")
