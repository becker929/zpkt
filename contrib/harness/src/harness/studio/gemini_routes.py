"""Gemini CLI sessions on the phone, under /studio/gemini/ behind the harness password (harness/gemini.py,
contrib/docs/gemini.md).

    GET    /studio/gemini/                          the page (static/gemini)
    GET    /studio/gemini/api/state                 the sessions, this month's estimated dollars, the models and modes
    POST   /studio/gemini/api/sessions              {model?, mode?}: a new Gemini CLI session in the zpkt checkout
    GET    /studio/gemini/api/sessions/<id>         one session and every event so far
    PATCH  /studio/gemini/api/sessions/<id>         {title?, model?, mode?}
    DELETE /studio/gemini/api/sessions/<id>         forget it here (Gemini CLI keeps its own record)
    POST   /studio/gemini/api/sessions/<id>/prompt  {text, images: [{mime, data}]}: starts a turn and returns at once
    GET    /studio/gemini/api/sessions/<id>/events  ?after=<n>: the events after n, then new ones as NDJSON until the
                                                    session is idle (the page reconnects; the turn never depends on it)
    POST   /studio/gemini/api/sessions/<id>/cancel  stop the turn
    POST   /studio/gemini/api/permissions/<pid>     {option}: answer what Gemini asked (null declines)
    GET    /studio/gemini/files/<id>/<name>         an attached image (cached forever: names are never reused)
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from aiohttp import web

from .. import gemini as G
from ..config import ZPKT
from .assets import accepts_gzip

log = logging.getLogger(__name__)

PAGE = Path(__file__).parent / "static" / "gemini"
MAX_PROMPT = 16 * 1024 * 1024      # images come inline; read from the stream, past the harness's 64 KB body cap
GEMINI_KEY = web.AppKey("gemini", dict)


def add_gemini_routes(sub: web.Application, *, gemini: G.Gemini | None = None) -> None:
    """`gemini` is for tests; the harness makes one from its config on first use."""
    sub[GEMINI_KEY] = {"gemini": gemini}
    r = sub.router
    r.add_get("/gemini", slash)
    r.add_get("/gemini/api/state", state)
    r.add_post("/gemini/api/sessions", new_session)
    r.add_get("/gemini/api/sessions/{id}", get_session)
    r.add_patch("/gemini/api/sessions/{id}", patch_session)
    r.add_delete("/gemini/api/sessions/{id}", delete_session)
    r.add_post("/gemini/api/sessions/{id}/prompt", prompt)
    r.add_get("/gemini/api/sessions/{id}/events", events)
    r.add_post("/gemini/api/sessions/{id}/cancel", cancel)
    r.add_post("/gemini/api/permissions/{pid}", permission)
    r.add_get("/gemini/files/{id}/{name}", attachment)
    r.add_get("/gemini/{path:.*}", page)
    sub.on_cleanup.append(_close)


async def _close(app: web.Application) -> None:
    g = app[GEMINI_KEY].get("gemini")
    if g is not None:
        await g.close()


def _g(request: web.Request) -> G.Gemini:
    box = request.config_dict[GEMINI_KEY]
    if box["gemini"] is None:
        from .routes import _studio
        cfg = _studio(request).cfg
        box["gemini"] = G.Gemini(cfg.studio_dir / "gemini", getattr(cfg, "studio_workdir", ZPKT), G.keychain_key,
                                 notify=G.phone_notify(lambda: cfg.app_url))
    return box["gemini"]


def _json(data, status: int = 200) -> web.Response:
    return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})


def _err(status: int, text: str) -> web.HTTPException:
    cls = {400: web.HTTPBadRequest, 404: web.HTTPNotFound, 409: web.HTTPConflict, 502: web.HTTPBadGateway}[status]
    return cls(text=json.dumps({"error": text}), content_type="application/json")


def _rec(request: web.Request) -> dict:
    try:
        return _g(request).record(request.match_info["id"])
    except KeyError:
        raise _err(404, "No such session.") from None


async def _body(request: web.Request, limit: int = 1 << 20) -> dict:
    raw = bytearray()
    async for chunk in request.content.iter_chunked(65536):
        raw += chunk
        if len(raw) > limit:
            raise web.HTTPRequestEntityTooLarge(max_size=limit, actual_size=len(raw))
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        raise _err(400, "Body must be JSON.") from None
    if not isinstance(body, dict):
        raise _err(400, "Body must be a JSON object.")
    return body


async def slash(_request: web.Request) -> web.Response:
    raise web.HTTPFound("/studio/gemini/")


async def page(request: web.Request) -> web.StreamResponse:
    rel = request.match_info["path"] or "index.html"
    path = (PAGE / rel).resolve()
    if not path.is_relative_to(PAGE.resolve()) or not path.is_file():
        raise web.HTTPNotFound()
    resp = web.FileResponse(path, headers={"Cache-Control": "no-cache"})
    if path.suffix in (".html", ".js", ".css", ".svg") and accepts_gzip(request.headers.get("Accept-Encoding", "")):
        resp.enable_compression(web.ContentCoding.gzip)
    return resp


async def state(request: web.Request) -> web.Response:
    g = _g(request)
    from .routes import _image_store
    try:
        manifest = _image_store(request).manifest
    except Exception:  # noqa: BLE001 - no studio in some tests
        manifest = g.root / "none"
    return _json({"sessions": g.list(), "usage": G.month_usage(g.usage_rows(), manifest), "offers": g.offers,
                  "modes": list(G.MODES), "cwd": str(g.cwd)})


async def new_session(request: web.Request) -> web.Response:
    body = await _body(request)
    try:
        rec = await _g(request).new(body.get("model") or None, body.get("mode") or "default")
    except (G.AcpError, ValueError, OSError) as e:
        raise _err(502, f"Could not start Gemini CLI: {e}") from None
    return _json(_g(request).view(rec))


async def get_session(request: web.Request) -> web.Response:
    rec = _rec(request)
    g = _g(request)
    return _json({**g.view(rec), "events": g.session(rec["id"]).events})


async def patch_session(request: web.Request) -> web.Response:
    rec = _rec(request)
    g = _g(request)
    body = await _body(request)
    try:
        if isinstance(body.get("model"), str) and body["model"] != rec.get("model"):
            rec = await g.set_model(rec["id"], body["model"])
        if isinstance(body.get("mode"), str) and body["mode"] != rec.get("mode"):
            rec = await g.set_mode(rec["id"], body["mode"])
    except ValueError as e:
        raise _err(400, str(e)) from None
    except G.AcpError as e:
        raise _err(502, str(e)) from None
    if isinstance(body.get("title"), str) and body["title"].strip():
        rec["title"] = body["title"].strip()[:80]
        g.save(rec)
    return _json(g.view(rec))


async def delete_session(request: web.Request) -> web.Response:
    rec = _rec(request)
    try:
        _g(request).delete(rec["id"])
    except ValueError as e:
        raise _err(409, str(e)) from None
    return _json({"ok": True})


async def prompt(request: web.Request) -> web.Response:
    rec = _rec(request)
    body = await _body(request, MAX_PROMPT)
    text = str(body.get("text") or "").strip()
    images = [im for im in body.get("images") or [] if isinstance(im, dict)]
    if not text and not images:
        raise _err(400, "Nothing to send.")
    g = _g(request)
    after = len(g.session(rec["id"]).events) - 1
    try:
        g.prompt(rec["id"], text, [{"mime": str(im.get("mime")), "data": str(im.get("data"))} for im in images])
    except ValueError as e:
        raise _err(409 if "already" in str(e) else 400, str(e)) from None
    return _json({"ok": True, "after": after})


async def events(request: web.Request) -> web.StreamResponse:
    rec = _rec(request)
    try:
        after = int(request.query.get("after", -1))
    except ValueError:
        raise _err(400, "after is a number") from None
    resp = web.StreamResponse(headers={"Content-Type": "application/x-ndjson", "Cache-Control": "no-store",
                                       "X-Accel-Buffering": "no"})
    await resp.prepare(request)
    try:
        async for ev in _g(request).events(rec["id"], after):
            await resp.write((json.dumps(ev) + "\n").encode())
    except (ConnectionResetError, asyncio.CancelledError):
        return resp                                   # the page went away; the turn goes on
    await resp.write_eof()
    return resp


async def cancel(request: web.Request) -> web.Response:
    rec = _rec(request)
    await _g(request).cancel(rec["id"])
    return _json({"ok": True})


async def permission(request: web.Request) -> web.Response:
    body = await _body(request)
    opt = body.get("option")
    try:
        ok = _g(request).answer(request.match_info["pid"], opt if isinstance(opt, str) else None)
    except ValueError as e:
        raise _err(400, str(e)) from None
    if not ok:
        raise _err(409, "That question is no longer waiting.")
    return _json({"ok": True})


async def attachment(request: web.Request) -> web.StreamResponse:
    path = _g(request).file(request.match_info["id"], request.match_info["name"])
    if path is None:
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": "private, max-age=31536000, immutable"})
