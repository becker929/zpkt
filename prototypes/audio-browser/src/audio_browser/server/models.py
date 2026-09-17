"""Response shapes.

Frozen Pydantic models, so the OpenAPI schema at ``/docs`` is generated from
the same definitions the routes return.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..projects.model import MAX_NAME_LENGTH, MAX_NOTES_LENGTH, MAX_REASON_LENGTH

BulkAction = Literal[
    "star", "unstar", "delete", "restore", "add_to_list", "remove_from_list"
]
"""Every action ``POST /api/bulk`` accepts.

``delete`` and ``restore`` are the soft-delete pair. Neither touches a file.
"""

MAX_BULK_HASHES = 1000
"""Cap on one bulk request.

A batch this size already covers a whole screen of work several times over, and
bounding it bounds how long the single write transaction holds the database.
"""

MAX_LIST_NAME = 120


class Frozen(BaseModel):
    """Base for every response model."""

    model_config = ConfigDict(frozen=True)


class FileSummary(Frozen):
    """One sound, as the list view needs it.

    ``path``, ``filename`` and ``root`` come from the primary alias: the
    lowest-numbered path that points at this hash. They are display values. The
    server never accepts them back.
    """

    hash: str
    filename: str
    ext: str
    path: str
    root: str
    size_bytes: int
    duration_s: float | None
    sample_rate: int | None
    channels: int | None
    codec: str | None
    sounding_s: float | None
    """Wall duration minus every silent gap of 2 seconds or more.

    This is the length the interface shows. ``duration_s`` stays alongside it
    and the two are shown together when they differ by more than a few seconds,
    because that difference is itself informative: a sound that runs for five
    minutes and sounds for forty seconds is usually a stem that barely plays.

    Null when the sound has no known duration, or when it has never been
    measured. A sounding length derived from nothing is worse than no number.
    """

    alias_count: int
    favorite: bool
    deleted: bool
    """True when the user discarded this sound.

    It says nothing about the filesystem. Every alias is still on disk; the row
    only means the list view hides it unless it is asked for.
    """

    has_peaks: bool
    transcoded: bool
    """True when the stream is re-encoded on the fly, which makes it unseekable.

    The interface needs this in the list, not only in the detail, because the
    player bar is fed from list rows.
    """


class FileList(Frozen):
    """A page of the collection."""

    total: int
    limit: int
    offset: int
    items: list[FileSummary]


class AliasInfo(Frozen):
    """One path that resolves to a hash. ``exists`` is checked per request."""

    id: int
    path: str
    root: str
    filename: str
    ext: str
    mtime: float
    exists: bool


class DeletedSighting(Frozen):
    """A path that used to hold this sound, and when it was removed.

    Written by the ``dedupe`` command. It outlives a rescan, so the interface
    can say "also seen at X, deleted on Y" instead of letting the path vanish
    without a trace.
    """

    path: str
    root: str
    deleted_at: str
    reason: str


class ListRef(Frozen):
    """A list this sound belongs to, named just enough to link to it."""

    id: int
    name: str


class FileDetail(FileSummary):
    """One sound with every path that reaches it, and every path that did.

    ``deleted_sightings`` and ``deleted`` answer different questions.
    ``deleted_sightings`` is the set of paths that used to hold these bytes and
    were removed from disk by the ``dedupe`` command. ``deleted`` is the user's
    judgement that they do not want this sound. Neither implies the other.
    """

    aliases: list[AliasInfo]
    deleted_sightings: list[DeletedSighting] = []
    tags: list[str]
    favorite_note: str | None
    favorited_at: str | None
    deleted_at: str | None
    delete_note: str | None
    lists: list[ListRef] = []
    probed_at: str | None
    playable: bool


class PeaksResponse(Frozen):
    """Waveform peaks as (minimum, maximum) pairs of signed 8-bit values.

    ``cached`` is false when this request is the one that computed them.
    """

    hash: str
    buckets: int
    duration_s: float | None
    cached: bool
    peaks: list[tuple[int, int]]


class FavoriteState(Frozen):
    """Favorite state of a hash, and how many paths inherit it."""

    hash: str
    favorite: bool
    created_at: str | None
    note: str | None
    alias_count: int


class FavoriteRequest(BaseModel):
    """Optional body of ``PUT /api/files/{hash}/favorite``."""

    note: str | None = None


class DeletedState(Frozen):
    """Soft-delete state of a hash, and how many paths inherit it.

    ``alias_count`` is how many paths point at these bytes. All of them are
    still on disk. The count is here so the interface can say "this hides 3
    copies", never so that anything can act on them.
    """

    hash: str
    deleted: bool
    deleted_at: str | None
    note: str | None
    alias_count: int


class DeleteRequest(BaseModel):
    """Optional body of ``PUT /api/files/{hash}/deleted``."""

    note: str | None = None


class ListSummary(Frozen):
    """One list, with the size of what is in it."""

    id: int
    name: str
    created_at: str
    member_count: int
    duration_s: float
    sounding_s: float | None
    """Playing time with the dead air taken out, or null when nothing is measured."""

    size_bytes: int


class ListCollection(Frozen):
    """Every list, newest name order aside, oldest first."""

    total: int
    items: list[ListSummary]


class ListDetail(ListSummary):
    """One list and a page of its members, in play order."""

    limit: int
    offset: int
    items: list[FileSummary]


class ListWriteRequest(BaseModel):
    """Body of ``POST /api/lists`` and ``PATCH /api/lists/{id}``."""

    name: str = Field(min_length=1, max_length=MAX_LIST_NAME)


class ListDeleted(Frozen):
    """What ``DELETE /api/lists/{id}`` removed.

    ``removed_members`` counts membership rows, not sounds and not files. The
    sounds themselves are untouched.
    """

    id: int
    name: str
    removed_members: int


class ListMembership(Frozen):
    """Whether a hash is in a list, and where in the running order."""

    list_id: int
    hash: str
    member: bool
    position: int | None
    added_at: str | None
    member_count: int


class BulkRequest(BaseModel):
    """Body of ``POST /api/bulk``.

    ``hashes`` are digests, never paths. Unknown digests are skipped rather
    than refused: the client's selection can be older than the last rescan, and
    failing a batch of 900 good hashes over one stale one helps nobody.
    """

    hashes: list[str] = Field(max_length=MAX_BULK_HASHES)
    action: BulkAction
    list_id: int | None = None


class BulkResult(Frozen):
    """Counts from one bulk action. Applied whole or not at all.

    ``requested`` is what arrived, ``unique`` is what was left after dropping
    repeats, ``matched`` is how many of those are sounds this index knows,
    ``changed`` is how many rows the action actually wrote or removed, and
    ``skipped`` is the unknown remainder. ``unchanged`` were already in the
    asked-for state.
    """

    action: BulkAction
    list_id: int | None
    requested: int
    unique: int
    matched: int
    changed: int
    unchanged: int
    skipped: int


class TriageCounts(Frozen):
    """How much of the collection has been dealt with.

    A sound is triaged when it is starred, discarded, or in at least one list.
    The three counts overlap, so they do not sum to ``triaged``: a sound that is
    both starred and in a list is counted once by ``triaged`` and once by each
    of ``starred`` and ``listed``.
    """

    total: int
    triaged: int
    untriaged: int
    percent: float
    starred: int
    deleted: int
    listed: int
    lists: int


class DupePath(Frozen):
    """One alias of a duplicated blob, and whether it may be removed.

    ``deletable`` is advice for the interface, not a capability. This server has
    no route that removes a file, and is not going to grow one.
    """

    path: str
    root: str
    in_bundle: bool
    deletable: bool


class DupeGroup(Frozen):
    """One blob reachable through more than one path.

    ``copies`` and ``wasted_bytes`` are scoped the same way the surrounding
    query is: with bundles excluded they count only the copies a cleanup could
    actually remove. ``paths`` and ``entries`` always list every alias, so the
    full picture stays visible even when part of it is untouchable.
    """

    hash: str
    filename: str
    size_bytes: int
    duration_s: float | None
    copies: int
    wasted_bytes: int
    favorite: bool
    bundle_copies: int
    paths: list[str]
    entries: list[DupePath]


class DupeList(Frozen):
    """A page of duplicate groups, plus the totals over all of them.

    ``excluded_bundle_groups`` and ``excluded_bundle_bytes`` are what the
    default scoping leaves out: redundancy that exists only inside DAW project
    bundles. Reporting it as reclaimable would invite deleting a project's own
    media, so it is counted separately and never mixed into ``wasted_bytes``.
    """

    total: int
    limit: int
    offset: int
    extra_copies: int
    wasted_bytes: int
    within_root: bool
    include_bundles: bool
    excluded_bundle_groups: int
    excluded_bundle_bytes: int
    items: list[DupeGroup]


class SpanInfo(Frozen):
    """One labelled region of a sound, as stage 3 will write it."""

    id: int
    hash: str
    method: str
    start_s: float
    end_s: float
    label: str
    confidence: float | None
    detail: str | None


class SpanList(Frozen):
    """Every span of one sound, optionally narrowed to a single method."""

    hash: str
    method: str | None
    total: int
    items: list[SpanInfo]


class RootCount(Frozen):
    """Per-root counters."""

    root: str
    aliases: int
    distinct_blobs: int
    bytes_on_disk: int


class NameCount(Frozen):
    """A format breakdown entry: an extension or a codec, and its count."""

    name: str
    count: int


class StatsResponse(Frozen):
    """Collection totals."""

    aliases: int
    blobs: int
    logical_bytes: int
    physical_bytes: int
    wasted_bytes: int
    duplicate_blobs: int
    extra_copies: int
    probed_blobs: int
    probe_failures: int
    peaks_cached: int
    total_duration_s: float
    total_sounding_s: float
    """Wall time minus every measured gap of 2 seconds or more.

    The header says this rather than ``total_duration_s``. Eleven and a half of
    the collection's hours are below −50 dB; counting them as listening time
    describes a collection nobody has.
    """

    measured_blobs: int
    """How many sounds have been through ``audio-browser silence``.

    ``total_sounding_s`` is only as complete as this. An unmeasured sound
    contributes its wall duration, because that is all that is known about it.
    """

    favorites: int
    tags: int
    roots: list[RootCount]
    extensions: list[NameCount]
    codecs: list[NameCount]


class Health(Frozen):
    """Liveness and a one-line description of the index behind it."""

    ok: bool
    database: str
    blobs: int
    aliases: int


# ---------------------------------------------------------------------- silence


class SilenceInterval(Frozen):
    """One gap, in seconds from the start of the sound."""

    start_s: float
    end_s: float


class SilenceReport(Frozen):
    """One sound's dead air, at the floor the caller asked for.

    Every gap down to 0.4 seconds is stored and the floor is applied when this
    is read, so ``min_gap`` is a setting rather than a property of the data.

    ``measured`` tells "measured and silent nowhere" apart from "never
    measured". The two look identical in ``intervals`` and mean opposite things:
    the first is a sound that plays all the way through, the second is a sound
    nobody has looked at. A client that cannot tell them apart either invents a
    sounding length or refuses to skip a file that is nine tenths silence.
    """

    hash: str
    measured: bool
    min_gap: float
    duration_s: float | None
    sounding_s: float | None
    silent_s: float
    measured_at: str | None
    max_db: float | None
    mean_db: float | None
    intervals: list[SilenceInterval]


# --------------------------------------------------------------------- projects
#
# Nothing below this line removes audio. A project holds content hashes; adding
# one writes a line into a JSON document and removing one deletes that line.
# Every path that held the bytes still holds them either way.


Placement = Literal["stored", "collage", "enrich", "released"]
BoardColumn = Literal["stored", "collage", "enrich"]


class Abandonment(Frozen):
    """When a project left the board without being promoted, and what it left.

    ``from_column`` is the column revive puts it back into. It is serialised as
    ``from``, which is the field name in the schema and a keyword in Python.
    """

    at: str
    from_: BoardColumn = Field(
        serialization_alias="from", validation_alias="from"
    )
    """The column revive puts it back into.

    ``from`` is the field name in the schema and a keyword in Python, so the
    attribute is ``from_`` and the two aliases carry the real name over the
    wire in both directions.
    """

    reason: str

    model_config = ConfigDict(frozen=True, populate_by_name=True)


class CommitEntry(Frozen):
    """One entry in the chain: which stage was frozen, when, and what it froze."""

    column: BoardColumn
    at: str
    digest: str


class ProjectSummary(Frozen):
    """One row of ``GET /api/projects``: a board card without opening the file.

    Every measure is nullable, and absent is null rather than zero. A length of
    0:00 against a project holding four minutes of audio is a lie, so the board
    says nothing instead.
    """

    id: str
    name: str
    column: Placement
    created_at: str
    updated_at: str
    abandoned: Abandonment | None
    """Non-null means off the board, holding no slot. Cleared by revive.

    ``column`` still records where it was, which is what revive needs.
    """

    commits: list[CommitEntry]
    sound_count: int
    duration_s: float | None
    sounding_s: float | None
    size_bytes: int | None
    sound_set_verified: bool | None
    """Whether the member hashes still hash to the digest the ``stored`` commit
    froze.

    Null means there is nothing to check yet. False means the file was edited
    after the freeze, which is exactly what the digest exists to make visible:
    the freeze is a fact that can be checked, not a rule the app promises to
    keep.
    """


class UnreadableProject(Frozen):
    """A project file that does not match the schema, and why.

    It is reported rather than skipped. A file that cannot be read is still a
    file somebody made, and one whose ``column`` is legible still holds that
    column's slot — otherwise a single junk key would free a slot with no
    override.
    """

    id: str
    problem: str


class ProjectList(Frozen):
    """Every project, and every file that could not be read as one."""

    total: int
    items: list[ProjectSummary]
    unreadable: list[UnreadableProject]


class ProjectIssue(Frozen):
    """One reason a document does not validate."""

    path: str
    message: str


class ProjectDetail(Frozen):
    """One project's document, its members as list rows, and what is wrong.

    A file that does not validate answers 200 with ``valid: false`` and the
    reasons, not 404. The file exists; it is the shape that is wrong, and
    hiding it behind "not found" would send somebody looking for a file that is
    right in front of them.
    """

    id: str
    valid: bool
    issues: list[ProjectIssue]
    summary: ProjectSummary | None
    items: list[FileSummary]
    document: dict[str, Any] | None


class ProjectCreateRequest(BaseModel):
    """Body of ``POST /api/projects``."""

    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    override: bool = False
    """Go past the cap on purpose.

    The board does not silently refuse and it does not hard block. It states the
    cap, takes this, and then keeps showing the column as over its limit until
    the count comes back down. A hard block would only teach people to edit the
    configuration.
    """


class ProjectPatchRequest(BaseModel):
    """Body of ``PATCH /api/projects/{id}``. Name and notes, and nothing else.

    ``column`` is accepted only so that sending it can be refused with a 409
    that says why. Commit is the only way a project advances; if a field could
    move it, every freeze would be sidesteppable by editing that field.
    """

    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_LENGTH)
    notes: str | None = Field(default=None, max_length=MAX_NOTES_LENGTH)
    column: str | None = None


class ProjectCommitRequest(BaseModel):
    """Body of ``POST /api/projects/{id}/commit``."""

    override: bool = False
    """Commit into a column that is already full. Capacity only."""

    expect_column: BoardColumn | None = None
    """The stage the caller believes it is freezing.

    Each commit freezes a different artifact, so a request says which one it
    means. Without it a second tab, or a retry after a timeout, presses "freeze
    the sound set" and freezes the arrangement instead: a stage nobody worked,
    with a digest of nothing, and commit is one way so the damage is permanent.
    A mismatch is refused and **no override gets through** — it is a stale
    client, not a capacity decision.
    """


class ProjectAbandonRequest(BaseModel):
    """Body of ``POST /api/projects/{id}/abandon``."""

    reason: str = Field(default="", max_length=MAX_REASON_LENGTH)


class ProjectReviveRequest(BaseModel):
    """Body of ``POST /api/projects/{id}/revive``."""

    override: bool = False


class ProjectCommitted(Frozen):
    """What one commit froze, and where the project is now."""

    summary: ProjectSummary
    commit: CommitEntry
    artifact_real: bool
    """False while the committing column has no view yet.

    ``collage`` and ``enrich`` are real applications and are not built. Their
    digest is deterministic and unique, so two commits never collide, but it is
    a digest of a placeholder and the interface says so rather than presenting
    it as a digest of work.
    """


class ProjectMembership(Frozen):
    """Whether a hash is in a project, and how big the project now is.

    ``member: false`` after a ``DELETE`` means the project no longer lists this
    sound. The sound, its aliases and its bytes are exactly as they were.
    """

    project_id: str
    hash: str
    member: bool
    added_at: str | None
    sound_count: int
    summary: ProjectSummary


class BoardColumnState(Frozen):
    """One column of ``GET /api/board``."""

    column: BoardColumn
    cap: int
    count: int
    unreadable: int
    """How many of ``count`` are files that could not be read.

    A file whose ``column`` is legible holds the slot it sits in even when the
    rest of it is nonsense. Skipping it would be a cap bypass that needs no
    override.
    """

    over: bool
    """The server's reading of its own cap.

    The client draws what this says and never decides for itself what counts as
    over, or it could show a column as fine while the server refuses writes to
    it.
    """


class Board(Frozen):
    """The three columns with their caps and occupancy, and what sits off it."""

    columns: list[BoardColumnState]
    released: int
    abandoned: int
    unreadable: int
