"""Plan and carry out a one-time deduplication inside a single root.

A sound is its BLAKE3 digest; a path is only an alias. When one root holds the
same digest at several paths, all but one of those paths are redundant. This
module decides which one survives and writes the removed ones into the
``deletion`` table so they are remembered rather than silently gone.

The module splits into a pure core and a thin effectful shell.

* :func:`plan_root` reads the index and returns a :class:`DedupePlan`. It
  deletes nothing and needs no write access. Its one filesystem dependency,
  "does this directory hold a DAW project file", is injected as a callable, so
  the planning logic can be exercised without touching a disk.
* :func:`apply_plan` is the only function that removes a file. It validates the
  whole plan before it unlinks anything, so a plan with a single bad path
  removes nothing at all.

Five rules decide what may go. Every one of them must hold.

1. **One root at a time.** Copies are counted inside a single root. The other
   root is a deliberate mirror, so a twin over there never makes a path here
   redundant.
2. **Never a bundle path.** A file inside a ``.logicx`` directory is that
   project's own media. Logic reads it from that exact path.
3. **Never beside a project file.** REAPER resolves media by bare filename next
   to the ``.rpp``, so any audio sharing a directory with a ``.rpp``,
   ``.rpp-bak``, or ``.als`` is load-bearing.
4. **Keep the shallowest survivor.** Among the copies that may be deleted, the
   one with the fewest path separators survives, ties broken alphabetically.
   Protected copies survive as well, on top of it.
5. **Never reduce a sound to zero copies in the root.** If every copy of a
   sound is protected, nothing is deleted for that sound. Because rule 4 always
   keeps one deletable copy, a sound that has any deletable copy also keeps one
   freely-browsable path, not just a copy buried inside a project folder.

Safety is asserted, not assumed. Every path is checked to lie under the root
that was asked for, at plan time and again immediately before the unlink, so a
root the caller did not name cannot be touched.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .config import Root
from .db import now_iso
from .report import is_bundle_path

# REAPER and Ableton project files. A project references its media by bare
# filename resolved beside the project file, so audio sharing a directory with
# one of these is part of that project, whatever else it also is.
PROJECT_SUFFIXES: tuple[str, ...] = (".rpp", ".rpp-bak", ".als")

BUNDLE_REASON = "inside a DAW project bundle"
PROJECT_DIR_REASON = "beside a DAW project file"

DEFAULT_REASON = "redundant copy"


class UnsafeDeletion(Exception):
    """A path was proposed for deletion that the tool refuses to touch.

    Raised before anything is removed. Seeing this means the index and the
    requested root disagree, which is a situation for a human, not a retry.
    """


@dataclass(frozen=True, slots=True)
class Copy:
    """One path of one sound inside one root.

    ``protection`` is ``None`` when the path may be deleted, otherwise a short
    phrase naming the rule that saves it.
    """

    path: str
    protection: str | None = None

    @property
    def deletable(self) -> bool:
        return self.protection is None


@dataclass(frozen=True, slots=True)
class SoundPlan:
    """What happens to one sound inside one root."""

    file_hash: str
    size_bytes: int
    keep: str
    """The deletable copy that survives: fewest separators, then alphabetical."""
    delete: tuple[str, ...]
    protected: tuple[Copy, ...]
    """Copies kept because a rule forbids removing them. Always survive."""

    @property
    def freed_bytes(self) -> int:
        return len(self.delete) * self.size_bytes

    @property
    def survivors(self) -> tuple[str, ...]:
        return (self.keep, *(c.path for c in self.protected))


@dataclass(frozen=True, slots=True)
class SkippedSound:
    """A duplicated sound where every copy is protected, so nothing goes."""

    file_hash: str
    size_bytes: int
    copies: tuple[Copy, ...]

    @property
    def unreclaimed_bytes(self) -> int:
        """Bytes a rule-free deduplication would have freed."""
        return (len(self.copies) - 1) * self.size_bytes


@dataclass(frozen=True, slots=True)
class DedupePlan:
    """Every deletion proposed for one root, and what was left alone."""

    root: str
    root_path: str
    sounds: tuple[SoundPlan, ...] = ()
    skipped: tuple[SkippedSound, ...] = ()

    @property
    def files(self) -> int:
        return sum(len(s.delete) for s in self.sounds)

    @property
    def bytes_freed(self) -> int:
        return sum(s.freed_bytes for s in self.sounds)

    @property
    def sounds_touched(self) -> int:
        return len(self.sounds)

    @property
    def sounds_skipped(self) -> int:
        return len(self.skipped)

    @property
    def skipped_bytes(self) -> int:
        return sum(s.unreclaimed_bytes for s in self.skipped)

    def deletions(self) -> Iterator[tuple[SoundPlan, str]]:
        """Every (sound, path) pair this plan would remove, in plan order."""
        for sound in self.sounds:
            for path in sound.delete:
                yield sound, path


@dataclass
class ApplyResult:
    """What actually happened when a plan was carried out."""

    deleted: int = 0
    bytes_freed: int = 0
    already_missing: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)

    def as_lines(self) -> list[str]:
        return [
            f"deleted          {self.deleted}",
            f"bytes freed      {self.bytes_freed}",
            f"already missing  {self.already_missing}",
            f"failed           {len(self.failed)}",
        ]


class ProjectDirs:
    """Answers "does this directory hold a DAW project file", with a cache.

    The index only stores audio files, so a ``.rpp`` sitting next to a sample is
    invisible to SQL. That question has to go to the filesystem, and the same
    directory is asked about many times, so the answer is remembered.

    A directory that cannot be read answers ``True``. When the evidence is
    missing, the safe answer is the one that keeps the file.
    """

    def __init__(self, suffixes: Iterable[str] = PROJECT_SUFFIXES) -> None:
        self._suffixes = tuple(s.lower() for s in suffixes)
        self._cache: dict[str, bool] = {}

    def __call__(self, directory: str) -> bool:
        cached = self._cache.get(directory)
        if cached is None:
            cached = self._scan(directory)
            self._cache[directory] = cached
        return cached

    def _scan(self, directory: str) -> bool:
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if not entry.name.lower().endswith(self._suffixes):
                        continue
                    if entry.is_file():
                        return True
        except OSError:
            return True
        return False


def no_project_dirs(directory: str) -> bool:
    """A :class:`ProjectDirs` stand-in that never finds a project file."""
    return False


def is_under_root(path: str, root_path: Path | str) -> bool:
    """Is ``path`` strictly inside ``root_path``?

    Pure string comparison over already-resolved paths. The scan stores paths
    with symlinks resolved and the config resolves each root, so both sides are
    absolute and free of ``..`` before they get here.
    """
    root = os.path.normpath(str(root_path))
    target = os.path.normpath(path)
    if target == root:
        return False
    return target.startswith(root.rstrip(os.sep) + os.sep)


def ensure_under_root(path: str, root_path: Path | str) -> None:
    """Raise :class:`UnsafeDeletion` unless ``path`` is inside ``root_path``.

    This is the guard that makes "never touch the other root" a property of the
    code rather than of the caller's care.
    """
    if not is_under_root(path, root_path):
        raise UnsafeDeletion(
            f"refusing to delete {path!r}: it is not under the requested root "
            f"{str(root_path)!r}"
        )


def protection_for(
    path: str, *, dir_has_project: Callable[[str], bool]
) -> str | None:
    """Why this path may not be deleted, or ``None`` when it may."""
    if is_bundle_path(path):
        return BUNDLE_REASON
    if dir_has_project(os.path.dirname(path)):
        return PROJECT_DIR_REASON
    return None


def survivor_key(path: str) -> tuple[int, str]:
    """Sort key picking the shallowest path, ties broken alphabetically."""
    return (path.count(os.sep), path)


def plan_sound(
    file_hash: str,
    size_bytes: int,
    paths: Iterable[str],
    *,
    dir_has_project: Callable[[str], bool],
) -> SoundPlan | SkippedSound | None:
    """Decide the fate of one sound's copies inside one root.

    Returns a :class:`SoundPlan` when something can go, a :class:`SkippedSound`
    when every copy is protected, and ``None`` when there is nothing to dedupe
    because the sound has fewer than two copies here.
    """
    copies = tuple(
        Copy(path=p, protection=protection_for(p, dir_has_project=dir_has_project))
        for p in sorted(set(paths), key=survivor_key)
    )
    if len(copies) < 2:
        return None

    deletable = [c for c in copies if c.deletable]
    protected = tuple(c for c in copies if not c.deletable)
    if not deletable:
        return SkippedSound(
            file_hash=file_hash, size_bytes=size_bytes, copies=copies
        )

    keep, *rest = sorted((c.path for c in deletable), key=survivor_key)
    if not rest:
        # One deletable copy and one or more protected ones. Everything here
        # already survives, so there is nothing to propose.
        return None
    return SoundPlan(
        file_hash=file_hash,
        size_bytes=size_bytes,
        keep=keep,
        delete=tuple(rest),
        protected=protected,
    )


def plan_root(
    conn: sqlite3.Connection,
    root: Root,
    *,
    dir_has_project: Callable[[str], bool] | None = None,
) -> DedupePlan:
    """Build the deletion plan for one root. Reads only; deletes nothing.

    Every alias recorded under ``root.name`` is checked to live under
    ``root.path`` first. A disagreement raises :class:`UnsafeDeletion` rather
    than being quietly dropped, because it means the index no longer describes
    the tree it claims to.
    """
    oracle = dir_has_project if dir_has_project is not None else ProjectDirs()
    rows = conn.execute(
        "SELECT a.hash AS hash, a.path AS path, b.size_bytes AS size_bytes "
        "FROM alias a JOIN blob b ON b.hash = a.hash "
        "WHERE a.root = ? ORDER BY a.hash, a.path",
        (root.name,),
    ).fetchall()

    grouped: dict[str, tuple[int, list[str]]] = {}
    for row in rows:
        path = str(row["path"])
        ensure_under_root(path, root.path)
        size, paths = grouped.setdefault(str(row["hash"]), (int(row["size_bytes"]), []))
        paths.append(path)

    sounds: list[SoundPlan] = []
    skipped: list[SkippedSound] = []
    for file_hash, (size, paths) in grouped.items():
        outcome = plan_sound(file_hash, size, paths, dir_has_project=oracle)
        if isinstance(outcome, SoundPlan):
            sounds.append(outcome)
        elif isinstance(outcome, SkippedSound):
            skipped.append(outcome)

    sounds.sort(key=lambda s: (-s.freed_bytes, s.file_hash))
    skipped.sort(key=lambda s: (-s.unreclaimed_bytes, s.file_hash))
    return DedupePlan(
        root=root.name,
        root_path=str(root.path),
        sounds=tuple(sounds),
        skipped=tuple(skipped),
    )


def validate_plan(plan: DedupePlan) -> None:
    """Check every path in the plan before a single one is removed.

    Raises :class:`UnsafeDeletion` on the first problem. Running this to
    completion first is what makes a bad plan remove nothing instead of
    stopping halfway through.
    """
    seen: set[str] = set()
    for sound in plan.sounds:
        ensure_under_root(sound.keep, plan.root_path)
        for copy in sound.protected:
            ensure_under_root(copy.path, plan.root_path)
        for path in sound.delete:
            ensure_under_root(path, plan.root_path)
            if path == sound.keep:
                raise UnsafeDeletion(
                    f"refusing to delete {path!r}: it is also the kept copy of "
                    f"{sound.file_hash}"
                )
            if path in {c.path for c in sound.protected}:
                raise UnsafeDeletion(
                    f"refusing to delete {path!r}: it is a protected copy of "
                    f"{sound.file_hash}"
                )
            if path in seen:
                raise UnsafeDeletion(f"{path!r} appears twice in the plan")
            seen.add(path)
        if not sound.delete:
            raise UnsafeDeletion(
                f"plan entry for {sound.file_hash} deletes nothing"
            )


def record_deletion(
    conn: sqlite3.Connection,
    *,
    file_hash: str,
    path: str,
    root: str,
    reason: str,
    when: str | None = None,
) -> None:
    """Write the durable record of one removed path, and drop its alias.

    The ``deletion`` row is what a rescan cannot erase. The ``alias`` row is
    dropped here so the index stops offering a path that is gone; a rescan's
    prune would do the same thing later anyway.
    """
    conn.execute(
        "INSERT INTO deletion (hash, path, root, deleted_at, reason) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(path) DO UPDATE SET "
        "hash = excluded.hash, root = excluded.root, "
        "deleted_at = excluded.deleted_at, reason = excluded.reason",
        (file_hash, path, root, when or now_iso(), reason),
    )
    conn.execute("DELETE FROM alias WHERE path = ?", (path,))


def deleted_sightings(
    conn: sqlite3.Connection, file_hash: str
) -> list[tuple[str, str, str, str]]:
    """Paths this sound used to be reachable through: (path, root, when, why)."""
    return [
        (str(r["path"]), str(r["root"]), str(r["deleted_at"]), str(r["reason"]))
        for r in conn.execute(
            "SELECT path, root, deleted_at, reason FROM deletion "
            "WHERE hash = ? ORDER BY deleted_at DESC, path",
            (file_hash,),
        )
    ]


def apply_plan(
    conn: sqlite3.Connection,
    plan: DedupePlan,
    *,
    reason: str = DEFAULT_REASON,
    unlink: Callable[[str], None] = os.remove,
    log: Callable[[str], None] = lambda _: None,
) -> ApplyResult:
    """Carry the plan out. The only function here that removes a file.

    The plan is validated in full first, so an unsafe entry anywhere aborts
    before anything is unlinked. Each path is then re-checked against the root,
    including through symlinks, immediately before it goes.
    """
    validate_plan(plan)
    real_root = os.path.realpath(plan.root_path)
    result = ApplyResult()
    pending = 0

    for sound, path in plan.deletions():
        ensure_under_root(path, plan.root_path)
        # Re-check through symlinks. A directory swapped for a link since the
        # plan was built would otherwise carry the unlink outside the root.
        real = os.path.realpath(path)
        if real != os.path.normpath(path):
            ensure_under_root(real, real_root)

        try:
            unlink(path)
        except FileNotFoundError:
            result.already_missing += 1
        except OSError as exc:
            result.failed.append((path, str(exc)))
            log(f"failed to delete {path}: {exc}")
            continue
        else:
            result.deleted += 1
            result.bytes_freed += sound.size_bytes

        record_deletion(
            conn,
            file_hash=sound.file_hash,
            path=path,
            root=plan.root,
            reason=f"{reason}; kept {sound.keep}",
        )
        pending += 1
        if pending >= 200:
            conn.commit()
            pending = 0

    conn.commit()
    return result


def plan_lines(plan: DedupePlan) -> Iterator[str]:
    """Render the plan as text: comment headers, then one path per line.

    Every line that is not a comment is a path to delete, so the file doubles as
    a list a human can read and as one a human can feed to a command.
    """
    yield f"# dedupe plan for root {plan.root!r} at {plan.root_path}"
    yield (
        f"# {plan.files} files, {plan.bytes_freed} bytes, "
        f"{plan.sounds_touched} sounds; "
        f"{plan.sounds_skipped} sounds skipped (every copy protected)"
    )
    yield "# lines starting with # are commentary; every other line is a deletion"
    for sound in plan.sounds:
        yield ""
        yield (
            f"# {sound.file_hash[:16]}  {sound.size_bytes} bytes  "
            f"x{len(sound.delete) + 1 + len(sound.protected)}"
        )
        yield f"#   keep      {sound.keep}"
        for copy in sound.protected:
            yield f"#   protected {copy.path}  ({copy.protection})"
        for path in sound.delete:
            yield path


def write_plan(plan: DedupePlan, out: Path) -> int:
    """Write the plan to a file. Returns the number of deletion lines."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(plan_lines(plan)) + "\n", encoding="utf-8")
    return plan.files


def example_lines(
    plan: DedupePlan, count: int = 10, *, per_sound: int = 2
) -> list[str]:
    """A few deletions with the survivor above each one, for a report.

    At most ``per_sound`` deletions are shown for any one sound. One sound with
    twenty-three redundant copies would otherwise fill the whole sample and say
    nothing about the other hundred and forty-seven.
    """
    lines: list[str] = []
    for sound in plan.sounds:
        if len(lines) >= count:
            break
        lines.append(f"keep  {sound.keep}")
        for path in sound.delete[:per_sound]:
            lines.append(f" del  {path}")
        extra = len(sound.delete) - per_sound
        if extra > 0:
            lines.append(f" del  ... and {extra} more copies of this sound")
    return lines[:count]
