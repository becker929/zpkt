"""The FastAPI application.

Every route that names a sound takes a hash. The hash is checked against
``^[0-9a-f]{64}$`` before it reaches SQL, and the path it maps to comes out of
the database. No route accepts, parses, or joins a client-supplied path, so
there is nothing for a traversal attempt to escape from.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi import Path as PathParam
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from ..config import Config, ProjectsConfig, ServerConfig, default_projects
from ..peaks import PeaksError, ensure_peaks, load_peaks
from ..projects import model as project_model
from ..projects.store import Caps, Loaded, ProjectError, ProjectStore
from ..silence import MIN_GAP_S
from . import board as board_view
from . import queries
from .database import Database
from .models import (
    Board,
    BulkRequest,
    BulkResult,
    DeletedState,
    DeleteRequest,
    DupeList,
    FileDetail,
    FileList,
    Health,
    PeaksResponse,
    ProjectAbandonRequest,
    ProjectCommitRequest,
    ProjectCommitted,
    ProjectCreateRequest,
    ProjectDetail,
    ProjectIssue,
    ProjectList,
    ProjectMembership,
    ProjectPatchRequest,
    ProjectReviveRequest,
    ProjectSummary,
    SilenceReport,
    SpanList,
    StatsResponse,
    SwipeNext,
    TriageCounts,
)
from .queries import MAX_LIMIT, FileFilters
from .streaming import (
    TRANSCODE_EXTS,
    RangeNotSatisfiable,
    TranscodeError,
    content_disposition,
    media_type_for,
    needs_transcode,
    parse_range,
    read_range,
    transcode_to_wav,
)

HASH_RE = re.compile(r"[0-9a-f]{64}")
# The same slug the schema accepts: lower-case words joined by single hyphens.
# A project id is a filename, so this gate is what keeps a path out of one.
SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

SWIPE_SPAN_METHOD = "yamnet"
"""The classifier whose spans tint the swipe waveform.

One method, not a choice. A picker here would be another thing to fiddle with
instead of deciding about the sound that is playing.
"""

Sort = Literal["name", "duration", "sounding"]
Order = Literal["asc", "desc"]
Deleted = Literal["false", "true", "any"]


def valid_hash(
    file_hash: Annotated[
        str, PathParam(description="blake3 hex digest of the sound")
    ],
) -> str:
    """Reject anything that is not a blake3 hex digest.

    This is the gate. A value that gets past it is 64 hex characters, which
    cannot be a path, a wildcard, or SQL.
    """
    if not HASH_RE.fullmatch(file_hash):
        raise HTTPException(
            status_code=400,
            detail="hash must be 64 lowercase hexadecimal characters",
        )
    return file_hash


FileHash = Annotated[str, Depends(valid_hash)]


def valid_project_id(
    project_id: Annotated[str, PathParam(description="the project's slug")],
) -> str:
    """Reject anything that is not a slug.

    The id is the filename, so this is the gate that keeps ``..`` and ``/`` out
    of a path the store is about to open. A value that gets past it cannot be a
    traversal, a wildcard, or a hidden file.
    """
    if len(project_id) > 100 or not SLUG_RE.fullmatch(project_id):
        raise HTTPException(
            status_code=400,
            detail="a project id is lower-case words joined by single hyphens",
        )
    return project_id


ProjectId = Annotated[str, Depends(valid_project_id)]


def create_app(
    db_path: Path,
    server: ServerConfig | None = None,
    *,
    create: bool = False,
    projects: ProjectsConfig | None = None,
) -> FastAPI:
    """Build the application around one index file."""
    settings = server or ServerConfig()
    db = Database(db_path, create=create)
    project_settings = projects or default_projects(db_path.parent)
    store = ProjectStore(
        project_settings.dir,
        validator=project_model.load_validator(project_settings.schemas_dir),
        caps=Caps(
            stored=project_settings.cap("stored"),
            collage=project_settings.cap("collage"),
        ),
        encumbrance=project_settings.encumbrance,
    )

    app = FastAPI(
        title="audio-browser",
        version="0.2.0",
        summary="Content-addressed browser for an audio collection.",
    )
    app.state.db = db
    app.state.settings = settings
    app.state.projects = store

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_origin_regex=settings.cors_origin_regex or None,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        allow_headers=["*"],
        expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
    )

    @app.get("/api/health", response_model=Health, tags=["meta"])
    def health() -> Health:
        conn = db.connection()
        counts = conn.execute(
            "SELECT (SELECT COUNT(*) FROM blob) AS blobs, "
            "       (SELECT COUNT(*) FROM alias) AS aliases"
        ).fetchone()
        return Health(
            ok=True,
            database=str(db.path),
            blobs=counts["blobs"],
            aliases=counts["aliases"],
        )

    @app.get("/api/files", response_model=FileList, tags=["files"])
    def list_files(
        q: Annotated[str | None, Query(description="substring of a filename")] = None,
        ext: Annotated[
            list[str] | None,
            Query(description="extension filter; repeat or comma-separate"),
        ] = None,
        deleted: Annotated[
            Deleted,
            Query(
                description=(
                    "discarded sounds: 'false' hides them (the default), 'true' "
                    "shows only them, 'any' shows both. This is the user's own "
                    "soft delete and has nothing to do with files on disk."
                )
            ),
        ] = "false",
        min_dur: Annotated[float | None, Query(ge=0)] = None,
        max_dur: Annotated[float | None, Query(ge=0)] = None,
        sort: Annotated[Sort, Query()] = "name",
        order: Annotated[Order, Query()] = "asc",
        limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> FileList:
        exts = _split_exts(ext)
        filters = FileFilters(
            q=q,
            exts=exts,
            min_dur=min_dur,
            max_dur=max_dur,
            deleted=deleted,
        )
        return queries.list_files(
            db.connection(),
            filters,
            sort=sort,
            order=order,
            limit=limit,
            offset=offset,
        )

    @app.get("/api/files/{file_hash}", response_model=FileDetail, tags=["files"])
    def file_detail(file_hash: FileHash) -> FileDetail:
        detail = queries.get_detail(
            db.connection(), file_hash, transcoded_exts=TRANSCODE_EXTS
        )
        if detail is None:
            raise HTTPException(status_code=404, detail="unknown hash")
        return detail

    @app.get(
        "/api/files/{file_hash}/peaks", response_model=PeaksResponse, tags=["files"]
    )
    def file_peaks(file_hash: FileHash) -> PeaksResponse:
        conn = db.connection()
        if not queries.blob_exists(conn, file_hash):
            raise HTTPException(status_code=404, detail="unknown hash")
        # One decode per hash at a time. Without this, a list view that asks for
        # ten waveforms at once starts ten ffmpeg processes on the same file.
        with db.peak_lock(file_hash):
            cached = load_peaks(conn, file_hash)
            if cached is not None:
                packed = cached
            else:
                try:
                    packed = ensure_peaks(conn, file_hash)
                except PeaksError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
        return queries.peaks_response(
            conn, file_hash, packed, cached=cached is not None
        )

    @app.get(
        "/api/files/{file_hash}/spans", response_model=SpanList, tags=["files"]
    )
    def file_spans(
        file_hash: FileHash,
        method: Annotated[
            str | None,
            Query(description="narrow to one classifier, e.g. yamnet"),
        ] = None,
    ) -> SpanList:
        conn = db.connection()
        if not queries.blob_exists(conn, file_hash):
            raise HTTPException(status_code=404, detail="unknown hash")
        return queries.spans(conn, file_hash, method=method)

    @app.api_route(
        "/api/files/{file_hash}/stream", methods=["GET", "HEAD"], tags=["files"]
    )
    def file_stream(file_hash: FileHash, request: Request) -> Response:
        conn = db.connection()
        if not queries.blob_exists(conn, file_hash):
            raise HTTPException(status_code=404, detail="unknown hash")
        alias = queries.playable_alias(conn, file_hash)
        if alias is None:
            raise HTTPException(
                status_code=404, detail="no alias of this hash exists on disk"
            )

        headers = {
            "Content-Disposition": content_disposition(alias.filename),
            "Cache-Control": "private, max-age=3600",
            "ETag": f'"{file_hash}"',
        }
        media_type = media_type_for(alias.ext)

        head = request.method == "HEAD"

        if needs_transcode(alias.ext):
            # A transcoded body has no length until ffmpeg finishes, so it
            # cannot be seeked. Say so instead of implying range support.
            headers["Accept-Ranges"] = "none"
            headers["X-Transcoded-From"] = alias.ext
            if head:
                # Nothing to measure, so do not start ffmpeg just to throw the
                # output away. The length is genuinely unknown until ffmpeg
                # finishes, so send no Content-Length rather than a wrong one.
                empty = Response(headers=headers, media_type=media_type)
                del empty.headers["content-length"]
                return empty
            try:
                stream = transcode_to_wav(alias.path)
            except TranscodeError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            return StreamingResponse(
                stream, media_type=media_type, headers=headers
            )

        size = alias.path.stat().st_size
        headers["Accept-Ranges"] = "bytes"
        try:
            span = parse_range(request.headers.get("range"), size)
        except RangeNotSatisfiable as exc:
            raise HTTPException(
                status_code=416,
                detail=str(exc),
                headers={"Content-Range": f"bytes */{size}"},
            ) from exc

        if span is None:
            headers["Content-Length"] = str(size)
            if head:
                return Response(headers=headers, media_type=media_type)
            return StreamingResponse(
                read_range(alias.path, 0, size - 1),
                media_type=media_type,
                headers=headers,
            )

        start, end = span
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        headers["Content-Length"] = str(end - start + 1)
        if head:
            return Response(status_code=206, headers=headers, media_type=media_type)
        return StreamingResponse(
            read_range(alias.path, start, end),
            status_code=206,
            media_type=media_type,
            headers=headers,
        )

    # There is no favourite route. A star meant "keep this, decide later", and
    # the queue has two answers and no later. The `favorite` table and its rows
    # are untouched: removing the route was the decision, and dropping the data
    # would be a second one nobody asked for.

    @app.put(
        "/api/files/{file_hash}/deleted",
        response_model=DeletedState,
        tags=["triage"],
    )
    def soft_delete(
        file_hash: FileHash, body: DeleteRequest | None = None
    ) -> DeletedState:
        """Discard a sound.

        This writes one row keyed on the hash. It does not remove, move, or
        even open a file. The sound drops out of the default list view and
        comes back with ``DELETE`` on this same path.
        """
        conn = db.connection()
        if not queries.blob_exists(conn, file_hash):
            raise HTTPException(status_code=404, detail="unknown hash")
        return queries.set_deleted(conn, file_hash, body.note if body else None)

    @app.delete(
        "/api/files/{file_hash}/deleted",
        response_model=DeletedState,
        tags=["triage"],
    )
    def restore(file_hash: FileHash) -> DeletedState:
        """Undiscard a sound. Nothing was destroyed, so nothing is rebuilt."""
        conn = db.connection()
        if not queries.blob_exists(conn, file_hash):
            raise HTTPException(status_code=404, detail="unknown hash")
        return queries.clear_deleted(conn, file_hash)

    # There are no list routes. Project membership replaced them: a list that is
    # not a project is a maybe-pile with no exit. The `list` and `list_member`
    # tables and their rows stay exactly as they are.

    @app.post("/api/bulk", response_model=BulkResult, tags=["triage"])
    def bulk(body: BulkRequest) -> BulkResult:
        """Discard or restore many hashes, applied as one transaction.

        Every hash is checked against the same rule a path parameter is, so a
        batch cannot smuggle in something that is not a digest. Unknown digests
        are skipped, because a selection can be older than the last rescan.

        The cap of ``MAX_BULK_HASHES`` is on the request model, so an oversized
        batch is refused with a 422 before this function runs.
        """
        for value in body.hashes:
            if not HASH_RE.fullmatch(value):
                raise HTTPException(
                    status_code=400,
                    detail="every hash must be 64 lowercase hexadecimal characters",
                )
        return queries.bulk(db.connection(), body.hashes, body.action)

    @app.get("/api/triage", response_model=TriageCounts, tags=["triage"])
    def triage() -> TriageCounts:
        """Progress through the collection: answered over total.

        The projects are synced from their files first, because a sound is
        triaged when it is discarded or in a project, and the files are where
        project membership actually lives.
        """
        _sync()
        return queries.triage(db.connection())

    @app.get("/api/swipe", response_model=SwipeNext, tags=["triage"])
    def swipe() -> SwipeNext:
        """The next sound to answer, with what the view needs to show it.

        This is the app's front door. One sound, two actions — take it into the
        project on the bench, or discard it — and no way to put it back
        undecided. The sound, its silent gaps and its spans come together so a
        phone makes one request per sound rather than three.

        Answering a sound is done through the routes that already exist:
        ``PUT /api/projects/{id}/sounds/{hash}`` takes it,
        ``PUT /api/files/{hash}/deleted`` discards it. Both drop it out of this
        queue, so it never comes round again.
        """
        loaded = _sync()
        conn = db.connection()
        counts = queries.triage(conn)
        sound = queries.next_undecided(conn)
        open_project = next(
            (
                item
                for item in loaded
                if item.valid
                and project_model.sound_set_open(cast(dict[str, Any], item.document))
            ),
            None,
        )
        return SwipeNext(
            total=counts.total,
            decided=counts.triaged,
            remaining=counts.untriaged,
            sound=sound,
            silence=(
                None
                if sound is None
                else queries.silence_report(conn, sound.hash, min_gap=MIN_GAP_S)
            ),
            spans=(
                None
                if sound is None
                else queries.spans(conn, sound.hash, method=SWIPE_SPAN_METHOD)
            ),
            project=None if open_project is None else _summary(open_project),
        )

    @app.get("/api/dupes", response_model=DupeList, tags=["reports"])
    def dupes(
        limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        within_root: Annotated[bool, Query()] = True,
        include_bundles: Annotated[
            bool,
            Query(
                description=(
                    "include copies inside DAW project bundles. They are never "
                    "deletable, so they are left out of the cleanup view by "
                    "default."
                )
            ),
        ] = False,
    ) -> DupeList:
        return queries.dupes(
            db.connection(),
            limit=limit,
            offset=offset,
            within_root=within_root,
            include_bundles=include_bundles,
        )

    @app.get("/api/stats", response_model=StatsResponse, tags=["reports"])
    def stats() -> StatsResponse:
        return queries.stats(db.connection())

    # ------------------------------------------------------------- silence

    @app.get(
        "/api/files/{file_hash}/silence",
        response_model=SilenceReport,
        tags=["files"],
    )
    def file_silence(
        file_hash: FileHash,
        min_gap: Annotated[
            float,
            Query(
                ge=0,
                description=(
                    "the shortest gap worth skipping, in seconds. Gaps are "
                    "stored down to 0.4 s and filtered here, so this is a "
                    "setting rather than a property of the data."
                ),
            ),
        ] = MIN_GAP_S,
    ) -> SilenceReport:
        """Where this sound is silent, and how long it actually sounds.

        Reads two tables. It never opens the audio and never rewrites it:
        skipping silence changes playback and nothing else.

        A sound that has not been measured answers 200 with ``measured: false``
        and no intervals, not a 404. The sound exists; it is the measurement
        that is missing, and the player needs to tell those apart to know
        whether it may skip.
        """
        conn = db.connection()
        if not queries.blob_exists(conn, file_hash):
            raise HTTPException(status_code=404, detail="unknown hash")
        return queries.silence_report(conn, file_hash, min_gap=min_gap)

    # ------------------------------------------------------------ projects
    #
    # The files in the projects directory are the truth. `_sync` runs before
    # every read below and rebuilds any index row whose file has moved on, so
    # the cache can never outvote its source.

    def _sync() -> list[Loaded]:
        return store.sync(db.connection(), at=project_model.utc_now())

    def _refuse(exc: ProjectError) -> HTTPException:
        """Turn a store refusal into the answer the interface reads.

        A capacity refusal carries ``cap``, ``column`` and ``count`` so the
        client can state the limit and offer the override. Every other refusal
        carries none of them, and the client must not offer a way through
        something that has no way through.
        """
        body: dict[str, object] = {"detail": exc.detail}
        if exc.capacity:
            body.update(
                {
                    "column": exc.column,
                    "cap": exc.cap,
                    "count": exc.count,
                    "overridable": True,
                }
            )
        if exc.missing_column is not None:
            # The end of the pipeline, not a limit. It names the stage that does
            # not exist and offers no override, because there is none to offer.
            body["missing_column"] = exc.missing_column
        return HTTPException(status_code=exc.status, detail=body)

    def _summary(item: Loaded) -> ProjectSummary:
        return board_view.summary(
            db.connection(), item, encumbrance=store.encumbrance
        )

    @app.get("/api/projects", response_model=ProjectList, tags=["projects"])
    def projects_index() -> ProjectList:
        """Every project, and every file that could not be read as one."""
        loaded = _sync()
        return ProjectList(
            total=len(loaded),
            items=[_summary(item) for item in loaded if item.valid],
            unreadable=[board_view.unreadable(i) for i in loaded if not i.valid],
        )

    @app.post(
        "/api/projects",
        response_model=ProjectSummary,
        status_code=201,
        tags=["projects"],
    )
    def new_project(body: ProjectCreateRequest) -> ProjectSummary:
        """Start a project in ``stored``.

        The cap check and the file creation happen under one lock, so two
        requests arriving together cannot both find room in a column with one
        slot left.
        """
        name = _clean_project_name(body.name)
        try:
            made = store.create(name, override=body.override, at=project_model.utc_now())
        except ProjectError as exc:
            raise _refuse(exc) from exc
        _sync()
        return _summary(made)

    @app.get(
        "/api/projects/{project_id}", response_model=ProjectDetail, tags=["projects"]
    )
    def project_detail(project_id: ProjectId) -> ProjectDetail:
        item = store.load(project_id)
        if item is None:
            raise HTTPException(status_code=404, detail="no such project")
        conn = db.connection()
        document = item.document if isinstance(item.document, dict) else None
        hashes = (
            [s["hash"] for s in document["sounds"]]
            if item.valid and document is not None
            else []
        )
        return ProjectDetail(
            id=item.id,
            valid=item.valid,
            issues=[
                ProjectIssue(path=i.path, message=i.message) for i in item.issues
            ],
            summary=_summary(item) if item.valid else None,
            items=queries.files_by_hash(conn, hashes),
            document=document,
        )

    @app.patch(
        "/api/projects/{project_id}", response_model=ProjectSummary, tags=["projects"]
    )
    def edit_project(project_id: ProjectId, body: ProjectPatchRequest) -> ProjectSummary:
        """Rename, or edit notes.

        Sending ``column`` is refused with 409. Commit is the boundary between
        columns and the only thing that crosses one; a project that could be
        moved by editing a field would make every freeze sidesteppable.
        """
        name = _clean_project_name(body.name) if body.name is not None else None
        try:
            edited = store.patch(
                project_id,
                name=name,
                notes=body.notes,
                column=body.column,
                at=project_model.utc_now(),
            )
        except ProjectError as exc:
            raise _refuse(exc) from exc
        _sync()
        return _summary(edited)

    @app.post(
        "/api/projects/{project_id}/commit",
        response_model=ProjectCommitted,
        tags=["projects"],
    )
    def commit_project(
        project_id: ProjectId, body: ProjectCommitRequest | None = None
    ) -> ProjectCommitted:
        """Freeze this column's artifact, append to the chain, and advance.

        Three refusals, and they are not the same kind:

        * 409 with ``cap``: the next column is full. That is the discipline
          working, so it is overridable and the board then shows the receiving
          column as over its limit.
        * 409 without ``cap``: ``expect_column`` named a stage this project has
          already left. A stale view, and **no override gets through**. Two tabs
          would otherwise walk a project ``stored → collage → enrich`` in two
          clicks and freeze a ``collage`` digest over an arrangement nobody
          made. Commit is one way, so that is permanent.
        * 422: a ``stored`` project holding no sounds. Freezing an empty sound
          set is not a discipline being tested; it is an operation with no
          meaning, and overriding it would make a project that can never gain a
          sound and never had one.
        """
        request = body or ProjectCommitRequest()
        try:
            written, entry, artifact = store.commit(
                project_id,
                override=request.override,
                expect_column=request.expect_column,
                at=project_model.utc_now(),
            )
        except ProjectError as exc:
            raise _refuse(exc) from exc
        _sync()
        return ProjectCommitted(
            summary=_summary(written),
            commit=entry,  # type: ignore[arg-type]
            artifact_real=artifact.real,
        )

    @app.post(
        "/api/projects/{project_id}/abandon",
        response_model=ProjectSummary,
        tags=["projects"],
    )
    def abandon_project(
        project_id: ProjectId, body: ProjectAbandonRequest | None = None
    ) -> ProjectSummary:
        """Leave the board and free the slot. The file is kept, not deleted.

        Lighter than committing, because it is reversible: it freezes nothing
        and appends nothing to ``commits``. Without it, a project you no longer
        believe in would hold its slot forever and the only escape would be to
        commit something you do not want.
        """
        try:
            left = store.abandon(
                project_id,
                reason=(body.reason if body else ""),
                at=project_model.utc_now(),
            )
        except ProjectError as exc:
            raise _refuse(exc) from exc
        _sync()
        return _summary(left)

    @app.post(
        "/api/projects/{project_id}/revive",
        response_model=ProjectSummary,
        tags=["projects"],
    )
    def revive_project(
        project_id: ProjectId, body: ProjectReviveRequest | None = None
    ) -> ProjectSummary:
        """Bring an abandoned project back to the column it left.

        It takes a slot like anything else, so it is refused when that column is
        full, with the same override treatment. Every commit it had it still
        has: one abandoned out of ``collage`` comes back to ``collage`` with its
        sound set still frozen.
        """
        try:
            back = store.revive(
                project_id,
                override=(body.override if body else False),
                at=project_model.utc_now(),
            )
        except ProjectError as exc:
            raise _refuse(exc) from exc
        _sync()
        return _summary(back)

    @app.put(
        "/api/projects/{project_id}/sounds/{file_hash}",
        response_model=ProjectMembership,
        tags=["projects"],
    )
    def add_project_sound(
        project_id: ProjectId, file_hash: FileHash
    ) -> ProjectMembership:
        return _set_project_sound(project_id, file_hash, member=True)

    @app.delete(
        "/api/projects/{project_id}/sounds/{file_hash}",
        response_model=ProjectMembership,
        tags=["projects"],
    )
    def drop_project_sound(
        project_id: ProjectId, file_hash: FileHash
    ) -> ProjectMembership:
        """Take one sound out of one project.

        This removes a line from a JSON document. It removes no audio: every
        path that held the bytes still holds them, and the sound is still in the
        library, in every list it was in, and in every other project.
        """
        return _set_project_sound(project_id, file_hash, member=False)

    def _set_project_sound(
        project_id: str, file_hash: str, *, member: bool
    ) -> ProjectMembership:
        conn = db.connection()
        if member and not queries.blob_exists(conn, file_hash):
            raise HTTPException(status_code=404, detail="unknown hash")
        try:
            changed = store.set_sound(
                project_id, file_hash, member=member, at=project_model.utc_now()
            )
        except ProjectError as exc:
            raise _refuse(exc) from exc
        _sync()
        document = changed.as_document()
        entry = next(
            (s for s in document["sounds"] if s["hash"] == file_hash), None
        )
        return ProjectMembership(
            project_id=project_id,
            hash=file_hash,
            member=entry is not None,
            added_at=entry["added_at"] if entry else None,
            sound_count=len(document["sounds"]),
            summary=_summary(changed),
        )

    @app.get("/api/board", response_model=Board, tags=["projects"])
    def board() -> Board:
        """Columns, caps, occupancy, which are over, and what cannot move.

        Every number drawn on screen is the one in this answer. A client that
        drew its own idea of the cap, the encumbrance threshold, or what counts
        as blocked could show a board as fine while the server was refusing
        writes to it.

        ``blocked`` with ``blocks`` is how the interface says why nothing is
        moving, and names the column that does not exist yet.
        """
        return board_view.board(
            _sync(), store.caps, encumbrance=store.encumbrance
        )

    return app


def _clean_project_name(raw: str) -> str:
    """Trim a project name and refuse an empty one.

    ``"  "`` and ``""`` are the same mistake. The schema refuses a name with
    leading or trailing space, so trimming here is what lets someone type one
    without being told off for it.
    """
    name = raw.strip()
    if not name:
        raise HTTPException(status_code=422, detail="a project needs a name")
    if len(name) > project_model.MAX_NAME_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"a project name is at most {project_model.MAX_NAME_LENGTH} characters",
        )
    return name


def _split_exts(raw: list[str] | None) -> tuple[str, ...]:
    """Accept ``?ext=wav&ext=.MP3`` and ``?ext=wav,mp3`` alike."""
    if not raw:
        return ()
    out: list[str] = []
    for item in raw:
        for part in item.split(","):
            norm = queries.normalize_ext(part)
            if norm and norm not in out:
                out.append(norm)
    return tuple(out)


def app_from_config(config: Config) -> FastAPI:
    """Build the application from a loaded ``config.toml``."""
    return create_app(config.db_path, config.server, projects=config.projects)


def serve_app(app: FastAPI, *, host: str, port: int) -> int:
    """Serve an already-built application until interrupted."""
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


def run(
    config: Config,
    *,
    host: str | None = None,
    port: int | None = None,
) -> int:
    """Build and serve. Binds broadly so a tailnet address reaches it."""
    return serve_app(
        app_from_config(config),
        host=host or config.server.host,
        port=port or config.server.port,
    )
