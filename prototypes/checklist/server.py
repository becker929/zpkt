"""The checklist prototype's server: the pages at /studio/checklist/ (the URLs they had in the harness), the map's check
sounds, and the harness routes the pages call (the artist agent's API, the regions' state and renders, site-audio),
on loopback, without a login.

    uv run python server.py [--port 8798] [--data DIR] [--no-model]

Without --data it uses the harness's own data (HARNESS_STUDIO and the other HARNESS_* folders), so the plates, the
repertoire and the regions are the ones the harness keeps. With --data everything lives under DIR (the tests do
this). The artist's quick question comes from a small Claude model unless --no-model; then from its rules.
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from aiohttp import web

from harness.config import Config
from harness.studio import Studio, routes
from harness.studio.files import FOREVER, static_file

STATIC = Path(__file__).parent / "static"
PORT = 8798
# The map's check sounds (rendered in Live by hands/scripts/ui_sounds; map/sounds.json names them) live in R2, since
# audio never goes in git, and come through a local copy. Names carry a hash of the content.
CHECK_SOUND = re.compile(r"[a-z]+-(hit|strong|land)-[0-9a-f]{8}\.m4a")
CHECK_SOUNDS_AT = "zpkt/check-sounds/"           # on the site (R2): public, but sent without CORS headers
CHECK_SOUNDS = Path(os.environ.get("HARNESS_CHECK_SOUNDS", Path.home() / "_agent_scratch" / "studio" / "check-sounds"))
CHECK_SOUNDS_KEY = web.AppKey("check_sounds", Path)


def config(data: Path | None) -> tuple[Config, Path]:
    """The harness's config and where the check sounds are copied: the harness's own, or everything under `data`."""
    if data is None:
        return Config(), CHECK_SOUNDS
    data = Path(data)
    return Config(studio_dir=data, site_audio=data / "site-audio", regions_audio=data / "regions"), data / "check-sounds"


async def slash(_request: web.Request) -> web.Response:
    raise web.HTTPFound("/studio/checklist/")


async def page(request: web.Request) -> web.StreamResponse:
    return static_file(request, STATIC, request.match_info["path"])


async def check_sound(request: web.Request) -> web.StreamResponse:
    name = request.match_info["name"]
    if not CHECK_SOUND.fullmatch(name):
        raise web.HTTPNotFound()
    studio = request.config_dict[routes.STUDIO_KEY]
    path = await routes.site_copy(studio.cfg.site, request.config_dict[CHECK_SOUNDS_KEY] / name, CHECK_SOUNDS_AT + name)
    return web.FileResponse(path, headers={"Cache-Control": FOREVER, "Content-Type": "audio/mp4"})


def app(data: Path | None = None, *, question_model: bool = False) -> web.Application:
    cfg, sounds = config(data)
    studio = Studio(cfg, question_model=question_model)
    sub = web.Application(client_max_size=1 << 20)
    sub[routes.STUDIO_KEY] = studio
    sub[CHECK_SOUNDS_KEY] = sounds
    sub.router.add_get("/checklist", slash)
    sub.router.add_get("/checklist/map/sounds/{name}", check_sound)
    sub.router.add_get("/checklist/{path:.*}", page)
    sub.router.add_get("/site-audio/{path:.+}", routes.site_audio)
    routes.add_artist_routes(sub)
    routes.add_region_routes(sub)

    async def close(_app: web.Application) -> None:
        await studio.close()

    sub.on_cleanup.append(close)
    root = web.Application()
    root.add_subapp("/studio", sub)
    return root


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--data", type=Path, help="keep everything under this folder instead of the harness's data")
    ap.add_argument("--no-model", action="store_true", help="the artist's quick question from its rules only")
    a = ap.parse_args()
    print(f"checklist on http://127.0.0.1:{a.port}/studio/checklist/")
    web.run_app(app(a.data, question_model=not a.no_model), host="127.0.0.1", port=a.port, print=None)


if __name__ == "__main__":
    main()
