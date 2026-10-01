"""Comparing what the classifiers said.

Without hand-made ground truth there is no accuracy to report, so the useful
question changes from "which one is right" to "where do they differ, and by how
much". Two methods that agree on 95% of a sound's seconds are interchangeable
for that sound. The 5% is where a person would have to look, and this module
finds it.

Agreement is measured in seconds, not in spans. Comparing span counts would
punish a method for using a finer frame even when it labelled every second the
same way. Walking the union of both timelines and asking what each says at every
instant is the comparison that does not care about frame size.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import combinations

from .audioset import LABELS
from .spans import Span, agreement_seconds, dominant_label, label_histogram, overlaps
from .store import load_spans


@dataclass(frozen=True, slots=True)
class PairAgreement:
    """How two methods compare over one sound."""

    hash: str
    left: str
    right: str
    agreed_s: float
    covered_s: float

    @property
    def fraction(self) -> float:
        return self.agreed_s / self.covered_s if self.covered_s > 0 else 0.0

    @property
    def disagreed_s(self) -> float:
        return self.covered_s - self.agreed_s


@dataclass(slots=True)
class PairSummary:
    """Totals for one pair of methods over every sound both have run on."""

    left: str
    right: str
    files: int = 0
    agreed_s: float = 0.0
    covered_s: float = 0.0
    # Where they differ, what each called it. Keyed by (left label, right label).
    confusion: dict[tuple[str, str], float] = field(default_factory=dict)
    worst: list[PairAgreement] = field(default_factory=list)

    @property
    def fraction(self) -> float:
        return self.agreed_s / self.covered_s if self.covered_s > 0 else 0.0


@dataclass(slots=True)
class MethodSummary:
    """Totals for one method on its own."""

    method: str
    files: int = 0
    spans: int = 0
    seconds: float = 0.0
    per_label_s: dict[str, float] = field(default_factory=dict)
    dominant: dict[str, int] = field(default_factory=dict)

    @property
    def spans_per_file(self) -> float:
        return self.spans / self.files if self.files else 0.0


def method_summary(conn: sqlite3.Connection, method: str) -> MethodSummary:
    """Span counts and per-label seconds for one method across the collection."""
    out = MethodSummary(method=method, per_label_s=dict.fromkeys(LABELS, 0.0))
    for row in conn.execute(
        "SELECT label, COUNT(*) AS n, SUM(end_s - start_s) AS s "
        "FROM span WHERE method = ? GROUP BY label",
        (method,),
    ):
        out.spans += int(row["n"])
        seconds = float(row["s"] or 0.0)
        out.seconds += seconds
        out.per_label_s[str(row["label"])] = (
            out.per_label_s.get(str(row["label"]), 0.0) + seconds
        )
    out.files = int(
        conn.execute(
            "SELECT COUNT(DISTINCT hash) AS n FROM span WHERE method = ?", (method,)
        ).fetchone()["n"]
    )
    out.dominant = _dominant_counts(conn, method)
    return out


def _dominant_counts(conn: sqlite3.Connection, method: str) -> dict[str, int]:
    """For each sound, which label covers the most seconds; then count those."""
    best: dict[str, tuple[float, str]] = {}
    for row in conn.execute(
        "SELECT hash, label, SUM(end_s - start_s) AS s FROM span WHERE method = ? "
        "GROUP BY hash, label",
        (method,),
    ):
        key = str(row["hash"])
        seconds = float(row["s"] or 0.0)
        if seconds > best.get(key, (-1.0, ""))[0]:
            best[key] = (seconds, str(row["label"]))
    counts = dict.fromkeys(LABELS, 0)
    for _seconds, label in best.values():
        counts[label] = counts.get(label, 0) + 1
    return counts


def compare_pair(
    conn: sqlite3.Connection, left: str, right: str, *, worst_n: int = 20
) -> PairSummary:
    """Agreement between two methods over every sound both have spans for."""
    shared = sorted(
        {str(r["hash"]) for r in conn.execute(
            "SELECT DISTINCT hash FROM span WHERE method = ?", (left,)
        )}
        & {str(r["hash"]) for r in conn.execute(
            "SELECT DISTINCT hash FROM span WHERE method = ?", (right,)
        )}
    )
    summary = PairSummary(left=left, right=right)
    per_file: list[PairAgreement] = []
    for file_hash in shared:
        a = load_spans(conn, file_hash, left)
        b = load_spans(conn, file_hash, right)
        agreed, covered = agreement_seconds(a, b)
        if covered <= 0:
            continue
        summary.files += 1
        summary.agreed_s += agreed
        summary.covered_s += covered
        _add_confusion(summary.confusion, a, b)
        per_file.append(
            PairAgreement(
                hash=file_hash,
                left=left,
                right=right,
                agreed_s=agreed,
                covered_s=covered,
            )
        )
    # Worst means most seconds in dispute, not lowest percentage. A ten-hour
    # recording that agrees 80% of the time is a bigger problem than a two-second
    # sample that agrees not at all.
    per_file.sort(key=lambda p: p.disagreed_s, reverse=True)
    summary.worst = per_file[:worst_n]
    return summary


def all_pairs(
    conn: sqlite3.Connection, methods: Sequence[str], *, worst_n: int = 20
) -> list[PairSummary]:
    """Every unordered pair of the given methods, compared."""
    return [
        compare_pair(conn, left, right, worst_n=worst_n)
        for left, right in combinations(methods, 2)
    ]


def _add_confusion(
    into: dict[tuple[str, str], float],
    left: Sequence[Span],
    right: Sequence[Span],
) -> None:
    """Accumulate seconds by (what left said, what right said)."""
    for width, a, b in overlaps(left, right):
        into[(a, b)] = into.get((a, b), 0.0) + width


# The only labels this collection carries that were not made by a model: the
# folders the user filed sounds into. They are a weak proxy for ground truth,
# not a substitute for it. A spoken-word memo has pauses in it, a music render
# can open with four seconds of silence, and a foley recording of a guitar case
# being shut is arguably neither. Treat a score here as "does this classifier
# broadly agree with how the user organised their own material".
FOLDER_PROXY: dict[str, str] = {
    "sounds - spoken": "speech",
    "music - previous demos": "music",
    "sounds - foley": "other",
}


@dataclass(slots=True)
class ProxyScore:
    """How one method's labels line up with one folder's expected label."""

    folder: str
    expected: str
    files: int = 0
    matched_s: float = 0.0
    total_s: float = 0.0

    @property
    def fraction(self) -> float:
        return self.matched_s / self.total_s if self.total_s > 0 else 0.0


def folder_proxy(
    conn: sqlite3.Connection,
    method: str,
    folders: dict[str, str] | None = None,
) -> list[ProxyScore]:
    """Score one method against the folders the user filed sounds into.

    For each folder, the share of labelled seconds that carry the label the
    folder implies. Files are matched by a substring of their path, and a file
    with aliases in two of the folders is counted in both, which is rare enough
    to leave alone.
    """
    out: list[ProxyScore] = []
    for folder, expected in (folders or FOLDER_PROXY).items():
        score = ProxyScore(folder=folder, expected=expected)
        for row in conn.execute(
            "SELECT s.label AS label, SUM(s.end_s - s.start_s) AS seconds "
            "FROM span s WHERE s.method = ? AND s.hash IN "
            "(SELECT hash FROM alias WHERE path LIKE ?) GROUP BY s.label",
            (method, f"%{folder}%"),
        ):
            seconds = float(row["seconds"] or 0.0)
            score.total_s += seconds
            if str(row["label"]) == expected:
                score.matched_s += seconds
        score.files = int(
            conn.execute(
                "SELECT COUNT(DISTINCT s.hash) AS n FROM span s WHERE s.method = ? "
                "AND s.hash IN (SELECT hash FROM alias WHERE path LIKE ?)",
                (method, f"%{folder}%"),
            ).fetchone()["n"]
        )
        out.append(score)
    return out


def file_disagreement(
    conn: sqlite3.Connection, file_hash: str, methods: Sequence[str]
) -> dict[str, list[Span]]:
    """Every method's spans for one sound, for looking at a concrete example."""
    return {method: load_spans(conn, file_hash, method) for method in methods}


def describe_file(
    conn: sqlite3.Connection, file_hash: str, methods: Sequence[str]
) -> list[str]:
    """One human-readable line per method for one sound."""
    lines: list[str] = []
    for method, spans in file_disagreement(conn, file_hash, methods).items():
        if not spans:
            lines.append(f"  {method:<8} (no spans)")
            continue
        totals = label_histogram(spans)
        parts = " ".join(
            f"{label}={totals.get(label, 0.0):.0f}s" for label in LABELS
        )
        lines.append(
            f"  {method:<8} {len(spans):3d} spans  {parts}  "
            f"dominant={dominant_label(spans)}"
        )
    return lines
