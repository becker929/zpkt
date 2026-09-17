"""Reads and writes behind the API routes.

Every function takes a connection and returns a response model. No function
here takes a filesystem path from anywhere but the database.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..db import now_iso
from ..dedupe import deleted_sightings
from ..peaks import decode_peaks
from .. import silence
from ..report import BUNDLE_PATH_LIKE, collect_stats, duplicate_summary, is_bundle_path
from ..silence import SOUNDING_S_SQL
from .models import (
    AliasInfo,
    BulkResult,
    DeletedSighting,
    DeletedState,
    DupeGroup,
    DupeList,
    DupePath,
    FavoriteState,
    FileDetail,
    FileList,
    FileSummary,
    ListCollection,
    ListDeleted,
    ListDetail,
    ListMembership,
    ListRef,
    ListSummary,
    NameCount,
    PeaksResponse,
    RootCount,
    SilenceInterval,
    SilenceReport,
    SpanInfo,
    SpanList,
    StatsResponse,
    TriageCounts,
)
from .streaming import TRANSCODE_EXTS

MAX_LIMIT = 1000
DEFAULT_LIMIT = 100

SORT_COLUMNS: dict[str, str] = {
    "name": "pa.filename COLLATE NOCASE",
    "duration": "b.duration_s",
    # Sorting by how long a sound actually sounds, rather than how long it runs.
    # A five minute stem holding forty seconds of audio belongs next to the
    # forty second sounds, not next to the five minute ones.
    "sounding": "sounding_s",
    "size": "b.size_bytes",
    "aliases": "alias_count",
}

# Sorts whose column is null for some rows. Null goes last whichever way the
# sort runs, so an unmeasured or unprobed sound never displaces a measured one
# at the top of the page.
_NULLABLE_SORTS = frozenset({"duration", "sounding"})

# The primary alias is the lowest-numbered path that points at the hash. Every
# alias has identical bytes, so any of them would do; picking the lowest id
# keeps list output stable between requests.
_PRIMARY_JOIN = (
    "JOIN alias pa ON pa.id = (SELECT MIN(y.id) FROM alias y WHERE y.hash = b.hash)"
)

_SUMMARY_COLUMNS = f"""
    b.hash            AS hash,
    b.size_bytes      AS size_bytes,
    b.duration_s      AS duration_s,
    ({SOUNDING_S_SQL}) AS sounding_s,
    b.sample_rate     AS sample_rate,
    b.channels        AS channels,
    b.codec           AS codec,
    b.probed_at       AS probed_at,
    (b.peaks IS NOT NULL) AS has_peaks,
    pa.filename       AS filename,
    pa.ext            AS ext,
    pa.path           AS path,
    pa.root           AS root,
    (SELECT COUNT(*) FROM alias x WHERE x.hash = b.hash) AS alias_count,
    EXISTS (SELECT 1 FROM favorite f WHERE f.hash = b.hash) AS favorite,
    EXISTS (SELECT 1 FROM soft_delete d WHERE d.hash = b.hash) AS deleted
"""


@dataclass(frozen=True, slots=True)
class FileFilters:
    """The list view's filters. Every field is optional.

    ``deleted`` is the exception: it always has a value, and that value is
    ``"false"``. Discarding a sound is a request to stop seeing it, so the
    default view must exclude it without the client having to ask.
    """

    q: str | None = None
    exts: tuple[str, ...] = ()
    favorite: bool | None = None
    min_dur: float | None = None
    max_dur: float | None = None
    deleted: str = "false"


@dataclass(frozen=True, slots=True)
class PlayableAlias:
    """A path that exists on disk right now, with its extension."""

    path: Path
    ext: str
    filename: str


def normalize_ext(raw: str) -> str:
    """``WAV`` and ``.wav`` both become ``.wav``."""
    ext = raw.strip().lower()
    if not ext:
        return ""
    return ext if ext.startswith(".") else f".{ext}"


def _like(term: str) -> str:
    """Wrap a search term for a case-insensitive LIKE, escaping its wildcards."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _where(filters: FileFilters) -> tuple[str, list[object]]:
    """Build the WHERE clause shared by the count and the page query."""
    clauses: list[str] = []
    params: list[object] = []

    if filters.q:
        clauses.append(
            "EXISTS (SELECT 1 FROM alias qa WHERE qa.hash = b.hash "
            "AND qa.filename LIKE ? ESCAPE '\\')"
        )
        params.append(_like(filters.q))

    if filters.exts:
        marks = ",".join("?" for _ in filters.exts)
        clauses.append(
            f"EXISTS (SELECT 1 FROM alias ea WHERE ea.hash = b.hash "
            f"AND ea.ext IN ({marks}))"
        )
        params.extend(filters.exts)

    if filters.favorite is not None:
        keyword = "EXISTS" if filters.favorite else "NOT EXISTS"
        clauses.append(f"{keyword} (SELECT 1 FROM favorite ff WHERE ff.hash = b.hash)")

    if filters.min_dur is not None:
        clauses.append("b.duration_s IS NOT NULL AND b.duration_s >= ?")
        params.append(filters.min_dur)

    if filters.max_dur is not None:
        clauses.append("b.duration_s IS NOT NULL AND b.duration_s <= ?")
        params.append(filters.max_dur)

    if filters.deleted == "false":
        clauses.append("NOT EXISTS (SELECT 1 FROM soft_delete df WHERE df.hash = b.hash)")
    elif filters.deleted == "true":
        clauses.append("EXISTS (SELECT 1 FROM soft_delete df WHERE df.hash = b.hash)")

    if not clauses:
        return "", params
    return "WHERE " + " AND ".join(clauses), params


def _order_by(sort: str, order: str) -> str:
    column = SORT_COLUMNS[sort]
    direction = "DESC" if order == "desc" else "ASC"
    if sort in _NULLABLE_SORTS:
        # An unprobed blob has no duration and an unmeasured one has no sounding
        # length. Keep both at the end whichever way the sort runs.
        return f"ORDER BY ({column} IS NULL), {column} {direction}, b.hash"
    return f"ORDER BY {column} {direction}, b.hash"


def _summary(row: sqlite3.Row) -> FileSummary:
    return FileSummary(
        hash=row["hash"],
        filename=row["filename"],
        ext=row["ext"],
        path=row["path"],
        root=row["root"],
        size_bytes=row["size_bytes"],
        duration_s=row["duration_s"],
        sounding_s=row["sounding_s"],
        sample_rate=row["sample_rate"],
        channels=row["channels"],
        codec=row["codec"],
        alias_count=row["alias_count"],
        favorite=bool(row["favorite"]),
        deleted=bool(row["deleted"]),
        has_peaks=bool(row["has_peaks"]),
        # Taken from the primary alias. Every alias of a hash holds the same
        # bytes, but not necessarily under the same extension, so the detail
        # view recomputes this from whichever alias will actually be served.
        transcoded=str(row["ext"]).lower() in TRANSCODE_EXTS,
    )


def list_files(
    conn: sqlite3.Connection,
    filters: FileFilters,
    *,
    sort: str = "name",
    order: str = "asc",
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> FileList:
    """One page of the collection, one row per sound."""
    where, params = _where(filters)
    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM blob b {_PRIMARY_JOIN} {where}", params
    ).fetchone()["n"]

    rows = conn.execute(
        f"SELECT {_SUMMARY_COLUMNS} FROM blob b {_PRIMARY_JOIN} {where} "
        f"{_order_by(sort, order)} LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()

    return FileList(
        total=int(total),
        limit=limit,
        offset=offset,
        items=[_summary(row) for row in rows],
    )


def files_by_hash(
    conn: sqlite3.Connection, hashes: Sequence[str]
) -> list[FileSummary]:
    """List rows for a set of hashes, in the order asked for.

    A hash this index has never seen is left out rather than faked. A project
    can name a sound the working copy no longer holds — that is the point of
    addressing sounds by content — and the interface says how many are missing
    by comparing this against the project's own count.
    """
    if not hashes:
        return []
    marks = ",".join("?" for _ in hashes)
    rows = {
        str(row["hash"]): _summary(row)
        for row in conn.execute(
            f"SELECT {_SUMMARY_COLUMNS} FROM blob b {_PRIMARY_JOIN} "
            f"WHERE b.hash IN ({marks})",
            list(hashes),
        )
    }
    return [rows[h] for h in hashes if h in rows]


def blob_exists(conn: sqlite3.Connection, file_hash: str) -> bool:
    """Is this hash in the index at all?"""
    row = conn.execute(
        "SELECT 1 FROM blob WHERE hash = ?", (file_hash,)
    ).fetchone()
    return row is not None


def get_detail(
    conn: sqlite3.Connection, file_hash: str, *, transcoded_exts: frozenset[str]
) -> FileDetail | None:
    """One sound with every alias, its tags, and its favorite state."""
    row = conn.execute(
        f"SELECT {_SUMMARY_COLUMNS} FROM blob b {_PRIMARY_JOIN} WHERE b.hash = ?",
        (file_hash,),
    ).fetchone()
    if row is None:
        return None

    aliases: list[AliasInfo] = []
    for alias in conn.execute(
        "SELECT id, path, root, filename, ext, mtime FROM alias "
        "WHERE hash = ? ORDER BY id",
        (file_hash,),
    ):
        aliases.append(
            AliasInfo(
                id=alias["id"],
                path=alias["path"],
                root=alias["root"],
                filename=alias["filename"],
                ext=alias["ext"],
                mtime=alias["mtime"],
                exists=Path(alias["path"]).is_file(),
            )
        )

    tags = [
        str(t["name"])
        for t in conn.execute(
            "SELECT name FROM tag WHERE hash = ? ORDER BY name", (file_hash,)
        )
    ]
    fav = conn.execute(
        "SELECT created_at, note FROM favorite WHERE hash = ?", (file_hash,)
    ).fetchone()
    discarded = conn.execute(
        "SELECT deleted_at, note FROM soft_delete WHERE hash = ?", (file_hash,)
    ).fetchone()
    memberships = [
        ListRef(id=int(row["id"]), name=str(row["name"]))
        for row in conn.execute(
            "SELECT l.id AS id, l.name AS name FROM list l "
            "JOIN list_member m ON m.list_id = l.id WHERE m.hash = ? "
            "ORDER BY l.name COLLATE NOCASE, l.id",
            (file_hash,),
        )
    ]

    playable = next((a for a in aliases if a.exists), None)
    fields = _summary(row).model_dump()
    # The stream comes from the first alias that still exists, which is not
    # always the primary one, so decide seekability from the alias that will be
    # served rather than from the display name.
    fields["transcoded"] = (
        playable is not None and playable.ext.lower() in transcoded_exts
    )
    # Paths the dedupe command removed. They are not aliases any more, but the
    # sound was once reachable through them and that is worth showing.
    removed = [
        DeletedSighting(path=path, root=root, deleted_at=when, reason=why)
        for path, root, when, why in deleted_sightings(conn, file_hash)
    ]

    return FileDetail(
        **fields,
        aliases=aliases,
        deleted_sightings=removed,
        tags=tags,
        favorite_note=fav["note"] if fav else None,
        favorited_at=fav["created_at"] if fav else None,
        deleted_at=discarded["deleted_at"] if discarded else None,
        delete_note=discarded["note"] if discarded else None,
        lists=memberships,
        probed_at=row["probed_at"],
        playable=playable is not None,
    )


def playable_alias(
    conn: sqlite3.Connection, file_hash: str
) -> PlayableAlias | None:
    """The first alias of this hash that still exists on disk.

    Aliases go stale between scans, so the lowest-numbered one may be gone. All
    aliases share the same bytes, so any survivor is the same sound.
    """
    for row in conn.execute(
        "SELECT path, ext, filename FROM alias WHERE hash = ? ORDER BY id",
        (file_hash,),
    ):
        path = Path(row["path"])
        if path.is_file():
            return PlayableAlias(
                path=path, ext=str(row["ext"]).lower(), filename=str(row["filename"])
            )
    return None


def favorite_state(conn: sqlite3.Connection, file_hash: str) -> FavoriteState:
    """Current favorite state, and the number of paths that inherit it."""
    fav = conn.execute(
        "SELECT created_at, note FROM favorite WHERE hash = ?", (file_hash,)
    ).fetchone()
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM alias WHERE hash = ?", (file_hash,)
    ).fetchone()["n"]
    return FavoriteState(
        hash=file_hash,
        favorite=fav is not None,
        created_at=fav["created_at"] if fav else None,
        note=fav["note"] if fav else None,
        alias_count=int(count),
    )


def set_favorite(
    conn: sqlite3.Connection, file_hash: str, note: str | None = None
) -> FavoriteState:
    """Mark the hash. Every alias of it is favorited by the same row."""
    conn.execute(
        "INSERT INTO favorite (hash, created_at, note) VALUES (?, ?, ?) "
        "ON CONFLICT(hash) DO UPDATE SET note = COALESCE(excluded.note, favorite.note)",
        (file_hash, now_iso(), note),
    )
    conn.commit()
    return favorite_state(conn, file_hash)


def clear_favorite(conn: sqlite3.Connection, file_hash: str) -> FavoriteState:
    """Unmark the hash. Removing a favorite that is not set is not an error."""
    conn.execute("DELETE FROM favorite WHERE hash = ?", (file_hash,))
    conn.commit()
    return favorite_state(conn, file_hash)


# ------------------------------------------------------------------ soft delete
#
# Everything below writes rows about sounds. Nothing below opens, moves, or
# removes a file. There is no import of `os`, `shutil`, or `Path.unlink` in this
# module, and the only `Path` use is reading a path the database already holds.


def deleted_state(conn: sqlite3.Connection, file_hash: str) -> DeletedState:
    """Current soft-delete state, and how many paths inherit it."""
    row = conn.execute(
        "SELECT deleted_at, note FROM soft_delete WHERE hash = ?", (file_hash,)
    ).fetchone()
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM alias WHERE hash = ?", (file_hash,)
    ).fetchone()["n"]
    return DeletedState(
        hash=file_hash,
        deleted=row is not None,
        deleted_at=row["deleted_at"] if row else None,
        note=row["note"] if row else None,
        alias_count=int(count),
    )


def set_deleted(
    conn: sqlite3.Connection, file_hash: str, note: str | None = None
) -> DeletedState:
    """Discard a sound. Writes one row and stops there.

    The audio is not read, not moved, and not removed. Every alias of the hash
    is still on disk after this returns, which is what makes restore free.
    """
    conn.execute(
        "INSERT INTO soft_delete (hash, deleted_at, note) VALUES (?, ?, ?) "
        "ON CONFLICT(hash) DO UPDATE SET "
        "note = COALESCE(excluded.note, soft_delete.note)",
        (file_hash, now_iso(), note),
    )
    conn.commit()
    return deleted_state(conn, file_hash)


def clear_deleted(conn: sqlite3.Connection, file_hash: str) -> DeletedState:
    """Restore a sound. Restoring one that was never discarded is not an error."""
    conn.execute("DELETE FROM soft_delete WHERE hash = ?", (file_hash,))
    conn.commit()
    return deleted_state(conn, file_hash)


# ------------------------------------------------------------------------ lists


class ListNameTaken(Exception):
    """Another list already has this name."""


_LIST_COLUMNS = f"""
    l.id         AS id,
    l.name       AS name,
    l.created_at AS created_at,
    (SELECT COUNT(*) FROM list_member m WHERE m.list_id = l.id) AS member_count,
    (SELECT COALESCE(SUM(b.duration_s), 0) FROM list_member m
       JOIN blob b ON b.hash = m.hash WHERE m.list_id = l.id) AS duration_s,
    (SELECT SUM({SOUNDING_S_SQL}) FROM list_member m
       JOIN blob b ON b.hash = m.hash WHERE m.list_id = l.id) AS sounding_s,
    (SELECT COALESCE(SUM(b.size_bytes), 0) FROM list_member m
       JOIN blob b ON b.hash = m.hash WHERE m.list_id = l.id) AS size_bytes
"""


def _list_summary(row: sqlite3.Row) -> ListSummary:
    return ListSummary(
        id=int(row["id"]),
        name=str(row["name"]),
        created_at=str(row["created_at"]),
        member_count=int(row["member_count"]),
        duration_s=float(row["duration_s"]),
        # SUM over a column that is null for every row is null, which is the
        # right answer: a playlist of unmeasured sounds has no known playing
        # time. SQLite skips nulls in a mixed list, so a partly measured list
        # reports the part it knows.
        sounding_s=row["sounding_s"],
        size_bytes=int(row["size_bytes"]),
    )


def all_lists(conn: sqlite3.Connection) -> ListCollection:
    """Every list, by name. There are never enough of these to need paging."""
    rows = conn.execute(
        f"SELECT {_LIST_COLUMNS} FROM list l ORDER BY l.name COLLATE NOCASE, l.id"
    ).fetchall()
    return ListCollection(total=len(rows), items=[_list_summary(r) for r in rows])


def get_list(conn: sqlite3.Connection, list_id: int) -> ListSummary | None:
    row = conn.execute(
        f"SELECT {_LIST_COLUMNS} FROM list l WHERE l.id = ?", (list_id,)
    ).fetchone()
    return _list_summary(row) if row else None


def create_list(conn: sqlite3.Connection, name: str) -> ListSummary:
    """Make a list. The name is unique, so a repeat is a conflict, not a copy."""
    try:
        cur = conn.execute(
            "INSERT INTO list (name, created_at) VALUES (?, ?)", (name, now_iso())
        )
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ListNameTaken(name) from exc
    conn.commit()
    made = get_list(conn, int(cur.lastrowid or 0))
    assert made is not None
    return made


def rename_list(
    conn: sqlite3.Connection, list_id: int, name: str
) -> ListSummary | None:
    """Rename a list. Returns None when there is no such list."""
    if get_list(conn, list_id) is None:
        return None
    try:
        conn.execute("UPDATE list SET name = ? WHERE id = ?", (name, list_id))
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ListNameTaken(name) from exc
    conn.commit()
    return get_list(conn, list_id)


def delete_list(conn: sqlite3.Connection, list_id: int) -> ListDeleted | None:
    """Remove a list and its membership rows.

    The sounds are untouched. Membership is a label on a hash; dropping the
    label leaves the sound, its aliases, and its bytes exactly as they were.
    """
    summary = get_list(conn, list_id)
    if summary is None:
        return None
    conn.execute("DELETE FROM list WHERE id = ?", (list_id,))
    conn.commit()
    return ListDeleted(
        id=summary.id, name=summary.name, removed_members=summary.member_count
    )


def _membership(conn: sqlite3.Connection, list_id: int, file_hash: str) -> ListMembership:
    row = conn.execute(
        "SELECT position, added_at FROM list_member WHERE list_id = ? AND hash = ?",
        (list_id, file_hash),
    ).fetchone()
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM list_member WHERE list_id = ?", (list_id,)
    ).fetchone()["n"]
    return ListMembership(
        list_id=list_id,
        hash=file_hash,
        member=row is not None,
        position=int(row["position"]) if row else None,
        added_at=str(row["added_at"]) if row else None,
        member_count=int(count),
    )


def add_to_list(
    conn: sqlite3.Connection, list_id: int, file_hash: str
) -> ListMembership:
    """Put a sound at the end of a list. Adding it twice keeps the first place."""
    conn.execute(
        "INSERT INTO list_member (list_id, hash, position, added_at) "
        "VALUES (?, ?, "
        "  (SELECT COALESCE(MAX(position), 0) + 1 FROM list_member WHERE list_id = ?),"
        "  ?) "
        "ON CONFLICT(list_id, hash) DO NOTHING",
        (list_id, file_hash, list_id, now_iso()),
    )
    conn.commit()
    return _membership(conn, list_id, file_hash)


def remove_from_list(
    conn: sqlite3.Connection, list_id: int, file_hash: str
) -> ListMembership:
    """Take a sound out of a list. Removing a non-member is not an error."""
    conn.execute(
        "DELETE FROM list_member WHERE list_id = ? AND hash = ?", (list_id, file_hash)
    )
    conn.commit()
    return _membership(conn, list_id, file_hash)


def list_detail(
    conn: sqlite3.Connection,
    list_id: int,
    *,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> ListDetail | None:
    """A list and a page of its members, in the order they will play.

    Soft-deleted members are still shown. Putting a sound in a list and then
    discarding it is a contradiction the user made; hiding half of it would
    make the list's own count wrong.
    """
    summary = get_list(conn, list_id)
    if summary is None:
        return None
    rows = conn.execute(
        f"SELECT {_SUMMARY_COLUMNS} FROM blob b {_PRIMARY_JOIN} "
        "JOIN list_member m ON m.hash = b.hash WHERE m.list_id = ? "
        "ORDER BY m.position, b.hash LIMIT ? OFFSET ?",
        (list_id, limit, offset),
    ).fetchall()
    return ListDetail(
        **summary.model_dump(),
        limit=limit,
        offset=offset,
        items=[_summary(row) for row in rows],
    )


# ------------------------------------------------------------------------- bulk


def _load_batch(conn: sqlite3.Connection, hashes: list[str]) -> int:
    """Stage the batch in a temporary table and report how many are known.

    A temporary table rather than a thousand bound parameters: it keeps the
    statement one fixed string, sidesteps SQLite's parameter ceiling, and lets
    each action run as a single set operation instead of a loop.

    ``ord`` preserves the order the client sent, which becomes list position.
    """
    conn.execute(
        "CREATE TEMP TABLE IF NOT EXISTS bulk_hash ("
        "  hash TEXT PRIMARY KEY, ord INTEGER NOT NULL)"
    )
    conn.execute("DELETE FROM bulk_hash")
    conn.executemany(
        "INSERT OR IGNORE INTO bulk_hash (hash, ord) VALUES (?, ?)",
        [(h, i) for i, h in enumerate(hashes)],
    )
    return int(
        conn.execute(
            "SELECT COUNT(*) AS n FROM bulk_hash t JOIN blob b ON b.hash = t.hash"
        ).fetchone()["n"]
    )


def _apply_action(
    conn: sqlite3.Connection, action: str, list_id: int | None, when: str
) -> int:
    """Run one action over the staged batch. Returns the number of rows changed.

    Every statement joins ``blob``, so a hash the index does not know writes
    nothing. That is what makes an unknown hash a skip rather than a failure.
    """
    if action == "star":
        cur = conn.execute(
            "INSERT INTO favorite (hash, created_at) "
            "SELECT t.hash, ? FROM bulk_hash t JOIN blob b ON b.hash = t.hash "
            "WHERE NOT EXISTS (SELECT 1 FROM favorite f WHERE f.hash = t.hash)",
            (when,),
        )
    elif action == "unstar":
        cur = conn.execute(
            "DELETE FROM favorite WHERE hash IN (SELECT hash FROM bulk_hash)"
        )
    elif action == "delete":
        cur = conn.execute(
            "INSERT INTO soft_delete (hash, deleted_at) "
            "SELECT t.hash, ? FROM bulk_hash t JOIN blob b ON b.hash = t.hash "
            "WHERE NOT EXISTS (SELECT 1 FROM soft_delete d WHERE d.hash = t.hash)",
            (when,),
        )
    elif action == "restore":
        cur = conn.execute(
            "DELETE FROM soft_delete WHERE hash IN (SELECT hash FROM bulk_hash)"
        )
    elif action == "add_to_list":
        cur = conn.execute(
            "INSERT INTO list_member (list_id, hash, position, added_at) "
            "SELECT ?, t.hash, "
            "  (SELECT COALESCE(MAX(position), 0) FROM list_member WHERE list_id = ?) "
            "  + ROW_NUMBER() OVER (ORDER BY t.ord), ? "
            "FROM bulk_hash t JOIN blob b ON b.hash = t.hash "
            "WHERE NOT EXISTS (SELECT 1 FROM list_member m "
            "                  WHERE m.list_id = ? AND m.hash = t.hash)",
            (list_id, list_id, when, list_id),
        )
    elif action == "remove_from_list":
        cur = conn.execute(
            "DELETE FROM list_member WHERE list_id = ? "
            "AND hash IN (SELECT hash FROM bulk_hash)",
            (list_id,),
        )
    else:  # pragma: no cover - the action is a Literal, so this cannot happen
        raise ValueError(f"unknown bulk action: {action}")
    return max(cur.rowcount, 0)


def bulk(
    conn: sqlite3.Connection,
    hashes: list[str],
    action: str,
    list_id: int | None = None,
) -> BulkResult:
    """Apply one action to many sounds, in one transaction.

    ``BEGIN IMMEDIATE`` takes the write lock up front and the whole batch
    commits together or rolls back together. A batch of a thousand that half
    applied could not be told from one that fully applied, and no one is going
    to repair it by hand, so there is no partial outcome to report.

    No branch of this function names a file.
    """
    unique = list(dict.fromkeys(hashes))
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        matched = _load_batch(conn, unique)
        changed = _apply_action(conn, action, list_id, now_iso())
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return BulkResult(
        action=action,  # type: ignore[arg-type]
        list_id=list_id,
        requested=len(hashes),
        unique=len(unique),
        matched=matched,
        changed=changed,
        unchanged=max(matched - changed, 0),
        skipped=len(unique) - matched,
    )


# ------------------------------------------------------------------------ triage


def triage(conn: sqlite3.Connection) -> TriageCounts:
    """How far the listening has got.

    A sound counts as triaged once a decision exists about it: starred,
    discarded, or filed into a list. The union is taken over hashes, so a sound
    decided three ways is still one sound done.
    """
    row = conn.execute(
        "SELECT (SELECT COUNT(*) FROM blob) AS total, "
        "       (SELECT COUNT(*) FROM favorite) AS starred, "
        "       (SELECT COUNT(*) FROM soft_delete) AS deleted, "
        "       (SELECT COUNT(DISTINCT hash) FROM list_member) AS listed, "
        "       (SELECT COUNT(*) FROM list) AS lists, "
        "       (SELECT COUNT(*) FROM ("
        "          SELECT hash FROM favorite "
        "          UNION SELECT hash FROM soft_delete "
        "          UNION SELECT hash FROM list_member)) AS triaged"
    ).fetchone()
    total = int(row["total"])
    triaged = int(row["triaged"])
    return TriageCounts(
        total=total,
        triaged=triaged,
        untriaged=max(total - triaged, 0),
        percent=round(100.0 * triaged / total, 2) if total else 0.0,
        starred=int(row["starred"]),
        deleted=int(row["deleted"]),
        listed=int(row["listed"]),
        lists=int(row["lists"]),
    )


def peaks_response(
    conn: sqlite3.Connection,
    file_hash: str,
    packed: bytes,
    *,
    cached: bool,
) -> PeaksResponse:
    """Wrap a packed peaks blob for the API."""
    row = conn.execute(
        "SELECT duration_s FROM blob WHERE hash = ?", (file_hash,)
    ).fetchone()
    pairs = decode_peaks(packed)
    return PeaksResponse(
        hash=file_hash,
        buckets=len(pairs),
        duration_s=row["duration_s"] if row else None,
        cached=cached,
        peaks=pairs,
    )


def dupes(
    conn: sqlite3.Connection,
    *,
    limit: int = 50,
    offset: int = 0,
    within_root: bool = True,
    include_bundles: bool = False,
) -> DupeList:
    """Duplicated hashes, most wasted bytes first.

    This is the cleanup view, so its default scoping answers one question: what
    could actually be removed?

    ``within_root`` counts a copy only when it repeats inside a single root.
    Roots that mirror each other on purpose, such as a working copy of the
    library, would otherwise report nearly every sound as a duplicate and hide
    the few hundred that are genuinely redundant. Pass ``within_root=False`` to
    count every alias regardless of root.

    ``include_bundles`` is off, so copies inside DAW project bundles are left
    out. Those are a project's own media: removing one corrupts the project, and
    the projects here exist only in the read-only originals. Pass
    ``include_bundles=True`` to see them; every such path comes back with
    ``deletable=False``.
    """
    exclude_bundles = not include_bundles
    summary = duplicate_summary(
        conn, within_root=within_root, exclude_bundles=exclude_bundles
    )
    if exclude_bundles:
        unscoped = duplicate_summary(conn, within_root=within_root)
        excluded_groups = unscoped.groups - summary.groups
        excluded_bytes = unscoped.wasted_bytes - summary.wasted_bytes
    else:
        excluded_groups = 0
        excluded_bytes = 0

    params: list[object] = []
    if within_root:
        scope = ""
        if exclude_bundles:
            scope = "WHERE path NOT LIKE ?"
            params.append(BUNDLE_PATH_LIKE)
        sql = (
            "SELECT b.hash AS hash, b.size_bytes AS size_bytes, "
            "       b.duration_s AS duration_s, MAX(p.c) AS copies, "
            "       EXISTS (SELECT 1 FROM favorite f WHERE f.hash = b.hash) AS favorite "
            "FROM blob b JOIN (SELECT hash, root, COUNT(*) AS c "
            f"                  FROM alias {scope} GROUP BY hash, root) p "
            "  ON p.hash = b.hash "
            "GROUP BY b.hash HAVING copies > 1 "
            "ORDER BY (copies - 1) * b.size_bytes DESC, b.hash "
            "LIMIT ? OFFSET ?"
        )
    else:
        scope = ""
        if exclude_bundles:
            scope = "AND a.path NOT LIKE ?"
            params.append(BUNDLE_PATH_LIKE)
        sql = (
            "SELECT b.hash AS hash, b.size_bytes AS size_bytes, "
            "       b.duration_s AS duration_s, COUNT(a.id) AS copies, "
            "       EXISTS (SELECT 1 FROM favorite f WHERE f.hash = b.hash) AS favorite "
            f"FROM blob b JOIN alias a ON a.hash = b.hash {scope} "
            "GROUP BY b.hash HAVING copies > 1 "
            "ORDER BY (copies - 1) * b.size_bytes DESC, b.hash "
            "LIMIT ? OFFSET ?"
        )
    rows = conn.execute(sql, (*params, limit, offset)).fetchall()

    items: list[DupeGroup] = []
    for row in rows:
        entries = [
            DupePath(
                path=str(p["path"]),
                root=str(p["root"]),
                in_bundle=is_bundle_path(str(p["path"])),
                deletable=not is_bundle_path(str(p["path"])),
            )
            for p in conn.execute(
                "SELECT path, root FROM alias WHERE hash = ? ORDER BY id",
                (row["hash"],),
            )
        ]
        paths = [entry.path for entry in entries]
        filename = Path(paths[0]).name if paths else ""
        copies = int(row["copies"])
        items.append(
            DupeGroup(
                hash=row["hash"],
                filename=filename,
                size_bytes=row["size_bytes"],
                duration_s=row["duration_s"],
                copies=copies,
                wasted_bytes=(copies - 1) * int(row["size_bytes"]),
                favorite=bool(row["favorite"]),
                bundle_copies=sum(1 for entry in entries if entry.in_bundle),
                paths=paths,
                entries=entries,
            )
        )

    return DupeList(
        total=summary.groups,
        limit=limit,
        offset=offset,
        extra_copies=summary.extra_copies,
        wasted_bytes=summary.wasted_bytes,
        within_root=within_root,
        include_bundles=include_bundles,
        excluded_bundle_groups=max(excluded_groups, 0),
        excluded_bundle_bytes=max(excluded_bytes, 0),
        items=items,
    )


def spans(
    conn: sqlite3.Connection, file_hash: str, *, method: str | None = None
) -> SpanList:
    """Labelled regions of one sound.

    Stage 2 never writes to the ``span`` table, so this is an empty list until
    stage 3 runs a classifier. The route exists now so the waveform has a
    contract to draw against rather than a 404 to swallow.
    """
    sql = (
        "SELECT id, hash, method, start_s, end_s, label, confidence, detail "
        "FROM span WHERE hash = ?"
    )
    params: list[object] = [file_hash]
    if method:
        sql += " AND method = ?"
        params.append(method)
    sql += " ORDER BY method, start_s, id"

    items = [
        SpanInfo(
            id=int(row["id"]),
            hash=str(row["hash"]),
            method=str(row["method"]),
            start_s=float(row["start_s"]),
            end_s=float(row["end_s"]),
            label=str(row["label"]),
            confidence=row["confidence"],
            detail=row["detail"],
        )
        for row in conn.execute(sql, params)
    ]
    return SpanList(
        hash=file_hash, method=method, total=len(items), items=items
    )


def silence_report(
    conn: sqlite3.Connection, file_hash: str, *, min_gap: float
) -> SilenceReport:
    """One sound's dead air, at the floor the caller asked for.

    Reads two tables and does arithmetic. It does not open the audio; the
    measurement was done once by ``audio-browser silence`` and the floor is
    applied here, so changing the floor costs nothing.
    """
    blob = conn.execute(
        "SELECT duration_s FROM blob WHERE hash = ?", (file_hash,)
    ).fetchone()
    duration = blob["duration_s"] if blob else None
    summary = silence.measured_at(conn, file_hash)
    if duration is None and summary is not None:
        duration = summary["duration_s"]

    intervals = silence.read_intervals(
        conn, file_hash, min_gap_s=min_gap, duration_s=duration
    )
    return SilenceReport(
        hash=file_hash,
        measured=summary is not None,
        min_gap=min_gap,
        duration_s=duration,
        # Null for a sound nobody has measured. Deriving a sounding length from
        # an empty interval list would report every unmeasured sound as playing
        # from end to end, which is exactly the claim there is no evidence for.
        sounding_s=(
            silence.sounding_seconds(duration, intervals) if summary is not None else None
        ),
        silent_s=silence.silent_seconds(intervals),
        measured_at=str(summary["measured_at"]) if summary else None,
        max_db=summary["max_db"] if summary else None,
        mean_db=summary["mean_db"] if summary else None,
        intervals=[
            SilenceInterval(start_s=i.start_s, end_s=i.end_s) for i in intervals
        ],
    )


def stats(conn: sqlite3.Connection) -> StatsResponse:
    """Collection totals, reusing the counters the CLI prints."""
    base = collect_stats(conn)
    # Stats report the footprint on disk, so every alias counts here, including
    # roots that mirror each other. The /api/dupes list is the cleanup view and
    # scopes to within-root by default.
    dup = duplicate_summary(conn, within_root=False)
    sounding = conn.execute(
        # An unmeasured sound contributes its wall duration, because that is
        # everything known about it. `measured_blobs` says how much of the total
        # has actually had the dead air taken out.
        f"SELECT COALESCE(SUM(COALESCE({SOUNDING_S_SQL}, b.duration_s, 0)), 0) AS sounding,"
        "        (SELECT COUNT(*) FROM silence) AS measured"
        " FROM blob b"
    ).fetchone()
    return StatsResponse(
        aliases=base.aliases,
        blobs=base.blobs,
        logical_bytes=base.logical_bytes,
        physical_bytes=base.physical_bytes,
        wasted_bytes=dup.wasted_bytes,
        duplicate_blobs=dup.groups,
        extra_copies=dup.extra_copies,
        probed_blobs=base.probed_blobs,
        probe_failures=base.probe_failures,
        peaks_cached=base.peaks_cached,
        total_duration_s=base.total_duration_s,
        total_sounding_s=float(sounding["sounding"]),
        measured_blobs=int(sounding["measured"]),
        favorites=base.favorites,
        tags=base.tags,
        roots=[
            RootCount(
                root=r.root,
                aliases=r.aliases,
                distinct_blobs=r.distinct_blobs,
                bytes_on_disk=r.bytes_on_disk,
            )
            for r in base.roots
        ],
        extensions=[NameCount(name=name, count=n) for name, n in base.extensions],
        codecs=[NameCount(name=name, count=n) for name, n in base.codecs],
    )
