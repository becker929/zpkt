"""The routes under /studio/, behind the harness password (the gate covers sub-apps too).

    GET  /studio/                 the home page: links to what is here (static/index.html)
    GET  /studio/lab/<file>       the lab: HW002's controls as phone surfaces (static/lab, contrib/docs/design/lab.md)
    GET  /studio/lab/audio/<file> its audio, built by `harness lab-audio` outside the repo (cached forever)
    GET  /studio/site-audio/<path>  the site's published audio (skrng batches, check sounds), through a local copy
                                  (the checklist prototype's gallery plays them: prototypes/checklist)
    POST /studio/api/artist/feedback            a thumbs up or down, stored at once (contrib/docs/design/artist-agent.md)
    POST /studio/api/artist/feedback/<id>/question   the quick question after it (a small model, else rules)
    POST /studio/api/artist/feedback/<id>/answer     his answer
    GET  /studio/api/artist/feedback            the newest presses with their questions and answers (?limit=)
    POST /studio/api/artist/plates              a plate for the gallery: the work as it played, the map, the render
    GET  /studio/api/artist/plates              the gallery's plates, oldest first (?track=)
    GET  /studio/api/artist/repertoire          the works the page chooses from (newest version; the seed at first)
    GET  /studio/api/regions/<id>/state         a region's permanent state: commits, the artifact carried, the plinths,
                                                completions (an empty state at first; contrib/docs/design/rummage.md, regions.py)
    POST /studio/api/regions/<id>/state         replace it (validated: 400 if the page could not have made it)
    GET  /studio/regions/<id>/audio/<file>      the region's renders (a combination per file, and its interface sounds,
                                                named by content: cached forever), from HARNESS_REGIONS_AUDIO/<id>/audio,
                                                outside the repo
    GET  /studio/images/          every image made with Gemini, as a wall (static/images, contrib/docs/images.md)
    GET  /studio/images/api/list  their records, newest first (?offset=&limit=&batch=), and the batches
    GET  /studio/images/files/<name>  an image or its gallery copy (cached forever: names are never reused)
    /studio/gemini/...            Gemini CLI sessions in zpkt, over ACP (gemini_routes.py, contrib/docs/gemini.md)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import ClientError, ClientSession, ClientTimeout, web

from . import artist as A
from . import regions as R
from .files import FOREVER, NO_STORE, gzipped, static_file
from .gemini_routes import add_gemini_routes

if TYPE_CHECKING:
    from . import Studio

log = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "static"
STUDIO_KEY = web.AppKey("studio", object)
IMAGES_KEY = web.AppKey("images", object)       # an images Store (the tests' stand-in server sets one)


def app(studio: "Studio") -> web.Application:
    sub = web.Application(client_max_size=1 << 20)
    sub[STUDIO_KEY] = studio
    sub.router.add_get("/", home)
    add_artist_routes(sub)
    add_region_routes(sub)
    sub.router.add_get("/lab", lab_slash)
    sub.router.add_get("/lab/audio/{name}", lab_audio)
    sub.router.add_get("/lab/{path:.*}", lab_file)
    sub.router.add_get("/site-audio/{path:.+}", site_audio)
    add_image_routes(sub)
    add_gemini_routes(sub)
    return sub


def add_image_routes(sub: web.Application) -> None:
    """The images' wall (also mounted by the browser tests' stand-in server)."""
    sub.router.add_get("/images", images_slash)
    sub.router.add_get("/images/api/list", images_list)
    sub.router.add_get("/images/files/{name}", images_file)
    sub.router.add_get("/images/{path:.*}", images_page)


def add_artist_routes(sub: web.Application) -> None:
    """The artist agent's API (also mounted by the browser tests' stand-in server)."""
    sub.router.add_post("/api/artist/feedback", artist_feedback)
    sub.router.add_get("/api/artist/feedback", artist_feedback_list)
    sub.router.add_post("/api/artist/feedback/{id}/question", artist_question)
    sub.router.add_post("/api/artist/feedback/{id}/answer", artist_answer)
    sub.router.add_post("/api/artist/plates", artist_plate)
    sub.router.add_get("/api/artist/plates", artist_plates)
    sub.router.add_get("/api/artist/repertoire", artist_repertoire)


def add_region_routes(sub: web.Application) -> None:
    """The regions' state and renders (also mounted by the browser tests' stand-in server)."""
    sub.router.add_get("/api/regions/{id}/state", region_state)
    sub.router.add_post("/api/regions/{id}/state", region_set_state)
    sub.router.add_get("/regions/{id}/audio/{name}", region_audio)


def _studio(request: web.Request) -> "Studio":
    return request.config_dict[STUDIO_KEY]


async def home(request: web.Request) -> web.StreamResponse:
    return static_file(request, STATIC, "index.html")


LAB = STATIC / "lab"


async def lab_slash(_request: web.Request) -> web.Response:
    raise web.HTTPFound("/studio/lab/")


async def lab_file(request: web.Request) -> web.StreamResponse:
    """The lab's page and modules, by relative path (so the same files run from any static server in tests),
    revalidated each load: it is a test bench, changed often."""
    return static_file(request, LAB, request.match_info["path"])


IMAGES_PAGE = STATIC / "images"


_IMAGE_STORES: dict = {}


def _image_store(request: web.Request):
    from ..images import Store
    store = request.config_dict.get(IMAGES_KEY)
    if store is None:
        root = _studio(request).cfg.images_dir
        store = _IMAGE_STORES.get(root) or _IMAGE_STORES.setdefault(root, Store(root))
    return store


async def images_slash(_request: web.Request) -> web.Response:
    raise web.HTTPFound("/studio/images/")


async def images_page(request: web.Request) -> web.StreamResponse:
    return static_file(request, IMAGES_PAGE, request.match_info["path"])


async def images_list(request: web.Request) -> web.Response:
    q = request.query
    try:
        offset, limit = max(0, int(q.get("offset", 0))), min(200, max(1, int(q.get("limit", 60))))
    except ValueError:
        raise web.HTTPBadRequest(text="offset and limit are numbers") from None
    recs, total, batches = _image_store(request).page(offset, limit, q.get("batch") or None)
    return gzipped(request, web.json_response({"items": [r.public() for r in recs], "total": total, "batches": batches},
                                               headers={"Cache-Control": "no-cache"}))


async def images_file(request: web.Request) -> web.StreamResponse:
    path = _image_store(request).path(request.match_info["name"])
    if path is None:
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": FOREVER})


SITE_AUDIO = re.compile(r"(skrng/[A-Za-z0-9._-]+\.mp3|zpkt/check-sounds/[a-z]+-(hit|strong|land)-[0-9a-f]{8}\.m4a)")
AUDIO_TYPES = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav"}


async def site_copy(site: str, path: Path, rel: str) -> Path:
    """The site's published audio at /audio/<rel>, copied to `path` the first time it is asked for. The site sends
    no CORS headers, so the page can't read it cross-origin; published files never change, so the copy is kept."""
    if not path.is_file():
        try:
            async with ClientSession(timeout=ClientTimeout(total=15)) as http, \
                    http.get(f"{site}/audio/{rel}") as r:
                if r.status != 200:
                    raise web.HTTPNotFound()
                data = await r.read()
        except (ClientError, TimeoutError):
            raise web.HTTPBadGateway(text="the site's audio did not answer") from None
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(".part")
        part.write_bytes(data)
        part.replace(path)
    return path


async def site_audio(request: web.Request) -> web.StreamResponse:
    """The site's published audio the checklist prototype plays (the gallery's renders: skrng batches; the check
    sounds), from an allowlist only, through a local copy kept for good."""
    rel = request.match_info["path"]
    if not SITE_AUDIO.fullmatch(rel):
        raise web.HTTPNotFound()
    cfg = _studio(request).cfg
    path = await site_copy(cfg.site, cfg.site_audio / rel, rel)
    return web.FileResponse(path, headers={"Cache-Control": FOREVER, "Content-Type": AUDIO_TYPES[path.suffix]})


# --- the artist agent: thumbs, questions, plates, the repertoire (contrib/docs/design/artist-agent.md) --------------------------
def _artist(request: web.Request) -> A.Artist:
    return _studio(request).artist


async def _body(request: web.Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text="expected JSON") from None
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="expected a JSON object")
    return body


async def artist_feedback(request: web.Request) -> web.Response:
    """A thumbs up or down: stored before anything else happens, so the press counts even if nothing follows."""
    body = await _body(request)
    try:
        ts = body.get("client_ts")
        made = _artist(request).add_feedback(body.get("vote"), str(body.get("view") or ""), body.get("context"),
                                             float(ts) if isinstance(ts, (int, float)) else None)
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from None
    return web.json_response(made, status=201, headers=NO_STORE)


async def artist_question(request: web.Request) -> web.Response:
    store = _artist(request)
    event = store.event(request.match_info["id"])
    if event is None:
        raise web.HTTPNotFound()
    q = await A.ask(event, getattr(_studio(request), "artist_model", None))
    store.set_question(event["id"], q["question"], q["choices"], q["by"])
    return web.json_response(q, headers=NO_STORE)


async def artist_answer(request: web.Request) -> web.Response:
    body = await _body(request)
    choice = body.get("choice")
    try:
        _artist(request).add_answer(request.match_info["id"], str(body.get("text") or ""),
                                    None if choice is None else str(choice))
    except KeyError:
        raise web.HTTPNotFound() from None
    return web.json_response({"ok": True}, headers=NO_STORE)


async def artist_feedback_list(request: web.Request) -> web.Response:
    try:
        limit = int(request.query.get("limit", "50"))
    except ValueError:
        raise web.HTTPBadRequest(text="limit is a number") from None
    return gzipped(request, web.json_response({"items": _artist(request).feedback(limit)}, headers=NO_STORE))


async def artist_plate(request: web.Request) -> web.Response:
    body = await _body(request)
    try:
        pid, n, at = _artist(request).add_plate(body)
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from None
    return web.json_response({"id": pid, "n": n, "at": at}, status=201, headers=NO_STORE)


async def artist_plates(request: web.Request) -> web.Response:
    track = request.query.get("track") or None
    return gzipped(request, web.json_response({"items": _artist(request).plates(track)}, headers=NO_STORE))


async def artist_repertoire(request: web.Request) -> web.Response:
    return gzipped(request, web.json_response(_artist(request).repertoire(), headers=NO_STORE))


# --- the regions: their permanent state and their renders (contrib/docs/design/rummage.md) --------------------------------------
def _region(request: web.Request) -> str:
    region = request.match_info["id"]
    if region not in R.REGIONS:
        raise web.HTTPNotFound()
    return region


async def region_state(request: web.Request) -> web.Response:
    return web.json_response(_studio(request).regions.get(_region(request)), headers=NO_STORE)


async def region_set_state(request: web.Request) -> web.Response:
    region = _region(request)
    body = await _body(request)
    try:
        kept = _studio(request).regions.put(region, body)
    except R.Invalid as exc:
        raise web.HTTPBadRequest(text=str(exc)) from None
    return web.json_response(kept, headers=NO_STORE)


# A combination's render: <track>-<bed>-<drums>-<bass>-<hash8>.m4a (the browser tests' fixtures are .wav), or one of
# the region's interface sounds: ui-<name>-<hash8>.m4a
REGION_AUDIO = re.compile(r"[a-z0-9]{2,16}-[1-3]-[1-3]-[1-3]-[0-9a-f]{8}\.(m4a|wav)|ui-[a-z]+-[0-9a-f]{8}\.m4a")


async def region_audio(request: web.Request) -> web.StreamResponse:
    """A region's renders, made in Live by the region's recipe (hands/scripts/<id>/) and kept outside the repo.
    The page plays them as rendered. Names carry a hash of the content, so they are cached for good."""
    region, name = _region(request), request.match_info["name"]
    if not REGION_AUDIO.fullmatch(name):
        raise web.HTTPNotFound()
    path = _studio(request).cfg.regions_audio / region / "audio" / name
    if not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": FOREVER, "Content-Type": AUDIO_TYPES[path.suffix]})


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
