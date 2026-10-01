"""Walk the roots, hash the bytes, record blobs and aliases.

Roots are read-only. The scan opens files for reading and never writes, moves,
or deletes anything under them.

Hashing is I/O-bound and probing spawns a process per file, so both run in a
thread pool. Only this module's caller thread writes to SQLite; workers hand
results back through the pool's result iterator.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import AUDIO_EXTENSIONS
from .config import Root
from .db import now_iso
from .hashing import hash_file
from .probe import ProbeResult, probe_file

DEFAULT_WORKERS = 8
DEFAULT_BATCH = 500
_SUBMIT_CHUNK = 512
MTIME_EPSILON = 1e-6


def _stderr(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


@dataclass
class ScanStats:
    """Counters for one scan run."""

    files_found: int = 0
    files_unchanged: int = 0
    files_hashed: int = 0
    bytes_hashed: int = 0
    blobs_new: int = 0
    aliases_new: int = 0
    aliases_updated: int = 0
    aliases_pruned: int = 0
    blobs_pruned: int = 0
    probed: int = 0
    probe_errors: int = 0
    read_errors: int = 0
    roots_skipped: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0

    def as_lines(self) -> list[str]:
        return [
            f"files found      {self.files_found}",
            f"unchanged        {self.files_unchanged}",
            f"hashed           {self.files_hashed} ({_human_bytes(self.bytes_hashed)})",
            f"new blobs        {self.blobs_new}",
            f"new aliases      {self.aliases_new}",
            f"updated aliases  {self.aliases_updated}",
            f"pruned aliases   {self.aliases_pruned}",
            f"pruned blobs     {self.blobs_pruned}",
            f"probed           {self.probed}",
            f"probe errors     {self.probe_errors}",
            f"read errors      {self.read_errors}",
            f"elapsed          {self.elapsed_s:.1f}s",
        ]


@dataclass(frozen=True, slots=True)
class Candidate:
    """A file on disk that might need hashing."""

    path: str  # absolute, symlinks resolved
    root: str
    size: int
    mtime: float


@dataclass(frozen=True, slots=True)
class Hashed:
    """A hashed candidate, or a candidate that could not be read."""

    candidate: Candidate
    file_hash: str | None
    error: str | None = None


def walk_audio_files(
    root_path: Path,
    *,
    extensions: Iterable[str] = AUDIO_EXTENSIONS,
    on_error: Callable[[str], None] = _stderr,
) -> Iterator[Path]:
    """Yield every file under ``root_path`` whose extension is in the allowlist.

    Directory symlinks are not followed, so a loop cannot trap the walk. File
    symlinks are yielded and resolved later by the caller.
    """
    allow = {e.lower() for e in extensions}
    stack = [str(root_path)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                            continue
                    except OSError:
                        continue
                    if entry.name.startswith("._"):
                        continue  # AppleDouble sidecar, never audio
                    ext = os.path.splitext(entry.name)[1].lower()
                    if ext in allow:
                        yield Path(entry.path)
        except OSError as exc:
            on_error(f"skip directory {current}: {exc}")


def scan_roots(
    conn: sqlite3.Connection,
    roots: Iterable[Root],
    *,
    workers: int = DEFAULT_WORKERS,
    batch_size: int = DEFAULT_BATCH,
    prune: bool = True,
    probe: bool = True,
    reprobe: bool = False,
    log: Callable[[str], None] = _stderr,
    progress_every: int = 250,
) -> ScanStats:
    """Index every root. Returns counters describing what changed."""
    started = time.monotonic()
    stats = ScanStats()
    roots = list(roots)

    known = _load_known_aliases(conn)
    seen_paths: set[str] = set()
    prunable_roots: list[str] = []

    for root in roots:
        if not root.path.exists():
            log(f"root {root.name!r} does not exist at {root.path}; skipping")
            stats.roots_skipped.append(root.name)
            continue
        log(f"scanning root {root.name!r} at {root.path}")
        found_before = stats.files_found
        candidates = _candidates_for_root(root, known, seen_paths, stats, log)
        _index_candidates(
            conn,
            candidates,
            stats=stats,
            workers=workers,
            batch_size=batch_size,
            log=log,
            progress_every=progress_every,
        )
        if stats.files_found > found_before:
            prunable_roots.append(root.name)
        else:
            # An empty root usually means an unmounted volume, not a deletion.
            # Pruning it would throw away the whole index for that tree.
            log(f"root {root.name!r} yielded no audio files; not pruning it")

    if prune and prunable_roots:
        _prune(conn, prunable_roots, seen_paths, stats, log)

    if probe:
        _probe_pass(
            conn,
            stats=stats,
            workers=workers,
            batch_size=batch_size,
            reprobe=reprobe,
            log=log,
            progress_every=progress_every,
        )

    conn.commit()
    stats.elapsed_s = time.monotonic() - started
    return stats


def _load_known_aliases(
    conn: sqlite3.Connection,
) -> dict[str, tuple[int, float, str]]:
    """Map path -> (size_bytes, mtime, root) for everything already indexed."""
    rows = conn.execute(
        "SELECT a.path, a.mtime, a.root, b.size_bytes "
        "FROM alias a JOIN blob b ON b.hash = a.hash"
    ).fetchall()
    return {r["path"]: (r["size_bytes"], r["mtime"], r["root"]) for r in rows}


def _candidates_for_root(
    root: Root,
    known: dict[str, tuple[int, float, str]],
    seen_paths: set[str],
    stats: ScanStats,
    log: Callable[[str], None],
) -> Iterator[Candidate]:
    """Yield the files under one root that need hashing.

    Files already recorded with the same size, mtime, and root are skipped.
    """
    for raw_path in walk_audio_files(root.path, on_error=log):
        try:
            resolved = raw_path.resolve()
            st = resolved.stat()
        except OSError as exc:
            stats.read_errors += 1
            log(f"skip {raw_path}: {exc}")
            continue
        if not os.path.isfile(resolved):
            continue

        key = str(resolved)
        if key in seen_paths:
            continue  # two symlinks onto the same file
        seen_paths.add(key)
        stats.files_found += 1

        prior = known.get(key)
        if (
            prior is not None
            and prior[0] == st.st_size
            and abs(prior[1] - st.st_mtime) < MTIME_EPSILON
            and prior[2] == root.name
        ):
            stats.files_unchanged += 1
            continue

        yield Candidate(
            path=key, root=root.name, size=st.st_size, mtime=st.st_mtime
        )


def _hash_candidate(candidate: Candidate) -> Hashed:
    try:
        digest = hash_file(Path(candidate.path))
    except OSError as exc:
        return Hashed(candidate, None, error=str(exc))
    return Hashed(candidate, digest)


def _index_candidates(
    conn: sqlite3.Connection,
    candidates: Iterator[Candidate],
    *,
    stats: ScanStats,
    workers: int,
    batch_size: int,
    log: Callable[[str], None],
    progress_every: int,
) -> None:
    """Hash candidates in a thread pool and write the rows from this thread."""
    pending = 0
    last_report = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for chunk in _chunks(candidates, _SUBMIT_CHUNK):
            for result in pool.map(_hash_candidate, chunk):
                if result.file_hash is None:
                    stats.read_errors += 1
                    log(f"skip {result.candidate.path}: {result.error}")
                    continue
                _write_row(conn, result, stats)
                stats.files_hashed += 1
                stats.bytes_hashed += result.candidate.size
                pending += 1
                if pending >= batch_size:
                    conn.commit()
                    pending = 0
                if (
                    progress_every
                    and stats.files_hashed % progress_every == 0
                    and time.monotonic() - last_report > 1.0
                ):
                    last_report = time.monotonic()
                    log(
                        f"  hashed {stats.files_hashed} files, "
                        f"{_human_bytes(stats.bytes_hashed)}"
                    )
    conn.commit()


def _write_row(conn: sqlite3.Connection, result: Hashed, stats: ScanStats) -> None:
    candidate = result.candidate
    digest = result.file_hash
    assert digest is not None
    now = now_iso()

    cur = conn.execute(
        "INSERT INTO blob (hash, size_bytes) VALUES (?, ?) "
        "ON CONFLICT(hash) DO NOTHING",
        (digest, candidate.size),
    )
    if cur.rowcount:
        stats.blobs_new += 1

    filename = os.path.basename(candidate.path)
    ext = os.path.splitext(filename)[1].lower()
    existed = conn.execute(
        "SELECT 1 FROM alias WHERE path = ?", (candidate.path,)
    ).fetchone()
    conn.execute(
        "INSERT INTO alias (hash, path, root, filename, ext, mtime, seen_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(path) DO UPDATE SET "
        "hash = excluded.hash, root = excluded.root, "
        "filename = excluded.filename, ext = excluded.ext, "
        "mtime = excluded.mtime, seen_at = excluded.seen_at",
        (
            digest,
            candidate.path,
            candidate.root,
            filename,
            ext,
            candidate.mtime,
            now,
        ),
    )
    if existed:
        stats.aliases_updated += 1
    else:
        stats.aliases_new += 1


def _prune(
    conn: sqlite3.Connection,
    roots: list[str],
    seen_paths: set[str],
    stats: ScanStats,
    log: Callable[[str], None],
) -> None:
    """Drop aliases whose file is gone, then blobs that lost every alias.

    A blob that is favorited or tagged is kept even with no alias, so a marked
    sound survives a move.
    """
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS scan_seen (path TEXT PRIMARY KEY)")
    conn.execute("DELETE FROM scan_seen")
    conn.executemany(
        "INSERT OR IGNORE INTO scan_seen (path) VALUES (?)",
        ((p,) for p in seen_paths),
    )
    placeholders = ",".join("?" for _ in roots)
    cur = conn.execute(
        f"DELETE FROM alias WHERE root IN ({placeholders}) "  # noqa: S608 - names are ours
        "AND path NOT IN (SELECT path FROM scan_seen)",
        roots,
    )
    stats.aliases_pruned = cur.rowcount or 0

    cur = conn.execute(
        "DELETE FROM blob WHERE hash NOT IN (SELECT hash FROM alias) "
        "AND hash NOT IN (SELECT hash FROM favorite) "
        "AND hash NOT IN (SELECT hash FROM tag)"
    )
    stats.blobs_pruned = cur.rowcount or 0
    conn.execute("DROP TABLE IF EXISTS scan_seen")
    conn.commit()
    if stats.aliases_pruned or stats.blobs_pruned:
        log(
            f"pruned {stats.aliases_pruned} missing aliases and "
            f"{stats.blobs_pruned} orphan blobs"
        )


def _probe_pass(
    conn: sqlite3.Connection,
    *,
    stats: ScanStats,
    workers: int,
    batch_size: int,
    reprobe: bool,
    log: Callable[[str], None],
    progress_every: int,
) -> None:
    """Run ffprobe over blobs that have never been probed.

    Probing is the slow part, so it happens once per blob, not once per alias.
    A failed probe still records ``probed_at`` so the next scan does not retry
    it; ``--reprobe`` clears that.
    """
    if reprobe:
        conn.execute("UPDATE blob SET probed_at = NULL")
        conn.commit()

    rows = conn.execute(
        "SELECT b.hash AS hash, MIN(a.path) AS path FROM blob b "
        "JOIN alias a ON a.hash = b.hash "
        "WHERE b.probed_at IS NULL GROUP BY b.hash"
    ).fetchall()
    if not rows:
        return
    log(f"probing {len(rows)} new blobs")

    targets = [(r["hash"], r["path"]) for r in rows]
    pending = 0
    last_report = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for chunk in _chunks(iter(targets), _SUBMIT_CHUNK):
            results = pool.map(lambda t: (t[0], probe_file(Path(t[1]))), chunk)
            for digest, probed in results:
                _write_probe(conn, digest, probed)
                stats.probed += 1
                if not probed.ok:
                    stats.probe_errors += 1
                pending += 1
                if pending >= batch_size:
                    conn.commit()
                    pending = 0
                if (
                    progress_every
                    and stats.probed % progress_every == 0
                    and time.monotonic() - last_report > 1.0
                ):
                    last_report = time.monotonic()
                    log(f"  probed {stats.probed}/{len(targets)}")
    conn.commit()


def _write_probe(
    conn: sqlite3.Connection, digest: str, probed: ProbeResult
) -> None:
    conn.execute(
        "UPDATE blob SET duration_s = ?, sample_rate = ?, channels = ?, "
        "codec = ?, probed_at = ? WHERE hash = ?",
        (
            probed.duration_s,
            probed.sample_rate,
            probed.channels,
            probed.codec,
            now_iso(),
            digest,
        ),
    )


def _chunks[T](source: Iterator[T], size: int) -> Iterator[list[T]]:
    batch: list[T] = []
    for item in source:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _human_bytes(count: int) -> str:
    step = 1024.0
    value = float(count)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < step or unit == "TiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= step
    return f"{value:.1f} TiB"
