"""Queries behind the ``dupes`` and ``stats`` commands.

These functions only read. They return plain data; the CLI does the printing.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

# A Logic project is a directory whose name ends in ``.logicx``. Its recorded
# audio lives inside it. The bytes may be identical to a sample stored
# elsewhere, but the project reads them from that exact path, so removing one
# corrupts the project that owns it. The projects in this collection exist only
# in the read-only originals, which makes that damage permanent.
#
# These paths are therefore never reclaimable. The cleanup view leaves them out
# by default and marks them as not deletable when they are shown.
BUNDLE_SUFFIXES: tuple[str, ...] = (".logicx",)

# SQLite's LIKE is case-insensitive over ASCII, which is what a macOS filesystem
# needs here.
BUNDLE_PATH_LIKE = "%.logicx/%"


def is_bundle_path(path: str) -> bool:
    """True when this path sits inside a DAW project bundle.

    The check is on a directory component, so a file merely named
    ``mix.logicx.wav`` is not caught and a file under ``Song.logicx/Media/`` is.
    """
    lower = path.lower()
    return any(f"{suffix}/" in lower for suffix in BUNDLE_SUFFIXES)


@dataclass(frozen=True, slots=True)
class DuplicateGroup:
    """One blob that is reachable through more than one path."""

    file_hash: str
    size_bytes: int
    paths: tuple[str, ...]

    @property
    def copies(self) -> int:
        return len(self.paths)

    @property
    def wasted_bytes(self) -> int:
        """Bytes that would be freed if only one copy of the blob remained."""
        return (self.copies - 1) * self.size_bytes


@dataclass(frozen=True, slots=True)
class DuplicateSummary:
    """Totals over every duplicated blob."""

    groups: int
    extra_copies: int
    wasted_bytes: int


@dataclass(frozen=True, slots=True)
class RedundancyReport:
    """Does every blob under one root also live under another root?"""

    subject_root: str
    reference_root: str
    subject_blobs: int
    subject_bytes: int
    twinned_blobs: int
    twinned_bytes: int
    untwinned_blobs: int
    untwinned_bytes: int
    untwinned_examples: tuple[tuple[str, str, int], ...] = ()

    @property
    def fully_redundant(self) -> bool:
        return self.subject_blobs > 0 and self.untwinned_blobs == 0


@dataclass(frozen=True, slots=True)
class RootStats:
    """Per-root counters."""

    root: str
    aliases: int
    bytes_on_disk: int
    distinct_blobs: int


@dataclass(frozen=True, slots=True)
class Stats:
    """Everything the ``stats`` command prints."""

    aliases: int
    blobs: int
    logical_bytes: int
    physical_bytes: int
    probed_blobs: int
    probe_failures: int
    peaks_cached: int
    total_duration_s: float
    favorites: int
    tags: int
    roots: tuple[RootStats, ...] = ()
    extensions: tuple[tuple[str, int], ...] = ()
    codecs: tuple[tuple[str, int], ...] = ()


def duplicate_groups(
    conn: sqlite3.Connection, *, limit: int | None = None
) -> list[DuplicateGroup]:
    """Every blob with more than one alias, largest waste first."""
    sql = (
        "SELECT b.hash AS hash, b.size_bytes AS size_bytes, COUNT(*) AS n "
        "FROM alias a JOIN blob b ON b.hash = a.hash "
        "GROUP BY b.hash HAVING n > 1 "
        "ORDER BY (n - 1) * b.size_bytes DESC, b.hash"
    )
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    groups: list[DuplicateGroup] = []
    for row in conn.execute(sql).fetchall():
        paths = [
            r["path"]
            for r in conn.execute(
                "SELECT path FROM alias WHERE hash = ? ORDER BY path",
                (row["hash"],),
            )
        ]
        groups.append(
            DuplicateGroup(
                file_hash=row["hash"],
                size_bytes=row["size_bytes"],
                paths=tuple(paths),
            )
        )
    return groups


def duplicate_summary(
    conn: sqlite3.Connection,
    *,
    within_root: bool = True,
    exclude_bundles: bool = False,
) -> DuplicateSummary:
    """Totals over duplicated blobs, computed in SQL so it stays cheap.

    ``within_root`` counts only copies that repeat inside a single root. A tree
    that is deliberately mirrored as a working copy would otherwise report
    almost every sound as duplicated, which buries the real redundancy.

    ``exclude_bundles`` drops every alias that sits inside a DAW project bundle
    before counting. Those bytes are not reclaimable at any price, so counting
    them as waste overstates what a cleanup could free. See
    :func:`is_bundle_path`.
    """
    params: list[object] = []
    if within_root:
        scope = ""
        if exclude_bundles:
            scope = "WHERE path NOT LIKE ?"
            params.append(BUNDLE_PATH_LIKE)
        sql = (
            "SELECT COUNT(*) AS groups, "
            "       COALESCE(SUM(n - 1), 0) AS extra, "
            "       COALESCE(SUM((n - 1) * size_bytes), 0) AS wasted "
            "FROM (SELECT b.hash, b.size_bytes AS size_bytes, MAX(p.c) AS n "
            "      FROM blob b JOIN (SELECT hash, root, COUNT(*) AS c "
            f"                        FROM alias {scope} GROUP BY hash, root) p "
            "        ON p.hash = b.hash "
            "      GROUP BY b.hash HAVING n > 1)"
        )
    else:
        scope = ""
        if exclude_bundles:
            scope = "WHERE a.path NOT LIKE ?"
            params.append(BUNDLE_PATH_LIKE)
        sql = (
            "SELECT COUNT(*) AS groups, "
            "       COALESCE(SUM(n - 1), 0) AS extra, "
            "       COALESCE(SUM((n - 1) * size_bytes), 0) AS wasted "
            "FROM (SELECT b.hash, b.size_bytes AS size_bytes, COUNT(*) AS n "
            "      FROM alias a JOIN blob b ON b.hash = a.hash "
            f"      {scope} "
            "      GROUP BY b.hash HAVING n > 1)"
        )
    row = conn.execute(sql, params).fetchone()
    return DuplicateSummary(
        groups=row["groups"],
        extra_copies=row["extra"],
        wasted_bytes=row["wasted"],
    )


def redundancy(
    conn: sqlite3.Connection,
    subject_root: str,
    reference_root: str,
    *,
    examples: int = 25,
) -> RedundancyReport:
    """Count blobs under ``subject_root`` that also exist under ``reference_root``.

    When the untwinned count is zero, every byte under the subject root is
    already present under the reference root.
    """
    subject = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes), 0) AS b FROM ("
        "  SELECT DISTINCT b.hash AS hash, b.size_bytes AS size_bytes"
        "  FROM alias a JOIN blob b ON b.hash = a.hash WHERE a.root = ?)",
        (subject_root,),
    ).fetchone()

    twinned = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes), 0) AS b FROM ("
        "  SELECT DISTINCT b.hash AS hash, b.size_bytes AS size_bytes"
        "  FROM alias a JOIN blob b ON b.hash = a.hash WHERE a.root = ?"
        "  AND EXISTS (SELECT 1 FROM alias c WHERE c.hash = b.hash"
        "              AND c.root = ?))",
        (subject_root, reference_root),
    ).fetchone()

    untwinned = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes), 0) AS b FROM ("
        "  SELECT DISTINCT b.hash AS hash, b.size_bytes AS size_bytes"
        "  FROM alias a JOIN blob b ON b.hash = a.hash WHERE a.root = ?"
        "  AND NOT EXISTS (SELECT 1 FROM alias c WHERE c.hash = b.hash"
        "                  AND c.root = ?))",
        (subject_root, reference_root),
    ).fetchone()

    sample = conn.execute(
        "SELECT b.hash AS hash, MIN(a.path) AS path, b.size_bytes AS size_bytes "
        "FROM alias a JOIN blob b ON b.hash = a.hash WHERE a.root = ? "
        "AND NOT EXISTS (SELECT 1 FROM alias c WHERE c.hash = b.hash "
        "                AND c.root = ?) "
        "GROUP BY b.hash ORDER BY b.size_bytes DESC LIMIT ?",
        (subject_root, reference_root, examples),
    ).fetchall()

    return RedundancyReport(
        subject_root=subject_root,
        reference_root=reference_root,
        subject_blobs=subject["n"],
        subject_bytes=subject["b"],
        twinned_blobs=twinned["n"],
        twinned_bytes=twinned["b"],
        untwinned_blobs=untwinned["n"],
        untwinned_bytes=untwinned["b"],
        untwinned_examples=tuple(
            (r["hash"], r["path"], r["size_bytes"]) for r in sample
        ),
    )


def collect_stats(conn: sqlite3.Connection) -> Stats:
    """Read the counters the ``stats`` command prints."""
    totals = conn.execute(
        "SELECT (SELECT COUNT(*) FROM alias) AS aliases, "
        "       (SELECT COUNT(*) FROM blob) AS blobs, "
        "       (SELECT COALESCE(SUM(size_bytes), 0) FROM blob) AS logical, "
        "       (SELECT COUNT(*) FROM blob WHERE probed_at IS NOT NULL) AS probed, "
        "       (SELECT COUNT(*) FROM blob WHERE probed_at IS NOT NULL "
        "        AND codec IS NULL) AS probe_failures, "
        "       (SELECT COUNT(*) FROM blob WHERE peaks IS NOT NULL) AS peaks, "
        "       (SELECT COALESCE(SUM(duration_s), 0) FROM blob) AS duration, "
        "       (SELECT COUNT(*) FROM favorite) AS favorites, "
        "       (SELECT COUNT(*) FROM tag) AS tags"
    ).fetchone()

    physical = conn.execute(
        "SELECT COALESCE(SUM(b.size_bytes), 0) AS n "
        "FROM alias a JOIN blob b ON b.hash = a.hash"
    ).fetchone()["n"]

    roots: list[RootStats] = []
    for row in conn.execute(
        "SELECT a.root AS root, COUNT(*) AS aliases, "
        "       COUNT(DISTINCT a.hash) AS blobs, "
        "       COALESCE(SUM(b.size_bytes), 0) AS bytes_on_disk "
        "FROM alias a JOIN blob b ON b.hash = a.hash "
        "GROUP BY a.root ORDER BY a.root"
    ):
        roots.append(
            RootStats(
                root=row["root"],
                aliases=row["aliases"],
                bytes_on_disk=row["bytes_on_disk"],
                distinct_blobs=row["blobs"],
            )
        )

    extensions = tuple(
        (row["ext"], row["n"])
        for row in conn.execute(
            "SELECT ext, COUNT(*) AS n FROM alias GROUP BY ext ORDER BY n DESC"
        )
    )
    codecs = tuple(
        (row["codec"] or "(unknown)", row["n"])
        for row in conn.execute(
            "SELECT codec, COUNT(*) AS n FROM blob GROUP BY codec ORDER BY n DESC"
        )
    )

    return Stats(
        aliases=totals["aliases"],
        blobs=totals["blobs"],
        logical_bytes=totals["logical"],
        physical_bytes=physical,
        probed_blobs=totals["probed"],
        probe_failures=totals["probe_failures"],
        peaks_cached=totals["peaks"],
        total_duration_s=totals["duration"],
        favorites=totals["favorites"],
        tags=totals["tags"],
        roots=tuple(roots),
        extensions=extensions,
        codecs=codecs,
    )
