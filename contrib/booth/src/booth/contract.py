"""The messages between the bot and the booth's HTTP API, typed: what the booth takes and what it answers.

One model per message. `scripts/gen_schema.py` writes each to `lib/contracts/booth-*.schema.json`; the booth's tests
check its answers against them, and the bot's fake booth (contrib/bot/fake-booth.mjs) is tested against the same files.
The wire field names are the protocol: they stay as they are. A model here describes; the booth's own code still
builds each answer (jobs.public, measure.measure, check.Result), so a test that validates them catches drift.

`parse_job_request` is the one parse of POST /v1/jobs. It is as lenient as the booth has always been where the bot
could not care (a `parent` that is not a string is ignored, a `want` that is not an object is empty), and strict where
it matters (the key). The score itself is checked by check.py.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Spelled out for the type checker; tests/test_api_contract.py checks they match jobs.STATES, jobs.FILES, measure.FLAGS.
State = Literal["queued", "building", "rendering", "measuring", "done", "failed", "held"]
FileName = Literal["render.m4a", "video.mp4", "still.jpg", "score.json", "measure.json", "loop.m4a"]
Flag = Literal["silent", "clipping", "too_quiet", "no_contrast", "lost_on_phone"]

MAX_KEY = 300  # the bot's keys are post URIs with a version (at://...#v2~1)


class _Open(BaseModel):
    """An answer may grow a field; a reader ignores what it does not know."""

    model_config = ConfigDict(extra="allow")


# ---- what the booth takes ------------------------------------------------------------------------------------------
class Want(_Open):
    """What the bot would like made beside the render. Only `loop` changes anything today; `video` and `stems` are
    what the bot sends, and the booth makes its video at config.toml's `video_size` whatever it asks."""

    loop: bool = Field(False, description="also a seamless loop.m4a of the song, for a Room World room")
    video: dict[str, Any] | None = Field(None, description='the bot sends {"size": [1080, 1920]}; not read')
    stems: bool | None = Field(None, description="not read")


class JobRequest(BaseModel):
    """POST /v1/jobs. The same key always answers the same job, so a bot that crashed never renders twice."""

    key: str = Field(min_length=1, max_length=MAX_KEY, description="the bot's idempotency key")
    score: dict[str, Any] = Field(description="a score (score.schema.json), checked by POST /v1/check's rules")
    parent: str | None = Field(None, description="the job this one revises, kept with the job (at most 300 characters)")
    want: Want = Field(default_factory=Want)


class BadRequest(ValueError):
    """A request the booth will not take: `code` is stable for the bot, the message says what to send instead."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def parse_job_request(data: dict[str, Any]) -> tuple[str, Any, str | None, dict[str, Any]]:
    """(key, raw score, parent, want) from a POST /v1/jobs body, or BadRequest. The score is returned raw: check.py
    gives the composer its errors with paths. `want` is returned as sent, since the job keeps it as sent."""
    key = data.get("key")
    if not isinstance(key, str) or not 1 <= len(key) <= MAX_KEY:
        raise BadRequest("bad_key", f"key is a string of 1-{MAX_KEY} characters")
    parent = data.get("parent")
    want = data.get("want")
    return (
        key,
        data.get("score"),
        parent[:MAX_KEY] if isinstance(parent, str) and parent else None,
        want if isinstance(want, dict) else {},
    )


# ---- what the booth answers ----------------------------------------------------------------------------------------
class Problem(BaseModel):
    """One error or warning of a check: `path` points into the score, `code` is stable."""

    path: str
    code: str
    message: str


class Estimate(_Open):
    audio_s: float
    render_s: int = Field(description="the booth's guess at the Live time the job takes, seconds")
    notes: int
    clips: int | None = Field(None, description="only when samples are placed as clips")


class CheckResult(BaseModel):
    """POST /v1/check."""

    ok: bool
    errors: list[Problem]
    warnings: list[Problem]
    estimate: Estimate | None


class Section(BaseModel):
    label: str = Field(description='"section 1", "section 2", ... in song order')
    start_s: float
    end_s: float
    lufs: float | None = Field(description="None when the section is too short or silent to measure")


class Measure(_Open):
    """measure.json, and a done job's `measure`. Every level is None for a silent render (which never finishes)."""

    seconds: float
    sample_rate: int
    lufs: float | None
    true_peak_db: float | None
    phone_db: float | None = Field(description="the level above 180 Hz against the whole, dB: the phone speaker model")
    sections: list[Section]
    flags: list[Flag]
    notes: list[str] = Field(description="each flag in plain words, in the same order")
    master_gain_db: float | None = Field(None, description="only when a quiet first export was made louder in Live")


class JobError(BaseModel):
    """Why a job failed or is held. `retryable`: sending the same score again later may work."""

    stage: str
    code: str
    message: str
    retryable: bool


class Job(BaseModel):
    """GET /v1/jobs/{id}, and the answer to POST /v1/jobs (202 for a new job, with `eta_s`; 200 for a key the booth
    already has, without it)."""

    job: str = Field(pattern=r"^[a-z0-9]{12}$")
    key: str
    state: State
    stage: str = Field(description='the step in progress ("open", "load p2", "export", "encode"), "" when none')
    parent: str | None
    position: int | None = Field(description="place in the queue from 1, None when not queued")
    timings: dict[str, float] = Field(description="seconds per finished step")
    measure: Measure | None
    files: list[FileName] = Field(description="the files GET /v1/jobs/{id}/files/{name} serves; empty until done")
    error: JobError | None
    eta_s: int | None = Field(
        None, description="only on POST /v1/jobs 202: seconds of Live time queued, this one included"
    )


class StatusLive(BaseModel):
    front: str | None = Field(description="the set in front of Live, None when Live cannot be asked")


class Today(BaseModel):
    jobs: int
    live_s: int


class Status(BaseModel):
    """GET /v1/status."""

    open: bool = Field(description="Anthony's switch (booth open / booth close)")
    reason: str = Field(description='why a job may not start now, "" when one may')
    running: str | None = Field(description="the job in Live now")
    queue: int
    live: StatusLive
    today: Today


class ErrorBody(_Open):
    """Every answer that is not a 2xx. 503 `closed` and 429 `queue_full` mean "not now" and carry `retry_in_s`."""

    error: str = Field(
        description="a stable code: unauthorized, bad_json, bad_key, invalid_score, queue_full, closed, ..."
    )
    message: str
    reason: str | None = Field(None, description="with 503 closed")
    retry_in_s: int | None = Field(None, description="with 503 closed and 429 queue_full")
    errors: list[Problem] | None = Field(None, description="with 400 invalid_score")


# The generated files in lib/contracts, by name.
SCHEMAS: dict[str, type[BaseModel]] = {
    "booth-job-request": JobRequest,
    "booth-job": Job,
    "booth-measure": Measure,
    "booth-check": CheckResult,
    "booth-status": Status,
    "booth-error": ErrorBody,
}
