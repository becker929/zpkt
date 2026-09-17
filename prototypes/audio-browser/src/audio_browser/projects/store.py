"""The directory of project files, and the index that caches it.

**The files are the truth.** ``audio-browser/projects/<id>.json`` is where a
project lives. SQLite indexes those files so the board can be drawn without
opening every one of them, but the index is a cache and nothing more: every read
path calls :meth:`ProjectStore.sync` first, which compares each file's
modification stamp against the row derived from it and re-reads any file that
has moved on. A row whose file is gone is dropped. The cache can never outvote
its source.

Two writes have to be atomic against each other, and the mock backend was
single-threaded and could not show it:

* **Create at the cap.** Counting the column and then writing the file is a
  read-then-write, and two of them interleave: both count 2 against a cap of 3,
  both write, and the column holds 4 without an override. Every write here runs
  under a lock, and the file itself is created with ``O_EXCL`` so two writers
  cannot even land on the same id.
* **Commit.** Read, check, append, write. Two tabs pressing "freeze" would
  otherwise walk a project ``stored → collage → enrich`` in two clicks, freezing
  a ``collage`` digest over an arrangement nobody made. Commit is one way, so
  that damage is permanent. The lock closes the window and ``expect_column``
  closes the rest of it.

The lock is two locks, because a second process is as real as a second thread:
a :class:`threading.Lock` for the threads inside this process, and ``flock`` on
``projects/.lock`` for everything outside it.

No function in this module removes audio. The only files it writes are JSON
documents inside the projects directory, and the only file it removes is its own
temporary file when a write fails part way.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft7Validator

from . import model
from .model import Artifact, Column, Issue, Placement

LOCK_NAME = ".lock"
"""The file ``flock`` is taken on. It holds nothing and is never read."""

SUFFIX = ".json"


class ProjectError(Exception):
    """A refusal, with the status the API should answer.

    ``cap`` is set only when the refusal is a capacity decision. That is the one
    kind the user may override, and carrying it here is what lets the route
    offer an override for exactly those and for nothing else.
    """

    def __init__(
        self,
        detail: str,
        *,
        status: int = 409,
        column: str | None = None,
        cap: int | None = None,
        count: int | None = None,
        missing_column: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status = status
        self.column = column
        self.cap = cap
        self.count = count
        self.missing_column = missing_column
        """The stage that would have received this, if it had been built.

        Set only when the refusal is "there is nowhere to go". No override
        conjures a column into existence, so this refusal carries no ``cap`` and
        the interface must not offer a way through it.
        """

    @property
    def capacity(self) -> bool:
        """Whether an ``override: true`` would have got through."""
        return self.cap is not None


@dataclass(frozen=True, slots=True)
class Loaded:
    """One project file as it was read.

    ``document`` is the parsed JSON whatever the schema thinks of it, so a file
    that does not validate can still be shown and still holds its slot.
    """

    id: str
    path: Path
    document: object
    issues: tuple[Issue, ...]
    mtime_ns: int
    size_bytes: int

    @property
    def valid(self) -> bool:
        return not self.issues

    @property
    def problem(self) -> str:
        return model.describe_issues(self.issues)

    def as_document(self) -> dict[str, Any]:
        """The document, which the caller has already established is valid."""
        if not self.valid:
            raise ProjectError(
                f"{self.id} does not match the project schema: {self.problem}",
                status=409,
            )
        return cast(dict[str, Any], self.document)


@dataclass(frozen=True, slots=True)
class Caps:
    """Slots per column.

    A cap of 0 is a legitimate setting and means the column is closed: nothing
    goes into it without an explicit override, and a column that already holds
    something reads as over its limit at once.
    """

    stored: int = model.DEFAULT_CAP
    collage: int = model.DEFAULT_CAP

    def of(self, column: Column) -> int:
        return cast(int, getattr(self, column))

    @classmethod
    def uniform(cls, cap: int) -> Caps:
        """One number for every column. Turning the board down is one line."""
        return cls(stored=cap, collage=cap)


class ProjectStore:
    """Every project file in one directory, and the cache in front of them."""

    def __init__(
        self,
        directory: Path,
        *,
        validator: Draft7Validator,
        caps: Caps | None = None,
        encumbrance: int = model.DEFAULT_ENCUMBRANCE,
    ) -> None:
        self.directory = directory
        self.validator = validator
        self.caps = caps or Caps()
        self.encumbrance = encumbrance
        """Sounds past which a project is marked encumbered.

        It is carried here, beside the caps, because it is the same kind of
        setting: a number the board draws from the server so a client can never
        show a project as fine while the server calls it encumbered.
        """

        self._threads = threading.Lock()

    # ------------------------------------------------------------ the lock

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        """Hold the directory against every other writer, in or out of process.

        The thread lock is taken first and the file lock second, always in that
        order, so two threads of this process queue behind each other rather
        than both blocking on the same descriptor.
        """
        self.directory.mkdir(parents=True, exist_ok=True)
        with self._threads:
            fd = os.open(self.directory / LOCK_NAME, os.O_CREAT | os.O_RDWR, 0o644)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    # ------------------------------------------------------------- reading

    def path_of(self, project_id: str) -> Path:
        return self.directory / f"{project_id}{SUFFIX}"

    def _read(self, path: Path) -> Loaded | None:
        """One file, parsed and checked. ``None`` when it vanished mid-read."""
        try:
            stat = path.stat()
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        issues: tuple[Issue, ...]
        try:
            document: object = json.loads(text)
        except json.JSONDecodeError as exc:
            document = None
            issues = (Issue(path="(root)", message=f"not JSON: {exc.msg}"),)
        else:
            issues = tuple(model.check_project(self.validator, document))
            # The filename is the id. A document claiming a different one would
            # be reachable under two names and writable under neither.
            if isinstance(document, dict) and document.get("id") != path.stem:
                issues = (
                    *issues,
                    Issue(
                        path="id",
                        message=(
                            f"the file is named {path.stem!r} but the document "
                            f"says {document.get('id')!r}"
                        ),
                    ),
                )
        return Loaded(
            id=path.stem,
            path=path,
            document=document,
            issues=issues,
            mtime_ns=stat.st_mtime_ns,
            size_bytes=stat.st_size,
        )

    def load(self, project_id: str) -> Loaded | None:
        return self._read(self.path_of(project_id))

    def files(self) -> list[Path]:
        """Every project file, by id. The lock file is not one."""
        if not self.directory.is_dir():
            return []
        return sorted(
            path
            for path in self.directory.glob(f"*{SUFFIX}")
            if path.is_file() and not path.name.startswith(".")
        )

    def ids(self) -> list[str]:
        return [path.stem for path in self.files()]

    def read_all(self) -> list[Loaded]:
        """Every project, straight from disk. The slow path, and the true one."""
        loaded = [self._read(path) for path in self.files()]
        return [item for item in loaded if item is not None]

    # ------------------------------------------------------------- writing

    def _write(self, project_id: str, document: dict[str, Any]) -> Loaded:
        """Replace one file, whole.

        The document is written to a temporary file beside the target and moved
        over it with ``os.replace``, which is atomic. A reader therefore sees
        either the document as it was or the document as it now is, and never
        half of either.

        The result is validated before it lands. A refusal here means the
        operation that built this document was wrong, and refusing beats writing
        a file the board cannot read.
        """
        issues = model.check_project(self.validator, document)
        if issues:
            raise ProjectError(
                "the change would write a document that does not match the "
                f"schema: {model.describe_issues(issues)}",
                status=422,
            )
        target = self.path_of(project_id)
        temp = target.with_name(f".{project_id}.tmp")
        text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
        try:
            temp.write_text(text, encoding="utf-8")
            os.replace(temp, target)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
        loaded = self._read(target)
        assert loaded is not None
        return loaded

    # ---------------------------------------------------------- occupancy

    def occupancy(self, loaded: Sequence[Loaded]) -> dict[Column, int]:
        """How many projects each column is holding.

        A file that does not validate is counted too, in whatever column it
        names. Skipping it would let one junk key free a slot, which is a cap
        bypass that needs no override.
        """
        counts: dict[Column, int] = {column: 0 for column in model.COLUMNS}
        for item in loaded:
            column = model.slot_holder(item.document)
            if column is not None:
                counts[column] += 1
        return counts

    def _check_cap(
        self, loaded: Sequence[Loaded], column: Column, override: bool
    ) -> None:
        """Refuse past the cap, unless the caller says so out loud.

        This is friction, not restriction: the refusal names the cap and the
        occupancy so the interface can state both, and ``override`` gets
        through. The board then shows the column as over its limit until the
        count comes back down.
        """
        cap = self.caps.of(column)
        count = self.occupancy(loaded)[column]
        if count < cap or override:
            return
        raise ProjectError(
            f"{column} is at its limit of {cap} and already holds {count}. "
            "Finish or abandon something there first, or say override.",
            status=409,
            column=column,
            cap=cap,
            count=count,
        )

    # ------------------------------------------------------------ actions

    def create(self, name: str, *, override: bool = False, at: str) -> Loaded:
        """Make a project in ``stored``.

        The cap check and the file creation happen inside one lock, so two
        requests arriving together cannot both find room. ``O_EXCL`` is the
        second guard: even without the lock, only one of two writers racing for
        the same id can win, and the loser takes the next id in the family
        rather than overwriting a project that already exists.
        """
        with self._exclusive():
            loaded = self.read_all()
            self._check_cap(loaded, "stored", override)
            base = model.project_id(name, at)
            candidate = model.unique_project_id(base, (item.id for item in loaded))
            project_id = self._claim(candidate)
            document = model.new_document(project_id, name, at)
            return self._write(project_id, document)

    def _claim(self, candidate: str) -> str:
        """Take an id by creating its file, or move on to the next free one.

        ``O_CREAT | O_EXCL`` fails when the file is already there, which is the
        whole point: the filesystem decides who owns the name, not a count taken
        a moment earlier.
        """
        taken: set[str] = set()
        for _ in range(1000):
            try:
                fd = os.open(
                    self.path_of(candidate), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644
                )
            except OSError as exc:
                if exc.errno != errno.EEXIST:
                    raise
                taken.add(candidate)
                base = candidate.rsplit("-", 1)[0] if candidate[-1].isdigit() else candidate
                candidate = model.unique_project_id(base, taken | set(self.ids()))
                continue
            os.close(fd)
            return candidate
        raise ProjectError("could not find a free project id", status=409)

    def patch(
        self,
        project_id: str,
        *,
        name: str | None = None,
        notes: str | None = None,
        column: object = None,
        at: str,
    ) -> Loaded:
        """Rename, or edit notes. It does not move a project between columns.

        Moving column by PATCH is refused outright. Commit is the only way a
        project advances; if a field could do it, every freeze would be
        sidesteppable by editing that field, and the commit chain would stop
        meaning anything.
        """
        if column is not None:
            raise ProjectError(
                "a project does not move column by being edited. Commit is the "
                "boundary between columns, and it is what freezes the artifact "
                "the next column builds on.",
                status=409,
            )
        with self._exclusive():
            current = self._require(project_id)
            document = dict(current.as_document())
            if name is not None:
                document["name"] = name
            if notes is not None:
                document["notes"] = notes
            document["updated_at"] = at
            return self._write(project_id, document)

    def set_sound(
        self, project_id: str, file_hash: str, *, member: bool, at: str
    ) -> Loaded:
        """Add or remove one sound.

        Refused with 409 once a ``stored`` commit exists, at the API and not
        only in the interface. A tab that was showing the project before it was
        committed will try this, and it has to be told no by the server rather
        than be trusted to have noticed.

        Removing a sound removes no audio. Every path that held the bytes still
        holds them; this drops one entry from a JSON array.
        """
        with self._exclusive():
            current = self._require(project_id)
            document = current.as_document()
            if not model.sound_set_open(document):
                raise ProjectError(self._why_closed(document), status=409)
            if member and len(document["sounds"]) >= model.MAX_PROJECT_SOUNDS:
                if not any(s["hash"] == file_hash for s in document["sounds"]):
                    raise ProjectError(
                        f"a project holds at most {model.MAX_PROJECT_SOUNDS} "
                        "sounds and this one is full",
                        status=409,
                    )
            changed = (
                model.with_sound(document, file_hash, at)
                if member
                else model.without_sound(document, file_hash, at)
            )
            if changed is document:
                return current
            return self._write(project_id, changed)

    @staticmethod
    def _why_closed(document: dict[str, Any]) -> str:
        """The reason membership is refused, in the user's terms."""
        if document["abandoned"] is not None:
            return (
                "this project was abandoned and is off the board. Revive it "
                "before changing what is in it."
            )
        if document["column"] != "stored":
            return (
                f"this project is in {document['column']}. Its sound set was "
                "frozen when it left stored and cannot change."
            )
        return (
            "the sound set was frozen by the stored commit. Freezing is one "
            "way: nothing reopens it."
        )

    @staticmethod
    def _nowhere_to_go(column: Column) -> str:
        """Why the last column cannot commit, and what would unblock it."""
        missing = model.next_planned(column)
        named = f"{missing} is not built yet" if missing else "there is no next stage"
        return (
            f"{column} is the last column that exists: {named}, so there is "
            "nowhere to commit this to. It stays in "
            f"{column} and keeps its lane. Abandoning it is the only way to "
            "free that lane, and that means saying the idea is dead."
        )

    def commit(
        self, project_id: str, *, override: bool = False, expect_column: str | None, at: str
    ) -> tuple[Loaded, dict[str, Any], Artifact]:
        """Freeze this column's artifact, append to the chain, and advance.

        ``expect_column`` is the stage the caller believes it is freezing, and a
        mismatch is refused with 409 that **no override gets through**. It is a
        stale-client error, not a capacity decision. Without it, two tabs press
        "freeze the sound set" one after the other and the second freezes the
        arrangement instead: a stage nobody worked, with a digest of nothing,
        one way, permanently.

        The downstream cap is the second refusal, and that one *is* a capacity
        decision: you cannot keep gathering material when the collage bench is
        full. It is overridable, and the board then shows the receiving column
        as over its limit.

        The third is the end of the pipeline. The last built column has nowhere
        to commit to, so it is refused and the project stays where it is,
        holding its lane. No override gets through: an override goes past a
        limit, and this is not a limit but a column that does not exist.
        """
        with self._exclusive():
            current = self._require(project_id)
            document = current.as_document()
            placement = cast(Placement, document["column"])

            if document["abandoned"] is not None:
                raise ProjectError(
                    "this project was abandoned and is off the board. Revive it "
                    "before committing it.",
                    status=409,
                )
            if not model.is_column(placement):
                raise ProjectError(
                    "this project is released. There is nothing left to freeze."
                    if placement == "released"
                    else (
                        f"this project sits in {placement}, which is not a "
                        "column on this board. Nothing there can be frozen."
                    ),
                    status=409,
                )
            column = cast(Column, placement)

            if expect_column is not None and expect_column != column:
                raise ProjectError(
                    f"you asked to freeze {expect_column}, but this project is "
                    f"in {column}. It moved on while your view was open. "
                    "Reload and look at what is actually there before freezing "
                    "it: a commit cannot be taken back.",
                    status=409,
                )

            if column == "stored" and not document["sounds"]:
                raise ProjectError(
                    "there are no sounds to freeze. A project committed out of "
                    "stored can never gain one, so an empty sound set would be "
                    "permanent and would mean nothing.",
                    status=422,
                )

            destination = model.next_placement(column)
            if destination is None:
                raise ProjectError(
                    self._nowhere_to_go(column),
                    status=409,
                    missing_column=model.next_planned(column),
                )
            self._check_cap(
                [item for item in self.read_all() if item.id != project_id],
                destination,
                override,
            )

            artifact = model.commit_artifact(
                project_id, [s["hash"] for s in document["sounds"]], column
            )
            written = self._write(
                project_id, model.committed(document, column, artifact, at)
            )
            entry = cast(list[dict[str, Any]], written.as_document()["commits"])[-1]
            return written, entry, artifact

    def abandon(self, project_id: str, *, reason: str, at: str) -> Loaded:
        """Leave the board and free the slot, keeping the file.

        Lighter than committing, because it is reversible. It freezes nothing
        and appends nothing to ``commits``. Without it a project you no longer
        believe in would hold its slot forever and the only way out would be to
        commit something you do not want, which would empty the word "committed"
        of meaning.
        """
        with self._exclusive():
            current = self._require(project_id)
            document = current.as_document()
            if document["abandoned"] is not None:
                raise ProjectError("this project is already abandoned", status=409)
            placement = cast(Placement, document["column"])
            if not model.is_column(placement):
                raise ProjectError(
                    "a released project is already off the board. There is no "
                    "slot to free.",
                    status=409,
                )
            return self._write(
                project_id,
                model.abandoned_doc(document, cast(Column, placement), reason, at),
            )

    def revive(self, project_id: str, *, override: bool = False, at: str) -> Loaded:
        """Bring an abandoned project back to the column it left.

        It takes a slot like anything else and is refused when that column is
        full, with the same override treatment. Reviving is not free; the cost
        is the slot, which is exactly the right price. Every commit it had it
        still has.
        """
        with self._exclusive():
            current = self._require(project_id)
            document = current.as_document()
            if document["abandoned"] is None:
                raise ProjectError("this project is not abandoned", status=409)
            column = cast(Column, document["abandoned"]["from"])
            self._check_cap(
                [item for item in self.read_all() if item.id != project_id],
                column,
                override,
            )
            return self._write(project_id, model.revived(document, at))

    def _require(self, project_id: str) -> Loaded:
        loaded = self.load(project_id)
        if loaded is None:
            raise ProjectError("no such project", status=404)
        return loaded

    # --------------------------------------------------------------- cache

    def sync(self, conn: sqlite3.Connection, *, at: str) -> list[Loaded]:
        """Bring the index into line with the directory and return the truth.

        This runs before every read. It compares each file's modification stamp
        with the row derived from it, re-reads the ones that have moved on, and
        drops rows whose file is gone. A project edited by hand, restored from a
        backup, or written by another process is therefore picked up on the next
        request rather than on a rebuild somebody has to remember to run.

        The return value comes from the files, never from the rows. The rows are
        written afterwards so the next caller has less to do.
        """
        indexed = {
            str(row["id"]): (int(row["mtime_ns"]), int(row["size_bytes"]))
            for row in conn.execute("SELECT id, mtime_ns, size_bytes FROM project")
        }
        loaded = self.read_all()
        present = {item.id for item in loaded}

        stale = [item for item in loaded if indexed.get(item.id) != (item.mtime_ns, item.size_bytes)]
        gone = [key for key in indexed if key not in present]

        if stale or gone:
            if conn.in_transaction:
                conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            try:
                for key in gone:
                    conn.execute("DELETE FROM project WHERE id = ?", (key,))
                for item in stale:
                    self._index_one(conn, item, at=at)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return loaded

    def _index_one(self, conn: sqlite3.Connection, item: Loaded, *, at: str) -> None:
        document = item.document if isinstance(item.document, dict) else {}
        placement = document.get("column")
        conn.execute("DELETE FROM project WHERE id = ?", (item.id,))
        conn.execute(
            "INSERT INTO project (id, path, mtime_ns, size_bytes, valid, problem,"
            " placement, abandoned, name, created_at, updated_at, document,"
            " sound_count, indexed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item.id,
                str(item.path),
                item.mtime_ns,
                item.size_bytes,
                1 if item.valid else 0,
                item.problem or None,
                placement if isinstance(placement, str) else None,
                0 if document.get("abandoned") is None else 1,
                document.get("name"),
                document.get("created_at"),
                document.get("updated_at"),
                json.dumps(document),
                len(document.get("sounds") or []),
                at,
            ),
        )
        sounds = document.get("sounds")
        if isinstance(sounds, list):
            conn.executemany(
                "INSERT OR REPLACE INTO project_sound"
                " (project_id, hash, position, added_at, role, note)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        item.id,
                        sound.get("hash"),
                        position,
                        sound.get("added_at"),
                        sound.get("role"),
                        sound.get("note"),
                    )
                    for position, sound in enumerate(sounds)
                    if isinstance(sound, dict) and isinstance(sound.get("hash"), str)
                ],
            )

    def rebuild(self, conn: sqlite3.Connection, *, at: str) -> int:
        """Throw the cache away and derive it again from the directory.

        Nothing depends on this being run; :meth:`sync` keeps up on its own. It
        is here because a cache you cannot rebuild from its source on demand is
        not a cache, and because saying so in code is stronger than saying so in
        a document.
        """
        if conn.in_transaction:
            conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM project")
            loaded = self.read_all()
            for item in loaded:
                self._index_one(conn, item, at=at)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return len(loaded)
