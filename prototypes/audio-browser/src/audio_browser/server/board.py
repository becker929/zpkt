"""Turning project files into board cards.

Every function here starts from a :class:`~audio_browser.projects.store.Loaded`,
which came from a file on disk, and reaches into the index only for the measures
a project document does not carry: how long its sounds run, how long they sound,
and how much space they take. Those come from ``blob``, keyed by content hash,
so they still resolve after a file moves or the working copy is rebuilt.

The cache is never asked where a project is. That answer is in the file.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from typing import Any, cast

from ..projects import model
from ..projects.store import Caps, Loaded
from ..silence import SOUNDING_S_SQL
from .models import (
    Abandonment,
    Board,
    BoardColumnState,
    CommitEntry,
    ProjectSummary,
    UnreadableProject,
)

_MEASURES_SQL = f"""
SELECT COALESCE(SUM(b.duration_s), 0)  AS duration_s,
       SUM({SOUNDING_S_SQL})           AS sounding_s,
       COALESCE(SUM(b.size_bytes), 0)  AS size_bytes,
       COUNT(*)                        AS known
FROM blob b WHERE b.hash IN (%s)
"""


def measures(
    conn: sqlite3.Connection, hashes: Sequence[str]
) -> tuple[float | None, float | None, int | None]:
    """Running time, sounding time and size of a set of hashes.

    All three are null for a project holding nothing, and for one whose sounds
    this index has never seen. Zero would be a lie in both cases: the board
    would print 0:00 against a project that may hold four minutes of audio it
    simply cannot find.
    """
    if not hashes:
        return (None, None, None)
    marks = ",".join("?" for _ in hashes)
    row = conn.execute(_MEASURES_SQL % marks, list(hashes)).fetchone()
    if row is None or int(row["known"]) == 0:
        return (None, None, None)
    return (float(row["duration_s"]), row["sounding_s"], int(row["size_bytes"]))


def verified(document: dict[str, Any]) -> bool | None:
    """Whether the sound set still hashes to what the ``stored`` commit froze.

    Null when there is nothing to check: no commit, so nothing was frozen.
    False means the file was hand-edited after the freeze, which is exactly what
    the digest exists to make visible. Because the manifest is content hashes,
    this holds for years — it still resolves after files move, get renamed, or
    the working copy is rebuilt.
    """
    commit = model.stored_commit(cast(list[dict[str, Any]], document["commits"]))
    if commit is None:
        return None
    artifact = model.commit_artifact(
        cast(str, document["id"]),
        [cast(str, s["hash"]) for s in document["sounds"]],
        "stored",
    )
    return artifact.digest == cast(str, commit["digest"])


def summary(conn: sqlite3.Connection, item: Loaded) -> ProjectSummary:
    """One board card. The caller has established the file validates."""
    document = cast(dict[str, Any], item.document)
    hashes = [cast(str, sound["hash"]) for sound in document["sounds"]]
    duration_s, sounding_s, size_bytes = measures(conn, hashes)
    abandoned = document["abandoned"]
    return ProjectSummary(
        id=cast(str, document["id"]),
        name=cast(str, document["name"]),
        column=document["column"],
        created_at=cast(str, document["created_at"]),
        updated_at=cast(str, document["updated_at"]),
        abandoned=(
            None
            if abandoned is None
            else Abandonment(
                at=abandoned["at"], from_=abandoned["from"], reason=abandoned["reason"]
            )
        ),
        commits=[
            CommitEntry(column=c["column"], at=c["at"], digest=c["digest"])
            for c in document["commits"]
        ],
        sound_count=len(hashes),
        duration_s=duration_s,
        sounding_s=sounding_s,
        size_bytes=size_bytes,
        sound_set_verified=verified(document),
    )


def unreadable(item: Loaded) -> UnreadableProject:
    return UnreadableProject(id=item.id, problem=item.problem)


def board(loaded: Sequence[Loaded], caps: Caps) -> Board:
    """Columns, caps, occupancy, and what sits off the board.

    A file that does not validate is counted in the column it names, because it
    is still holding that slot. One that names no column is counted only in
    ``unreadable``: there is no column to hold it in.
    """
    counts: dict[str, int] = {column: 0 for column in model.COLUMNS}
    broken: dict[str, int] = {column: 0 for column in model.COLUMNS}
    released = 0
    abandoned = 0
    unplaceable = 0

    for item in loaded:
        if not item.valid:
            unplaceable += 1
        column = model.slot_holder(item.document)
        if column is not None:
            counts[column] += 1
            if not item.valid:
                broken[column] += 1
            continue
        if not item.valid:
            continue
        document = cast(dict[str, Any], item.document)
        if document["abandoned"] is not None:
            abandoned += 1
        elif document["column"] == "released":
            released += 1

    return Board(
        columns=[
            BoardColumnState(
                column=column,
                cap=caps.of(column),
                count=counts[column],
                unreadable=broken[column],
                over=model.is_over(counts[column], caps.of(column)),
            )
            for column in model.COLUMNS
        ],
        released=released,
        abandoned=abandoned,
        unreadable=unplaceable,
    )
