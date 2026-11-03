"""The booth's HTTP API on 127.0.0.1 (docs/bluesky-bot.md, "The API"). Every request needs the bot's token.

The worker runs in a thread beside the server and takes one job at a time (runner.py); a request never waits on Live.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from pathlib import Path

from aiohttp import web

from . import palette as P
from . import samples as S
from .check import check
from .config import Settings
from .jobs import FILES, Jobs
from .runner import Runner
from .score import MAX_AUDIO_S, MAX_BARS, MAX_CLIPS, MAX_NOTES, MAX_PARTS, MAX_SLICES, Score

log = logging.getLogger(__name__)
EXAMPLES = Path(__file__).resolve().parents[2] / "palettes" / "examples"

RULES = """\
- A score is data: palette instruments, notes, gains, pans, two sends and named macros. 4/4 only.
- Time is in beats. A pattern is `bars` long; its notes start at `t` beats from its start, last `d` beats.
- A pattern repeats to fill each song section that plays it, and is cut at the section's end.
- Each section lists which part plays which pattern; a part left out is silent there.
- Keep every note inside its instrument's `range`. Drum kits play pads 36-51.
- Sends (`room`, `echo`) are 0..1; 0 is off. `mix` picks one room and one echo setting for the whole piece.
- Feel (swing, humanize, velocity jitter) is applied by the booth, seeded: write notes on the grid.
- The master chain is fixed and brings the piece to about -14 LUFS: balance with gain_db, don't fight the limiter.
- Make sections differ in level and density: a build, a drop, a breakdown. Flat pieces come back flagged.
"""


SAMPLE_RULES = {
    "": """\
- Samples: a request may come with samples, audio someone shared, each with its booth id, its length in seconds and
  where its hits start (onsets_s). A part may play one instead of an instrument: `"sample": {"id": ..., "mode": ...}`
  and no `instrument`. Use only the ids given with the request. A sample part is levelled like an instrument: balance
  it with gain_db, pan and the sends; it has no macros.
""",
    "clip": """\
- mode "clip": the recording itself, placed in the arrangement from `start_beat` (song beats). `loop` repeats it back
  to back until `length_beats` or the song's end; it is always cut at the song's end. `warp` "off" plays it as
  recorded (it lasts seconds x bpm / 60 beats, so it drifts off the grid unless it was made at this tempo); "beats"
  (drums, loops) or "complex" (voices, music, anything else) stretch the whole sample to `fit_beats` (default: the
  nearest whole bars), so a loop lands on the grid. `transpose` in semitones (with warp off it also plays faster or
  slower, like tape). A clip part plays no patterns: leave it out of `patterns` and the song's sections.
""",
    "one_shot": """\
- mode "one_shot": patterns play the whole sample from each note, like a drum hit; pitch 60 plays it as recorded,
  each semitone repitches it (24-96).
""",
    "slices": """\
- mode "slices": the sample is cut where `slices` says (seconds into it, rising, the first 0, at most %d; onsets_s is
  a good start, or even steps for a loop); pitch 36 plays the first slice, 37 the second, and so on, each from its
  start to the next. Write patterns that chop and reorder them.
""" % MAX_SLICES,
}


def sample_rules(modes) -> str:
    modes = [m for m in ("clip", "one_shot", "slices") if m in (modes or ())]
    return "".join(SAMPLE_RULES[m] for m in ["", *modes]) if modes else ""


def examples(pal: P.Palette) -> list[dict]:
    """The example scores, written for that palette: those whose instruments it has, with its version."""
    out = []
    for path in sorted(EXAMPLES.glob("*.json")):
        ex = json.loads(path.read_text())
        if all(part["instrument"] in pal.instruments for part in ex["parts"]):
            out.append({**ex, "palette": pal.version})
    return out


def guide(version: str | None = None, samples: list[str] | tuple[str, ...] = ()) -> dict:
    """That palette's guide, else palette.SERVED's. The server asks for config.toml's `palette`, or the request's
    `?palette=`, so the bot can be tried on the next palette before the booth serves it. KeyError: no such palette.
    `samples` are the sample modes the booth takes (config.toml's `samples`): with none, the guide says nothing about
    samples, so the composer never writes a part the booth would refuse."""
    pal = P.load(version) if version else P.served()
    limits = {"parts": MAX_PARTS, "bars": [4, MAX_BARS], "audio_s": MAX_AUDIO_S, "notes": MAX_NOTES, "bpm": [60, 180]}
    out = {**pal.guide(), "schema": Score.model_json_schema(), "rules": RULES + sample_rules(samples),
           "examples": examples(pal), "limits": limits}
    if samples:
        limits.update(sample_clips=MAX_CLIPS, sample_slices=MAX_SLICES)
        out["samples"] = {"modes": [m for m in ("clip", "one_shot", "slices") if m in samples],
                          "upload": {"bytes": S.MAX_BYTES, "seconds": S.MAX_S, "formats": ["wav", "aiff", "flac", "mp3"]}}
    return out


def _err(status: int, code: str, message: str, **extra) -> web.Response:
    return web.json_response({"error": code, "message": message, **extra}, status=status)


def app(jobs: Jobs, runner: Runner, settings: Settings, token: str) -> web.Application:
    @web.middleware
    async def auth(request: web.Request, handler):
        got = request.headers.get("Authorization", "")
        if not token or not hmac.compare_digest(got.encode(), f"Bearer {token}".encode()):
            return _err(401, "unauthorized", "a booth token is needed")
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except Exception as exc:          # answer JSON, and never leak a traceback to the bot
            log.exception("request %s", request.path)
            return _err(500, "internal", type(exc).__name__)

    async def body(request: web.Request) -> dict:
        try:
            data = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise web.HTTPBadRequest(text=json.dumps({"error": "bad_json", "message": "the body is not JSON"}),
                                     content_type="application/json")
        if not isinstance(data, dict):
            raise web.HTTPBadRequest(text=json.dumps({"error": "bad_json", "message": "the body is not an object"}),
                                     content_type="application/json")
        return data

    async def get_guide(request):
        version = request.query.get("palette") or settings.palette or None
        try:
            return web.json_response(guide(version, settings.samples))
        except KeyError:
            return _err(404, "unknown_palette", f"the booth has palettes {P.versions()}")

    async def post_check(request):
        data = await body(request)
        return web.json_response(check(data.get("score"), samples=settings.samples).json())

    async def post_job(request):
        data = await body(request)
        key = data.get("key")
        if not isinstance(key, str) or not 1 <= len(key) <= 300:
            return _err(400, "bad_key", "key is a string of 1-300 characters")
        old = jobs.by_key(key)
        if old:
            return web.json_response(jobs.public(old), status=200)
        res = check(data.get("score"), samples=settings.samples)
        if not res.ok:
            return _err(400, "invalid_score", "the score does not pass check", errors=res.errors)
        if len(jobs.queue()) >= settings.queue_max:
            return _err(429, "queue_full", f"{settings.queue_max} pieces are waiting", retry_in_s=300)
        reason = runner.gate.reason(jobs)
        if reason and jobs.kv("open", "0") != "1":      # closed by Anthony or held: don't take more work
            return _err(503, "closed", reason, reason=reason, retry_in_s=600)
        parent = data.get("parent") if isinstance(data.get("parent"), str) else None
        want = data.get("want") if isinstance(data.get("want"), dict) else {}
        job, _ = jobs.add(key, res.score.model_dump(), want, parent[:300] if parent else None)
        out = jobs.public(job)
        out["eta_s"] = int(sum(check(j["score"]).estimate["render_s"] for j in jobs.queue()))
        return web.json_response(out, status=202)

    async def get_job(request):
        job = jobs.get(request.match_info["job"])
        if not job:
            return _err(404, "no_job", "no such job")
        return web.json_response(jobs.public(job))

    async def get_file(request):
        jid, name = request.match_info["job"], request.match_info["name"]
        job = jobs.get(jid)
        if not job or name not in FILES:
            return _err(404, "no_file", "no such file")
        path = jobs.dir / job["id"] / name
        if not path.is_file() or (job["state"] != "done" and name != "score.json"):
            return _err(404, "no_file", "not ready")
        return web.FileResponse(path)

    async def delete_job(request):
        jid = request.match_info["job"]
        if not jobs.get(jid):
            return _err(404, "no_job", "no such job")
        return web.json_response({"cancelled": jobs.cancel(jid)})

    async def post_sample(request):
        """The request's body is the file itself (any content type). Answers 201 for a new sample, 200 for one the
        booth already has from the same bytes."""
        if not settings.samples:
            return _err(403, "samples_off", "the booth takes no samples now")
        size = request.content_length
        if size is not None and size > S.MAX_BYTES:
            return _err(413, "too_large", f"{size} bytes; at most {S.MAX_BYTES}")
        data = bytearray()
        async for chunk in request.content.iter_chunked(1 << 16):      # past the app's 1 MB body limit, to our own
            data += chunk
            if len(data) > S.MAX_BYTES:
                return _err(413, "too_large", f"over {S.MAX_BYTES} bytes")
        if not data:
            return _err(400, "empty", "no file in the body")
        try:
            meta, new = await asyncio.to_thread(S.add, bytes(data))
        except S.SampleError as exc:
            return _err(exc.status, exc.code, str(exc))
        return web.json_response(S.public(meta), status=201 if new else 200)

    async def get_sample(request):
        meta = S.info(request.match_info["sample"])
        if not meta:
            return _err(404, "no_sample", "no such sample")
        return web.json_response(S.public(meta))

    async def get_status(_):
        reason = runner.gate.reason(jobs)
        front = await asyncio.to_thread(runner.gate.front)
        return web.json_response({"open": jobs.kv("open", "0") == "1", "reason": reason or "", "running": runner.current,
                                  "queue": len(jobs.queue()), "live": {"front": front}, "today": jobs.today()})

    a = web.Application(middlewares=[auth], client_max_size=1 << 20)
    a.add_routes([
        web.get("/v1/guide", get_guide), web.post("/v1/check", post_check), web.post("/v1/jobs", post_job),
        web.get("/v1/jobs/{job}", get_job), web.get("/v1/jobs/{job}/files/{name}", get_file),
        web.delete("/v1/jobs/{job}", delete_job), web.get("/v1/status", get_status),
        web.post("/v1/samples", post_sample), web.get("/v1/samples/{sample}", get_sample),
    ])

    async def worker(_app):
        async def loop():
            while True:
                try:
                    await asyncio.to_thread(runner.tick)
                except Exception:
                    log.exception("worker")
                await asyncio.sleep(2)
        task = asyncio.create_task(loop())
        yield
        task.cancel()

    a.cleanup_ctx.append(worker)
    return a
