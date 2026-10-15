"""The studio's routes, mounted at /studio/ behind the harness password (the gate covers sub-apps too).

    GET  /studio/                 the page, with the newest page of history in it (never cached)
    GET  /studio/static/<version>/<file>  its scripts and styles (gzipped; cached forever: assets.py)
    GET  /studio/media/<name>     speech, music and screenshots (content-addressed: cached forever)
    GET  /studio/api/messages     history, a page at a time (?before=<seq>&limit=<n>)
    GET  /studio/api/timings      the last turns' timing marks (?turns=<n>)
    POST /studio/api/conversation start a new conversation
    GET  /studio/ws               the WebSocket (docs/studio.md)
    GET  /studio/lab/<file>       the lab: HW002's controls as phone surfaces (static/lab, docs/lab.md)
    GET  /studio/lab/audio/<file> its audio, built by `harness lab-audio` outside the repo (cached forever)
    GET  /studio/checklist/<file> the track's checklist across the spine (static/checklist, docs/studio-agent.md)
    GET  /studio/checklist/map/sounds/<file>  its check sounds, from R2 through a local copy (cached forever)
"""

from __future__ import annotations

import logging
import re
import secrets
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import ClientError, ClientSession, ClientTimeout, WSMsgType, web

from .assets import Assets, accepts_gzip
from .conversation import PAGE
from .hub import Client
from .model import Prefs
from .protocol import MIC, BadMessage, parse_binary, parse_text

if TYPE_CHECKING:
    from . import Studio

log = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "static"
STUDIO_KEY = web.AppKey("studio", object)
ASSETS_KEY = web.AppKey("assets", Assets)
FOREVER = "private, max-age=31536000, immutable"
GZIP_FROM = 1024              # bytes: a page or JSON answer longer than this goes gzipped


def app(studio: "Studio") -> web.Application:
    sub = web.Application(client_max_size=1 << 20)
    sub[STUDIO_KEY] = studio
    sub[ASSETS_KEY] = Assets(STATIC)
    sub.router.add_get("/", index)
    sub.router.add_get("/static/{path:.+}", static)
    sub.router.add_get("/media/{name}", media)
    sub.router.add_get("/api/messages", messages)
    sub.router.add_get("/api/timings", timings)
    sub.router.add_post("/api/conversation", new_conversation)
    sub.router.add_get("/ws", socket)
    sub.router.add_get("/lab", lab_slash)
    sub.router.add_get("/lab/audio/{name}", lab_audio)
    sub.router.add_get("/lab/{path:.*}", lab_file)
    sub.router.add_get("/checklist", checklist_slash)
    sub.router.add_get("/checklist/map/sounds/{name}", check_sound)
    sub.router.add_get("/checklist/{path:.*}", checklist_file)
    return sub


def _studio(request: web.Request) -> "Studio":
    return request.config_dict[STUDIO_KEY]


async def index(request: web.Request) -> web.StreamResponse:
    studio = _studio(request)
    conv = studio.conversation.conv
    items, more = studio.store.page(conv.id, None, PAGE)
    html = request.config_dict[ASSETS_KEY].page(
        {"conversation": conv.id, "items": [m.wire() for m in items], "has_more": more})
    return _gzipped(request, web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-cache"}))


async def static(request: web.Request) -> web.StreamResponse:
    """A versioned file is cached for good. The page always names the current version; a file asked for under
    another one (or none: the browser tests' stand-in server) is the current file, revalidated each time."""
    assets: Assets = request.config_dict[ASSETS_KEY]
    version, rel = assets.split(request.match_info["path"])
    if version is None or version != assets.version():
        path = (STATIC / rel).resolve()
        if not path.is_relative_to(STATIC.resolve()) or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={"Cache-Control": "no-cache"})
    entry = assets.file(rel)
    if entry is None:
        raise web.HTTPNotFound()
    data, gz, ctype = entry
    headers = {"Cache-Control": FOREVER, "Content-Type": ctype, "Vary": "Accept-Encoding"}
    if accepts_gzip(request.headers.get("Accept-Encoding", "")):
        return web.Response(body=gz, headers={**headers, "Content-Encoding": "gzip"})
    return web.Response(body=data, headers=headers)


LAB = STATIC / "lab"


async def lab_slash(_request: web.Request) -> web.Response:
    raise web.HTTPFound("/studio/lab/")


async def lab_file(request: web.Request) -> web.StreamResponse:
    """The lab's page and modules, by relative path (so the same files run from any static server in tests),
    revalidated each load: it is a test bench, changed often."""
    return _bench_file(request, LAB)


CHECKLIST = STATIC / "checklist"


async def checklist_slash(_request: web.Request) -> web.Response:
    raise web.HTTPFound("/studio/checklist/")


async def checklist_file(request: web.Request) -> web.StreamResponse:
    """The checklist page (a first draft: its items are in its own data file), served like the lab."""
    return _bench_file(request, CHECKLIST)


def _bench_file(request: web.Request, root: Path) -> web.StreamResponse:
    rel = request.match_info["path"] or "index.html"
    path = (root / rel).resolve()
    if path.is_dir() and path.is_relative_to(root.resolve()):
        if not request.path.endswith("/"):                  # so the page's relative links resolve inside the folder
            raise web.HTTPFound(request.path + "/")
        path = path / "index.html"
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise web.HTTPNotFound()
    resp = web.FileResponse(path, headers={"Cache-Control": "no-cache"})
    if path.suffix in (".html", ".js", ".css", ".json", ".svg") and accepts_gzip(request.headers.get("Accept-Encoding", "")):
        resp.enable_compression(web.ContentCoding.gzip)
    return resp


CHECK_SOUND = re.compile(r"[a-z]+-(hit|strong|land)-[0-9a-f]{8}\.m4a")
CHECK_SOUNDS_AT = "/audio/zpkt/check-sounds/"         # on the site (R2): public, but sent without CORS headers


async def check_sound(request: web.Request) -> web.StreamResponse:
    """The map checklist's check sounds (rendered in Live by hands/scripts/ui_sounds; map/sounds.json names them).
    They live in R2, since audio never goes in git; the page can't read the site's audio cross-origin, so the first
    request copies a file here and every later one is served from that copy. Names carry a hash of the content."""
    name = request.match_info["name"]
    if not CHECK_SOUND.fullmatch(name):
        raise web.HTTPNotFound()
    cfg = _studio(request).cfg
    path = cfg.check_sounds / name
    if not path.is_file():
        try:
            async with ClientSession(timeout=ClientTimeout(total=15)) as http, \
                    http.get(cfg.site + CHECK_SOUNDS_AT + name) as r:
                if r.status != 200:
                    raise web.HTTPNotFound()
                data = await r.read()
        except (ClientError, TimeoutError):
            raise web.HTTPBadGateway(text="the check sounds' store did not answer") from None
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(".part")
        part.write_bytes(data)
        part.replace(path)
    return web.FileResponse(path, headers={"Cache-Control": FOREVER, "Content-Type": "audio/mp4"})


async def lab_audio(request: web.Request) -> web.StreamResponse:
    """HW002's stems and source clips for the lab, from HARNESS_LAB_AUDIO (built by `harness lab-audio`; the
    audio and its manifest never go in the repo). The manifest is revalidated; the audio is named by content."""
    root = _studio(request).cfg.lab_audio.resolve()
    name = request.match_info["name"]
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise web.HTTPNotFound()
    cache = "no-cache" if name.endswith(".json") else FOREVER
    return web.FileResponse(path, headers={"Cache-Control": cache})


async def media(request: web.Request) -> web.StreamResponse:
    path = _studio(request).store.media_file(request.match_info["name"])
    if path is None:
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": FOREVER})


def _gzipped(request: web.Request, resp: web.Response) -> web.Response:
    """Text over GZIP_FROM bytes goes gzipped to a browser that takes it."""
    if resp.body is not None and len(resp.body) > GZIP_FROM and accepts_gzip(request.headers.get("Accept-Encoding", "")):
        resp.enable_compression(web.ContentCoding.gzip)
    return resp


async def messages(request: web.Request) -> web.Response:
    studio = _studio(request)
    try:
        before = int(request.query["before"]) if request.query.get("before") else None
        limit = int(request.query.get("limit", "30"))
    except ValueError:
        raise web.HTTPBadRequest(text="before and limit are numbers") from None
    items, more = studio.store.page(studio.conversation.conv.id, before, limit)
    return _gzipped(request, web.json_response({"items": [m.wire() for m in items], "has_more": more},
                                               headers={"Cache-Control": "no-store"}))


async def timings(request: web.Request) -> web.Response:
    try:
        turns = int(request.query.get("turns", "10"))
    except ValueError:
        raise web.HTTPBadRequest(text="turns is a number") from None
    return _gzipped(request, web.json_response(_studio(request).store.timings(turns),
                                               headers={"Cache-Control": "no-store"}))


async def new_conversation(request: web.Request) -> web.Response:
    studio = _studio(request)
    try:
        studio.conversation.new_conversation()
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=409)
    return web.json_response({"conversation": studio.conversation.conv.wire()})


async def socket(request: web.Request) -> web.WebSocketResponse:
    studio = _studio(request)
    conv = studio.conversation
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=1 << 20)
    await ws.prepare(request)
    client: Client | None = None
    try:
        async for frame in ws:
            if frame.type == WSMsgType.BINARY:
                if client is None:
                    continue
                try:
                    channel, payload = parse_binary(frame.data)
                except BadMessage:
                    continue
                if channel == MIC:
                    conv.hear(client, payload)
                continue
            if frame.type != WSMsgType.TEXT:
                continue
            try:
                msg = parse_text(frame.data)
            except BadMessage as exc:
                error = {"type": "notice", "level": "error", "text": f"Bad message: {exc}"}
                if client is not None:
                    client.send(error)          # through its writer, so frames never interleave
                else:
                    await ws.send_json(error)
                continue
            kind = msg["type"]
            if kind == "hello":
                if client is not None:
                    studio.hub.remove(client)
                    await client.close()
                client = Client(ws, str(msg.get("client") or secrets.token_hex(6))[:64], Prefs.parse(msg.get("prefs")),
                                str(msg.get("ua", ""))[:300])
                studio.hub.add(client)
                conv.welcome(client)
            elif client is None:
                await ws.send_json({"type": "notice", "level": "error", "text": "Say hello first."})
            else:
                await dispatch(studio, client, kind, msg)
    finally:
        if client is not None:
            studio.hub.remove(client)
            conv.left(client)
            await client.close()
    return ws


async def dispatch(studio: "Studio", client: Client, kind: str, msg: dict) -> None:
    conv = studio.conversation
    if kind == "prefs":
        conv.prefs_changed(client, Prefs.parse(msg["prefs"]))
    elif kind == "start":
        conv.start_talking(client)
    elif kind == "pause":
        conv.pause(client)
    elif kind == "mic":
        conv.mic(client, msg["state"], msg.get("open_ms"))
    elif kind == "say":
        conv.typed(client, msg["text"])
    elif kind == "end_turn":
        conv.end_turn(client)
    elif kind == "interrupt":
        await conv.interrupt(client)
    elif kind == "playback":
        conv.playback(client, msg["state"], msg.get("done"))
    elif kind == "mark":
        extra = {k: v for k, v in msg.items() if k not in ("type", "turn", "name", "ms") and isinstance(v, (int, float, str))}
        conv.mark(client, msg.get("turn"), msg["name"], msg.get("ms"), extra)
    elif kind == "log":
        log.warning("page %s (%s): %s", client.id, client.ua[:80], msg["text"][:500])
    elif kind == "ping":
        client.send({"type": "pong", "t": msg.get("t")})
