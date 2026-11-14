"""The Gemini chat's routes, under /studio/gemini/ behind the harness password (harness/gemini.py, contrib/docs/gemini.md).

    GET    /studio/gemini/                       the page (static/gemini)
    GET    /studio/gemini/api/state              the chats, the defaults, this month's estimated dollars
    GET    /studio/gemini/api/models             the text models the key can use (cached an hour)
    POST   /studio/gemini/api/settings           change the defaults a new chat starts with
    GET    /studio/gemini/api/chats/<id>         one chat
    PATCH  /studio/gemini/api/chats/<id>         its title or settings
    DELETE /studio/gemini/api/chats/<id>         delete it and its attachments
    POST   /studio/gemini/api/chats/<id>/send    {text, images: [{mime, data}], settings?}: the answer, streamed as
                                                 NDJSON events (chat, text, tool, images, usage, error, done);
                                                 <id> "new" starts a chat
    POST   /studio/gemini/api/chats/<id>/retry   answer the last message again (streamed the same way)
    GET    /studio/gemini/files/<id>/<name>      an attachment (cached forever: names are never reused)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, web

from .. import gemini as G
from ..config import ZPKT, secret
from .assets import accepts_gzip

log = logging.getLogger(__name__)

PAGE = Path(__file__).parent / "static" / "gemini"
MAX_SEND = 16 * 1024 * 1024        # attachments come inline; read from the stream, past the harness's 64 KB body cap
GEMINI_KEY = web.AppKey("gemini", dict)
NOT_A_TEXT_MODEL = ("image", "tts", "live", "embedding", "robotics", "computer-use", "transcribe", "omni",
                    "native-audio", "decision", "customtools", "argon", "carbon", "hydrogen")


def add_gemini_routes(sub: web.Application, *, root: Path | None = None, repo: Path | None = None,
                      key=None, stream=None, image_post=None) -> None:
    """`root`, `repo`, `key`, `stream` and `image_post` are for tests; the harness takes them from its config."""
    sub[GEMINI_KEY] = {"root": root, "repo": repo, "key": key, "stream": stream, "image_post": image_post,
                       "models": (0.0, None), "busy": set()}
    r = sub.router
    r.add_get("/gemini", slash)
    r.add_get("/gemini/api/state", state)
    r.add_get("/gemini/api/models", models)
    r.add_post("/gemini/api/settings", set_defaults)
    r.add_get("/gemini/api/chats/{id}", get_chat)
    r.add_patch("/gemini/api/chats/{id}", patch_chat)
    r.add_delete("/gemini/api/chats/{id}", delete_chat)
    r.add_post("/gemini/api/chats/{id}/send", send)
    r.add_post("/gemini/api/chats/{id}/retry", retry)
    r.add_get("/gemini/files/{id}/{name}", attachment)
    r.add_get("/gemini/{path:.*}", page)


async def slash(_request: web.Request) -> web.Response:
    raise web.HTTPFound("/studio/gemini/")


def _g(request: web.Request) -> dict:
    return request.config_dict[GEMINI_KEY]


def _root(request: web.Request) -> Path:
    g = _g(request)
    if g["root"] is None:
        from .routes import _studio
        g["root"] = _studio(request).cfg.studio_dir / "gemini"
    return g["root"]


def _chats(request: web.Request) -> G.Chats:
    g = _g(request)
    if "chats" not in g:
        g["chats"] = G.Chats(_root(request))
    return g["chats"]


def _repo(request: web.Request) -> G.Repo:
    g = _g(request)
    if "repo_obj" not in g:
        g["repo_obj"] = G.Repo(g["repo"] or ZPKT)
    return g["repo_obj"]


def _images(request: web.Request):
    from .routes import _image_store
    return _image_store(request)


def _key(request: web.Request) -> str:
    g = _g(request)
    k = g["key"] or secret("gemini")
    if not k:
        raise web.HTTPServiceUnavailable(text=json.dumps({"error": "No Gemini key (Keychain zpkt-gemini-api-key)."}),
                                         content_type="application/json")
    return k


def _json(data, status: int = 200) -> web.Response:
    return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})


def _chat_or_404(request: web.Request) -> dict:
    try:
        return _chats(request).get(request.match_info["id"])
    except KeyError:
        raise web.HTTPNotFound(text=json.dumps({"error": "No such chat."}), content_type="application/json") from None


# --- pages and reads ----------------------------------------------------------------------------------------------

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
    chats = _chats(request)
    manifest = _images(request).manifest
    return _json({"chats": chats.list(), "settings": chats.settings(), "usage": G.month_usage(chats, manifest),
                  "branch": _repo(request).branch()})


async def models(request: web.Request) -> web.Response:
    g = _g(request)
    at, cached = g["models"]
    if cached is None or time.monotonic() - at > 3600:
        key = _key(request)
        async with ClientSession(timeout=ClientTimeout(total=15)) as http, \
                http.get(f"{G.BASE}/models?pageSize=200", headers={"x-goog-api-key": key}) as r:
            data = await r.json(content_type=None)
            if r.status != 200:
                return _json({"error": (data.get("error") or {}).get("message", f"Upstream {r.status}")}, r.status)
        cached = [{"id": m["name"].removeprefix("models/"), "name": m.get("displayName") or m["name"]}
                  for m in data.get("models", [])
                  if "generateContent" in (m.get("supportedGenerationMethods") or [])
                  and m["name"].startswith("models/gemini")
                  and not any(w in m["name"] for w in NOT_A_TEXT_MODEL)]
        g["models"] = (time.monotonic(), cached)
    return _json({"models": cached})


async def set_defaults(request: web.Request) -> web.Response:
    return _json({"settings": _chats(request).set_settings(await request.json())})


async def get_chat(request: web.Request) -> web.Response:
    chat = _chat_or_404(request)
    return _json({**chat, "dollars": round(_chats(request).spent_by_chat().get(chat["id"], 0.0), 4)})


async def patch_chat(request: web.Request) -> web.Response:
    chat = _chat_or_404(request)
    body = await request.json()
    if isinstance(body.get("title"), str) and body["title"].strip():
        chat["title"] = body["title"].strip()[:80]
    if isinstance(body.get("settings"), dict):
        chat["settings"].update(G.clean_settings(body["settings"]))
    _chats(request).save(chat)
    return _json(chat)


async def delete_chat(request: web.Request) -> web.Response:
    try:
        _chats(request).delete(request.match_info["id"])
    except KeyError:
        raise web.HTTPNotFound() from None
    return _json({"ok": True})


async def attachment(request: web.Request) -> web.StreamResponse:
    path = _chats(request).file(request.match_info["id"], request.match_info["name"])
    if path is None:
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": "private, max-age=31536000, immutable"})


# --- a turn, streamed ---------------------------------------------------------------------------------------------

async def _body(request: web.Request) -> dict:
    raw = bytearray()
    async for chunk in request.content.iter_chunked(65536):
        raw += chunk
        if len(raw) > MAX_SEND:
            raise web.HTTPRequestEntityTooLarge(max_size=MAX_SEND, actual_size=len(raw))
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        raise web.HTTPBadRequest(text="Body must be JSON.") from None
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="Body must be a JSON object.")
    return body


async def send(request: web.Request) -> web.StreamResponse:
    body = await _body(request)
    chats = _chats(request)
    text = str(body.get("text") or "").strip()
    pics = body.get("images") or []
    if not text and not pics:
        return _json({"error": "Nothing to send."}, 400)
    cid = request.match_info["id"]
    if cid == "new":
        chat = chats.new(body.get("settings") or {})
        chat["title"] = G.title_from(text)
    else:
        chat = _chat_or_404(request)
        if isinstance(body.get("settings"), dict):
            chat["settings"].update(G.clean_settings(body["settings"]))
    parts: list[dict] = []
    try:
        for p in pics[:8]:
            parts.append({"file": chats.attach(chat["id"], str(p.get("mime")), str(p.get("data"))), "mime": p.get("mime")})
    except (ValueError, TypeError) as e:
        return _json({"error": f"Attachment: {e}"}, 400)
    parts.append({"text": text or " "})
    chat["contents"].append({"role": "user", "parts": parts, "_meta": {"at": G.now()}})
    chats.save(chat)
    return await _run(request, chat)


async def retry(request: web.Request) -> web.StreamResponse:
    chat = _chat_or_404(request)
    if G.truncate_to_last_user(chat) is None:
        return _json({"error": "Nothing to retry."}, 400)
    _chats(request).save(chat)
    return await _run(request, chat)


async def _run(request: web.Request, chat: dict) -> web.StreamResponse:
    g = _g(request)
    if chat["id"] in g["busy"]:
        return _json({"error": "This chat is already answering."}, 409)
    key = _key(request)
    resp = web.StreamResponse(headers={"Content-Type": "application/x-ndjson", "Cache-Control": "no-store",
                                       "X-Accel-Buffering": "no"})
    await resp.prepare(request)

    async def emit(ev: dict) -> None:
        await resp.write((json.dumps(ev) + "\n").encode())

    g["busy"].add(chat["id"])
    try:
        await emit({"type": "chat", "id": chat["id"], "title": chat["title"]})
        await G.turn(chat, _chats(request), key=key, repo=_repo(request), images=_images(request),
                     stream=g["stream"] or sse_stream, emit=emit, image_post=g["image_post"])
        await emit({"type": "done"})
    except (ConnectionResetError, asyncio.CancelledError):
        log.info("gemini chat %s: the page went away mid-answer", chat["id"])
        raise
    except Exception as e:  # noqa: BLE001 - shown in the chat, not a crash
        log.warning("gemini chat %s: %s", chat["id"], e)
        try:
            await emit({"type": "error", "error": str(e)[:600]})
        except ConnectionResetError:
            pass
    finally:
        g["busy"].discard(chat["id"])
    await resp.write_eof()
    return resp


async def sse_stream(url: str, body: dict, headers: dict) -> AsyncIterator[dict]:
    """streamGenerateContent's server-sent events, as dicts."""
    async with ClientSession(timeout=ClientTimeout(total=300, sock_read=120)) as http, \
            http.post(url, json=body, headers=headers) as r:
        if r.status != 200:
            data = await r.json(content_type=None)
            raise RuntimeError((data.get("error") or {}).get("message", f"Gemini answered {r.status}"))
        buf = b""
        async for chunk in r.content.iter_any():
            buf += chunk.replace(b"\r\n", b"\n")
            while b"\n\n" in buf:
                ev, buf = buf.split(b"\n\n", 1)
                for line in ev.split(b"\n"):
                    if line.startswith(b"data:"):
                        try:
                            yield json.loads(line[5:])
                        except ValueError:
                            pass
