"""The studio's routes, mounted at /studio/ behind the harness password (the gate covers sub-apps too).

    GET  /studio/                 the page
    GET  /studio/static/<file>    its scripts and styles (revalidated: they change with the code)
    GET  /studio/media/<name>     speech, music and screenshots (content-addressed: cached forever)
    GET  /studio/api/messages     history, a page at a time (?before=<seq>&limit=<n>)
    GET  /studio/api/timings      the last turns' timing marks (?turns=<n>)
    POST /studio/api/conversation start a new conversation
    GET  /studio/ws               the WebSocket (docs/studio.md)
"""

from __future__ import annotations

import logging
import secrets
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import WSMsgType, web

from .hub import Client
from .model import Prefs
from .protocol import MIC, BadMessage, parse_binary, parse_text

if TYPE_CHECKING:
    from . import Studio

log = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "static"
STUDIO_KEY = web.AppKey("studio", object)


def app(studio: "Studio") -> web.Application:
    sub = web.Application(client_max_size=1 << 20)
    sub[STUDIO_KEY] = studio
    sub.router.add_get("/", index)
    sub.router.add_get("/static/{path:.+}", static)
    sub.router.add_get("/media/{name}", media)
    sub.router.add_get("/api/messages", messages)
    sub.router.add_get("/api/timings", timings)
    sub.router.add_post("/api/conversation", new_conversation)
    sub.router.add_get("/ws", socket)
    return sub


def _studio(request: web.Request) -> "Studio":
    return request.config_dict[STUDIO_KEY]


async def index(_request: web.Request) -> web.StreamResponse:
    return web.FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


async def static(request: web.Request) -> web.StreamResponse:
    path = (STATIC / request.match_info["path"]).resolve()
    if not path.is_relative_to(STATIC.resolve()) or not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": "no-cache"})


async def media(request: web.Request) -> web.StreamResponse:
    path = _studio(request).store.media_file(request.match_info["name"])
    if path is None:
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": "private, max-age=31536000, immutable"})


async def messages(request: web.Request) -> web.Response:
    studio = _studio(request)
    try:
        before = int(request.query["before"]) if request.query.get("before") else None
        limit = int(request.query.get("limit", "30"))
    except ValueError:
        raise web.HTTPBadRequest(text="before and limit are numbers") from None
    items, more = studio.store.page(studio.conversation.conv.id, before, limit)
    return web.json_response({"items": [m.wire() for m in items], "has_more": more},
                             headers={"Cache-Control": "no-store"})


async def timings(request: web.Request) -> web.Response:
    try:
        turns = int(request.query.get("turns", "10"))
    except ValueError:
        raise web.HTTPBadRequest(text="turns is a number") from None
    return web.json_response(_studio(request).store.timings(turns), headers={"Cache-Control": "no-store"})


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
    elif kind == "ping":
        client.send({"type": "pong", "t": msg.get("t")})
